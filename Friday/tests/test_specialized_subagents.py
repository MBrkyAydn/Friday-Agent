import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional

from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionTier
from friday.tools.filesystem import ViewFileTool, WriteFileTool, EditFileTool
from friday.tools.shell import RunCommandTool
from friday.agent.llm import (
    LLMProvider,
    LLMMessage,
    LLMResponse,
    ToolCall,
    FunctionCall,
)
from friday.agent.subagents.base import SubagentResult, BaseSubagent
from friday.agent.subagents.researcher import ResearcherSubagent
from friday.agent.subagents.coder import CoderSubagent
from friday.agent.subagents.tester import TesterSubagent
from friday.agent.subagents.pool import SubagentPool


class MockSubagentLLM(LLMProvider):
    def __init__(self, responses: List[LLMResponse]) -> None:
        self.responses = responses
        self.call_count = 0

    async def complete(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> LLMResponse:
        if self.call_count < len(self.responses):
            resp = self.responses[self.call_count]
            self.call_count += 1
            return resp
        return LLMResponse(model="mock", content="Done", finish_reason="stop")


def test_researcher_enforces_read_only_tools(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)

    view_tool = ViewFileTool(workspace=guard, permissions=perms)
    write_tool = WriteFileTool(workspace=guard, permissions=perms)
    cmd_tool = RunCommandTool(workspace=guard, permissions=perms)

    researcher = ResearcherSubagent(
        workspace=guard,
        tools=[view_tool, write_tool, cmd_tool],
    )

    assert researcher.role == "researcher"
    # Ensure write and shell tools were stripped out
    tool_names = [t.name for t in researcher.tools]
    assert "view_file" in tool_names
    assert "write_file" not in tool_names
    assert "run_command" not in tool_names


@pytest.mark.asyncio
async def test_researcher_subagent_explores_and_returns_summary(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    view_tool = ViewFileTool(workspace=guard, permissions=perms)

    (tmp_path / "config.py").write_text("PORT = 8080\nHOST = 'localhost'", encoding="utf-8")

    resp1 = LLMResponse(
        model="mock",
        content="I will inspect config.py",
        tool_calls=[
            ToolCall(
                id="call_v1",
                function=FunctionCall(name="view_file", arguments={"path": "config.py"}),
            )
        ],
    )
    resp2 = LLMResponse(
        model="mock",
        content="The server port is configured to 8080.",
        finish_reason="stop",
    )

    mock_llm = MockSubagentLLM([resp1, resp2])
    researcher = ResearcherSubagent(
        workspace=guard,
        llm=mock_llm,
        tools=[view_tool],
    )

    result = await researcher.run("What is the configured port?")
    assert result.success is True
    assert "8080" in result.summary


@pytest.mark.asyncio
async def test_coder_subagent_modifies_code(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    write_tool = WriteFileTool(workspace=guard, permissions=perms)

    resp1 = LLMResponse(
        model="mock",
        content="Creating utils.py",
        tool_calls=[
            ToolCall(
                id="call_w1",
                function=FunctionCall(
                    name="write_file",
                    arguments={"path": "utils.py", "content": "def add(a, b): return a + b\n"},
                ),
            )
        ],
    )
    resp2 = LLMResponse(
        model="mock",
        content="Successfully created utils.py with add function.",
        finish_reason="stop",
    )

    mock_llm = MockSubagentLLM([resp1, resp2])
    coder = CoderSubagent(
        workspace=guard,
        llm=mock_llm,
        tools=[write_tool],
    )

    assert coder.role == "coder"
    result = await coder.run("Create utils.py with an add function")

    assert result.success is True
    assert (tmp_path / "utils.py").exists()
    assert "def add" in (tmp_path / "utils.py").read_text(encoding="utf-8")
    assert "utils.py" in result.summary


@pytest.mark.asyncio
async def test_tester_subagent_executes_tests_and_parses_results(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    cmd_tool = RunCommandTool(workspace=guard, permissions=perms)

    resp1 = LLMResponse(
        model="mock",
        content="Running test command",
        tool_calls=[
            ToolCall(
                id="call_t1",
                function=FunctionCall(
                    name="run_command",
                    arguments={"command": "python -c \"print('42 passed')\""},
                ),
            )
        ],
    )
    resp2 = LLMResponse(
        model="mock",
        content="Test execution passed: 42 tests succeeded.",
        finish_reason="stop",
    )

    mock_llm = MockSubagentLLM([resp1, resp2])
    tester = TesterSubagent(
        workspace=guard,
        llm=mock_llm,
        tools=[cmd_tool],
    )

    assert tester.role == "tester"
    result = await tester.run("Execute test suite")

    assert result.success is True
    assert "42 tests succeeded" in result.summary


@pytest.mark.asyncio
async def test_subagent_pool_spawn_worker_with_specialized_subagents(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    view_tool = ViewFileTool(workspace=guard, permissions=perms)

    (tmp_path / "readme.txt").write_text("FRIDAY CLI Documentation", encoding="utf-8")

    resp1 = LLMResponse(
        model="mock",
        content="Inspecting readme",
        tool_calls=[
            ToolCall(
                id="call_vw",
                function=FunctionCall(name="view_file", arguments={"path": "readme.txt"}),
            )
        ],
    )
    resp2 = LLMResponse(
        model="mock",
        content="Read documentation: FRIDAY CLI Documentation.",
        finish_reason="stop",
    )

    mock_llm = MockSubagentLLM([resp1, resp2])
    researcher = ResearcherSubagent(workspace=guard, llm=mock_llm, tools=[view_tool])

    pool = SubagentPool(bus=bus, workspace=guard)
    task_id = await pool.spawn_worker(researcher, "Read readme.txt")

    assert task_id.startswith("subagent-researcher-")
    result = await pool.wait_for(task_id)

    assert result.success is True
    assert "Documentation" in result.summary


@pytest.mark.asyncio
async def test_subagent_handles_tool_errors_gracefully(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)

    # Missing tools map
    resp1 = LLMResponse(
        model="mock",
        content="Invoking unknown tool",
        tool_calls=[
            ToolCall(
                id="call_err",
                function=FunctionCall(name="non_existent_tool", arguments={}),
            )
        ],
    )
    resp2 = LLMResponse(
        model="mock",
        content="Encountered tool error and reported.",
        finish_reason="stop",
    )

    mock_llm = MockSubagentLLM([resp1, resp2])
    researcher = ResearcherSubagent(workspace=guard, llm=mock_llm, tools=[])

    result = await researcher.run("Try unknown tool")
    assert result.success is True
    assert "reported" in result.summary.lower()
