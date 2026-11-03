# Pixel Agents Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Integrate Pixel Agents (`pixel-agents`) with FRIDAY and JARVIS to visualize multi-agent activity as an animated 2D pixel-art office in real time, with non-blocking event dispatching and resilient fail-open behavior.

**Architecture:** A lightweight `PixelAgentsBridge` subscribes to FRIDAY's typed `EventBus`. It checks `~/.pixel-agents/server.json` for active server connection details and enqueues events into an internal `asyncio.Queue`. A background worker translates and dispatches normalized HTTP POST hook requests to `http://127.0.0.1:{port}/api/hooks/claude`. A new Typer CLI group (`friday office start/stop/status`) manages the standalone pixel office process.

**Tech Stack:** Python 3.11+, Typer, asyncio, httpx, pydantic, pytest, pytest-asyncio, Node.js (`npx pixel-agents`).

**Spec:** `docs/superpowers/specs/2026-10-08-pixel-agents-integration-design.md`

## Global Constraints
- Python 3.11+ compatibility on Windows.
- Zero latency impact on FRIDAY's primary reasoning and execution loops (non-blocking async queue).
- Fail-open resilience: If Pixel Agents is offline or unresponsive, all calls degrade silently without raising exceptions or logging spam.
- Strict workspace boundary: Code lives in `D:\AI-Agents\Friday`.

## Review Focus
- Pixel Agents server is not running: bridge must detect missing `server.json` and skip HTTP calls without throwing or delaying.
- Event queue saturation: under high event volume, the internal queue drops oldest events cleanly instead of blocking.
- `delegate_jarvis` tool calls: must translate to `SubagentStart` (agent_type="Jarvis", run_in_background=True) and `SubagentStop` so JARVIS spawns as his own animated character.
- `PermissionPromptEvent`: must map to `PermissionRequest` to trigger the character's hand-raise and permission bubble.
- Process cleanup on `friday office stop`: cleanly kills the detached `npx pixel-agents` Node process without orphan leaks.

---

### Task 1: Pixel Agents Bridge & Event Translation Engine

**Files:**
- Create: `D:\AI-Agents\Friday\friday\visual\__init__.py`
- Create: `D:\AI-Agents\Friday\friday\visual\pixel_bridge.py`
- Create: `D:\AI-Agents\Friday\tests\test_pixel_bridge.py`

**Interfaces:**
- Consumes: `friday.core.bus.EventBus`, `friday.core.bus.Event` (and subclasses: `ToolCallRequestedEvent`, `ToolResultEvent`, `PermissionPromptEvent`, `TaskDoneEvent`, `UserPromptEvent`).
- Produces: `PixelAgentsBridge(bus, workspace_path, provider="claude")`
  - `start() -> None`: starts background queue worker.
  - `stop() -> None`: flushes queue and closes HTTP client.
  - `is_connected() -> bool`: checks if Pixel Agents server is detected and responding.

- [ ] **Step 1: Write the failing unit tests for PixelAgentsBridge**

Write `tests/test_pixel_bridge.py` testing:
1. `test_server_config_discovery`: Reads `~/.pixel-agents/server.json` mock file, extracts port and token.
2. `test_event_translation_tool_and_subagent`: Translates `ToolCallRequestedEvent` (generic tool vs `delegate_jarvis`) into `PreToolUse` and `SubagentStart`.
3. `test_event_translation_permission`: Translates `PermissionPromptEvent` into `PermissionRequest`.
4. `test_event_translation_task_done`: Translates `TaskDoneEvent` into `Stop`.
5. `test_fail_open_when_offline`: When `server.json` does not exist or server returns connection error, bridge drops events without raising exceptions.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pixel_bridge.py -v`  
Expected: FAIL (ModuleNotFoundError: No module named 'friday.visual')

- [ ] **Step 3: Implement `friday.visual.pixel_bridge`**

Create `friday/visual/__init__.py` and `friday/visual/pixel_bridge.py`:
- `PixelAgentsBridge` class with async worker task and `httpx.AsyncClient`.
- Method `read_server_config() -> Optional[Tuple[int, str]]`.
- Method `post_event(payload: dict) -> None`.
- EventBus handlers for `ToolCallRequestedEvent`, `ToolResultEvent`, `PermissionPromptEvent`, `TaskDoneEvent`, `UserPromptEvent`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pixel_bridge.py -v`  
Expected: 5 passed (100% PASS).

