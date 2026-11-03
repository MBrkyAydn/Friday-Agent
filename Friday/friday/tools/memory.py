from pathlib import Path
from typing import Any, Dict, Optional
from friday.core.memory import AgencyMemory
from friday.core.permissions import PermissionController, PermissionTier
from friday.core.workspace import WorkspaceGuard
from friday.tools.base import BaseTool, ToolResult


class RememberTool(BaseTool):
    name = "remember"
    description = "Store an insight, solution, user preference, or architectural rule into persistent long-term memory."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "category": {
                "type": "string",
                "description": "Category of memory: 'error_fix', 'user_preference', 'architecture', 'convention'",
            },
            "key": {
                "type": "string",
                "description": "Unique descriptive identifier key for this memory",
            },
            "content": {
                "type": "string",
                "description": "The insight or knowledge to store",
            },
            "metadata": {
                "type": "object",
                "description": "Optional extra structured tags/metadata",
            },
        },
        "required": ["category", "key", "content"],
    }

    def __init__(
        self,
        memory: AgencyMemory,
        workspace: Optional[WorkspaceGuard] = None,
        permissions: Optional[PermissionController] = None,
    ) -> None:
        self.memory = memory
        super().__init__(
            workspace=workspace or WorkspaceGuard(target_dir=Path(".")),
            permissions=permissions or PermissionController(yolo_mode=True),
        )

    async def execute(
        self,
        category: str,
        key: str,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ToolResult:
        try:
            m_id = self.memory.remember(
                category=category,
                key=key,
                content=content,
                metadata=metadata,
            )
            return ToolResult(
                success=True,
                output=f"Remembered #{m_id} in category '{category}' with key '{key}'.",
            )
        except Exception as e:
            return ToolResult(success=False, error=str(e))


class RecallTool(BaseTool):
    name = "recall"
    description = "Search and recall insights, solutions, and rules from persistent long-term memory."
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "query": {
                "type": "string",
                "description": "Search terms or description of problem/question",
            },
            "category": {
                "type": "string",
                "description": "Optional category filter",
            },
            "limit": {
                "type": "integer",
                "description": "Maximum number of memories to return (default: 5)",
                "default": 5,
            },
        },
        "required": ["query"],
    }

    def __init__(
        self,
        memory: AgencyMemory,
        workspace: Optional[WorkspaceGuard] = None,
        permissions: Optional[PermissionController] = None,
    ) -> None:
        self.memory = memory
        super().__init__(
            workspace=workspace or WorkspaceGuard(target_dir=Path(".")),
            permissions=permissions or PermissionController(yolo_mode=True),
        )

    async def execute(
        self,
        query: str,
        category: Optional[str] = None,
        limit: int = 5,
    ) -> ToolResult:
        try:
            items = self.memory.recall(query=query, category=category, limit=limit)
            if not items:
                return ToolResult(
                    success=True,
                    output=f"No matching memories found for query: '{query}'.",
                )

            lines = [f"Found {len(items)} relevant memories:"]
            for item in items:
                lines.append(f"- [{item.category}] {item.key}: {item.content}")
            return ToolResult(success=True, output="\n".join(lines))
        except Exception as e:
            return ToolResult(success=False, error=str(e))
