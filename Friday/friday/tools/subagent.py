from typing import Any, Dict, List, Optional
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionTier
from friday.core.bus import EventBus
from friday.tools.base import BaseTool, ToolResult
from friday.agent.llm import LLMProvider
from friday.agent.subagents.pool import SubagentPool
from friday.agent.subagents.researcher import ResearcherSubagent
from friday.agent.subagents.coder import CoderSubagent
from friday.agent.subagents.tester import TesterSubagent


class DelegateSubagentTool(BaseTool):
    """Jailed subagent delegation tool allowing LeadAgent to dispatch background worker agents."""

    name = "delegate_subagent"
    description = (
        "Delegate a focused task to a specialized background subagent. "
        "Roles: 'researcher' (read-only codebase exploration), "
        "'coder' (isolated file editing and implementation), "
        "'tester' (test suite running and error analysis)."
    )
    tier = PermissionTier.TIER_0_SAFE
    parameters: Dict[str, Any] = {
        "type": "object",
        "properties": {
            "role": {
                "type": "string",
                "enum": ["researcher", "coder", "tester"],
                "description": "Role of the specialized subagent to dispatch",
            },
            "task_description": {
                "type": "string",
                "description": "Clear natural language prompt with instructions and context for the subagent",
            },
        },
        "required": ["role", "task_description"],
    }

    def __init__(
        self,
        workspace: WorkspaceGuard,
        permissions: PermissionController,
        pool: Optional[SubagentPool] = None,
        llm: Optional[LLMProvider] = None,
        bus: Optional[EventBus] = None,
        subagent_tools: Optional[List[BaseTool]] = None,
    ) -> None:
        super().__init__(workspace=workspace, permissions=permissions)
        self.pool = pool
        self.llm = llm
        self.bus = bus
        self.subagent_tools = subagent_tools or []

    async def execute(
        self, role: str, task_description: str, **kwargs: Any
    ) -> ToolResult:
        if role not in ("researcher", "coder", "tester"):
            return ToolResult(
                success=False,
                error=f"Unsupported subagent role: '{role}'. Supported roles are: 'researcher', 'coder', 'tester'.",
            )

        if self.pool is None:
            return ToolResult(
                success=False,
                error="No SubagentPool configured on DelegateSubagentTool.",
            )

        if role == "researcher":
            worker = ResearcherSubagent(
                workspace=self.workspace,
                llm=self.llm,
                tools=self.subagent_tools,
            )
        elif role == "coder":
            worker = CoderSubagent(
                workspace=self.workspace,
                llm=self.llm,
                tools=self.subagent_tools,
            )
        else:  # tester
            worker = TesterSubagent(
                workspace=self.workspace,
                llm=self.llm,
                tools=self.subagent_tools,
            )

        try:
            task_id = await self.pool.spawn_worker(worker=worker, prompt=task_description)
            sub_res = await self.pool.wait_for(task_id)
            return ToolResult(
                success=sub_res.success,
                output=sub_res.summary,
                error=sub_res.error,
            )
        except Exception as exc:
            return ToolResult(
                success=False,
                error=f"Failed to execute subagent '{role}': {exc}",
            )
