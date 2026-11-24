import json
import os
import sqlite3
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

DEFAULT_AGY_DIR = Path.home() / ".gemini" / "antigravity-cli"
DEFAULT_DB_PATH = DEFAULT_AGY_DIR / "conversation_summaries.db"
DEFAULT_PRESENCE_DIR = DEFAULT_AGY_DIR / "presence"
DEFAULT_BRAIN_DIR = DEFAULT_AGY_DIR / "brain"


def resolve_workspace_path(workspace_uris: Optional[str]) -> str:
    """Converts Antigravity workspace URI (or JSON array) into a clean local filesystem path."""
    if not workspace_uris or not isinstance(workspace_uris, str):
        return ""

    raw = workspace_uris.strip()
    if not raw:
        return ""

    uri = raw
    if raw.startswith("[") and raw.endswith("]"):
        try:
            arr = json.loads(raw)
            if isinstance(arr, list) and len(arr) > 0 and isinstance(arr[0], str):
                uri = arr[0]
        except Exception:
            pass

    # Decode percent encoding like %20 -> space
    decoded = urllib.parse.unquote(uri)

    # Strip file:/// or file://
    if decoded.startswith("file:///"):
        path_str = decoded[8:]
    elif decoded.startswith("file://"):
        path_str = decoded[7:]
    else:
        path_str = decoded

    # On Windows: if path starts with /D:/, strip leading slash
    if len(path_str) >= 3 and path_str[0] == "/" and path_str[2] == ":":
        path_str = path_str[1:]

    # Normalize slashes for Windows
    path_str = path_str.replace("/", "\\")
    return path_str


class AgyTracker:
    def __init__(
        self,
        db_path: Optional[Path] = None,
        presence_dir: Optional[Path] = None,
        brain_dir: Optional[Path] = None,
    ):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB_PATH
        self.presence_dir = Path(presence_dir) if presence_dir else DEFAULT_PRESENCE_DIR
        self.brain_dir = Path(brain_dir) if brain_dir else DEFAULT_BRAIN_DIR

    def get_active_presence_ids(self) -> Set[str]:
        """Returns session IDs that have an active lock file in the presence directory."""
        active = set()
        if not self.presence_dir.exists() or not self.presence_dir.is_dir():
            return active

        try:
            for entry in self.presence_dir.glob("*.lock"):
                conv_id = entry.stem
                if conv_id:
                    active.add(conv_id)
        except Exception:
            pass
        return active

    def list_sessions(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Queries conversation summaries and returns PC-wide Antigravity sessions."""
        if not self.db_path.exists():
            return []

        active_presence = self.get_active_presence_ids()
        sessions: List[Dict[str, Any]] = []

        try:
            # Open read-only connection
            db_uri = f"file:{self.db_path.as_posix()}?mode=ro"
            conn = sqlite3.connect(db_uri, uri=True, timeout=5.0)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            query = """
                SELECT conversation_id, title, preview, step_count, last_modified_time,
                       workspace_uris, status, not_fully_idle
                FROM conversation_summaries
                ORDER BY last_modified_time DESC
                LIMIT ?
            """
            rows = cursor.execute(query, (limit,)).fetchall()

            for row in rows:
                conv_id = row["conversation_id"]
                db_status = row["status"] or ""
                not_fully_idle = bool(row["not_fully_idle"])
                has_lock = conv_id in active_presence

                is_running = has_lock or (db_status == "CASCADE_RUN_STATUS_RUNNING" and not_fully_idle)
                status_label = "RUNNING" if is_running else "IDLE"

                workspace_dir = resolve_workspace_path(row["workspace_uris"])
                title = row["title"] or f"Session {conv_id[:8]}"

                sessions.append(
                    {
                        "conversation_id": conv_id,
                        "title": title,
                        "preview": row["preview"] or "",
                        "step_count": row["step_count"] or 0,
                        "last_modified_time": row["last_modified_time"] or "",
                        "workspace_dir": workspace_dir,
                        "status": status_label,
                        "is_running": is_running,
                        "has_lock": has_lock,
                    }
                )
            conn.close()
        except Exception as exc:
            # Fallback if query fails
            print(f"[AgyTracker] Error querying sessions DB: {exc}")

        return sessions

    def get_session_transcript(self, conversation_id: str, max_turns: int = 20) -> Dict[str, Any]:
        """Reads recent conversation turns from transcript logs in the brain directory."""
        result: Dict[str, Any] = {
            "conversation_id": conversation_id,
            "title": "",
            "turns": [],
            "found": False,
        }

        # Candidate paths for transcript.jsonl
        candidates = [
            self.brain_dir / conversation_id / ".system_generated" / "logs" / "transcript.jsonl",
            self.brain_dir / conversation_id / "transcript.jsonl",
        ]

        transcript_path: Optional[Path] = None
        for p in candidates:
            if p.exists():
                transcript_path = p
                break

        if not transcript_path:
            return result

        result["found"] = True
        try:
            # Read last N lines
            lines: List[str] = []
            with open(transcript_path, "r", encoding="utf-8", errors="replace") as f:
                lines = f.readlines()

            recent = lines[-max_turns:] if len(lines) > max_turns else lines
            parsed_turns: List[Dict[str, Any]] = []

            for line in recent:
                line_str = line.strip()
                if not line_str:
                    continue
                try:
                    obj = json.loads(line_str)
                    role = obj.get("role") or obj.get("sender") or "unknown"
                    message = obj.get("message") or obj.get("content") or obj.get("summary") or ""
                    # Handle turn content if structured
                    if isinstance(message, dict):
                        message = json.dumps(message)
                    elif isinstance(message, list):
                        parts = []
                        for part in message:
                            if isinstance(part, dict):
                                parts.append(part.get("text", ""))
                            else:
                                parts.append(str(part))
                        message = "\n".join(parts)

                    parsed_turns.append(
                        {
                            "role": role,
                            "message": str(message),
                            "timestamp": obj.get("timestamp") or obj.get("created_at") or "",
                        }
                    )
                except Exception:
                    continue

            result["turns"] = parsed_turns
        except Exception as exc:
            result["error"] = str(exc)

        return result