- [ ] **Step 5: Commit**

```bash
git add friday/visual/ tests/test_pixel_bridge.py
git commit -m "feat(visual): implement PixelAgentsBridge event translation engine"
```

---

### Task 2: Runtime Wiring & Session Lifecycle Integration

**Files:**
- Modify: `D:\AI-Agents\Friday\friday\cli.py`
- Modify: `D:\AI-Agents\Friday\friday\agent\lead.py`
- Create: `D:\AI-Agents\Friday\tests\test_pixel_runtime_wiring.py`

**Interfaces:**
- Consumes: `PixelAgentsBridge` from `friday.visual.pixel_bridge`.
- Produces: Runtime with automatic `PixelAgentsBridge` lifecycle attached to `setup_runtime(workspace_root)`.

- [ ] **Step 1: Write failing integration test for runtime wiring**

Create `tests/test_pixel_runtime_wiring.py`:
- Test that `setup_runtime` initializes `PixelAgentsBridge` and attaches it to the `EventBus`.
- Test that executing a prompt emits `SessionStart` and `ToolCallRequestedEvent` reaches the bridge worker.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_pixel_runtime_wiring.py -v`  
Expected: FAIL (Bridge not registered in runtime).

- [ ] **Step 3: Wire PixelAgentsBridge into `friday/cli.py`**

In `setup_runtime`:
- Instantiate `PixelAgentsBridge(bus=bus, workspace_path=workspace_root)`.
- Start the bridge background worker.
- Register bridge cleanup on exit.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_pixel_runtime_wiring.py -v`  
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add friday/cli.py tests/test_pixel_runtime_wiring.py
git commit -m "feat(runtime): wire PixelAgentsBridge into setup_runtime"
```

---

### Task 3: CLI Commands (`friday office start / stop / status`)

**Files:**
- Modify: `D:\AI-Agents\Friday\friday\cli.py`
- Create: `D:\AI-Agents\Friday\tests\test_cli_office.py`

**Interfaces:**
- Produces: CLI commands:
  - `friday office start [--port 3100] [--no-browser]`
  - `friday office stop`
  - `friday office status`

- [ ] **Step 1: Write failing CLI tests**

Create `tests/test_cli_office.py`:
- Test `friday office status` when server is offline: prints helpful message and exit code 0.
- Test `friday office status` when mock `server.json` and health endpoint exist: prints running status, port, and token.
- Test `friday office stop`: cleans up PID file.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli_office.py -v`  
Expected: FAIL (No such command 'office').

- [ ] **Step 3: Implement `office` command group in `friday/cli.py`**

- Create `office_app = typer.Typer(name="office", help="Manage Pixel Agents visual office")`.
- `friday office start`: spawns `npx.cmd pixel-agents --port <port>`, writes PID to `.pixel_office.pid`, waits for `~/.pixel-agents/server.json`, opens browser.
- `friday office stop`: reads PID and terminates process cleanly.
- `friday office status`: displays active port, URL, token, and health check.
- Register `app.add_typer(office_app, name="office")`.

- [ ] **Step 4: Run tests to verify all pass**

Run: `python -m pytest tests/test_cli_office.py -v`  
Expected: 3 passed (100% PASS).

- [ ] **Step 5: Commit**

```bash
git add friday/cli.py tests/test_cli_office.py
git commit -m "feat(cli): add friday office start, stop, and status commands"
```

---

### Task 4: Full Suite Regression & End-to-End Verification

**Files:**
- Existing test suite in `D:\AI-Agents\Friday\tests`.

- [ ] **Step 1: Run full test suite regression**

Run: `python -m pytest` across all test suites in `D:\AI-Agents\Friday`.  
Expected: All 190+ tests pass with 0 failures.

- [ ] **Step 2: Live end-to-end smoke verification**

Verify `friday office status` in terminal.  
Verify that running `friday task run "echo test"` succeeds without visual errors.

- [ ] **Step 3: Final Commit & Tag**

```bash
git commit -am "chore: complete Pixel Agents integration and verify full test suite"
```
