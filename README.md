# FRIDAY Multi-Agent Ecosystem

An enterprise-grade autonomous developer CLI agent and distributed multi-agent coordination ecosystem built with Python, AsyncIO, and modern Large Language Models.

---

## Architecture Overview

The ecosystem is designed with strict boundary isolation, reactive messaging, and automated verification loops:

```
AI-Agents/
├── Friday/                  # Autonomous Developer CLI Agent & TUI
│   ├── friday/              # Core agent engine, tools, event bus, and UI
│   ├── tests/               # Comprehensive test suites (120+ unit/integration tests)
│   ├── docs/                # Architecture design specs & implementation plans
│   └── pyproject.toml
│
├── Jarvis/                  # Autonomous Background Execution Worker
│   ├── jarvis/              # IPC consumer, code executor, and background daemon
│   └── pyproject.toml
│
├── Shared/                  # Multi-Agent Coordination Infrastructure
│   ├── mailboxes/           # File-based IPC message queues
│   ├── state/               # Distributed task manifests and process tracking
│   └── memory/              # Shared persistence and long-term memory
│
└── Logs/                    # Centralized execution & telemetry logs (git-ignored)
```

---

## Core Tenets & Capabilities

1. **Mandatory Verification & Self-Repair:**
   * FRIDAY never assumes code is done just because it was generated.
   * Automated verification (syntax, linters, `pytest`) runs after edits, entering a bounded self-repair loop on failure.
2. **Strict Workspace Isolation (Jail):**
   * Target projects remain strictly isolated from FRIDAY's own codebase and neighboring agents. Path traversal and unauthorized directory escapes raise security exceptions.
3. **Decoupled Reactive EventBus:**
   * High-performance asynchronous event bus decoupling the Rich/Prompt-Toolkit TUI from agent reasoning and tool execution.
4. **Multi-LLM Routing & Resilient Fallback:**
   * Automatic provider failover (Gemini, Groq, Ollama) handling rate limits and context budgeting smoothly.
5. **Interactive Remote Control & Observability:**
   * 4-tier interactive approval via Telegram Daemon and live Web Observability Dashboard.

---

## Quickstart

### Prerequisites
* Python 3.11+
* Git

### Installation

Clone the repository:
```bash
git clone https://github.com/MBrkyAydn/Friday-Private.git
cd Friday-Private
```

Install the FRIDAY CLI package in editable mode:
```bash
cd Friday
pip install -e .
```

### Running Tests
Verify the entire test suite:
```bash
pytest
```

### Usage
Start the interactive developer CLI:
```bash
friday
```

Or execute a single prompt within a target directory:
```bash
friday run /path/to/project --prompt "Refactor authentication module and verify tests"
```

---

## Security & Privacy
* All credentials, API tokens, and local environment variables (`.env`) are strictly isolated and git-ignored.
* Inter-agent communication is sandboxed locally through `Shared/` protocols.

## License
MIT License.
