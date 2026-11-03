# FRIDAY CLI: Autonomous AI Coding & Workflow Automation Engine
## Architectural Design Specification

- **Date:** 2026-09-30
- **Status:** Approved
- **Target Platform:** Windows / Cross-platform (Python 3.13+)
- **System Type:** Autonomous Developer CLI Agent & Multi-Agent Node

---

## 1. Executive Summary & Vision

**FRIDAY** is an autonomous AI coding and workflow automation system built as an interactive developer CLI. Designed to deliver a streamlined developer experience similar to modern terminal coding agents, FRIDAY operates natively within the developer's terminal to accept natural-language instructions, inspect codebases, execute shell commands, perform precision code editing, run builds and tests, and coordinate background subagents.

### Non-Negotiable Core Tenets
1. **Mandatory Verification & Self-Repair:** FRIDAY never declares a task `DONE` solely because code was written. It must execute automated verification (builds, tests, linters). On failure, it enters an iterative self-repair loop up to a bounded retry limit. If repairs fail, it reports `BLOCKED` with full failure traces and diagnostics instead of claiming success.
2. **Strict Target Project Isolation:** FRIDAY's own source repository is completely distinct from the projects it operates on. File tools and shell execution are anchored strictly to the designated target project.
3. **Multi-Agent Boundary Enforcement:** Within the broader `D:\AI-Agents\` ecosystem (`Friday`, `Jarvis`, `Shared`, `Logs`), FRIDAY and JARVIS must never directly modify each other's workspaces. All cross-agent communication occurs strictly through `Shared/`, and system telemetry routes to `Logs/`.
4. **Reactive Decoupled Kernel:** Terminal rendering, agent reasoning, tool execution, and subagent workers communicate via an asynchronous `EventBus`.

---

## 2. Multi-Agent Directory Topology & Boundary Architecture

```
D:\AI-Agents\
├── Friday\                  # FRIDAY Source Code & Agent Engine
│   ├── friday/              # Core Python package
│   ├── tests/               # Test suites
│   ├── docs/specs/          # Design specifications
│   └── pyproject.toml
│
├── Jarvis\                  # JARVIS Agent Workspace (Strictly Isolated)
│   └── ...                  # Forbidden for FRIDAY to write directly
│
├── Shared\                  # Multi-Agent Coordination Infrastructure
│   ├── mailboxes\           # Inter-agent message queues (e.g. friday_inbox, jarvis_inbox)
│   ├── state\               # Distributed task manifests & shared registries
│   └── artifacts\           # Shared handoff documents and diffs
│
└── Logs\                    # Centralized Execution & Telemetry Logs
    ├── friday\              # FRIDAY session traces and structured run logs
    ├── jarvis\              # JARVIS session traces
    └── audit.log            # Multi-agent event timeline
```

### Isolation & Permission Rules
* **Target Workspace Parameter:** When FRIDAY runs, it accepts a target project directory (`friday run [PATH]` or `friday --project-dir [PATH]`, default: current working directory).
* **Workspace Jail:** All file system tools (`view_file`, `write_file`, `edit_file`) and shell execution (`run_command`) resolve relative to the target project directory. Attempting to modify paths outside the target project without explicit confirmation will be rejected.
* **Agent Mutual Exclusion:** FRIDAY's path guard explicitly rejects file modification requests pointing to `D:\AI-Agents\Jarvis\` or other agent source directories.
* **Inter-Agent Protocol:** FRIDAY communicates with external agents only by writing typed JSON messages to `D:\AI-Agents\Shared\mailboxes\` or reading assigned tasks from the shared directory.

---

## 3. System Architecture & Component Design

```
┌────────────────────────────────────────────────────────────────────────┐
│                        Terminal User Interface                         │
│       Prompt Toolkit REPL  │  Rich Streaming Display & Live Diffs      │
└───────────────────────────────────▲────────────────────────────────────┘
                                    │ (Events, Keystrokes, Prompts)
