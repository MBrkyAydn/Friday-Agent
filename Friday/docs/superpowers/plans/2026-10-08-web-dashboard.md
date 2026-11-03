# Web Observability Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a zero-compile, high-performance, dark-mode Web Observability Dashboard for FRIDAY and JARVIS using FastAPI, WebSockets, and HTML5/Tailwind, providing real-time log streaming, mailbox inspection, agent metrics, and interactive command execution.

**Architecture:** A FastAPI server exposes REST endpoints and a `/ws` WebSocket endpoint. A `DashboardBusBridge` translates FRIDAY `EventBus` events into live WebSocket messages. An ultra-responsive single-page HTML application rendered with Tailwind CSS provides live consoles, agent status cards, and mailbox feeds. The background daemon is controlled via `friday dashboard start/stop/status`.

**Tech Stack:** Python 3.11+, FastAPI, Uvicorn, WebSockets, Typer, pytest, pytest-asyncio, httpx.

**Spec:** `docs/superpowers/specs/2026-10-08-web-dashboard-design.md`

## Global Constraints
- Python 3.11+ compatibility on Windows.
- No Node.js / npm dependencies: all backend and frontend assets load natively via Python.
- Non-blocking WebSocket broadcasting: slow or disconnected browser clients must never block FRIDAY.
- Strict workspace boundary: Code lives in `D:\AI-Agents\Friday`.

## Review Focus
- Server offline handling: CLI `friday dashboard status` cleanly identifies when server is down without exceptions.
- Disconnected WebSocket clients: client disconnection must be caught cleanly without unhandled exceptions or broadcast stalls.
- Mailbox directory missing: `GET /api/mailbox` gracefully handles missing `Shared/mailboxes` folders and returns empty lists.
- Workspace file access security: `GET /api/files` must respect workspace boundaries (WorkspaceGuard) and never read system files.
- Process cleanup on `friday dashboard stop`: cleanly kills the background uvicorn process using saved PID.

---

### Task 1: FastAPI Dashboard Server & REST Endpoints

**Files:**
- Create: `D:\AI-Agents\Friday\friday\dashboard\__init__.py`
- Create: `D:\AI-Agents\Friday\friday\dashboard\server.py`
- Create: `D:\AI-Agents\Friday\tests\test_dashboard_api.py`

**Interfaces:**
- Produces: `create_dashboard_app(workspace_path: Path, bus: Optional[EventBus] = None) -> FastAPI`
  - `GET /api/status`: returns `{ status: "ok", workspace: str, friday_state: str, jarvis_state: str, active_profile: str }`
  - `GET /api/mailbox`: returns list of messages from `D:\AI-Agents\Shared\mailboxes`
  - `GET /api/files`: returns workspace file tree and file content reader

- [x] **Step 1: Write failing unit tests for Dashboard REST API**

Write `tests/test_dashboard_api.py` using `fastapi.testclient.TestClient`:
1. `test_status_endpoint`: verifies `GET /api/status` returns status, workspace, and agent states.
2. `test_mailbox_endpoint`: verifies `GET /api/mailbox` reads messages from inbox folders.
3. `test_files_endpoint`: verifies `GET /api/files` lists files in workspace.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_api.py -v`  
Expected: FAIL (ModuleNotFoundError: No module named 'friday.dashboard')

- [x] **Step 3: Implement `friday.dashboard.server`**

Create `friday/dashboard/__init__.py` and `friday/dashboard/server.py`:
- `create_dashboard_app(workspace_path, bus)` factory.
- Endpoints: `/api/status`, `/api/mailbox`, `/api/files`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_api.py -v`  
Expected: 3 passed (100% PASS).

- [x] **Step 5: Commit**

```bash
git add friday/dashboard/ tests/test_dashboard_api.py
git commit -m "feat(dashboard): implement FastAPI core and REST endpoints"
```

---

### Task 2: WebSocket Event Broadcasting & Bus Bridge

**Files:**
- Create: `D:\AI-Agents\Friday\friday\dashboard\bus_bridge.py`
- Modify: `D:\AI-Agents\Friday\friday\dashboard\server.py`
- Create: `D:\AI-Agents\Friday\tests\test_dashboard_ws.py`

**Interfaces:**
- Consumes: `friday.core.bus.EventBus`
- Produces: `DashboardBusBridge(bus)`
  - Subscribes to `EventBus` events.
  - Broadcasts messages across all connected WebSocket clients on `/ws`.

- [x] **Step 1: Write failing WebSocket integration test**

