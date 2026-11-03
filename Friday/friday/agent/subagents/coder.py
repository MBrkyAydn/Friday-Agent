from typing import List, Optional
from friday.core.workspace import WorkspaceGuard
from friday.tools.base import BaseTool
from friday.agent.llm import LLMProvider
from friday.agent.subagents.base import BaseSubagent


class CoderSubagent(BaseSubagent):
    """Specialized code modification and implementation subagent."""

    role = "coder"
    system_prompt = (
        "You are a specialized coding subagent.\n"
        "Your objective is to implement requested code changes with precision.\n"
        "Use view, write, and edit tools to implement modifications in the target project.\n"
        "When complete, summarize the changes you made."
    )

    def __init__(
        self,
        workspace: WorkspaceGuard,
        llm: Optional[LLMProvider] = None,
        tools: Optional[List[BaseTool]] = None,
        max_steps: int = 5,
    ) -> None:
        super().__init__(
            workspace=workspace,
            llm=llm,
            tools=tools,
            max_steps=max_steps,
        )