┌───────────────────────────────────▼────────────────────────────────────┐
│                       Async Event Bus (Kernel)                         │
├────────────────────┬────────────────────┬──────────────────────────────┤
│    Lead Agent      │   Subagent Pool    │    Tool Registry & Gates     │
│ (ReAct Controller) │(Worker Tasks: R/C/T│ (Filesystem, Shell, Git, RG) │
├────────────────────┴────────────────────┴──────────────────────────────┤
│                 Mandatory Verification & Self-Repair Loop              │
├────────────────────────────────────────────────────────────────────────┤
│                 Workspace Jail & Permission Controller                 │
└────────┬────────────────────────┬──────────────────────┬───────────────┘
         │                        │                      │
         ▼                        ▼                      ▼
    LLM Gateway           Target Workspace       Shared Multi-Agent
(LiteLLM Multi-Model)    (User Project Dir)     (D:\AI-Agents\Shared)
```

### 3.1. Async Event Bus (`friday/core/bus.py`)
Decouples UI rendering from core execution. Events include:
* `UserPromptEvent`: User entered input in REPL.
* `AgentThoughtEvent`: Intermediate reasoning tokens or steps.
* `StreamChunkEvent`: Live LLM response tokens.
* `ToolCallRequestedEvent`: Tool invocation requested by LLM.
* `PermissionPromptEvent`: Tiered security check requiring user confirmation.
* `ToolResultEvent`: Output from tool execution.
* `SubagentSpawnEvent` / `SubagentProgressEvent` / `SubagentDoneEvent`: Subagent lifecycle notifications.
* `VerificationStartedEvent` / `VerificationPassedEvent` / `VerificationFailedEvent`: Test execution states.
* `TaskDoneEvent` / `TaskBlockedEvent`: Final terminal lifecycle statuses.

### 3.2. Lead Agent Orchestrator (`friday/agent/lead.py`)
* Implements an asynchronous ReAct (Reason + Act) loop.
* Interacts with LiteLLM (supporting Gemini, Anthropic Claude, OpenAI, DeepSeek, and Ollama).
* Constructs prompts containing project instructions (e.g. `FRIDAY.md` in the target project), tool schemas, and recent conversation turns.
* Manages context window pruning (`friday/agent/context.py`) when token usage exceeds configured watermarks (75% threshold).

### 3.3. Subagent Pool (`friday/agent/subagents/`)
Specialized background agents running as isolated `asyncio.Task` instances with independent context windows:
1. **`researcher`**: Read-only access to files, ripgrep search, and web search. Performs codebase exploration and returns structured summaries to the lead agent without polluting its context.
2. **`coder`**: Executes bounded code modifications in specific files or components.
3. **`tester`**: Runs test runners and build commands, parsing output into structured failure summaries.

---

## 4. Mandatory Verification & Self-Repair Engine

```
[Code Implementation or Change Completed]
                   │
                   ▼
       [Automated Verification Phase]
   (Runs detected build, test runner, linters)
                   │
        ┌──────────┴──────────┐
        │                     │
[All Tests Pass]      [Failures Detected]
        │                     │
        ▼                     ▼
  Status: DONE        [Self-Repair Diagnosis]
                              │
                              ▼
                      [Apply Targeted Fix]
                              │
                    (Retries < Max Retries?)
                      ├── YES ──> [Re-run Verification Phase]
                      └── NO  ──> Status: BLOCKED
                                  (Report failure trace & attempts)
```

### 4.1. Contract
1. **Never Declare DONE on Write:** Writing or modifying files is an unverified intermediate state.
2. **Auto-Detection of Test Frameworks:** Inspects the target workspace for:
   * Python: `pytest`, `python -m unittest`
   * Node/TypeScript: `npm test`, `pnpm test`, `yarn test`
   * Rust: `cargo test`
   * Go: `go test ./...`
   * Custom: User-defined command in `.friday/config.yaml` or via `/verify <cmd>`.
3. **Self-Repair Loop (`friday/core/verifier.py`):**
   * If verification fails, captures exit code, stdout, and stderr.
   * Prompts the agent with the exact failure trace and asks for a root-cause diagnosis and repair diff.
   * Applies the repair and re-executes verification.
   * **Bounded Retries:** Default `3` retries.
4. **Terminal Outcomes:**
   * **`DONE`**: Emitted only when code has passed all verification checks with evidence.
   * **`BLOCKED`**: Emitted when retries expire or non-repairable environment/dependency issues occur. Displays failure analysis, traces, and attempted fixes to the user.

---

## 5. Security & Permission Architecture

### 5.1. Tiered Permissions (`friday/core/permissions.py`)
* **Tier 0 (Safe / Auto-Approved):** Read-only inspection (`view_file`, `search_code`, `git_status`, directory listing). Runs without prompting.
* **Tier 1 (Guarded):** Target project file writes (`edit_file`, `write_file`) and verification commands (`pytest`, `npm test`). Prompts user with interactive diff and `[y/n/always]` unless `--yolo` is enabled.
* **Tier 2 (Destructive):** High-risk shell commands (`rm`, `git reset --hard`, network requests, destructive scripts). Prompts user regardless of standard settings unless `--dangerously-skip-permissions` is passed.
* **Prohibited Tier:** Any write targeting `D:\AI-Agents\Jarvis\` or other agent home directories is strictly blocked.

---

## 6. Terminal UI & Interaction Design

### 6.1. Interactive Prompt Toolkit REPL (`friday/ui/repl.py`)
* Prompt format: `FRIDAY [target-project-name] ❯ `
* Slash commands:
  * `/verify` — Explicitly trigger verification suite.
  * `/model <name>` — Switch active LLM on the fly.
  * `/subagents` — List running background subagent tasks.
  * `/yolo` — Toggle auto-approval mode.
  * `/status` — Display token consumption, cost, target workspace, and git branch.
  * `/clear` — Clear terminal screen.
  * `/reset` — Reset conversation history.
  * `/help` — View commands and shortcuts.

### 6.2. Rich Live Renderer (`friday/ui/renderer.py`)
* Live markdown streaming.
* Animated spinners for thought and reasoning states.
* Collapsible tool execution panels showing arguments and run duration.
* Unified colorized diffs (additions in green, deletions in red) for proposed file changes.
* Visual status banners:
  * Bold Green: `[DONE] Verification passed (42 tests, 0 failures)`
  * Bold Red: `[BLOCKED] Verification failed after 3 repair attempts. Reason: ...`

---

## 7. Directory & Module Layout

```
Friday/
├── pyproject.toml
├── README.md
├── docs/
│   └── superpowers/
│       └── specs/
│           └── 2026-09-30-friday-cli-design.md
├── friday/
│   ├── __init__.py
│   ├── cli.py               # CLI entrypoint (Typer/Click)
│   ├── core/
│   │   ├── __init__.py
│   │   ├── bus.py           # Async EventBus & typed events
│   │   ├── config.py        # Settings & YAML configuration
│   │   ├── workspace.py     # Target project isolation & path guard
│   │   ├── session.py       # Session history & state persistence
│   │   ├── permissions.py   # Tiered permission gates
│   │   ├── verifier.py      # Mandatory verification & self-repair loop
│   │   └── shared_bus.py    # D:\AI-Agents\Shared coordination protocol
│   ├── agent/
│   │   ├── __init__.py
│   │   ├── lead.py          # Lead orchestrator (ReAct loop)
│   │   ├── context.py       # Context window budgeting & compaction
│   │   ├── llm.py          # LiteLLM streaming client with fallback
│   │   └── subagents/
│   │       ├── __init__.py
│   │       ├── base.py      # Base subagent worker
│   │       ├── pool.py      # Background task pool manager
│   │       ├── researcher.py# Read-only exploration agent
│   │       ├── coder.py     # Code modification agent
│   │       └── tester.py    # Test runner agent
│   ├── tools/
│   │   ├── __init__.py
│   │   ├── base.py          # Base tool definition & registry
│   │   ├── filesystem.py    # view_file, edit_file, write_file (jailed)
│   │   ├── shell.py         # run_command with timeouts & streaming
│   │   ├── search.py        # search_code (ripgrep/regex)
│   │   └── git.py           # git status, diff, commit
│   └── ui/
│       ├── __init__.py
│       ├── repl.py          # Prompt Toolkit interactive shell
│       ├── renderer.py      # Rich live display, diffs, tool panels
│       └── prompts.py       # Interactive confirmation dialogs
└── tests/
    ├── conftest.py
    ├── test_bus.py          # Event bus async pub/sub
    ├── test_workspace.py    # Workspace jail & isolation enforcement
    ├── test_permissions.py  # Tiered security checks & yolo bypass
    ├── test_verifier.py     # Verification state machine (DONE vs BLOCKED)
    ├── test_tools.py        # Jailed file and shell tool tests
    └── test_lead_agent.py   # End-to-end agent orchestration loop
```

---

## 8. Verification & Testing Strategy for FRIDAY

### 8.1. Unit Tests
* **`test_bus.py`:** Tests event publication, subscription, filtering, and ordering in async environments.
* **`test_workspace.py`:** Tests that path resolution blocks traversal out of the target workspace into `D:\AI-Agents\Jarvis\` or other forbidden roots.
* **`test_permissions.py`:** Tests auto-approval of safe reads, blocking of unconfirmed writes, and `--yolo` behavior.
* **`test_verifier.py`:** Tests state transitions:
  * Successful run $\to$ `DONE`.
  * Failure $\to$ self-repair $\to$ pass $\to$ `DONE`.
  * Failure $\to$ retries exhausted $\to$ `BLOCKED` with diagnostic report.
* **`test_tools.py`:** Tests atomic file writes, line-slice reading, and shell timeout enforcement.

### 8.2. Integration Tests
* **End-to-End Simulation:** Runs the lead agent loop against a mock LLM gateway on a temporary mock project, confirming that file editing initiates the automated verification loop and does not emit `DONE` until the test suite passes.
