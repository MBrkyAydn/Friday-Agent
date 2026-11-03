import asyncio
from typing import Any, Dict, List, Optional

from friday.core.permissions import PermissionTier, PermissionDecision
from friday.tools.base import BaseTool, ToolResult


class GitStatusTool(BaseTool):
    """Jailed git status inspection tool."""

    name = "git_status"
    description = "Get current git status of the workspace repository."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    async def execute(self, **kwargs: Any) -> ToolResult:
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "status",
                "--short",
                cwd=str(self.workspace.target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                return ToolResult(success=False, error=f"Git status error: {err_msg}")

            out = stdout.decode("utf-8", errors="replace").strip()
            return ToolResult(
                success=True,
                output=out if out else "Working tree clean, nothing to commit.",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitDiffTool(BaseTool):
    """Jailed git diff inspection tool."""

    name = "git_diff"
    description = "View git diff for working tree or specific file."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Optional file path to diff"},
            "staged": {
                "type": "boolean",
                "description": "Diff staged changes instead of working tree",
                "default": False,
            },
        },
    }

    async def execute(
        self, path: Optional[str] = None, staged: bool = False, **kwargs: Any
    ) -> ToolResult:
        try:
            cmd = ["git", "diff"]
            if staged:
                cmd.append("--cached")
            if path:
                target = self.workspace.resolve_path(path)
                rel_path = target.relative_to(self.workspace.target_dir)
                cmd.extend(["--", str(rel_path)])

            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(self.workspace.target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await proc.communicate()
            if proc.returncode != 0:
                err_msg = stderr.decode("utf-8", errors="replace").strip()
                return ToolResult(success=False, error=f"Git diff error: {err_msg}")

            out = stdout.decode("utf-8", errors="replace").strip()
            return ToolResult(
                success=True,
                output=out if out else "No changes detected.",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class GitCommitTool(BaseTool):
    """Jailed git commit tool with tiered permission gating."""

    name = "git_commit"
    description = "Stage changes and create a git commit in the workspace."
    tier = PermissionTier.TIER_1_GUARDED
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "message": {"type": "string", "description": "Commit message"},
            "files": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Optional list of files to stage and commit; defaults to all changes",
            },
        },
        "required": ["message"],
    }

    async def execute(
        self, message: str, files: Optional[List[str]] = None, **kwargs: Any
    ) -> ToolResult:
        try:
            decision = await self.permissions.request_permission(
                tool_name=self.name,
                tier=self.tier,
                details={"message": message, "files": files or "all"},
            )
            if decision == PermissionDecision.DENY:
                return ToolResult(success=False, error="Git commit denied by user.")

            # Stage files
            add_cmd = ["git", "add"]
            if files:
                for f in files:
                    resolved = self.workspace.resolve_path(f)
                    add_cmd.append(str(resolved.relative_to(self.workspace.target_dir)))
            else:
                add_cmd.append("-A")

            add_proc = await asyncio.create_subprocess_exec(
                *add_cmd,
                cwd=str(self.workspace.target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            _, add_err = await add_proc.communicate()
            if add_proc.returncode != 0:
                return ToolResult(
                    success=False,
                    error=f"Git add failed: {add_err.decode('utf-8', errors='replace')}",
                )

            # Commit
            commit_proc = await asyncio.create_subprocess_exec(
                "git",
                "commit",
                "-m",
                message,
                cwd=str(self.workspace.target_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await commit_proc.communicate()
            if commit_proc.returncode != 0:
                err_text = stderr.decode("utf-8", errors="replace").strip()
                out_text = stdout.decode("utf-8", errors="replace").strip()
                return ToolResult(
                    success=False,
                    error=f"Git commit failed: {err_text or out_text}",
                )

            return ToolResult(
                success=True,
                output=stdout.decode("utf-8", errors="replace").strip(),
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))
