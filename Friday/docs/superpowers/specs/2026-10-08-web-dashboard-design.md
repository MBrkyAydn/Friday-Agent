# FRIDAY & JARVIS — Live Web Observability Dashboard Design Specification
**Date:** 2026-10-08  
**Topic:** Real-Time Local Web Dashboard & Observability Center for FRIDAY and JARVIS  
**Target:** `D:\AI-Agents\Friday` & `D:\AI-Agents\Shared`  

---

## 1. Executive Summary & Goals
While Pixel Agents provides a playful 2D office visualization, software engineering and autonomous debugging require a rigorous, technical observability dashboard.
The goal of this subsystem is to provide a zero-compile, ultra-lightweight, local-only web dashboard powered by FastAPI and WebSockets, rendering real-time agent metrics, live terminal and test logs, inter-agent mailbox traffic, file workspace inspection, and interactive prompt/approval controls.

---

## 2. Technical Architecture & Component Structure

```
┌────────────────────────────────────────────────────────┐
│                   FRIDAY Runtime                       │
│                                                        │
│  ┌──────────────┐      EventBus      ┌──────────────┐  │
│  │  Lead Agent  │ ──────────────────►│ Dashboard    │  │
│  │   & Jarvis   │   (Async Pub/Sub)  │ Bridge       │  │
│  └──────────────┘                    └──────┬───────┘  │
└─────────────────────────────────────────────┼──────────┘
                                              │ In-Memory Queue
                                              ▼
┌────────────────────────────────────────────────────────┐
│           FastAPI & Uvicorn Dashboard Server           │
│                                                        │
│  ┌────────────────────┐     WebSocket    ┌──────────┐  │
│  │ /ws (Live Stream)  │ ◄──────────────► │ Browser  │  │
│  ├────────────────────┤     HTTP REST    │ Client   │  │
│  │ /api/status        │ ◄──────────────► │ SPA      │  │
│  │ /api/mailbox       │                  │ (HTML5 + │  │
│  │ /api/files         │                  │ Tailwind)│  │
│  │ /api/task/run      │                  │          │  │
│  │ /api/permission    │                  │          │  │
│  └────────────────────┘                  └──────────┘  │
└────────────────────────────────────────────────────────┘
```

### 2.1 Component Modules in `friday/dashboard/`
1. **`friday.dashboard.server`**:
   - FastAPI application instance.
   - Serves standalone single-page HTML application at `GET /`.
   - Exposes REST endpoints:
     - `GET /api/status`: Returns current agent states (Friday, Jarvis), active LLM profile, and workspace path.
     - `GET /api/mailbox`: Reads and returns messages from `D:\AI-Agents\Shared\mailboxes`.
     - `GET /api/files`: Lists files in current workspace with content fetching for inspection.
     - `POST /api/task/run`: Dispatches new prompt to FRIDAY lead agent asynchronously.
     - `POST /api/permission/respond`: Resolves pending permission prompt with approval or denial.
   - Exposes `GET /ws`: WebSocket endpoint broadcasting real-time events to all connected browser tabs.
2. **`friday.dashboard.bus_bridge.DashboardBusBridge`**:
   - Subscribes to FRIDAY's typed `EventBus`.
   - Normalizes events (`ToolCallRequestedEvent`, `ToolResultEvent`, `AgentThoughtEvent`, `PermissionPromptEvent`, `TaskDoneEvent`, `TaskBlockedEvent`, `LLMFallbackEvent`).
   - Broadcasts JSON payloads across active WebSocket connections without blocking the execution loop.
3. **`friday.dashboard.static.index.html`**:
   - Modern, responsive dark-mode UI styled with Tailwind CSS (CDN).
   - Component panels:
     * **Top Navigation:** Active workspace path, LLM profile, system health indicator.
     * **Agent Cards:** FRIDAY status card (idle/running/verifying) and JARVIS status card (idle/coding/testing).
     * **Live Console / Terminal Log:** High-contrast terminal log displaying tool executions, syntax checks, pytest output, and error traces.
     * **Mailbox Stream:** WhatsApp/Slack style chat feed displaying IPC messages exchanged between FRIDAY and JARVIS.
     * **Interactive Command Bar:** Input bar allowing the user to submit new natural language prompts and click `[Approve]` / `[Deny]` for Tier 2 permission prompts.
4. **`friday.cli` (`dashboard_app`)**:
   - `friday dashboard start [--port 8000] [--no-browser]`: Spawns uvicorn process in detached mode, saves PID to `.dashboard.pid`, opens browser.
   - `friday dashboard stop`: Terminates the background uvicorn process cleanly.
   - `friday dashboard status`: Checks health endpoint (`GET /api/status`) and reports server port and PID.

---

## 3. Data Flow & Event Normalization

| EventBus Event | WebSocket Broadcast Type | UI Rendering Target |
| :--- | :--- | :--- |
| `AgentThoughtEvent` | `type: "thought"` | Added to thought drawer / badge |
| `ToolCallRequestedEvent` | `type: "tool_start"` | Live Terminal: Displays command or file action |
| `ToolResultEvent` | `type: "tool_result"` | Live Terminal: Appends output, highlights errors in red |
| `PermissionPromptEvent` | `type: "permission_prompt"` | Prompts Bar: Renders prominent Approval Modal with options |
| `TaskDoneEvent` | `type: "task_done"` | Notification banner: Displays green verification pass |
| `TaskBlockedEvent` | `type: "task_blocked"` | Notification banner: Displays red blocked alert |
| `LLMFallbackEvent` | `type: "llm_fallback"` | Agent Card: Updates badge to reflect fallback to local Ollama |

---

## 4. Performance & Reliability Guarantees
1. **Zero Node/npm Dependencies:** Entire server and frontend run natively via Python (`fastapi`, `uvicorn`). No `node_modules`, no build steps, instant startup (< 500 ms).
2. **Ultra-Low Memory Footprint:** FastAPI/uvicorn server consumes ~30 MB RAM and 0% CPU when idle.
3. **Fail-Open & Non-Blocking:** WebSocket broadcast is completely async. Slow clients or disconnected browsers are discarded without slowing FRIDAY down.
4. **Clean Process Control:** PID-tracked background daemon management prevents orphan processes.

---

## 5. Testing & Verification Plan
1. **Unit & API Tests (`tests/test_dashboard_api.py`)**:
   - Test `GET /api/status`, `GET /api/mailbox`, `GET /api/files` with mock workspaces.
   - Test WebSocket broadcast: verify connected client receives normalized events.
   - Test task submission: verify `POST /api/task/run` initiates turn.
2. **CLI Tests (`tests/test_cli_dashboard.py`)**:
   - Test `friday dashboard status` when offline vs online.
   - Test `friday dashboard start` and `friday dashboard stop`.
3. **End-to-End Regression**:
   - Ensure all existing test suites in FRIDAY (200 tests) and JARVIS (19 tests) remain 100% green.
