import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

from friday.core.bus import (
    EventBus,
    AgentThoughtEvent,
    ToolCallRequestedEvent,
    ToolResultEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
)
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController
from friday.core.verifier import TaskStatus, VerificationResult
from friday.tools.filesystem import ViewFileTool, WriteFileTool, EditFileTool
from friday.tools.shell import RunCommandTool
from friday.agent.lead import LeadAgent
from friday.agent.llm import (
    LLMProvider,
    LLMMessage,
    LLMResponse,
    ToolCall,
    FunctionCall,
    TokenUsage,
)


class MockLLMProvider(LLMProvider):
    def __init__(self, responses: Optional[List[LLMResponse]] = None) -> None:
        self.responses: List[LLMResponse] = responses or []
        self.call_count = 0
        self.history: List[List[LLMMessage]] = []
        self.tools_received: List[Optional[List[Dict[str, Any]]]] = []

    async def complete(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        self.history.append(list(messages))
        self.tools_received.append(tools)
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        # Default fallback response if no more configured
        self.call_count += 1
        return LLMResponse(
        model="mock-model",content="Done", finish_reason="stop")


def test_tool_to_schema(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)

    view_tool = ViewFileTool(workspace=guard, permissions=perms)
    write_tool = WriteFileTool(workspace=guard, permissions=perms)
    edit_tool = EditFileTool(workspace=guard, permissions=perms)
    cmd_tool = RunCommandTool(workspace=guard, permissions=perms)

    for tool in [view_tool, write_tool, edit_tool, cmd_tool]:
        schema = tool.to_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == tool.name
        assert fn["description"] == tool.description
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
        assert "properties" in fn["parameters"]


@pytest.mark.asyncio
async def test_react_loop_executes_tool_and_completes(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    write_tool = WriteFileTool(workspace=guard, permissions=perms)

    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="All tests passed"))

    # Turn 1: LLM decides to call write_file
    resp1 = LLMResponse(
        model="mock-model",
        content="I will create hello.py",
        tool_calls=[
            ToolCall(
                id="call_1",
                function=FunctionCall(
                    name="write_file",
                    arguments={"path": "hello.py", "content": "print('hello world')"},
                ),
            )
        ],
    )
    # Turn 2: LLM observes tool result and finishes
    resp2 = LLMResponse(
        model="mock-model",
        content="File created successfully. Done.",
        tool_calls=[],
        finish_reason="stop",
    )

    mock_llm = MockLLMProvider(responses=[resp1, resp2])
    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=mock_llm,
        tools=[write_tool],
    )

    status = await agent.run_turn("Create hello.py with hello world")

    assert status == TaskStatus.DONE
    assert (tmp_path / "hello.py").exists()
    assert (tmp_path / "hello.py").read_text(encoding="utf-8") == "print('hello world')"
    assert mock_llm.call_count == 2
    verifier.verify.assert_called_once()


@pytest.mark.asyncio
async def test_react_loop_publishes_all_bus_events(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    write_tool = WriteFileTool(workspace=guard, permissions=perms)

    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="OK"))

    events = []
    bus.subscribe(AgentThoughtEvent, lambda e: events.append(e))
    bus.subscribe(ToolCallRequestedEvent, lambda e: events.append(e))
    bus.subscribe(ToolResultEvent, lambda e: events.append(e))
    bus.subscribe(TaskDoneEvent, lambda e: events.append(e))

    resp1 = LLMResponse(
        model="mock-model",
        content="Writing test file",
        tool_calls=[
            ToolCall(
                id="call_abc",
                function=FunctionCall(
                    name="write_file",
                    arguments={"path": "test.txt", "content": "data"},
                ),
            )
        ],
    )
    resp2 = LLMResponse(
        model="mock-model",content="Work finished", finish_reason="stop")

    mock_llm = MockLLMProvider(responses=[resp1, resp2])
    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=mock_llm,
        tools=[write_tool],
    )

    await agent.run_turn("Write test.txt")

    event_types = [type(e) for e in events]
    assert AgentThoughtEvent in event_types
    assert ToolCallRequestedEvent in event_types
    assert ToolResultEvent in event_types
    assert TaskDoneEvent in event_types

    tool_req = next(e for e in events if isinstance(e, ToolCallRequestedEvent))
    assert tool_req.tool_name == "write_file"
    assert tool_req.tool_call_id == "call_abc"

    tool_res = next(e for e in events if isinstance(e, ToolResultEvent))
    assert tool_res.tool_name == "write_file"
    assert tool_res.success is True


