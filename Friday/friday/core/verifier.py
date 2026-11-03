import shutil
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
    def __init__(
        self,
        workspace: WorkspaceGuard,
        command_runner: Any,
        max_retries: int = 3,
        verification_command: str | None = None,
    ) -> None:
        self.workspace = workspace
        self.command_runner = command_runner
        self.max_retries = max_retries
        self.verification_command = verification_command

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

    async def verify(
        self,
        custom_command: str | None = None,
        files_modified: bool = True,
    ) -> Tuple[TaskStatus, VerificationResult]:
        if not files_modified:
            return TaskStatus.DONE, VerificationResult(
                passed=True,
                stdout="Read-only turn: no code files modified.",
                attempts=1,
            )

        cmd = custom_command or self.verification_command or self.detect_verification_command()
        if cmd == "pytest" and shutil.which("pytest") is None:
            cmd = "python -m pytest"

        is_fallback = False
        if not cmd:
            # Fallback syntax check for python files
            cmd = "python -m compileall -q ."
            is_fallback = True

        res = await self.command_runner.execute(command=cmd)
        if res.success:
            stdout_msg = res.output
            if is_fallback and not stdout_msg:
                stdout_msg = "No test suite configured; syntax check passed."
            return TaskStatus.DONE, VerificationResult(
                passed=True,
                stdout=stdout_msg,
                stderr=res.error or "",
                attempts=1,
            )
        else:
            return TaskStatus.IN_PROGRESS, VerificationResult(
                passed=False,
                stdout=res.output,
                stderr=res.error or "Test execution failed",
                attempts=1,
            )

    async def run_repair_loop(
        self,
        custom_command: str | None = None,
        repair_fn: RepairFunction | None = None,
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
