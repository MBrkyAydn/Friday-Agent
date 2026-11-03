from typing import List, Optional
from friday.core.workspace import WorkspaceGuard
from friday.tools.base import BaseTool
from friday.agent.llm import LLMProvider
from friday.agent.subagents.base import BaseSubagent


class TesterSubagent(BaseSubagent):
    """Specialized test execution and failure diagnosis subagent."""

    __test__ = False
    role = "tester"
    system_prompt = (
        "You are a specialized testing subagent.\n"
        "Your objective is to run test runners and build verification commands.\n"
        "Inspect execution outputs, parse test counts, errors, and stack traces.\n"
        "Return a structured summary of test results."
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