@pytest.mark.asyncio
async def test_react_loop_triggers_self_repair_on_verification_failure(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    write_tool = WriteFileTool(workspace=guard, permissions=perms)

    verifier = AsyncMock()
    # First verify fails; second verify passes
    verifier.verify.side_effect = [
        (TaskStatus.BLOCKED, VerificationResult(passed=False, stderr="SyntaxError: invalid syntax")),
        (TaskStatus.DONE, VerificationResult(passed=True, stdout="All 10 tests passed")),
    ]

    # Turn 1: Write buggy code
    resp1 = LLMResponse(
        model="mock-model",
        content="Writing buggy code",
        tool_calls=[
            ToolCall(
                id="c1",
                function=FunctionCall(
                    name="write_file",
                    arguments={"path": "main.py", "content": "def broken("},
                ),
            )
        ],
    )
    # Turn 2: Done initial implementation -> verification triggers and fails
    resp2 = LLMResponse(
        model="mock-model",content="Done initial code")
    # Turn 3: Received verification failure feedback, fixes the bug
    resp3 = LLMResponse(
        model="mock-model",
        content="Fixing syntax error",
        tool_calls=[
            ToolCall(
                id="c2",
                function=FunctionCall(
                    name="write_file",
                    arguments={"path": "main.py", "content": "def broken(): pass"},
                ),
            )
        ],
    )
    # Turn 4: Done repair
    resp4 = LLMResponse(
        model="mock-model",content="Fixed error. Verifying again.")

    mock_llm = MockLLMProvider(responses=[resp1, resp2, resp3, resp4])
    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=mock_llm,
        tools=[write_tool],
        max_repair_retries=3,
    )

    status = await agent.run_turn("Build main.py")

    assert status == TaskStatus.DONE
    assert verifier.verify.call_count == 2
    # Verify the failure trace was passed to the LLM in message history
    history_contains_error = any(
        "SyntaxError: invalid syntax" in str(msg.content)
        for h in mock_llm.history
        for msg in h
    )
    assert history_contains_error


@pytest.mark.asyncio
async def test_react_loop_blocks_when_max_repair_retries_exceeded(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)

    verifier = AsyncMock()
    # Always fails
    verifier.verify.return_value = (
        TaskStatus.BLOCKED,
        VerificationResult(passed=False, stderr="Persistent failure"),
    )

    # LLM keeps responding with "Trying fix"
    responses = [
        LLMResponse(
        model="mock-model",content=f"Attempting repair turn {i}")
        for i in range(10)
    ]
    mock_llm = MockLLMProvider(responses=responses)

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=mock_llm,
        max_repair_retries=2,
    )

    status = await agent.run_turn("Fix the failing test")

    assert status == TaskStatus.BLOCKED
    assert verifier.verify.call_count == 3  # Initial + 2 retries


@pytest.mark.asyncio
async def test_react_loop_bounds_max_steps(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    write_tool = WriteFileTool(workspace=guard, permissions=perms)

    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="OK"))

    # LLM infinitely generates tool calls
    infinite_tool_responses = [
        LLMResponse(
        model="mock-model",
            content=f"Loop step {i}",
            tool_calls=[
                ToolCall(
                    id=f"call_{i}",
                    function=FunctionCall(
                        name="write_file",
                        arguments={"path": f"file_{i}.txt", "content": "data"},
                    ),
                )
            ],
        )
        for i in range(20)
    ]
    mock_llm = MockLLMProvider(responses=infinite_tool_responses)

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=mock_llm,
        tools=[write_tool],
        max_steps=4,
    )

    blocked_events = []
    bus.subscribe(TaskBlockedEvent, lambda e: blocked_events.append(e))

    status = await agent.run_turn("Run endlessly")

    assert status == TaskStatus.BLOCKED
    assert mock_llm.call_count == 4
    assert len(blocked_events) == 1
    assert "step limit" in blocked_events[0].reason.lower()


@pytest.mark.asyncio
async def test_react_loop_handles_tool_execution_error(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()

    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="OK"))

    # Tool call to non-existent tool
    resp1 = LLMResponse(
        model="mock-model",
        content="Calling unknown tool",
        tool_calls=[
            ToolCall(
                id="call_unknown",
                function=FunctionCall(
                    name="non_existent_tool",
                    arguments={"foo": "bar"},
                ),
            )
        ],
    )
    resp2 = LLMResponse(
        model="mock-model",content="Handled missing tool. Done.")

    mock_llm = MockLLMProvider(responses=[resp1, resp2])
    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=mock_llm,
        tools=[],
    )

    status = await agent.run_turn("Try unknown tool")
    assert status == TaskStatus.DONE

    # Verify that the tool error message was returned to the LLM
    last_history = mock_llm.history[-1]
    tool_message = next((m for m in last_history if m.role == "tool"), None)
    assert tool_message is not None
    assert "Unknown tool" in tool_message.content or "not found" in tool_message.content.lower()


@pytest.mark.asyncio
async def test_backwards_compatibility_without_llm(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="Verified"))

    agent = LeadAgent(bus=bus, workspace=guard, verifier=verifier, llm=None)
    status = await agent.run_turn("No LLM instruction")

    assert status == TaskStatus.DONE
    verifier.verify.assert_called_once()
