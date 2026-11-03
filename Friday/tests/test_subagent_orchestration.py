import io
import json
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController
from friday.core.verifier import TaskStatus, VerificationResult
from friday.agent.lead import LeadAgent
from friday.agent.llm import (
    LLMProvider,
    LLMMessage,
    LLMResponse,
    ToolCall,
    FunctionCall,
    LLMConfig,
)
from friday.agent.subagents.pool import SubagentPool
from friday.agent.subagents.base import SubagentResult
from friday.tools.subagent import DelegateSubagentTool
from friday.cli import setup_runtime
from friday.ui.repl import FridayREPL
from rich.console import Console


@pytest.mark.asyncio
async def test_lead_agent_compacts_context_in_flight(tmp_path: Path):
    """Verify that LeadAgent calls context_manager.compact() in-flight during run_turn()."""
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    mock_verifier = MagicMock()
    mock_verifier.verify = AsyncMock(
        return_value=(TaskStatus.DONE, VerificationResult(passed=True, stdout="Passed"))
    )

    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(model="test-model", content="Completed work", finish_reason="stop")
    )

    mock_context_mgr = MagicMock()
    mock_context_mgr.compact = MagicMock(side_effect=lambda msgs: msgs)

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=mock_verifier,
        llm=mock_llm,
        context_manager=mock_context_mgr,
    )

    status = await agent.run_turn("Inspect codebase")
    assert status == TaskStatus.DONE
    assert mock_context_mgr.compact.call_count >= 1


@pytest.mark.asyncio
async def test_lead_agent_delegates_to_subagent_tool(tmp_path: Path):
    """Verify LeadAgent can execute delegate_subagent tool call in ReAct loop."""
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    pool = SubagentPool(bus=bus, workspace=guard)

    tool = DelegateSubagentTool(workspace=guard, permissions=perms, pool=pool)

    # Mock pool.spawn_worker and wait_for
    pool.spawn_worker = AsyncMock(return_value="subagent-task-1")
    pool.wait_for = AsyncMock(
        return_value=SubagentResult(success=True, summary="Researcher examined repository architecture.")
    )

    mock_verifier = MagicMock()
    mock_verifier.verify = AsyncMock(
        return_value=(TaskStatus.DONE, VerificationResult(passed=True, stdout="All verified"))
    )

    # Step 1: LLM returns delegate_subagent tool call
    tc = ToolCall(
        id="call_delegate_1",
        function=FunctionCall(
            name="delegate_subagent",
            arguments={"role": "researcher", "task_description": "Analyze design"},
        ),
    )
    resp1 = LLMResponse(model="test-model", tool_calls=[tc], content="")
    # Step 2: LLM returns final summary
    resp2 = LLMResponse(model="test-model", content="I analyzed the design via researcher.", finish_reason="stop")

    mock_llm = MagicMock()
    mock_llm.complete = AsyncMock(side_effect=[resp1, resp2])

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=mock_verifier,
        llm=mock_llm,
        tools=[tool],
    )

    status = await agent.run_turn("Research project design")
    assert status == TaskStatus.DONE
    assert pool.spawn_worker.call_count == 1
    assert pool.wait_for.call_count == 1


def test_cli_wires_subagent_pool_and_tool(tmp_path: Path):
    """Verify setup_runtime initializes SubagentPool, DelegateSubagentTool, and wires them to agent and REPL."""
    runtime = setup_runtime(target_dir=tmp_path, yolo=True)

    # SubagentPool initialized and exposed in runtime
    assert "subagent_pool" in runtime
    assert isinstance(runtime["subagent_pool"], SubagentPool)

    # DelegateSubagentTool is registered in tools
    tool_names = [t.name for t in runtime["tools"]]
    assert "delegate_subagent" in tool_names

    # Agent has delegate_subagent tool
    agent_tool_names = [t.name for t in runtime["agent"].tools]
    assert "delegate_subagent" in agent_tool_names

    # REPL has subagent_pool reference
    assert runtime["repl"].subagent_pool is runtime["subagent_pool"]


@pytest.mark.asyncio
async def test_repl_model_command_switches_model(tmp_path: Path):
    """Verify /model command in REPL updates the active model on the agent."""
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=False, color_system=None)
    renderer = MagicMock()

    mock_llm = MagicMock()
    mock_llm.config = LLMConfig(model="gemini/gemini-flash-lite-latest")
    mock_agent = MagicMock()
    mock_agent.llm = mock_llm

    repl = FridayREPL(
        agent=mock_agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
    )

    cont = await repl.handle_input("/model claude-3-5-sonnet")
    assert cont is True
    assert mock_llm.config.model == "claude-3-5-sonnet"
    assert "Model switched to: claude-3-5-sonnet" in out_buf.getvalue()


@pytest.mark.asyncio
async def test_repl_subagents_command(tmp_path: Path):
    """Verify /subagents command in REPL renders subagent task information."""
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=False, color_system=None)
    renderer = MagicMock()
    pool = SubagentPool(bus=bus, workspace=guard)

    repl = FridayREPL(
        agent=MagicMock(),
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
        subagent_pool=pool,
    )

    # Empty active tasks
    cont = await repl.handle_input("/subagents")
    assert cont is True
    assert "No active subagent tasks" in out_buf.getvalue()

