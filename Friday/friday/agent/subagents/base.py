import json
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional
from pydantic import BaseModel

from friday.core.workspace import WorkspaceGuard
from friday.agent.llm import LLMProvider, LLMMessage, LLMResponse
from friday.tools.base import BaseTool, ToolResult


class SubagentResult(BaseModel):
    success: bool
    summary: str
    error: Optional[str] = None


class BaseSubagent(ABC):
    """Abstract base class for specialized background subagent workers."""

    role: str = "generic_worker"
    system_prompt: str = "You are a specialized worker subagent."

    def __init__(
        self,
        workspace: WorkspaceGuard,
        llm: Optional[LLMProvider] = None,
        tools: Optional[List[BaseTool]] = None,
        max_steps: int = 5,
    ) -> None:
        self.workspace = workspace
        self.llm = llm
        self.tools: List[BaseTool] = tools or []
        self.tools_map: Dict[str, BaseTool] = {t.name: t for t in self.tools}
        self.max_steps = max_steps

    async def run(self, prompt: str) -> SubagentResult:
        """Run the subagent's execution loop."""
        if self.llm is None:
            return SubagentResult(
                success=True,
                summary=f"Subagent [{self.role}] processed instruction: {prompt}",
            )

        messages: List[LLMMessage] = [
            LLMMessage(role="system", content=self.system_prompt),
            LLMMessage(role="user", content=prompt),
        ]

        tool_schemas = [t.to_schema() for t in self.tools] if self.tools else None
        step_count = 0

        while step_count < self.max_steps:
            step_count += 1
            try:
                resp: LLMResponse = await self.llm.complete(
                    messages=messages, tools=tool_schemas
                )
            except Exception as e:
                return SubagentResult(
                    success=False,
                    summary="",
                    error=f"LLM completion error in subagent [{self.role}]: {e}",
                )

            if resp.tool_calls:
                messages.append(
                    LLMMessage(
                        role="assistant",
                        content=resp.content,
                        tool_calls=resp.tool_calls,
                    )
                )

                for tc in resp.tool_calls:
                    args = tc.function.arguments or {}
                    if isinstance(args, str):
                        try:
                            args = json.loads(args)
                        except Exception:
                            args = {}

                    tool = self.tools_map.get(tc.function.name)
                    if tool is None:
                        err_msg = f"Unknown tool: '{tc.function.name}'"
                        messages.append(
                            LLMMessage(
                                role="tool",
                                tool_call_id=tc.id,
                                name=tc.function.name,
                                content=err_msg,
                            )
                        )
                    else:
                        try:
                            res: ToolResult = await tool.execute(**args)
                            out_str = (
                                res.output if res.success else (res.error or "Tool execution failed")
                            )
                            messages.append(
                                LLMMessage(
                                    role="tool",
                                    tool_call_id=tc.id,
                                    name=tc.function.name,
                                    content=out_str,
                                )
                            )
                        except Exception as exc:
                            messages.append(
                                LLMMessage(
                                    role="tool",
                                    tool_call_id=tc.id,
                                    name=tc.function.name,
                                    content=f"Tool error: {exc}",
                                )
                            )
            else:
                return SubagentResult(
                    success=True,
                    summary=resp.content or "Completed successfully",
                )

        return SubagentResult(
            success=False,
            summary="",
            error=f"Subagent [{self.role}] exceeded step limit ({self.max_steps})",
        )