Write `tests/test_dashboard_ws.py`:
1. Connect via `client.websocket_connect("/ws")`.
2. Publish `ToolCallRequestedEvent` and `TaskDoneEvent` on `bus`.
3. Verify client receives normalized JSON payloads (`type: "tool_start"`, `type: "task_done"`).

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_ws.py -v`  
Expected: FAIL.

- [x] **Step 3: Implement `DashboardBusBridge` and `/ws` route**

Create `friday/dashboard/bus_bridge.py`:
- `ConnectionManager` class to register and broadcast to active WebSockets.
- Event handlers normalizing `EventBus` events.
- Mount `/ws` route in `friday/dashboard/server.py`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_ws.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add friday/dashboard/bus_bridge.py friday/dashboard/server.py tests/test_dashboard_ws.py
git commit -m "feat(dashboard): implement WebSocket live event broadcasting"
```

---

### Task 3: Modern Dark-Mode SPA Frontend

**Files:**
- Create: `D:\AI-Agents\Friday\friday\dashboard\static\index.html`
- Modify: `D:\AI-Agents\Friday\friday\dashboard\server.py`
- Create: `D:\AI-Agents\Friday\tests\test_dashboard_spa.py`

**Interfaces:**
- Produces: `GET /` serving responsive HTML with:
  - Top header (workspace, profile, live badge)
  - Agent status cards (FRIDAY, JARVIS)
  - Live console / terminal panel with auto-scroll
  - Mailbox messages feed
  - Workspace file viewer modal
  - Command input bar with submit button

- [x] **Step 1: Write failing test for SPA route**

Write `tests/test_dashboard_spa.py`:
- Verify `GET /` returns status code 200 and contains `"FRIDAY & JARVIS"` and HTML elements.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_dashboard_spa.py -v`  
Expected: FAIL.

- [x] **Step 3: Create `friday/dashboard/static/index.html` and mount static route**

Create complete, polished `index.html` with Tailwind CSS, WebSocket reconnection, live logs, agent status cards, and interactive command execution. Mount `GET /` in `server.py`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_dashboard_spa.py -v`  
Expected: PASS.

- [x] **Step 5: Commit**

```bash
git add friday/dashboard/static/index.html friday/dashboard/server.py tests/test_dashboard_spa.py
git commit -m "feat(dashboard): add modern dark-mode SPA frontend"
```

---

### Task 4: CLI Integration (`friday dashboard start / stop / status`)

**Files:**
- Modify: `D:\AI-Agents\Friday\friday\cli.py`
- Create: `D:\AI-Agents\Friday\tests\test_cli_dashboard.py`

**Interfaces:**
- Produces:
  - `friday dashboard start [--port 8000] [--no-browser]`
  - `friday dashboard stop`
  - `friday dashboard status`

- [x] **Step 1: Write failing CLI tests**

Write `tests/test_cli_dashboard.py`:
- Test `friday dashboard status` when offline.
- Test `friday dashboard status` when online.
- Test `friday dashboard stop` when process is inactive.
- Test `friday dashboard start` spawns uvicorn process.

- [x] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_dashboard.py -v`  
Expected: FAIL (No such command 'dashboard').

- [x] **Step 3: Implement `dashboard_app` in `friday/cli.py`**

Create `dashboard_app = typer.Typer(help="Manage FRIDAY & JARVIS Web Observability Dashboard")`.
Implement `start`, `stop`, `status` commands and register `app.add_typer(dashboard_app, name="dashboard")`.

- [x] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_cli_dashboard.py -v`  
Expected: 4 passed (100% PASS).

- [x] **Step 5: Commit**

```bash
git add friday/cli.py tests/test_cli_dashboard.py
git commit -m "feat(cli): add friday dashboard start, stop, and status commands"
```

---

### Task 5: Full Suite Regression & End-to-End Verification

**Files:**
- Full test suite across `D:\AI-Agents\Friday\tests` and `D:\AI-Agents\Jarvis\tests`.

- [x] **Step 1: Run full regression across Friday**

Run: `python -m pytest -q` in `D:\AI-Agents\Friday`.  
Expected: 210+ passed with 0 failures.

- [x] **Step 2: Run full regression across Jarvis**

Run: `python -m pytest -q` in `D:\AI-Agents\Jarvis`.  
Expected: 19 passed with 0 failures.

- [x] **Step 3: Final Commit & Tag**

```bash
git commit -am "chore: complete Web Observability Dashboard and verify full test suite"
```
