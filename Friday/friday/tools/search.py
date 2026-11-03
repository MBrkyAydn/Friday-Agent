import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from friday.core.permissions import PermissionTier
from friday.core.workspace import SecurityError
from friday.tools.base import BaseTool, ToolResult

IGNORE_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    ".venv",
    "venv",
    ".pytest_cache",
    ".superpowers",
}


class SearchCodeTool(BaseTool):
    """Jailed text and regular expression search tool across workspace files."""

    name = "search_code"
    description = "Search for text or regex patterns across files in the workspace."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "Text or regex pattern to search for"},
            "path": {
                "type": "string",
                "description": "Subdirectory or file to search within (relative to workspace)",
                "default": ".",
            },
            "regex": {
                "type": "boolean",
                "description": "Whether query is a regular expression pattern",
                "default": False,
            },
            "case_sensitive": {
                "type": "boolean",
                "description": "Case-sensitive matching",
                "default": False,
            },
            "max_results": {
                "type": "integer",
                "description": "Maximum number of matching lines to return",
                "default": 50,
            },
        },
        "required": ["query"],
    }

    def execute_sync(
        self,
        query: str,
        path: str = ".",
        regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 50,
    ) -> ToolResult:
        try:
            target_path = self.workspace.resolve_path(path)
        except SecurityError as e:
            return ToolResult(success=False, error=f"SecurityError: {e}")
        except Exception as e:
            return ToolResult(success=False, error=str(e))

        flags = 0 if case_sensitive else re.IGNORECASE
        pattern = None
        if regex:
            try:
                pattern = re.compile(query, flags)
            except re.error as e:
                return ToolResult(success=False, error=f"Invalid regex: {e}")
        else:
            q_clean = query if case_sensitive else query.lower()

        results: List[str] = []
        files_to_search: List[Path] = []

        if target_path.is_file():
            files_to_search.append(target_path)
        elif target_path.is_dir():
            for root_dir, dirs, files in target_path.walk():
                # Filter out ignored directories in-place
                dirs[:] = [d for d in dirs if d not in IGNORE_DIRS]
                for file_name in files:
                    files_to_search.append(root_dir / file_name)

        for file_p in files_to_search:
            if len(results) >= max_results:
                break
            try:
                # Read text, skipping binary files
                content = file_p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                continue

            rel_path = file_p.relative_to(self.workspace.target_dir)
            lines = content.splitlines()

            for idx, line in enumerate(lines):
                if len(results) >= max_results:
                    break

                matched = False
                if regex and pattern:
                    matched = bool(pattern.search(line))
                else:
                    target_line = line if case_sensitive else line.lower()
                    matched = q_clean in target_line

                if matched:
                    results.append(f"{rel_path}:{idx + 1}: {line}")

        if not results:
            return ToolResult(success=True, output=f"No matches found for query: '{query}'")

        output = "\n".join(results)
        if len(results) >= max_results:
            output += f"\n... (results capped at {max_results} matches)"
        return ToolResult(success=True, output=output)

    async def execute(
        self,
        query: str,
        path: str = ".",
        regex: bool = False,
        case_sensitive: bool = False,
        max_results: int = 50,
        **kwargs: Any,
    ) -> ToolResult:
        return self.execute_sync(
            query=query,
            path=path,
            regex=regex,
            case_sensitive=case_sensitive,
            max_results=max_results,
        )
