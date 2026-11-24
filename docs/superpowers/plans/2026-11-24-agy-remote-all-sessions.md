# Antigravity Remote All-Sessions Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform the local `agy_remote` bridge into a full PC-wide Antigravity tracker and control center, allowing an Android phone to monitor all active/past `agy` sessions across the entire PC, inspect their transcripts, and attach/resume interactive terminal sessions with one tap.

**Architecture:** A lightweight Python module (`agy_tracker.py`) inspects the PC's global Antigravity database (`conversation_summaries.db`), presence lock directory, and session transcripts. FastAPI (`server.py`) exposes REST endpoints to list, inspect, and resume any session via ConPTY (`agy -r <id>`). A mobile-first responsive PWA UI (`static/index.html`) provides a unified dashboard with two tabs: a live Sessions Tracker (with transcript inspector & one-tap resume) and the interactive xterm.js Terminal with touch quick-keys.

**Tech Stack:** Python 3.10+, FastAPI, Uvicorn, SQLite3, PyWinPTY, xterm.js, HTML5/CSS3/ES6.

**Spec:** Direct user request to track and access all `agy` sessions across the PC from a mobile phone.

## Global Constraints
- Target platform is Windows 11 with PowerShell (`pwsh.exe` or `powershell.exe`) and `agy.exe`.
- SQLite access to `C:\Users\admin\.gemini\antigravity-cli\conversation_summaries.db` must be read-only (`mode=ro` or immutable) so it never locks out Antigravity itself.
- All session endpoints must be secured with the existing URL / header token authentication (`AUTH_TOKEN`).
- Mobile UI must be responsive, touch-friendly, and retain existing PWA features (manifest, theme color, offline shell, xterm quick-keys).

## Review Focus
- **Concurrent DB Access**: Antigravity is actively writing to `conversation_summaries.db`; reads must use URI `file:...sqlite3?mode=ro` and handle short-lived locks gracefully.
- **Path Resolution**: `workspace_uris` in the database are stored as JSON arrays of file URIs (e.g. `["file:///D:/Work/Projects/Neon"]`); must be cleanly converted to Windows native filesystem paths.
- **Session Status Accuracy**: A session is only truly active if its presence lock file in `presence/` exists and is fresh or its DB status is `CASCADE_RUN_STATUS_RUNNING` with `not_fully_idle=1`.
- **Transcript Parsing**: `transcript.jsonl` files can be large; parsing must only fetch the last N messages to avoid mobile network bottlenecks and high memory usage.
- **PTY Terminal Handshake**: When resuming a session with `agy -r <id>`, PTY must initialize with the workspace CWD of that specific conversation.

---

### Task 1: Antigravity Session Discovery & Transcript Parser Module (`agy_tracker.py`)

**Files:**
- Create: `agy_tracker.py`
- Test: `tests/test_agy_tracker.py`

**Interfaces:**
- Produces:
  - `AgyTracker`:
    - `list_sessions(limit: int = 50) -> List[Dict[str, Any]]`
    - `get_session_transcript(conversation_id: str, max_turns: int = 15) -> Dict[str, Any]`
    - `resolve_workspace_path(workspace_uris: str) -> str`

- [ ] **Step 1: Write the failing tests in `tests/test_agy_tracker.py`**
  Verify `resolve_workspace_path` converts `file:///D:/Path` to `D:\Path`, `list_sessions` extracts sessions from SQLite, and `get_session_transcript` extracts turns from `transcript.jsonl`.

- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv\Scripts\pytest tests/test_agy_tracker.py -v`
  Expected: FAIL with ModuleNotFoundError or test failures.

- [ ] **Step 3: Implement `agy_tracker.py`**
  Implement SQLite reader with read-only connection, presence lock detection, workspace URI conversion, and transcript JSONL tail parser.

- [ ] **Step 4: Run test to verify it passes**
  Run: `.venv\Scripts\pytest tests/test_agy_tracker.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add agy_tracker.py tests/test_agy_tracker.py
  git commit -m "feat: add agy session discovery and transcript parser module"
  ```

---

### Task 2: Backend Endpoints for PC Sessions & Resume in `server.py`

**Files:**
- Modify: `server.py`
- Test: `tests/test_server_endpoints.py`

**Interfaces:**
- Consumes: `agy_tracker.AgyTracker`
- Produces:
  - `GET /api/pc-sessions` -> `{ "sessions": [...] }`
  - `GET /api/pc-sessions/{conversation_id}/transcript` -> `{ "transcript": [...] }`
  - `POST /api/pc-sessions/{conversation_id}/resume` -> `{ "session": TerminalSessionDict }`
  - `POST /api/pc-sessions/new` -> `{ "session": TerminalSessionDict }`

- [ ] **Step 1: Write the failing tests in `tests/test_server_endpoints.py`**
  Test API responses with valid and invalid tokens using `fastapi.testclient.TestClient`.

- [ ] **Step 2: Run test to verify it fails**
  Run: `.venv\Scripts\pytest tests/test_server_endpoints.py -v`
  Expected: FAIL (endpoints not found or 404).

- [ ] **Step 3: Implement routes in `server.py`**
  Mount `AgyTracker`, add routes for `/api/pc-sessions`, `/api/pc-sessions/{conversation_id}/transcript`, `/api/pc-sessions/{conversation_id}/resume` (spawns PTY session in workspace with `agy -r <conversation_id>`), and `/api/pc-sessions/new`.

- [ ] **Step 4: Run test to verify it passes**
  Run: `.venv\Scripts\pytest tests/test_server_endpoints.py -v`
  Expected: PASS

- [ ] **Step 5: Commit**
  ```bash
  git add server.py tests/test_server_endpoints.py
  git commit -m "feat: add pc sessions and resume endpoints to server"
  ```

---

### Task 3: Mobile Dashboard & Transcript Inspector in `static/index.html`

**Files:**
- Modify: `static/index.html`

**Interfaces:**
- Consumes: `/api/pc-sessions`, `/api/pc-sessions/{id}/transcript`, `/api/pc-sessions/{id}/resume`
- Produces:
  - Tab switcher: `[🖥️ PC Sessions]` | `[⌨️ Terminal]`
  - Sessions View:
    - Search & filter bar
    - Running vs Idle session cards
    - Transcript drawer / modal showing dialogue turns
    - "Resume in Terminal" action button that switches to Terminal tab connected to that session
  - Live auto-refresh polling every 6 seconds when Sessions tab is active

- [ ] **Step 1: Update UI layout and CSS in `static/index.html`**
  Add top navigation tabs, session card styling, transcript modal styling, and active badge counter.

- [ ] **Step 2: Add client-side logic to fetch and render PC sessions**
  Render list of sessions with status pills, relative time, step count, and workspace paths. Implement transcript modal viewer and one-tap resume handler.

- [ ] **Step 3: Verify frontend in browser / headless check**
  Run test script to verify HTML syntax, scripts, and API contracts.

- [ ] **Step 4: Commit**
  ```bash
  git add static/index.html
  git commit -m "feat: add mobile pc sessions tracker and transcript inspector to UI"
  ```

---

### Task 4: Launcher, Firewall Verification & Full Integration Test

**Files:**
- Modify: `start_agy_remote.bat`
- Modify: `README.md`
- Test: Full integration test script `tests/test_integration.py`

- [ ] **Step 1: Write integration test `tests/test_integration.py`**
  Verify the full flow: start FastAPI test server, list real sessions from PC DB, fetch transcript of current conversation, trigger resume session, verify websocket stream.

- [ ] **Step 2: Run integration tests**
  Run: `.venv\Scripts\pytest tests/test_integration.py -v`
  Expected: PASS

- [ ] **Step 3: Update `start_agy_remote.bat` & `README.md`**
  Ensure batch file detects IP, supports backgrounding/starting cleanly, prints the QR code and URL clearly, and documents how to access from phone.

- [ ] **Step 4: Commit**
  ```bash
  git add start_agy_remote.bat README.md tests/test_integration.py
  git commit -m "feat: finalize launcher, documentation, and integration tests"
  ```
