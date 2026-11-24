import json
import sqlite3
import pytest
from pathlib import Path
from agy_tracker import AgyTracker, resolve_workspace_path

def test_resolve_workspace_path():
    assert resolve_workspace_path('["file:///D:/Work/Projects/Neon"]') == r"D:\Work\Projects\Neon"
    assert resolve_workspace_path('["file:///D:/My%20Projects/Test%20App"]') == r"D:\My Projects\Test App"
    assert resolve_workspace_path("file:///C:/Users/admin") == r"C:\Users\admin"
    assert resolve_workspace_path("") == ""
    assert resolve_workspace_path(None) == ""

def test_list_sessions_mock(tmp_path):
    # Setup temporary mock database and presence dir
    db_file = tmp_path / "conversation_summaries.db"
    conn = sqlite3.connect(str(db_file))
    conn.execute("""
        CREATE TABLE conversation_summaries (
            conversation_id TEXT PRIMARY KEY,
            title TEXT,
            preview TEXT,
            step_count INTEGER,
            last_modified_time TEXT,
            workspace_uris TEXT,
            status TEXT,
            not_fully_idle INTEGER
        )
    """)
    conn.execute("""
        INSERT INTO conversation_summaries VALUES (
            'test-conv-1',
            'Test Session Active',
            'Doing work...',
            12,
            '2026-11-24 14:00:00',
            '["file:///D:/Test/Workspace"]',
            'CASCADE_RUN_STATUS_RUNNING',
            1
        )
    """)
    conn.execute("""
        INSERT INTO conversation_summaries VALUES (
            'test-conv-2',
            'Test Session Idle',
            'Done.',
            5,
            '2026-11-24 13:00:00',
            '["file:///D:/Test/Workspace2"]',
            'CASCADE_RUN_STATUS_IDLE',
            0
        )
    """)
    conn.commit()
    conn.close()

    presence_dir = tmp_path / "presence"
    presence_dir.mkdir()
    (presence_dir / "test-conv-1.lock").touch()

    tracker = AgyTracker(db_path=db_file, presence_dir=presence_dir, brain_dir=tmp_path / "brain")
    sessions = tracker.list_sessions()
    assert len(sessions) == 2
    s1 = next(s for s in sessions if s["conversation_id"] == "test-conv-1")
    assert s1["is_running"] is True
    assert s1["status"] == "RUNNING"
    assert s1["workspace_dir"] == r"D:\Test\Workspace"

    s2 = next(s for s in sessions if s["conversation_id"] == "test-conv-2")
    assert s2["is_running"] is False
    assert s2["status"] == "IDLE"

def test_get_session_transcript_mock(tmp_path):
    brain_dir = tmp_path / "brain"
    conv_dir = brain_dir / "test-conv-1" / ".system_generated" / "logs"
    conv_dir.mkdir(parents=True)
    transcript_file = conv_dir / "transcript.jsonl"
    
    lines = [
        {"role": "user", "message": "List files", "timestamp": "2026-11-24T14:01:00Z"},
        {"role": "assistant", "message": "Here are the files", "timestamp": "2026-11-24T14:01:05Z"}
    ]
    with open(transcript_file, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")

    tracker = AgyTracker(db_path=tmp_path / "none.db", presence_dir=tmp_path, brain_dir=brain_dir)
    res = tracker.get_session_transcript("test-conv-1", max_turns=10)
    assert res["conversation_id"] == "test-conv-1"
    assert len(res["turns"]) == 2
    assert res["turns"][0]["role"] == "user"
    assert res["turns"][1]["role"] == "assistant"


def test_live_pc_sessions():
    tracker = AgyTracker()
    sessions = tracker.list_sessions(limit=5)
    # On this PC, there should be at least one real session (the current one!)
    assert len(sessions) > 0
    # One of the sessions should be the current conversation
    conv_ids = [s["conversation_id"] for s in sessions]
    assert "c7f97ebe-b2e4-4e9f-be1d-10e5951b319d" in conv_ids
    # Verify current conversation has correct properties
    current = next(s for s in sessions if s["conversation_id"] == "c7f97ebe-b2e4-4e9f-be1d-10e5951b319d")
    assert current["is_running"] is True
    assert "agy_remote" in current["workspace_dir"]
