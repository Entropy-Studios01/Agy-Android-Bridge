import pytest
from fastapi.testclient import TestClient
from server import create_app, AUTH_TOKEN

@pytest.fixture
def client(tmp_path):
    app = create_app(default_cwd=str(tmp_path))
    # In test client, startup event can be triggered via with TestClient(app)
    with TestClient(app) as c:
        yield c

def test_pc_sessions_unauthorized(client):
    res = client.get("/api/pc-sessions")
    assert res.status_code == 401

def test_pc_sessions_authorized(client):
    res = client.get(f"/api/pc-sessions?token={AUTH_TOKEN}")
    assert res.status_code == 200
    data = res.json()
    assert "sessions" in data
    assert isinstance(data["sessions"], list)

def test_pc_session_transcript(client):
    res = client.get(f"/api/pc-sessions/c7f97ebe-b2e4-4e9f-be1d-10e5951b319d/transcript?token={AUTH_TOKEN}")
    assert res.status_code == 200
    data = res.json()
    assert data["conversation_id"] == "c7f97ebe-b2e4-4e9f-be1d-10e5951b319d"
    assert "turns" in data

def test_pc_session_resume(client):
    res = client.post(
        f"/api/pc-sessions/c7f97ebe-b2e4-4e9f-be1d-10e5951b319d/resume?token={AUTH_TOKEN}",
        json={"name": "resume-test"}
    )
    assert res.status_code == 200
    data = res.json()
    assert "session" in data
    assert "resume-test" in data["session"]["name"]
