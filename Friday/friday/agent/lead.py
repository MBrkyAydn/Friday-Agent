import json
from typing import Any, Dict, List, Optional
from friday.core.bus import (
    EventBus,
    AgentThoughtEvent,
    ToolCallRequestedEvent,
    ToolResultEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
)
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import TaskStatus
from friday.tools.base import BaseTool, ToolResult
from friday.agent.llm import LLMProvider, LLMMessage, LLMResponse
from friday.agent.context import ContextManager


class LeadAgent:
    def __init__(
        self,
        bus: EventBus,
        workspace: WorkspaceGuard,
        verifier: Any,
        llm: Optional[LLMProvider] = None,
        tools: Optional[List[BaseTool]] = None,
        max_steps: int = 10,
        max_repair_retries: int = 3,
        system_prompt: Optional[str] = None,
        context_manager: Optional[ContextManager] = None,
        memory: Optional[Any] = None,
    ) -> None:
        self.bus = bus
        self.workspace = workspace
        self.verifier = verifier
        self.llm = llm
        self.tools: List[BaseTool] = tools or []
        self.tools_map: Dict[str, BaseTool] = {t.name: t for t in self.tools}
        self.max_steps = max_steps
        self.max_repair_retries = max_repair_retries
        self.system_prompt = system_prompt
        self.context_manager = context_manager
        self.memory = memory

    async def run_turn(self, user_prompt: str, session: Optional[Any] = None) -> TaskStatus:
        # Fallback mode when no LLM provider is configured (Tasks 1-10 behavior)
        if self.llm is None:
            await self.bus.publish(AgentThoughtEvent(thought=f"Analyzing instruction: '{user_prompt}'"))
            status, v_res = await self.verifier.verify()
            if status == TaskStatus.DONE:
                await self.bus.publish(
                    TaskDoneEvent(
                        task_id="turn",
                        summary="Task completed with verified pass",
                        evidence=v_res.stdout,
                    )
                )
                return TaskStatus.DONE
            else:
                await self.bus.publish(
                    TaskBlockedEvent(
                        task_id="turn",
                        reason="Verification failed",
                        diagnostics=v_res.stderr or v_res.stdout,
                    )
                )
                return TaskStatus.BLOCKED

        # Autonomous ReAct Loop with LLM
        sys_prompt = self.system_prompt or (
            f"You are FRIDAY, an autonomous developer lead manager agent.\n"
            f"Target workspace: {self.workspace.target_dir}\n"
            "You have access to tools to view, list, write, edit files, run commands, and delegate.\n"
            "When the user requests implementing features, creating services, or writing code, use the 'delegate_jarvis' tool to delegate coding and testing to JARVIS.\n"
            "CRITICAL: ONLY invoke tools that are explicitly defined in the provided tools list. Never invent or hallucinate tool names.\n"
            "Reason step-by-step. If the user greets you or asks a conversational question, reply politely and directly in their language (e.g. Turkish).\n"
            "When you have completed your work, respond with a clear summary."
        )

        friday_md_path = self.workspace.target_dir / "FRIDAY.md"
        if friday_md_path.is_file():
            try:
                friday_content = friday_md_path.read_text(encoding="utf-8", errors="replace")[:4000]
                sys_prompt += f"\n\n## Target Project Instructions (from FRIDAY.md):\n{friday_content}"
            except Exception:
                pass

        if self.memory:
            try:
                base_prefs = self.memory.list_all(category="user_preference") if hasattr(self.memory, "list_all") else []
                recalled = self.memory.recall(user_prompt, limit=4) if hasattr(self.memory, "recall") else []
                seen_ids = set()
                combined_memories = []
                for m in (base_prefs + recalled):
                    if m.id not in seen_ids:
                        seen_ids.add(m.id)
                        combined_memories.append(m)
                if combined_memories:
                    mem_hints = "\n".join(f"- [{m.category}] {m.key}: {m.content}" for m in combined_memories[:6])
                    sys_prompt += f"\n\n## Relevant Learned Agency Memory & Rules:\n{mem_hints}"
            except Exception:
                pass

        messages: List[LLMMessage] = [
            LLMMessage(role="system", content=sys_prompt),
        ]

        if session is not None and getattr(session, "turns", None):
            for turn in session.turns:
                messages.append(LLMMessage(role="user", content=turn.user_prompt))
                asst_content = ""
                if getattr(turn, "thoughts", None):
                    asst_content = "\n".join(turn.thoughts)
                elif getattr(turn, "status", None):
                    asst_content = f"Turn completed with status: {turn.status}"
                else:
                    asst_content = "Turn completed."
                messages.append(LLMMessage(role="assistant", content=asst_content))

        messages.append(LLMMessage(role="user", content=user_prompt))

        tool_schemas = [t.to_schema() for t in self.tools] if self.tools else None
        step_count = 0
        repair_attempts = 0
        last_call_sig = None
        files_modified = False

        while step_count < self.max_steps:
            step_count += 1

            if self.context_manager is not None:
                messages = self.context_manager.compact(messages)

            try:
                resp: LLMResponse = await self.llm.complete(messages=messages, tools=tool_schemas)
            except Exception as e:
                await self.bus.publish(
                    TaskBlockedEvent(
                        task_id="turn",
                        reason=f"LLM completion error: {e}",
                        diagnostics=str(e),
                    )
                )
                return TaskStatus.BLOCKED

            if resp.content:
                await self.bus.publish(AgentThoughtEvent(thought=resp.content))

            if resp.tool_calls:
                call_sig = [(tc.function.name, str(tc.function.arguments)) for tc in resp.tool_calls]
                if last_call_sig == call_sig:
                    # Model repeated identical tool call; proceed to verification
                    status, v_res = await self.verifier.verify(files_modified=files_modified)
                    if status == TaskStatus.DONE:
                        await self.bus.publish(
                            TaskDoneEvent(
                                task_id="turn",
                                summary="Task completed with verified pass",
                                evidence=v_res.stdout,
                            )
                        )
                        return TaskStatus.DONE
                last_call_sig = call_sig

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

                    await self.bus.publish(
                        ToolCallRequestedEvent(
                            tool_call_id=tc.id,
                            tool_name=tc.function.name,
                            arguments=args,
                        )
                    )

                    tool = self.tools_map.get(tc.function.name)
                    if tool is None:
                        err_msg = f"Unknown tool: '{tc.function.name}'"
                        await self.bus.publish(
                            ToolResultEvent(
                                tool_call_id=tc.id,
                                tool_name=tc.function.name,
                                success=False,
                                output="",
                                error=err_msg,
                            )
                        )
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
                            if res.success and tc.function.name in ("write_file", "edit_file", "write_to_file", "replace_file_content"):
                                files_modified = True
                            out_str = res.output if res.success else (res.error or "Tool execution failed")
                            await self.bus.publish(
                                ToolResultEvent(
                                    tool_call_id=tc.id,
                                    tool_name=tc.function.name,
                                    success=res.success,
                                    output=res.output,
                                    error=res.error,
                                )
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
                            err_str = f"Tool execution error: {exc}"
                            await self.bus.publish(
                                ToolResultEvent(
                                    tool_call_id=tc.id,
                                    tool_name=tc.function.name,
                                    success=False,
                                    output="",
                                    error=err_str,
                                )
                            )
                            messages.append(
                                LLMMessage(
                                    role="tool",
                                    tool_call_id=tc.id,
                                    name=tc.function.name,
                                    content=err_str,
                                )
                            )
            else:
                # LLM finished its tool operations and generated final conclusion/thought
                messages.append(LLMMessage(role="assistant", content=resp.content))

                # Verification Phase
                status, v_res = await self.verifier.verify(files_modified=files_modified)
                if status == TaskStatus.DONE:
                    await self.bus.publish(
                        TaskDoneEvent(
                            task_id="turn",
                            summary="Task completed with verified pass",
                            evidence=v_res.stdout,
                        )
                    )
                    return TaskStatus.DONE
                else:
                    # Verification failed: attempt self-repair if budget permits
                    if repair_attempts < self.max_repair_retries:
                        repair_attempts += 1
                        diag = v_res.stderr or v_res.stdout or v_res.diagnostics
                        repair_prompt = (
                            f"Verification failed (attempt {repair_attempts}/{self.max_repair_retries}):\n"
                            f"{diag}\n"
                            "Please diagnose the failure, repair the code using tools, and ensure all tests pass."
                        )
                        messages.append(LLMMessage(role="user", content=repair_prompt))
                        continue
                    else:
                        diag = v_res.stderr or v_res.stdout or v_res.diagnostics
                        await self.bus.publish(
                            TaskBlockedEvent(
                                task_id="turn",
                                reason="Verification failed after maximum retries",
                                diagnostics=diag,
                            )
                        )
                        return TaskStatus.BLOCKED

        # Exceeded max steps
        await self.bus.publish(
            TaskBlockedEvent(
                task_id="turn",
                reason=f"Execution exceeded maximum step limit ({self.max_steps})",
                diagnostics="Step limit reached",
            )
        )
        return TaskStatus.BLOCKED
