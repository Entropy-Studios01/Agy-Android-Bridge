import json
import pytest
from fastapi.testclient import TestClient
from server import create_app, AUTH_TOKEN

def test_full_remote_integration(tmp_path):
    app = create_app(default_cwd=str(tmp_path))
    with TestClient(app) as client:
        # 1. Health check
        h_res = client.get("/api/health")
        assert h_res.status_code == 200
        assert h_res.json()["ok"] is True

        # 2. List PC-wide Antigravity sessions
        pc_res = client.get(f"/api/pc-sessions?token={AUTH_TOKEN}")
        assert pc_res.status_code == 200
        pc_data = pc_res.json()
        assert "sessions" in pc_data
        sessions = pc_data["sessions"]
        assert len(sessions) > 0

        # Find current active session
        curr_session = next((s for s in sessions if s["conversation_id"] == "c7f97ebe-b2e4-4e9f-be1d-10e5951b319d"), None)
        assert curr_session is not None
        assert curr_session["is_running"] is True

        # 3. Fetch transcript for current session
        t_res = client.get(f"/api/pc-sessions/{curr_session['conversation_id']}/transcript?token={AUTH_TOKEN}")
        assert t_res.status_code == 200
        t_data = t_res.json()
        assert t_data["conversation_id"] == curr_session["conversation_id"]
        assert isinstance(t_data["turns"], list)

        # 4. Resume session
        r_res = client.post(
            f"/api/pc-sessions/{curr_session['conversation_id']}/resume?token={AUTH_TOKEN}",
            json={"name": "test-resumed-session"}
        )
        assert r_res.status_code == 200
        resumed = r_res.json()["session"]
        assert resumed["name"] == "test-resumed-session"
        resumed_id = resumed["id"]

        # 5. Verify resumed session in terminal sessions list
        list_res = client.get(f"/api/sessions?token={AUTH_TOKEN}")
        assert list_res.status_code == 200
        active_terminal_ids = [s["id"] for s in list_res.json()["sessions"]]
        assert resumed_id in active_terminal_ids

        # 6. Test WebSocket handshake
        with client.websocket_connect(f"/ws/{resumed_id}?token={AUTH_TOKEN}") as ws:
            # First message should be history or status
            first_msg = ws.receive_json()
            assert first_msg["type"] in ("history", "status", "output")
            # Send ping
            ws.send_json({"type": "ping"})
            pong = ws.receive_json()
            assert pong["type"] in ("pong", "history", "status", "output")
