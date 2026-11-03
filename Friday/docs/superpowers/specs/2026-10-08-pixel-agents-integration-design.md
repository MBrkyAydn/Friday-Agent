# FRIDAY & JARVIS — Pixel Agents Integration Design Specification
**Date:** 2026-10-08  
**Topic:** Real-Time Pixel Art Office Visualization via Pixel Agents Bridge  
**Target:** `D:\AI-Agents\Friday` & `D:\AI-Agents\Jarvis`  

---

## 1. Executive Summary & Intent
Pixel Agents (`https://github.com/pixel-agents-hq/pixel-agents`) transforms AI coding agents running in terminals into animated 2D pixel-art characters working in a virtual office.
The goal of this subsystem is to seamlessly connect FRIDAY (Lead/Orchestrator Agent) and JARVIS (Worker Specialist Agent) to Pixel Agents with maximum performance, zero latency impact on the core agent execution loops, and complete resilience (fail-open degradation if the visualization server is offline).

---

## 2. Architecture & Components

```
┌────────────────────────────────────────────────────────┐
│                   FRIDAY Runtime                       │
│                                                        │
│  ┌──────────────┐      EventBus      ┌──────────────┐  │
│  │  Lead Agent  │ ──────────────────►│ PixelAgents  │  │
│  │   & Jarvis   │   (Async Pub/Sub)  │    Bridge    │  │
│  └──────────────┘                    └──────┬───────┘  │
└─────────────────────────────────────────────┼──────────┘
                                              │ In-Memory Queue
                                              │ Non-blocking
                                              ▼
                                   ┌──────────────────────┐
                                   │ Async Worker Task    │
                                   └──────────┬───────────┘
                                              │ HTTP POST /api/hooks/claude
                                              │ Authorization: Bearer <token>
                                              ▼
                                   ┌──────────────────────┐
                                   │ Pixel Agents Server  │
                                   │ (Fastify localhost)  │
                                   └──────────┬───────────┘
                                              │ WebSocket / Canvas
                                              ▼
                                   ┌──────────────────────┐
                                   │ Pixel Art Office UI  │
                                   │ (Browser / VS Code)  │
                                   └──────────────────────┘
```

### 2.1 Core Components
1. **`friday.visual.pixel_bridge.PixelAgentsBridge`**:
   - Subscribes to FRIDAY's `EventBus`.
   - Discovers active Pixel Agents server by reading `~/.pixel-agents/server.json` (auto-detects port & Bearer token).
   - Buffers normalized hook events in an internal `asyncio.Queue`.
   - Sends HTTP POST requests asynchronously to `http://127.0.0.1:{port}/api/hooks/claude` without blocking FRIDAY.
   - Health check with automatic fallback: If the server is unreachable or offline, drops events silently without raising exceptions or logging spam.
2. **`friday.cli.office` (CLI Commands)**:
   - `friday office start`: Launches `npx pixel-agents --port 3100` as a detached background daemon and opens `http://127.0.0.1:3100` in the default web browser.
   - `friday office stop`: Terminates the background daemon cleanly.
   - `friday office status`: Inspects `~/.pixel-agents/server.json` and checks `/api/health` to report live status.
3. **Event Mapping Engine**:
   - Translates FRIDAY's internal events (`ToolCallRequestedEvent`, `ToolResultEvent`, `PermissionPromptEvent`, `TaskDoneEvent`) into canonical Pixel Agents hook payloads (`SessionStart`, `PreToolUse`, `PostToolUse`, `PermissionRequest`, `SubagentStart`, `SubagentStop`, `Stop`).

---

## 3. Event Mapping Specification

| FRIDAY Event | Condition / Data | Pixel Agents Hook Payload | Character Animation in Office |
| :--- | :--- | :--- | :--- |
| **Turn Started / Init** | `session_id`, `cwd` | `hook_event_name: "SessionStart"` | FRIDAY spawns and sits at the desk. |
| **Tool Call Requested** | Generic tool (Bash, Read, Write, etc.) | `hook_event_name: "PreToolUse"`, `tool_name`, `tool_input` | Character types on keyboard; activity label displays action. |
| **JARVIS Delegated** | `tool_name == "delegate_jarvis"` | `hook_event_name: "SubagentStart"`, `agent_type: "Jarvis"`, `run_in_background: true` | JARVIS character spawns, walks to his desk, and sits down. |
| **Permission Requested** | Tier 2 approval / confirmation | `hook_event_name: "PermissionRequest"` | Character raises hand; permission speech bubble appears. |
| **Tool Completed** | Generic tool | `hook_event_name: "PostToolUse"` | Tool activity clears; character returns to idle typing. |
| **JARVIS Finished** | `tool_name == "delegate_jarvis"` completed | `hook_event_name: "SubagentStop"` | JARVIS finishes task and despawns or transitions to idle. |
| **Task Done** | `TaskDoneEvent` | `hook_event_name: "Stop"` | Done notification badge; character celebrates/relaxes. |
| **Waiting for Prompt** | REPL idle prompt | `hook_event_name: "Notification"`, `notification_type: "idle_prompt"` | Character displays thinking / idle bubble. |

---

## 4. Performance & Reliability Guarantees
1. **Zero Latency Impact:** Event delivery happens on a dedicated background worker task using an `asyncio.Queue(maxsize=100)`. If the queue is full or server is slow, stale events are dropped without stalling the LLM or tool executor.
2. **Silent Failure & Fail-Open:** If `server.json` does not exist or network connection fails, `PixelAgentsBridge` marks itself inactive for a cooldown period (e.g. 5 seconds) and returns immediately.
3. **No External Heavy Dependencies:** Uses existing `httpx` and Python standard library `asyncio`, `subprocess`, `json`, `pathlib`.
4. **Seamless Dual Mode:** Works identically whether the user runs `npx pixel-agents` in a browser or uses the VS Code Pixel Agents extension.

---

## 5. Testing & Verification Plan
1. **Unit Tests (`tests/test_pixel_bridge.py`)**:
   - Mocked HTTP server testing all event translations (`SessionStart`, `PreToolUse`, `PermissionRequest`, `SubagentStart`, `Stop`).
   - Server offline test: verifies bridge degrades silently without raising exceptions.
   - Queue overflow test: verifies non-blocking behavior under high load.
2. **CLI Tests (`tests/test_cli_office.py`)**:
   - Test `friday office status` with mock and real config files.
   - Test `friday office start` process spawning parameters.
3. **Integration Verification**:
   - Start pixel agents, run end-to-end task in FRIDAY workspace, confirm HTTP event receipt on `/api/hooks/claude`, verify status code 200 responses.
