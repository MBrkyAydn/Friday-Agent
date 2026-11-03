from pathlib import Path
from typing import Any, Dict
from friday.tools.base import BaseTool, ToolResult
from friday.core.permissions import PermissionTier, PermissionDecision


class ViewFileTool(BaseTool):
    name = "view_file"
    description = "View contents of a file with line slicing."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "start_line": {"type": "integer", "description": "1-based starting line number", "default": 1},
            "end_line": {"type": "integer", "description": "1-based ending line number", "default": 500},
        },
        "required": ["path"],
    }

    async def execute(self, path: str, start_line: int = 1, end_line: int = 500) -> ToolResult:
        try:
            target = self.workspace.resolve_path(path)
            if not target.is_file():
                return ToolResult(success=False, error=f"File not found: {path}")

            lines = target.read_text(encoding="utf-8", errors="replace").splitlines()
            total_lines = len(lines)
            s_idx = max(0, start_line - 1)
            e_idx = min(total_lines, end_line, s_idx + 500)

            sliced = [f"{i+1:4d} | {lines[i]}" for i in range(s_idx, e_idx)]
            output = f"Showing lines {s_idx + 1} to {e_idx} of {total_lines}:\n" + "\n".join(sliced)
            return ToolResult(success=True, output=output)
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Create or overwrite a file in the workspace."
    tier = PermissionTier.TIER_1_GUARDED
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "content": {"type": "string", "description": "Full file content to write"},
        },
        "required": ["path", "content"],
    }

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
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative path to file"},
            "old_str": {"type": "string", "description": "Existing exact string to replace"},
            "new_str": {"type": "string", "description": "New replacement string"},
        },
        "required": ["path", "old_str", "new_str"],
    }

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


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List files and directories in the workspace."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative directory path (default: .)", "default": "."},
            "depth": {"type": "integer", "description": "Maximum recursion depth (default: 2)", "default": 2},
        },
    }

    async def execute(self, path: str = ".", depth: int = 2) -> ToolResult:
        try:
            target = self.workspace.resolve_path(path)
            if not target.exists():
                return ToolResult(success=False, error=f"Directory not found: {path}")

            results = []
            base_level = len(target.parts)
            for item in sorted(target.rglob("*")):
                rel = item.relative_to(target)
                if any(part.startswith((".", "__pycache__", "venv", ".git")) for part in rel.parts):
                    continue
                level = len(item.parts) - base_level
                if level <= depth:
                    indent = "  " * (level - 1)
                    badge = "[DIR] " if item.is_dir() else "[FILE]"
                    results.append(f"{indent}{badge} {item.name}")

            out = "\n".join(results) if results else "(empty directory)"
            return ToolResult(success=True, output=f"Files in {path}:\n{out}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class PrintTreeTool(BaseTool):
    name = "print_tree"
    description = "Display directory tree structure of workspace."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Relative directory path (default: empty or .)", "default": ""},
            "depth": {"type": "integer", "description": "Maximum tree depth (default: 2)", "default": 2},
        },
    }

    async def execute(self, path: str = "", depth: int = 2) -> ToolResult:
        rel = path if path else "."
        tool = ListFilesTool(workspace=self.workspace, permissions=self.permissions)
        return await tool.execute(path=rel, depth=depth)
