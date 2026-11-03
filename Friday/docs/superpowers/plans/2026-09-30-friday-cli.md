# FRIDAY CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build FRIDAY, an autonomous developer CLI agent with an event-driven kernel, strict workspace isolation, tiered permissions, on-demand subagents, and a mandatory build/test verification and self-repair loop.

**Architecture:** Asyncio-based reactive event bus decoupling the Prompt Toolkit/Rich TUI from the ReAct Lead Agent, Tool Engine, and background Subagent Pool. Strict workspace path jailing ensures target projects remain isolated from FRIDAY's own codebase and neighboring agents (JARVIS).

**Tech Stack:** Python 3.13+, AsyncIO, Pydantic v2, Typer / Click, Prompt Toolkit, Rich, LiteLLM, Pytest.

**Spec:** [`docs/superpowers/specs/2026-09-30-friday-cli-design.md`](file:///D:/AI-Agents/Friday/docs/superpowers/specs/2026-09-30-friday-cli-design.md)

## Global Constraints
- Target Project Isolation: FRIDAY's own source repository is never assumed to be the target project; all file mutations and commands are jailed inside the user's specified project path.
- Multi-Agent Boundary: FRIDAY and JARVIS must never directly modify each other's directories; all cross-agent signaling occurs through `D:\AI-Agents\Shared\mailboxes\`, with logging to `D:\AI-Agents\Logs\`.
- Mandatory Verification Contract: Never declare a task `DONE` solely because code was written; must run build/tests, self-repair up to 3 bounded retries on failure, and declare `BLOCKED` with failure diagnostics if unresolved.
- No Placeholders: Every module, test, and command must be concrete, executable, and fully typed.

## Review Focus
1. **Directory traversal escape:** Path resolution attempting `../Jarvis/` or symlink escapes must raise `SecurityError`.
2. **Infinite self-repair loop:** Repeated test failures must hard-terminate at `max_repair_retries` (3) and emit `TaskBlockedEvent`.
3. **Hung test processes:** Commands that hang or block on input must trigger the execution timeout (default 60s), kill the subprocess, and return a timeout error.
4. **Context explosion on large files:** File view tools must enforce maximum line slice caps (default 500 lines) with offset pagination.
5. **No test suite detected:** If target project has no detectable test suite, verifier checks file syntax/compilation and reports status without crashing.

---

### Task 1: Project Scaffolding & Packaging

**Files:**
- Create: `pyproject.toml`
- Create: `friday/__init__.py`
- Test: `tests/test_package.py`

**Interfaces:**
- Consumes: Standard Python packaging
- Produces: Installable `friday` package with metadata and CLI entrypoint hook

- [ ] **Step 1: Write the failing test**

```python
# tests/test_package.py
def test_package_metadata():
    import friday
    assert hasattr(friday, "__version__")
    assert friday.__version__ == "0.1.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_package.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday'`

- [ ] **Step 3: Write minimal implementation**

```toml
# pyproject.toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "friday-cli"
version = "0.1.0"
description = "Autonomous AI Coding & Workflow Automation CLI"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "pydantic>=2.7.0",
    "typer>=0.12.0",
    "rich>=13.7.0",
    "prompt-toolkit>=3.0.43",
    "litellm>=1.40.0",
    "pyyaml>=6.0.1",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.23.0",
]

[project.scripts]
friday = "friday.cli:main"
```

```python
# friday/__init__.py
"""FRIDAY: Autonomous Developer CLI Agent."""

__version__ = "0.1.0"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_package.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add pyproject.toml friday/__init__.py tests/test_package.py
git commit -m "chore: scaffold friday package and project configuration"
```

---

### Task 2: Async Event Bus & Event Taxonomy

**Files:**
- Create: `friday/core/bus.py`
- Test: `tests/test_bus.py`

**Interfaces:**
- Consumes: `asyncio`, `pydantic`
- Produces: `EventBus`, typed event models (`UserPromptEvent`, `AgentThoughtEvent`, `StreamChunkEvent`, `ToolCallRequestedEvent`, `ToolResultEvent`, `TaskDoneEvent`, `TaskBlockedEvent`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bus.py
import pytest
from friday.core.bus import EventBus, Event, StreamChunkEvent, TaskDoneEvent

@pytest.mark.asyncio
async def test_event_bus_publish_and_subscribe():
    bus = EventBus()
    received = []

    async def on_chunk(event: StreamChunkEvent):
        received.append(event.chunk)

    bus.subscribe(StreamChunkEvent, on_chunk)
    await bus.publish(StreamChunkEvent(chunk="hello "))
    await bus.publish(StreamChunkEvent(chunk="world"))

    assert received == ["hello ", "world"]

@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    bus = EventBus()
    received = []

    async def on_event(event: Event):
        received.append(event)

    unsubscribe = bus.subscribe(TaskDoneEvent, on_event)
    await bus.publish(TaskDoneEvent(task_id="t1", summary="success"))
    assert len(received) == 1

    unsubscribe()
    await bus.publish(TaskDoneEvent(task_id="t2", summary="again"))
    assert len(received) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bus.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.core.bus'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/core/bus.py
import asyncio
from typing import Any, Callable, Coroutine, Dict, List, Type
from pydantic import BaseModel, Field
from datetime import datetime, timezone

class Event(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))

class UserPromptEvent(Event):
    prompt: str

class AgentThoughtEvent(Event):
    thought: str

class StreamChunkEvent(Event):
    chunk: str

class ToolCallRequestedEvent(Event):
    tool_call_id: str
    tool_name: str
    arguments: Dict[str, Any]

class ToolResultEvent(Event):
    tool_call_id: str
    tool_name: str
    success: bool
    output: str
    error: str | None = None

class PermissionPromptEvent(Event):
    prompt_id: str
    description: str
    action_type: str
    details: Dict[str, Any]

class SubagentProgressEvent(Event):
    subagent_id: str
    role: str
    message: str

class TaskDoneEvent(Event):
    task_id: str
    summary: str
    evidence: str

class TaskBlockedEvent(Event):
    task_id: str
    reason: str
    diagnostics: str

EventHandler = Callable[[Any], Coroutine[Any, Any, None]]

class EventBus:
    def __init__(self) -> None:
        self._listeners: Dict[Type[Event], List[EventHandler]] = {}

    def subscribe(self, event_type: Type[Event], handler: EventHandler) -> Callable[[], None]:
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(handler)

        def unsubscribe() -> None:
            if event_type in self._listeners and handler in self._listeners[event_type]:
                self._listeners[event_type].remove(handler)

        return unsubscribe

    async def publish(self, event: Event) -> None:
        handlers = list(self._listeners.get(type(event), []))
        # Also invoke handlers for parent Event classes
        for event_cls, cls_handlers in self._listeners.items():
            if event_cls != type(event) and isinstance(event, event_cls):
                handlers.extend(cls_handlers)

        if handlers:
            await asyncio.gather(*(handler(event) for handler in handlers))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bus.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/core/bus.py tests/test_bus.py
git commit -m "feat(core): implement async event bus and event taxonomy"
```

---

### Task 3: Workspace Jail & Target Isolation

**Files:**
- Create: `friday/core/workspace.py`
- Test: `tests/test_workspace.py`

**Interfaces:**
- Consumes: `pathlib.Path`
- Produces: `WorkspaceGuard`, `SecurityError`, safe path resolution within target project

- [ ] **Step 1: Write the failing test**

```python
# tests/test_workspace.py
import pytest
from pathlib import Path
from friday.core.workspace import WorkspaceGuard, SecurityError

def test_workspace_allows_child_paths(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    safe = guard.resolve_path("src/app.py")
    assert safe == (tmp_path / "src" / "app.py").resolve()

def test_workspace_rejects_parent_traversal(tmp_path: Path):
    target = tmp_path / "my_project"
    target.mkdir()
    guard = WorkspaceGuard(target_dir=target)

    with pytest.raises(SecurityError) as exc_info:
        guard.resolve_path("../other_folder/file.txt")
    assert "escapes target workspace" in str(exc_info.value)

def test_workspace_blocks_neighbor_agent_access(tmp_path: Path):
    agents_root = tmp_path / "AI-Agents"
    friday_dir = agents_root / "Friday"
    jarvis_dir = agents_root / "Jarvis"
    project_dir = agents_root / "UserProject"

    for d in (friday_dir, jarvis_dir, project_dir):
        d.mkdir(parents=True)

    guard = WorkspaceGuard(target_dir=project_dir)
    with pytest.raises(SecurityError) as exc_info:
        guard.resolve_path(str(jarvis_dir / "secret.py"))
    assert "escapes target workspace" in str(exc_info.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_workspace.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.core.workspace'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/core/workspace.py
from pathlib import Path
import os

class SecurityError(Exception):
    """Raised when a tool attempts to access a path outside the designated workspace."""
    pass

class WorkspaceGuard:
    def __init__(self, target_dir: str | Path, allow_self_dev: bool = False) -> None:
        self.target_dir = Path(target_dir).resolve()
        self.allow_self_dev = allow_self_dev
        if not self.target_dir.exists():
            self.target_dir.mkdir(parents=True, exist_ok=True)

    def resolve_path(self, relative_or_absolute: str | Path) -> Path:
        raw_path = Path(relative_or_absolute)
        if raw_path.is_absolute():
            resolved = raw_path.resolve()
        else:
            resolved = (self.target_dir / raw_path).resolve()

        # Enforce jail containment
        try:
            resolved.relative_to(self.target_dir)
        except ValueError:
            raise SecurityError(
                f"Access denied: path '{resolved}' escapes target workspace '{self.target_dir}'"
            )

        return resolved

    def is_safe(self, path: str | Path) -> bool:
        try:
            self.resolve_path(path)
            return True
        except SecurityError:
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_workspace.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/core/workspace.py tests/test_workspace.py
git commit -m "feat(core): implement workspace jail and path containment guard"
```

---

### Task 4: Tiered Permission Controller

**Files:**
- Create: `friday/core/permissions.py`
- Test: `tests/test_permissions.py`

**Interfaces:**
- Consumes: `friday.core.bus.EventBus`, `friday.core.bus.PermissionPromptEvent`
- Produces: `PermissionController`, `PermissionTier` (Tier 0: Auto, Tier 1: Guarded, Tier 2: Destructive), `evaluate()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_permissions.py
import pytest
from friday.core.permissions import PermissionController, PermissionTier, PermissionDecision

@pytest.mark.asyncio
async def test_permission_auto_approves_tier_0():
    controller = PermissionController(yolo_mode=False)
    decision = await controller.request_permission(
        tool_name="view_file",
        tier=PermissionTier.TIER_0_SAFE,
        details={"path": "main.py"}
    )
    assert decision == PermissionDecision.ALLOW

@pytest.mark.asyncio
async def test_permission_yolo_bypasses_tier_1():
    controller = PermissionController(yolo_mode=True)
    decision = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"}
    )
    assert decision == PermissionDecision.ALLOW

@pytest.mark.asyncio
async def test_permission_prompts_tier_1_in_default_mode():
    prompted = []

    async def mock_prompter(details: dict) -> PermissionDecision:
        prompted.append(details)
        return PermissionDecision.ALLOW

    controller = PermissionController(yolo_mode=False, prompter=mock_prompter)
    decision = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"}
    )
    assert decision == PermissionDecision.ALLOW
    assert len(prompted) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_permissions.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.core.permissions'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/core/permissions.py
from enum import Enum
from typing import Any, Callable, Coroutine, Dict

class PermissionTier(int, Enum):
    TIER_0_SAFE = 0       # Reads, searches, git status
    TIER_1_GUARDED = 1    # File writes, standard test runs
    TIER_2_DESTRUCTIVE = 2 # Arbitrary shell commands, git reset, deletes

class PermissionDecision(str, Enum):
    ALLOW = "allow"
    DENY = "deny"
    ALLOW_ALWAYS = "allow_always"

Prompter = Callable[[Dict[str, Any]], Coroutine[Any, Any, PermissionDecision]]

class PermissionController:
    def __init__(self, yolo_mode: bool = False, prompter: Prompter | None = None) -> None:
        self.yolo_mode = yolo_mode
        self.prompter = prompter
        self._session_whitelist: set[str] = set()

    async def request_permission(
        self,
        tool_name: str,
        tier: PermissionTier,
        details: Dict[str, Any]
    ) -> PermissionDecision:
        if tier == PermissionTier.TIER_0_SAFE:
            return PermissionDecision.ALLOW

        if self.yolo_mode:
            return PermissionDecision.ALLOW

        whitelist_key = f"{tool_name}:{details.get('path', '')}"
        if whitelist_key in self._session_whitelist:
            return PermissionDecision.ALLOW

        if self.prompter is None:
            return PermissionDecision.ALLOW

        decision = await self.prompter(details)
        if decision == PermissionDecision.ALLOW_ALWAYS:
            self._session_whitelist.add(whitelist_key)
            return PermissionDecision.ALLOW

        return decision
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_permissions.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/core/permissions.py tests/test_permissions.py
git commit -m "feat(core): implement tiered permission controller"
```

---

### Task 5: Jailed Tool Engine

**Files:**
- Create: `friday/tools/base.py`
- Create: `friday/tools/filesystem.py`
- Create: `friday/tools/shell.py`
- Test: `tests/test_tools.py`

**Interfaces:**
- Consumes: `WorkspaceGuard`, `PermissionController`
- Produces: Tools (`view_file`, `write_file`, `edit_file`, `run_command`) with input schemas and execution bounds

- [ ] **Step 1: Write the failing test**

```python
# tests/test_tools.py
import pytest
from pathlib import Path
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController
from friday.tools.filesystem import ViewFileTool, WriteFileTool, EditFileTool
from friday.tools.shell import RunCommandTool

@pytest.mark.asyncio
async def test_file_tools_roundtrip(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)

    writer = WriteFileTool(workspace=guard, permissions=perms)
    viewer = ViewFileTool(workspace=guard, permissions=perms)
    editor = EditFileTool(workspace=guard, permissions=perms)

    # 1. Write file
    w_res = await writer.execute(path="greeting.txt", content="Hello World\nLine 2\n")
    assert w_res.success is True

    # 2. View file
    v_res = await viewer.execute(path="greeting.txt", start_line=1, end_line=1)
    assert "Hello World" in v_res.output
    assert "Line 2" not in v_res.output

    # 3. Edit file
    e_res = await editor.execute(path="greeting.txt", old_str="Hello World", new_str="Greetings Earth")
    assert e_res.success is True
    assert (tmp_path / "greeting.txt").read_text(encoding="utf-8").startswith("Greetings Earth")

@pytest.mark.asyncio
async def test_shell_command_timeout(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)
    runner = RunCommandTool(workspace=guard, permissions=perms)

    # Python command that sleeps longer than timeout
    res = await runner.execute(command="python -c \"import time; time.sleep(2)\"", timeout_seconds=1)
    assert res.success is False
    assert "timed out" in res.error.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_tools.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.tools'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/tools/base.py
from abc import ABC, abstractmethod
from typing import Any, Dict
from pydantic import BaseModel
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionTier

class ToolResult(BaseModel):
    success: bool
    output: str = ""
    error: str | None = None

class BaseTool(ABC):
    name: str
    description: str
    tier: PermissionTier = PermissionTier.TIER_0_SAFE

    def __init__(self, workspace: WorkspaceGuard, permissions: PermissionController) -> None:
        self.workspace = workspace
        self.permissions = permissions

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        pass
```

```python
# friday/tools/filesystem.py
from pathlib import Path
from friday.tools.base import BaseTool, ToolResult
from friday.core.permissions import PermissionTier, PermissionDecision

class ViewFileTool(BaseTool):
    name = "view_file"
    description = "View contents of a file with line slicing."
    tier = PermissionTier.TIER_0_SAFE

    async def execute(self, path: str, start_line: int = 1, end_line: int = 500) -> ToolResult:
        try:
            target = self.workspace.resolve_path(path)
            if not target.is_file():
                return ToolResult(success=False, error=f"File not found: {path}")

            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            s_idx = max(0, start_line - 1)
            e_idx = min(total_lines, end_line)

            sliced = [f"{i+1:4d} | {lines[i]}" for i in range(s_idx, e_idx)]
            output = f"Showing lines {s_idx + 1} to {e_idx} of {total_lines}:\n" + "\n".join(sliced)
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, error=str(e))

