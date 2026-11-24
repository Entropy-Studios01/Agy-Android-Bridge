import argparse
import asyncio
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set

from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from agy_tracker import AgyTracker

IS_WINDOWS = sys.platform == "win32"
if IS_WINDOWS:
    from winpty import PtyProcess  # type: ignore
else:
    import fcntl
    import pty
    import struct
    import termios

BASE_DIR = Path(__file__).resolve().parent
STATIC_DIR = BASE_DIR / "static"
TOKEN_FILE = BASE_DIR / ".agy_remote_token"
MAX_SCROLLBACK_CHARS = 200_000


def load_or_create_token() -> str:
    env_token = os.environ.get("AGY_REMOTE_TOKEN", "").strip()
    if env_token:
        return env_token
    if TOKEN_FILE.exists():
        saved = TOKEN_FILE.read_text(encoding="utf-8").strip()
        if saved:
            return saved
    token = secrets.token_urlsafe(24)
    TOKEN_FILE.write_text(token, encoding="utf-8")
    return token


AUTH_TOKEN = load_or_create_token()


class PosixPtyWrapper:
    """Fallback PTY wrapper for Linux/macOS testing."""

    def __init__(self, argv: List[str], cwd: str, rows: int, cols: int):
        self.master_fd, slave_fd = pty.openpty()
        self.setwinsize(rows, cols)
        self.proc = subprocess.Popen(
            argv,
            cwd=cwd,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            close_fds=True,
            start_new_session=True,
        )
        os.close(slave_fd)

    def read(self, size: int = 4096) -> str:
        data = os.read(self.master_fd, size)
        return data.decode("utf-8", errors="replace")

    def write(self, data: str) -> None:
        os.write(self.master_fd, data.encode("utf-8", errors="replace"))

    def setwinsize(self, rows: int, cols: int) -> None:
        winsize = struct.pack("HHHH", max(rows, 5), max(cols, 20), 0, 0)
        fcntl.ioctl(self.master_fd, termios.TIOCSWINSZ, winsize)

    def isalive(self) -> bool:
        return self.proc.poll() is None

    def terminate(self) -> None:
        try:
            self.proc.terminate()
        except Exception:
            pass
        try:
            os.close(self.master_fd)
        except Exception:
            pass


