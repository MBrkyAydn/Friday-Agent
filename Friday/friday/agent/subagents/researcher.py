from typing import List, Optional
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionTier
from friday.tools.base import BaseTool
from friday.agent.llm import LLMProvider
from friday.agent.subagents.base import BaseSubagent


class ResearcherSubagent(BaseSubagent):
    """Specialized read-only codebase exploration subagent."""

    role = "researcher"
    system_prompt = (
        "You are a specialized read-only research subagent.\n"
        "Your objective is to inspect files and extract findings to answer queries factually.\n"
        "You must never modify, create, or delete any files or execute shell commands.\n"
        "Return a concise, accurate summary of your findings when complete."
    )

    def __init__(
        self,
        workspace: WorkspaceGuard,
        llm: Optional[LLMProvider] = None,
        tools: Optional[List[BaseTool]] = None,
        max_steps: int = 5,
    ) -> None:
        # Strictly enforce Tier 0 Safe tools (read-only); filter out any mutating or shell tools
        safe_tools = [
            t for t in (tools or []) if getattr(t, "tier", None) == PermissionTier.TIER_0_SAFE
        ]
        super().__init__(
            workspace=workspace,
            llm=llm,
            tools=safe_tools,
            max_steps=max_steps,
        )
