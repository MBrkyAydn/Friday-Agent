import asyncio
from typing import Any, Dict
from friday.tools.base import BaseTool, ToolResult
from friday.core.permissions import PermissionTier, PermissionDecision


class RunCommandTool(BaseTool):
    name = "run_command"
    description = "Execute a shell command within the workspace directory."
    tier = PermissionTier.TIER_2_DESTRUCTIVE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "command": {"type": "string", "description": "Shell command to execute"},
            "timeout_seconds": {"type": "integer", "description": "Execution timeout in seconds", "default": 60},
        },
        "required": ["command"],
    }

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
                try:
                    process.kill()
                    await process.wait()
                except (ProcessLookupError, Exception):
                    pass
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
