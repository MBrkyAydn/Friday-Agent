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
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {},
    }

    def __init__(self, workspace: WorkspaceGuard, permissions: PermissionController) -> None:
        self.workspace = workspace
        self.permissions = permissions

    def to_schema(self) -> Dict[str, Any]:
        """Produce OpenAI/LiteLLM function tool schema definition."""
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    @abstractmethod
    async def execute(self, **kwargs: Any) -> ToolResult:
        pass
