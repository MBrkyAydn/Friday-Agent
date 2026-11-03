import pytest
from io import StringIO
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from rich.console import Console
from typer.testing import CliRunner

from friday.core.bus import (
    EventBus,
    AgentThoughtEvent,
    StreamChunkEvent,
    ToolCallRequestedEvent,
    ToolResultEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
    SubagentProgressEvent,
)
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionDecision
from friday.core.verifier import TaskStatus, VerificationResult
from friday.ui.renderer import UIRenderer
from friday.ui.prompts import TerminalPrompter
from friday.ui.repl import FridayREPL
from friday.cli import app


@pytest.mark.asyncio
async def test_renderer_thought_and_stream_events():
    bus = EventBus()
    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    await bus.publish(AgentThoughtEvent(thought="Analyzing repository structure..."))
    await bus.publish(StreamChunkEvent(chunk="Generating code..."))

    output = string_io.getvalue()
    assert "Analyzing repository structure..." in output
    assert "Generating code..." in output


@pytest.mark.asyncio
async def test_renderer_tool_events():
    bus = EventBus()
    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    await bus.publish(
        ToolCallRequestedEvent(
            tool_call_id="c1",
            tool_name="run_command",
            arguments={"command": "pytest -v"},
        )
    )
    await bus.publish(
        ToolResultEvent(
            tool_call_id="c1",
            tool_name="run_command",
            success=True,
            output="5 passed in 0.1s",
        )
    )
    await bus.publish(
        ToolResultEvent(
            tool_call_id="c2",
            tool_name="write_file",
            success=False,
            output="",
            error="Permission denied",
        )
    )

    output = string_io.getvalue()
    assert "run_command" in output
    assert "pytest -v" in output
    assert "5 passed in 0.1s" in output
    assert "Permission denied" in output


@pytest.mark.asyncio
async def test_renderer_task_done_and_blocked_events():
    bus = EventBus()
    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    await bus.publish(
        TaskDoneEvent(
            task_id="t1",
            summary="All tests passed successfully",
            evidence="64 passed",
        )
    )
    await bus.publish(
        TaskBlockedEvent(
            task_id="t2",
            reason="Build failed",
            diagnostics="SyntaxError in main.py:10",
        )
    )

    output = string_io.getvalue()
    assert "DONE" in output
    assert "All tests passed successfully" in output
    assert "64 passed" in output
    assert "BLOCKED" in output
    assert "Build failed" in output
    assert "SyntaxError in main.py:10" in output


@pytest.mark.asyncio
async def test_prompter_allow_deny_always():
    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)

    # Test 'y' -> ALLOW
    prompter_y = TerminalPrompter(console=console, input_fn=lambda prompt: "y")
    decision = await prompter_y({"tool": "write_file", "path": "test.py"})
    assert decision == PermissionDecision.ALLOW

    # Test 'n' -> DENY
    prompter_n = TerminalPrompter(console=console, input_fn=lambda prompt: "n")
    decision = await prompter_n({"tool": "run_command", "command": "rm -rf"})
    assert decision == PermissionDecision.DENY

    # Test 'a' -> ALLOW_ALWAYS
    prompter_a = TerminalPrompter(console=console, input_fn=lambda prompt: "a")
    decision = await prompter_a({"tool": "edit_file", "path": "app.py"})
    assert decision == PermissionDecision.ALLOW_ALWAYS


@pytest.mark.asyncio
async def test_repl_slash_commands(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=False)
    verifier = AsyncMock()
    agent = AsyncMock()
    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None, width=300)
    renderer = UIRenderer(bus=bus, console=console)

    repl = FridayREPL(
        agent=agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
    )

    assert "FRIDAY" in repl.get_prompt_string()

    # /help
    cont = await repl.handle_input("/help")
    assert cont is True
    assert "Available commands" in string_io.getvalue()

    # /yolo toggle
    assert perms.yolo_mode is False
    cont = await repl.handle_input("/yolo")
    assert cont is True
    assert perms.yolo_mode is True
    assert "YOLO mode enabled" in string_io.getvalue()

    cont = await repl.handle_input("/yolo")
    assert cont is True
    assert perms.yolo_mode is False
    assert "YOLO mode disabled" in string_io.getvalue()

    # /status
    cont = await repl.handle_input("/status")
    assert cont is True
    assert tmp_path.name in string_io.getvalue()

    # /exit and /quit
    assert await repl.handle_input("/exit") is False
    assert await repl.handle_input("/quit") is False


@pytest.mark.asyncio
async def test_repl_verify_command(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="64 passed"))
    agent = MagicMock()
    agent.verifier = verifier

    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    repl = FridayREPL(
        agent=agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
    )

    cont = await repl.handle_input("/verify")
    assert cont is True
    verifier.verify.assert_called_once()
    assert "64 passed" in string_io.getvalue()


@pytest.mark.asyncio
async def test_repl_dispatches_user_instruction(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    agent = AsyncMock()
    agent.run_turn.return_value = TaskStatus.DONE

    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    repl = FridayREPL(
        agent=agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
    )

    cont = await repl.handle_input("Build features")
    assert cont is True
    agent.run_turn.assert_called_once_with("Build features")


def test_cli_single_prompt_mode(tmp_path: Path):
    from friday.agent.llm import LLMResponse

    runner = CliRunner()
    mock_resp = LLMResponse(model="test-model", content="Done task", finish_reason="stop")
    with patch("friday.agent.llm.litellm_provider.LiteLLMProvider.complete", new=AsyncMock(return_value=mock_resp)):
        result = runner.invoke(app, ["run", str(tmp_path), "--prompt", "inspect repo", "--yolo"])
        assert result.exit_code == 0
        assert "FRIDAY initialized" in result.stdout
        assert "Executing instruction: 'inspect repo'" in result.stdout


@pytest.mark.asyncio
async def test_repl_use_command(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    agent = AsyncMock()
    mock_router = MagicMock()
    mock_router.active_provider.config.model = "ollama/qwen2.5-coder:7b"
    agent.llm = mock_router

    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    repl = FridayREPL(
        agent=agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
    )

    cont = await repl.handle_input("/use local")
    assert cont is True
    mock_router.set_active_profile.assert_called_once_with("local")
    assert "Switched active profile to: local" in string_io.getvalue()