@dataclass
class TerminalSession:
    session_id: str
    name: str
    cwd: str
    command: List[str]
    rows: int = 32
    cols: int = 100
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    scrollback: str = ""
    clients: Set[WebSocket] = field(default_factory=set)
    _pty: Optional[object] = field(default=None, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    _closed: bool = False

    def start(self, loop: asyncio.AbstractEventLoop, initial_cmd: Optional[str] = None) -> None:
        if IS_WINDOWS:
            self._pty = PtyProcess.spawn(
                self.command,
                cwd=self.cwd,
                dimensions=(self.rows, self.cols),
            )
        else:
            self._pty = PosixPtyWrapper(self.command, self.cwd, self.rows, self.cols)

        reader = threading.Thread(
            target=self._read_loop,
            args=(loop,),
            daemon=True,
            name=f"pty-reader-{self.session_id}",
        )
        reader.start()

        if initial_cmd:
            # Give shell a moment to initialize before sending startup command
            def _send_startup() -> None:
                time.sleep(0.8)
                self.write(initial_cmd.rstrip("\r\n") + "\r")

            threading.Thread(target=_send_startup, daemon=True).start()

    def _read_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        while not self._closed and self._pty is not None:
            try:
                chunk = self._pty.read(4096)
                if not chunk:
                    if not self.is_alive():
                        break
                    time.sleep(0.02)
                    continue
                self._append_scrollback(chunk)
                self.last_activity = time.time()
                asyncio.run_coroutine_threadsafe(self._broadcast({"type": "output", "data": chunk}), loop)
            except EOFError:
                break
            except OSError:
                break
            except Exception as exc:
                err_msg = f"\r\n[agy-remote] PTY read error: {exc}\r\n"
                self._append_scrollback(err_msg)
                asyncio.run_coroutine_threadsafe(self._broadcast({"type": "output", "data": err_msg}), loop)
                break

        self._closed = True
        exit_notice = "\r\n[agy-remote] Shell session ended.\r\n"
        self._append_scrollback(exit_notice)
        asyncio.run_coroutine_threadsafe(
            self._broadcast({"type": "status", "alive": False, "message": "Session ended"}),
            loop,
        )

    def _append_scrollback(self, chunk: str) -> None:
        with self._lock:
            self.scrollback += chunk
            if len(self.scrollback) > MAX_SCROLLBACK_CHARS:
                self.scrollback = self.scrollback[-MAX_SCROLLBACK_CHARS:]

    def get_scrollback(self) -> str:
        with self._lock:
            return self.scrollback

    async def _broadcast(self, payload: dict) -> None:
        dead: List[WebSocket] = []
        text = json.dumps(payload)
        for ws in list(self.clients):
            try:
                await ws.send_text(text)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.clients.discard(ws)

    def write(self, data: str) -> None:
        if self._pty is None or self._closed:
            return
        try:
            self._pty.write(data)
        except Exception:
            pass

    def resize(self, rows: int, cols: int) -> None:
        if self._pty is None or self._closed:
            return
        self.rows = max(8, min(rows, 200))
        self.cols = max(20, min(cols, 300))
        try:
            self._pty.setwinsize(self.rows, self.cols)
        except Exception:
            pass

    def is_alive(self) -> bool:
        if self._closed or self._pty is None:
            return False
        try:
            return bool(self._pty.isalive())
        except Exception:
            return False

    def status_label(self) -> str:
        if not self.is_alive():
            return "stopped"
        if (time.time() - self.last_activity) < 4.0:
            return "active"
        return "idle"

    def close(self) -> None:
        self._closed = True
        if self._pty is not None:
            try:
                self._pty.terminate()
            except Exception:
                pass

    def to_dict(self) -> dict:
        return {
            "id": self.session_id,
            "name": self.name,
            "cwd": self.cwd,
            "alive": self.is_alive(),
            "status": self.status_label(),
            "last_activity": self.last_activity,
            "clients": len(self.clients),
        }


class SessionManager:
    def __init__(self, default_cwd: str, default_shell: Optional[str] = None):
        self.default_cwd = default_cwd
        self.default_shell = default_shell or self._detect_shell()
        self.sessions: Dict[str, TerminalSession] = {}
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    @staticmethod
    def _detect_shell() -> str:
        if IS_WINDOWS:
            if shutil.which("pwsh.exe"):
                return "pwsh.exe"
            return "powershell.exe"
        return os.environ.get("SHELL", "/bin/bash")

    def _build_command(self) -> List[str]:
        if IS_WINDOWS:
            return [self.default_shell, "-NoLogo"]
        return [self.default_shell]

    def create_session(
        self,
        name: Optional[str] = None,
        cwd: Optional[str] = None,
        initial_cmd: Optional[str] = None,
    ) -> TerminalSession:
        assert self.loop is not None, "Event loop not initialized"
        resolved_cwd = cwd or self.default_cwd
        if not os.path.isdir(resolved_cwd):
            resolved_cwd = self.default_cwd
        sid = uuid.uuid4().hex[:8]
        session_name = name or f"agy-{len(self.sessions) + 1}"
        session = TerminalSession(
            session_id=sid,
            name=session_name,
            cwd=resolved_cwd,
            command=self._build_command(),
        )
        session.start(self.loop, initial_cmd=initial_cmd)
        self.sessions[sid] = session
        return session

    def get(self, session_id: str) -> Optional[TerminalSession]:
        return self.sessions.get(session_id)

    def delete(self, session_id: str) -> bool:
        session = self.sessions.pop(session_id, None)
        if not session:
            return False
        session.close()
        return True

    def list_sessions(self) -> List[dict]:
        return [s.to_dict() for s in self.sessions.values()]

    def shutdown_all(self) -> None:
        for session in list(self.sessions.values()):
            session.close()
        self.sessions.clear()


class CreateSessionRequest(BaseModel):
    name: Optional[str] = None
    cwd: Optional[str] = None
    initial_cmd: Optional[str] = None


class ResumeSessionRequest(BaseModel):
    name: Optional[str] = None


class NewPcSessionRequest(BaseModel):
    name: Optional[str] = None
    cwd: Optional[str] = None
    initial_prompt: Optional[str] = None


def verify_token_value(token: Optional[str]) -> bool:
    return bool(token) and secrets.compare_digest(token, AUTH_TOKEN)


def require_auth(request: Request, token: Optional[str] = Query(default=None)) -> None:
    header_token = request.headers.get("X-Auth-Token")
    if not (verify_token_value(header_token) or verify_token_value(token)):
        raise HTTPException(status_code=401, detail="Invalid or missing auth token")


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"


def get_tailscale_ip() -> Optional[str]:
    try:
        out = subprocess.check_output(
            ["tailscale", "ip", "-4"],
            stderr=subprocess.DEVNULL,
            timeout=2,
            text=True,
        ).strip()
        if out:
            return out.splitlines()[0].strip()
    except Exception:
        pass
    return None


def print_banner(port: int, auto_cmd: Optional[str]) -> None:
    lan_ip = get_lan_ip()
    ts_ip = get_tailscale_ip()
    lan_url = f"http://{lan_ip}:{port}/?token={AUTH_TOKEN}"
    ts_url = f"http://{ts_ip}:{port}/?token={AUTH_TOKEN}" if ts_ip else None
    primary_url = ts_url or lan_url

    print("\n" + "=" * 64)
    print("  AGY REMOTE — PC PowerShell <-> Android Bridge")
    print("=" * 64)
    print(f"  Token      : {AUTH_TOKEN}")
    print(f"  Local WiFi : {lan_url}")
    if ts_url:
        print(f"  Tailscale  : {ts_url}  (works from 4G/5G anywhere!)")
    else:
        print("  Tailscale  : Not detected (install Tailscale for 4G/5G access)")
    if auto_cmd:
        print(f"  Startup Cmd: {auto_cmd}")
    print("=" * 64)

    try:
        import qrcode

        qr = qrcode.QRCode(border=1)
        qr.add_data(primary_url)
        qr.make(fit=True)
        print("  Scan with your Android camera / Brave browser:")
        qr.print_ascii(invert=True)
    except Exception:
        pass
    print("  Tip: Open the link on Android -> Menu -> Add to Home Screen.\n")


def create_app(default_cwd: str, auto_cmd: Optional[str] = None, shell: Optional[str] = None) -> FastAPI:
    app = FastAPI(title="AGY Remote", version="1.0.0")
    manager = SessionManager(default_cwd=default_cwd, default_shell=shell)
    tracker = AgyTracker()
    app.state.manager = manager
    app.state.tracker = tracker

    @app.on_event("startup")
    async def on_startup() -> None:
        manager.loop = asyncio.get_running_loop()
        manager.create_session(name="agy-main", cwd=default_cwd, initial_cmd=auto_cmd)

    @app.on_event("shutdown")
    async def on_shutdown() -> None:
        manager.shutdown_all()

    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

    @app.get("/")
    async def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    @app.get("/manifest.json")
    async def manifest() -> FileResponse:
        return FileResponse(STATIC_DIR / "manifest.json", media_type="application/manifest+json")

    @app.get("/api/health")
    async def health() -> JSONResponse:
        return JSONResponse({"ok": True, "platform": sys.platform})

    @app.get("/api/sessions")
    async def list_sessions(request: Request, token: Optional[str] = Query(default=None)) -> JSONResponse:
        require_auth(request, token)
        return JSONResponse({"sessions": manager.list_sessions()})

    @app.post("/api/sessions")
    async def create_session_route(
        body: CreateSessionRequest,
        request: Request,
        token: Optional[str] = Query(default=None),
    ) -> JSONResponse:
        require_auth(request, token)
        session = manager.create_session(
            name=body.name,
            cwd=body.cwd,
            initial_cmd=body.initial_cmd,
        )
        return JSONResponse({"session": session.to_dict()})

    @app.delete("/api/sessions/{session_id}")
    async def delete_session_route(
        session_id: str,
        request: Request,
        token: Optional[str] = Query(default=None),
    ) -> JSONResponse:
        require_auth(request, token)
        if not manager.delete(session_id):
            raise HTTPException(status_code=404, detail="Session not found")
        return JSONResponse({"deleted": session_id})

    @app.get("/api/pc-sessions")
    async def list_pc_sessions(
        request: Request,
        token: Optional[str] = Query(default=None),
        limit: int = 50,
    ) -> JSONResponse:
        require_auth(request, token)
        sessions = tracker.list_sessions(limit=limit)
        return JSONResponse({"sessions": sessions, "count": len(sessions)})

    @app.get("/api/pc-sessions/{conversation_id}/transcript")
    async def get_pc_session_transcript(
        conversation_id: str,
        request: Request,
        token: Optional[str] = Query(default=None),
        max_turns: int = 25,
    ) -> JSONResponse:
        require_auth(request, token)
        data = tracker.get_session_transcript(conversation_id, max_turns=max_turns)
        return JSONResponse(data)

    @app.post("/api/pc-sessions/{conversation_id}/resume")
    async def resume_pc_session(
        conversation_id: str,
        request: Request,
        body: Optional[ResumeSessionRequest] = None,
        token: Optional[str] = Query(default=None),
    ) -> JSONResponse:
        require_auth(request, token)
        # Find session details to get its workspace directory
        all_pc = tracker.list_sessions(limit=100)
        target = next((s for s in all_pc if s["conversation_id"] == conversation_id), None)
        target_cwd = target["workspace_dir"] if (target and target.get("workspace_dir")) else default_cwd
        if not os.path.isdir(target_cwd):
            target_cwd = default_cwd

        name = (body.name if body and body.name else None) or f"agy-{conversation_id[:6]}"
        initial_cmd = f"agy -r {conversation_id}"

        session = manager.create_session(
            name=name,
            cwd=target_cwd,
            initial_cmd=initial_cmd,
        )
        return JSONResponse({"session": session.to_dict(), "resumed": conversation_id})

    @app.post("/api/pc-sessions/new")
    async def new_pc_session(
        body: NewPcSessionRequest,
        request: Request,
        token: Optional[str] = Query(default=None),
    ) -> JSONResponse:
        require_auth(request, token)
        target_cwd = body.cwd or default_cwd
        if not os.path.isdir(target_cwd):
            target_cwd = default_cwd
        name = body.name or "agy-new"
        cmd = "agy"
        if body.initial_prompt:
            cmd = f'agy -i "{body.initial_prompt}"'
        session = manager.create_session(
            name=name,
            cwd=target_cwd,
            initial_cmd=cmd,
        )
        return JSONResponse({"session": session.to_dict()})

    @app.websocket("/ws/{session_id}")
    async def terminal_ws(ws: WebSocket, session_id: str, token: Optional[str] = Query(default=None)) -> None:
        if not verify_token_value(token):
            await ws.close(code=4401, reason="Unauthorized")
            return

        session = manager.get(session_id)
        if not session:
            await ws.close(code=4404, reason="Session not found")
            return

        await ws.accept()
        session.clients.add(ws)

        try:
            # Replay recent scrollback immediately so phone sees what agy has been doing
            history = session.get_scrollback()
            if history:
                await ws.send_text(json.dumps({"type": "history", "data": history}))
            await ws.send_text(
                json.dumps(
                    {
                        "type": "status",
                        "alive": session.is_alive(),
                        "status": session.status_label(),
                    }
                )
            )

            while True:
                raw = await ws.receive_text()
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type")
                if msg_type == "input":
                    data = msg.get("data", "")
                    if isinstance(data, str) and data:
                        session.write(data)
                elif msg_type == "resize":
                    rows = int(msg.get("rows", 30))
                    cols = int(msg.get("cols", 80))
                    session.resize(rows, cols)
                elif msg_type == "ping":
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "pong",
                                "alive": session.is_alive(),
                                "status": session.status_label(),
                            }
                        )
                    )
        except WebSocketDisconnect:
            pass
        finally:
            session.clients.discard(ws)

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="AGY Remote PowerShell Bridge")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=8765, help="Port (default: 8765)")
    parser.add_argument("--cwd", default=os.getcwd(), help="Working directory for PowerShell sessions")
    parser.add_argument("--auto-cmd", default=None, help="Optional command to run automatically (e.g. agy)")
    parser.add_argument("--shell", default=None, help="Shell executable override (e.g. pwsh.exe)")
    args = parser.parse_args()

    import uvicorn

    print_banner(args.port, args.auto_cmd)
    app = create_app(default_cwd=args.cwd, auto_cmd=args.auto_cmd, shell=args.shell)
    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