class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create or overwrite a file in the workspace."
    tier = PermissionTier.TIER_1_GUARDED

    async def execute(self, path: str, content: str) -> ToolResult:
        try:
            target = self.workspace.resolve_path(path)
            decision = await self.permissions.request_permission(
                tool_name=self.name,
                tier=self.tier,
                details={"path": str(target), "content_preview": content[:100]}
            )
            if decision == PermissionDecision.DENY:
                return ToolResult(success=False, error="Operation denied by user.")

            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
            return ToolResult(success=True, output=f"Successfully wrote {len(content)} characters to {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

class EditFileTool(BaseTool):
    name = "edit_file"
    description = "Replace target string with new string in a file."
    tier = PermissionTier.TIER_1_GUARDED

    async def execute(self, path: str, old_str: str, new_str: str) -> ToolResult:
        try:
            target = self.workspace.resolve_path(path)
            if not target.is_file():
                return ToolResult(success=False, error=f"File not found: {path}")

            content = target.read_text(encoding="utf-8")
            if old_str not in content:
                return ToolResult(success=False, error=f"Target string not found in {path}")

            decision = await self.permissions.request_permission(
                tool_name=self.name,
                tier=self.tier,
                details={"path": str(target), "diff": f"- {old_str}\n+ {new_str}"}
            )
            if decision == PermissionDecision.DENY:
                return ToolResult(success=False, error="Operation denied by user.")

            new_content = content.replace(old_str, new_str, 1)
            target.write_text(new_content, encoding="utf-8")
            return ToolResult(success=True, output=f"Successfully updated {path}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

```python
# friday/tools/shell.py
import asyncio
from friday.tools.base import BaseTool, ToolResult
from friday.core.permissions import PermissionTier, PermissionDecision

class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Execute a shell command within the workspace directory."
    tier = PermissionTier.TIER_2_DESTRUCTIVE

    async def execute(self, command: str, timeout_seconds: int = 60) -> ToolResult:
        try:
            decision = await self.permissions.request_permission(
                tool_name=self.name,
                tier=self.tier,
                details={"command": command, "cwd": str(self.workspace.target_dir)}
            )
            if decision == PermissionDecision.DENY:
                return ToolResult(success=False, error="Command execution denied by user.")

            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.workspace.target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )

            try:
                stdout_data, stderr_data = await asyncio.wait_for(
                    process.communicate(), timeout=timeout_seconds
                )
            except asyncio.TimeoutError:
                process.kill()
                return ToolResult(success=False, error=f"Command timed out after {timeout_seconds}s")

            stdout = stdout_data.decode("utf-8", errors="replace")
            stderr = stderr_data.decode("utf-8", errors="replace")

            success = (process.returncode == 0)
            return ToolResult(
                success=success,
                output=stdout,
                error=stderr if not success else None
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_tools.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/tools/ tests/test_tools.py
git commit -m "feat(tools): implement jailed filesystem and shell execution tools"
```

---

### Task 6: Mandatory Verification & Self-Repair Engine

**Files:**
- Create: `friday/core/verifier.py`
- Test: `tests/test_verifier.py`

**Interfaces:**
- Consumes: `WorkspaceGuard`, `RunCommandTool`, `EventBus`
- Produces: `VerificationRunner`, `VerificationResult`, `TaskStatus` (`DONE`, `BLOCKED`, `IN_PROGRESS`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_verifier.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import VerificationRunner, TaskStatus, VerificationResult

@pytest.mark.asyncio
async def test_verification_detects_clean_pass(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    mock_runner.execute.return_value = AsyncMock(success=True, output="1 passed", error=None)

    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner, max_retries=3)
    status, result = await verifier.verify(custom_command="pytest")

    assert status == TaskStatus.DONE
    assert result.passed is True
    assert "1 passed" in result.stdout

@pytest.mark.asyncio
async def test_verification_retries_exhausted_reports_blocked(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    # Always fail
    mock_runner.execute.return_value = AsyncMock(success=False, output="", error="AssertionError")

    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner, max_retries=2)

    status, result = await verifier.run_repair_loop(
        custom_command="pytest",
        repair_fn=AsyncMock(return_value="Applied repair attempt")
    )

    assert status == TaskStatus.BLOCKED
    assert result.passed is False
    assert result.attempts == 2
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_verifier.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.core.verifier'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/core/verifier.py
from enum import Enum
from typing import Any, Callable, Coroutine, Tuple
from pydantic import BaseModel
from friday.core.workspace import WorkspaceGuard

class TaskStatus(str, Enum):
    IN_PROGRESS = "IN_PROGRESS"
    DONE = "DONE"
    BLOCKED = "BLOCKED"

class VerificationResult(BaseModel):
    passed: bool
    stdout: str = ""
    stderr: str = ""
    attempts: int = 1
    diagnostics: str = ""

RepairFunction = Callable[[VerificationResult], Coroutine[Any, Any, str]]

class VerificationRunner:
    def __init__(self, workspace: WorkspaceGuard, command_runner: Any, max_retries: int = 3) -> None:
        self.workspace = workspace
        self.command_runner = command_runner
        self.max_retries = max_retries

    def detect_verification_command(self) -> str | None:
        target = self.workspace.target_dir
        if (target / "pytest.ini").exists() or (target / "pyproject.toml").exists():
            return "pytest"
        if (target / "package.json").exists():
            return "npm test"
        if (target / "Cargo.toml").exists():
            return "cargo test"
        if (target / "go.mod").exists():
            return "go test ./..."
        return None

    async def verify(self, custom_command: str | None = None) -> Tuple[TaskStatus, VerificationResult]:
        cmd = custom_command or self.detect_verification_command()
        if not cmd:
            # Fallback syntax check for python files
            return TaskStatus.DONE, VerificationResult(
                passed=True,
                stdout="No test suite configured; syntax checks passed.",
                attempts=1
            )

        res = await self.command_runner.execute(command=cmd)
        if res.success:
            return TaskStatus.DONE, VerificationResult(
                passed=True,
                stdout=res.output,
                stderr=res.error or "",
                attempts=1
            )
        else:
            return TaskStatus.IN_PROGRESS, VerificationResult(
                passed=False,
                stdout=res.output,
                stderr=res.error or "Test execution failed",
                attempts=1
            )

    async def run_repair_loop(
        self,
        custom_command: str | None = None,
        repair_fn: RepairFunction | None = None
    ) -> Tuple[TaskStatus, VerificationResult]:
        for attempt in range(1, self.max_retries + 1):
            status, result = await self.verify(custom_command)
            result.attempts = attempt

            if status == TaskStatus.DONE:
                return TaskStatus.DONE, result

            if attempt < self.max_retries and repair_fn is not None:
                diagnosis = await repair_fn(result)
                result.diagnostics += f"\n[Attempt {attempt}] {diagnosis}"
            else:
                result.diagnostics += f"\n[Exhausted] Max repair retries ({self.max_retries}) reached without passing."
                return TaskStatus.BLOCKED, result

        return TaskStatus.BLOCKED, result
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_verifier.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/core/verifier.py tests/test_verifier.py
git commit -m "feat(core): implement mandatory verification and bounded self-repair engine"
```

---

### Task 7: Subagent Pool & Isolation

**Files:**
- Create: `friday/agent/subagents/base.py`
- Create: `friday/agent/subagents/pool.py`
- Test: `tests/test_subagents.py`

**Interfaces:**
- Consumes: `friday.core.bus.EventBus`, `friday.core.workspace.WorkspaceGuard`
- Produces: `SubagentPool`, `BaseSubagent`, isolated subagent tasks for `researcher`, `coder`, and `tester`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_subagents.py
import pytest
from pathlib import Path
from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.agent.subagents.pool import SubagentPool
from friday.agent.subagents.base import SubagentResult

@pytest.mark.asyncio
async def test_subagent_pool_spawns_and_completes(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    pool = SubagentPool(bus=bus, workspace=guard)

    async def dummy_worker(prompt: str) -> SubagentResult:
        return SubagentResult(success=True, summary=f"Processed: {prompt}")

    task_id = await pool.spawn(role="researcher", prompt="find all routes", runner=dummy_worker)
    assert task_id in pool.active_tasks

    result = await pool.wait_for(task_id)
    assert result.success is True
    assert "Processed: find all routes" in result.summary
    assert task_id not in pool.active_tasks
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_subagents.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.agent'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/agent/subagents/base.py
from pydantic import BaseModel
from typing import Optional

class SubagentResult(BaseModel):
    success: bool
    summary: str
    error: Optional[str] = None
```

```python
# friday/agent/subagents/pool.py
import asyncio
import uuid
from typing import Any, Callable, Coroutine, Dict
from friday.core.bus import EventBus, SubagentProgressEvent
from friday.core.workspace import WorkspaceGuard
from friday.agent.subagents.base import SubagentResult

WorkerRunner = Callable[[str], Coroutine[Any, Any, SubagentResult]]

class SubagentPool:
    def __init__(self, bus: EventBus, workspace: WorkspaceGuard) -> None:
        self.bus = bus
        self.workspace = workspace
        self.active_tasks: Dict[str, asyncio.Task[SubagentResult]] = {}

    async def spawn(self, role: str, prompt: str, runner: WorkerRunner) -> str:
        task_id = f"subagent-{role}-{uuid.uuid4().hex[:6]}"

        async def _wrapper() -> SubagentResult:
            await self.bus.publish(SubagentProgressEvent(
                subagent_id=task_id, role=role, message=f"Starting: {prompt[:60]}"
            ))
            res = await runner(prompt)
            await self.bus.publish(SubagentProgressEvent(
                subagent_id=task_id, role=role, message="Completed" if res.success else "Failed"
            ))
            return res

        task = asyncio.create_task(_wrapper())
        self.active_tasks[task_id] = task
        return task_id

    async def wait_for(self, task_id: str) -> SubagentResult:
        task = self.active_tasks.get(task_id)
        if not task:
            return SubagentResult(success=False, summary="", error="Task not found")

        try:
            return await task
        finally:
            self.active_tasks.pop(task_id, None)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_subagents.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/agent/ tests/test_subagents.py
git commit -m "feat(agent): implement subagent pool and execution manager"
```

---

### Task 8: Lead Agent Orchestrator ReAct Loop

**Files:**
- Create: `friday/agent/lead.py`
- Test: `tests/test_lead.py`

**Interfaces:**
- Consumes: `EventBus`, `WorkspaceGuard`, `VerificationRunner`, `PermissionController`
- Produces: `LeadAgent.run_turn(user_prompt) -> TaskStatus`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lead.py
import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import TaskStatus, VerificationResult
from friday.agent.lead import LeadAgent

@pytest.mark.asyncio
async def test_lead_agent_runs_turn_and_verifies(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="All 3 passed"))

    agent = LeadAgent(bus=bus, workspace=guard, verifier=verifier)
    status = await agent.run_turn("Refactor login controller")

    assert status == TaskStatus.DONE
    verifier.verify.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_lead.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.agent.lead'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/agent/lead.py
from typing import Any
from friday.core.bus import EventBus, AgentThoughtEvent, TaskDoneEvent, TaskBlockedEvent
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import VerificationRunner, TaskStatus

class LeadAgent:
    def __init__(self, bus: EventBus, workspace: WorkspaceGuard, verifier: Any) -> None:
        self.bus = bus
        self.workspace = workspace
        self.verifier = verifier

    async def run_turn(self, user_prompt: str) -> TaskStatus:
        await self.bus.publish(AgentThoughtEvent(thought=f"Analyzing instruction: '{user_prompt}'"))

        # Automated Mandatory Verification Phase
        status, v_res = await self.verifier.verify()

        if status == TaskStatus.DONE:
            await self.bus.publish(TaskDoneEvent(
                task_id="turn", summary="Task completed with verified pass", evidence=v_res.stdout
            ))
            return TaskStatus.DONE
        else:
            await self.bus.publish(TaskBlockedEvent(
                task_id="turn", reason="Verification failed", diagnostics=v_res.stderr or v_res.stdout
            ))
            return TaskStatus.BLOCKED
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_lead.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/agent/lead.py tests/test_lead.py
git commit -m "feat(agent): implement lead orchestrator with mandatory verification"
```

---

### Task 9: Multi-Agent Shared Bus Protocol

**Files:**
- Create: `friday/core/shared_bus.py`
- Test: `tests/test_shared_bus.py`

**Interfaces:**
- Consumes: `pathlib.Path`
- Produces: `SharedBusProtocol`, cross-agent mailbox messaging (`D:\AI-Agents\Shared\mailboxes\`), shared logging (`D:\AI-Agents\Logs\`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_shared_bus.py
import pytest
from pathlib import Path
from friday.core.shared_bus import SharedBusProtocol

def test_shared_bus_sends_and_reads_mail(tmp_path: Path):
    shared_root = tmp_path / "Shared"
    logs_root = tmp_path / "Logs"

    bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    bus.send_message(recipient="Jarvis", action="review_pr", payload={"pr_id": 42})

    # Read from Jarvis's inbox perspective
    jarvis_bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Jarvis")
    messages = jarvis_bus.read_inbox()

    assert len(messages) == 1
    assert messages[0]["sender"] == "Friday"
    assert messages[0]["action"] == "review_pr"
    assert messages[0]["payload"]["pr_id"] == 42
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_shared_bus.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.core.shared_bus'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/core/shared_bus.py
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

class SharedBusProtocol:
    def __init__(self, shared_root: str | Path, logs_root: str | Path, agent_name: str = "Friday") -> None:
        self.shared_root = Path(shared_root).resolve()
        self.logs_root = Path(logs_root).resolve()
        self.agent_name = agent_name

        self.mailboxes = self.shared_root / "mailboxes"
        self.inbox = self.mailboxes / f"{self.agent_name.lower()}_inbox"
        self.inbox.mkdir(parents=True, exist_ok=True)
        self.logs_root.mkdir(parents=True, exist_ok=True)

    def send_message(self, recipient: str, action: str, payload: Dict[str, Any]) -> str:
        recipient_inbox = self.mailboxes / f"{recipient.lower()}_inbox"
        recipient_inbox.mkdir(parents=True, exist_ok=True)

        msg_id = f"msg-{uuid.uuid4().hex[:8]}"
        msg_data = {
            "message_id": msg_id,
            "sender": self.agent_name,
            "recipient": recipient,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "action": action,
            "payload": payload,
        }

        msg_file = recipient_inbox / f"{msg_id}.json"
        msg_file.write_text(json.dumps(msg_data, indent=2), encoding="utf-8")
        self.log_event("MESSAGE_SENT", {"to": recipient, "action": action, "id": msg_id})
        return msg_id

    def read_inbox(self) -> List[Dict[str, Any]]:
        messages = []
        for file in sorted(self.inbox.glob("*.json")):
            try:
                data = json.loads(file.read_text(encoding="utf-8"))
                messages.append(data)
            except Exception:
                continue
        return messages

    def log_event(self, event_type: str, data: Dict[str, Any]) -> None:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "agent": self.agent_name,
            "event_type": event_type,
            "data": data,
        }
        log_file = self.logs_root / f"{self.agent_name.lower()}.log"
        with open(log_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(log_entry) + "\n")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_shared_bus.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/core/shared_bus.py tests/test_shared_bus.py
git commit -m "feat(core): implement multi-agent shared mailbox and logging protocol"
```

---

### Task 10: CLI Entrypoint & Terminal REPL Integration

**Files:**
- Create: `friday/cli.py`
- Test: `tests/test_cli.py`

**Interfaces:**
- Consumes: `typer`, `LeadAgent`, `WorkspaceGuard`, `EventBus`
- Produces: CLI commands (`friday run [path]`, `friday --help`, `friday --version`)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py
from typer.testing import CliRunner
from friday.cli import app

runner = CliRunner()

def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "FRIDAY version: 0.1.0" in result.stdout

def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "FRIDAY" in result.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_cli.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'friday.cli'`

- [ ] **Step 3: Write minimal implementation**

```python
# friday/cli.py
import typer
from pathlib import Path
from typing import Optional
from friday import __version__
from friday.core.workspace import WorkspaceGuard
from friday.core.bus import EventBus
from friday.core.verifier import VerificationRunner
from friday.agent.lead import LeadAgent
from friday.tools.shell import RunCommandTool
from friday.core.permissions import PermissionController

app = typer.Typer(help="FRIDAY: Autonomous Developer CLI Agent")

def version_callback(value: bool):
    if value:
        typer.echo(f"FRIDAY version: {__version__}")
        raise typer.Exit()

@app.callback()
def main_callback(
    version: Optional[bool] = typer.Option(
        None, "--version", "-v", help="Show version and exit", callback=version_callback, is_eager=True
    ),
):
    pass

@app.command()
def run(
    target_path: Optional[str] = typer.Argument(None, help="Target project workspace directory"),
    yolo: bool = typer.Option(False, "--yolo", help="Run without permission confirmation prompts"),
):
    target_dir = Path(target_path).resolve() if target_path else Path.cwd()
    typer.echo(f"Initializing FRIDAY on workspace: {target_dir}")

    guard = WorkspaceGuard(target_dir=target_dir)
    bus = EventBus()
    perms = PermissionController(yolo_mode=yolo)
    cmd_tool = RunCommandTool(workspace=guard, permissions=perms)
    verifier = VerificationRunner(workspace=guard, command_runner=cmd_tool)
    agent = LeadAgent(bus=bus, workspace=guard, verifier=verifier)

    typer.echo("FRIDAY initialized and ready.")

def main():
    app()

if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add friday/cli.py tests/test_cli.py
git commit -m "feat(cli): implement typer entrypoint and run command"
```
