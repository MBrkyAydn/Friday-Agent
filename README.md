<div align="center">

# 🤖 FRIDAY: Autonomous Multi-Agent AI Developer Ecosystem

**An enterprise-grade autonomous developer CLI agent and distributed multi-agent system built with Python 3.11+, AsyncIO, and reactive event-driven architecture.**

[![Python](https://img.shields.io/badge/Python-3.11%2B-blue.svg?logo=python&logoColor=white)](https://www.python.org/)
[![Architecture](https://img.shields.io/badge/Architecture-Event--Driven%20%7C%20ReAct-orange.svg)](docs/superpowers/specs/2026-09-30-friday-cli-design.md)
[![Tests](https://img.shields.io/badge/Tests-120%2B%20Passing-brightgreen.svg?logo=pytest&logoColor=white)](Friday/tests/)
[![License](https://img.shields.io/badge/License-MIT-purple.svg)](LICENSE)
[![Safety](https://img.shields.io/badge/Safety-Workspace%20Jail%20%26%20Tiered%20Permissions-red.svg)](#security--workspace-jail)

[🇬🇧 English](README.md) • [🇹🇷 Türkçe](README.tr.md)

</div>

---

## 📌 Executive Summary

**FRIDAY** is an interactive, terminal-first autonomous AI coding agent designed to inspect, edit, execute, test, and self-repair real-world codebases. Inspired by state-of-the-art developer CLI agents (such as Claude Code), FRIDAY couples an asynchronous **Reactive Event Bus** with a **ReAct Lead Agent**, strict **Workspace Jail containment**, a **Subagent Worker Pool**, and a dedicated background daemon named **JARVIS**.

Unlike standard LLM code-generation scripts that blindly output snippets, FRIDAY enforces a **Mandatory Verification Contract**: *No task is ever declared completed (`DONE`) until build, syntax, and automated test suites pass.* If tests fail, FRIDAY enters an autonomous, bounded self-repair loop to fix its own regressions.

---

## 🏛️ System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                       Interactive Terminal & Web UI                         │
│     Prompt Toolkit REPL  │  Rich Streaming Display  │  FastAPI Dashboard   │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │ Async Events
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                     Reactive AsyncIO Event Bus (Kernel)                      │
│             Publish/Subscribe decouples UI, Reasoning, and I/O              │
└──────┬───────────────────────┬───────────────────────────────┬──────────────┘
       │                       │                               │
┌──────▼──────────────┐ ┌──────▼────────────────┐    ┌─────────▼──────────────┐
│  ReAct Lead Agent   │ │   Tiered Permissions   │    │  Jailed Tool Engine    │
│  - Multi-LLM Router │ │  - Read-Only (Tier 0) │    │  - Workspace Guard     │
│  - Context Compactor│ │  - Safe Execution (T1)│    │  - Shell / AST Editor  │
│  - State Machine    │ │  - Dangerous / YOLO   │    │  - Code Search / Git   │
└──────┬──────────────┘ └───────────────────────┘    └─────────┬──────────────┘
       │                                                       │
       ├─────────────────────────────────┐                     │
┌──────▼───────────────────────┐ ┌────────▼────────────────────▼──────────────┐
│     Subagent Worker Pool     │ │       Mandatory Verification Loop          │
│  - Researcher (Read-only)    │ │   Execute Target Tests / Linters           │
│  - Coder (Precision patch)   │ │   Failure -> Bounded Self-Repair (3 tries) │
│  - Tester (Pytest / Linters) │ │   Unresolved -> BLOCKED Diagnostic Report  │
└──────────────────────────────┘ └────────────────────────────────────────────┘
                                       │ IPC JSON
┌──────────────────────────────────────▼──────────────────────────────────────┐
│             Cross-Agent Shared Bus Protocol (D:\AI-Agents\Shared)           │
│     Mailbox Queues (IPC)  │  Shared State Manifests  │  FTS5 SQLite Memory  │
└──────────────────────────────────────┬──────────────────────────────────────┘
                                       │
┌──────────────────────────────────────▼──────────────────────────────────────┐
│                        JARVIS Worker Daemon (Background)                    │
│      Silent asynchronous coding agent executing delegated heavy tasks       │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 🌟 Core Tenets & Key Architectural Features

### 1. Mandatory Verification & Autonomous Self-Repair
* **Verification Contract:** FRIDAY never assumes code works simply because an LLM produced it. All modifications are followed by syntax compilation, linter passes, and targeted test execution (`pytest`, `npm test`, etc.).
* **Iterative Self-Repair:** Upon test failure, the error trace and stdout are fed back into the reasoning loop, allowing up to **3 bounded repair attempts**.
* **Failsafe BLOCKED Status:** If repairs do not resolve the issue, FRIDAY halts and generates a detailed diagnostic report (`BLOCKED`), preventing hallucinated successes.

### 2. Strict Workspace Jail (Target Isolation)
* FRIDAY distinguishes between its own source engine and the target repository it is operating on.
* All filesystem tools (`view_file`, `write_file`, `replace_file_content`) and shell commands (`run_command`) resolve strictly within a sandboxed `target_dir`.
* Directory traversal attacks (`../../`) and escapes into sensitive operating system folders are intercepted by `WorkspaceGuard`, raising immediate `SecurityError` exceptions.

### 3. Multi-Agent Shared Bus Protocol (IPC)
* FRIDAY collaborates with **JARVIS**, a dedicated background worker daemon.
* Inter-agent signaling is strictly asynchronous and decoupled via file-based mailbox queues located in `Shared/mailboxes/`.
* Agents never mutate each other's source trees directly; coordination happens entirely via typed JSON envelopes.

### 4. Multi-LLM Router & Auto-Fallback Engine
* Integrates **LiteLLM** and local **Ollama** providers.
* Configurable profiles:
  * **Gemini** (`gemini/gemini-2.5-flash`, `gemini/gemini-3.8-flash`)
  * **Groq** (`groq/openai/gpt-oss-120b`, `llama-3.3-70b-versatile`)
  * **Local Ollama** (`ollama/deepseek-r1`, `qwen2.5-coder`) for 100% offline development.
* Resilient failover: If a provider encounters a rate limit (HTTP 429), server error (503), or context window exhaustion, the router automatically fails over to the next tier without interrupting the user.

### 5. Context Budgeting & Compaction
* Enforces hard token limits to prevent context explosions on large codebases.
* In-flight token compaction summarizes prior turns and removes redundant intermediate tool outputs before token thresholds are breached.

### 6. Human-in-the-Loop & Multi-Channel Observability
* **Telegram Bot Integration:** 4-tier interactive approval cards with inline buttons (`Approve`, `Deny`, `Always Allow`, `YOLO`). Remote prompt execution and push notifications.
* **FastAPI + Vue/Vanilla Dark-Mode Dashboard:** Real-time WebSocket event streaming, live agent state monitoring, profile switching, and manual task dispatching.

---

## 📂 Repository Topology

```
AI-Agents/
├── Friday/                              # Core FRIDAY CLI Package
│   ├── friday/
│   │   ├── agent/                       # ReAct Lead Agent, LLM Provider & Subagents
│   │   ├── core/                        # EventBus, WorkspaceGuard, Permissions, Verifier
│   │   ├── dashboard/                   # FastAPI Web Observability Dashboard & WebSocket
│   │   ├── telegram/                    # Telegram daemon, 4-tier bridge, interactive prompter
│   │   ├── tools/                       # Jailed filesystem, shell, git, and search tools
│   │   └── ui/                          # Rich streaming display & Prompt Toolkit REPL
│   ├── tests/                           # 120+ unit, integration, and E2E test suites
│   ├── docs/superpowers/                # Architecture design specs & SDD implementation plans
│   └── pyproject.toml                   # Python packaging & dependencies
│
├── Jarvis/                              # JARVIS Autonomous Background Worker
│   ├── jarvis/                          # IPC mailbox listener & autonomous coder engine
│   ├── tests/                           # Unit tests for daemon and worker
│   └── pyproject.toml
│
├── Shared/                              # Multi-Agent Coordination Infrastructure
│   ├── mailboxes/                       # JSON IPC queues (friday_inbox, jarvis_inbox)
│   ├── state/                           # Daemon PID tracking and manifests
│   └── memory/                          # Persistent SQLite FTS5 long-term memory
│
├── Logs/                                # Centralized telemetry (strictly git-ignored)
├── .gitignore                           # Comprehensive secrets & cache isolation rules
└── README.md                            # Main Documentation
```

---

## 🚀 Quickstart Guide

### Prerequisites
* **Python 3.11+**
* **Git**
* *(Optional)* API keys for Gemini / Groq, or a running local **Ollama** instance.

### Installation

1. **Clone the repository:**
   ```bash
   git clone https://github.com/MBrkyAydn/Friday-Private.git
   cd Friday-Private
   ```

2. **Install FRIDAY in editable mode:**
   ```bash
   cd Friday
   pip install -e .
   ```

3. **Verify the installation:**
   ```bash
   friday --version
   ```

---

## 💻 CLI Commands & Usage

### 1. Interactive REPL Mode
Launch the interactive developer prompt inside the current directory:
```bash
friday
```

Or target a specific isolated project:
```bash
friday --project-dir /path/to/target/project
```

### 2. Single-Turn Execution (One-Shot Task)
Directly run a coding or refactoring task from your terminal:
```bash
friday -p "Refactor the authentication middleware to use JWT and verify tests pass"
```

### 3. Model Profile Switching
Switch between LLM providers dynamically:
```bash
# In CLI or REPL:
friday use gemini
friday use groq
friday use local
```

### 4. Background Web Dashboard
Start the real-time observability web dashboard:
```bash
friday dashboard start --port 8000
# Open http://localhost:8000 in your browser
```

### 5. Telegram Remote Daemon
Listen for remote commands and handle mobile permission requests:
```bash
friday telegram listen
```

---

## 🧪 Comprehensive Test Suite

FRIDAY is built using rigorous **Test-Driven Development (TDD)** and **Spec-Driven Development (SDD)**. It contains over **120 unit and integration tests** verifying every boundary:

```bash
cd Friday
pytest -v
```

### Test Coverage Highlights:
* `test_workspace.py`: Verifies directory traversal blocks, path sanitization, and symlink escape defenses.
* `test_verifier.py`: Verifies autonomous build checking, syntax validation, and the 3-step self-repair loop.
* `test_router.py`: Verifies LLM failover from primary to backup profiles on rate limits.
* `test_permissions.py`: Verifies tiered security levels and command confirmation prompts.
* `test_bus.py`: Tests asynchronous event dispatching and latency isolation.

---

## 🔒 Security & Workspace Containment

* **Zero Hardcoded Credentials:** All credentials (API keys, Telegram bot tokens, chat IDs) are strictly read from local `.env` files or environment variables.
* **Hermetic .gitignore:** Root and subdirectory `.gitignore` files prevent accidental leakage of environment files (`**/.env*`), runtime logs (`Logs/`), and temporary IPC artifacts.
* **Continuous Auditing:** Fully verified with **Gitleaks** and **Security Audit** workflows across all git commit histories.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
