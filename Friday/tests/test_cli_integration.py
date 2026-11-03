import os
import asyncio
import io
import json
import shutil
import sys
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock, patch
from rich.console import Console

import pytest
from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController
from friday.core.verifier import VerificationRunner, TaskStatus
from friday.core.config import FridayConfig, save_config, load_config
from friday.core.session import SessionManager, Session
from friday.ui.renderer import UIRenderer
from friday.ui.repl import FridayREPL
from friday.cli import app, setup_runtime


def test_main_module_execution():
    """Verify that python -m friday --version executes successfully."""
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "-m", "friday", "--version"],
        cwd=str(repo_root),
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, f"Failed: {result.stderr}"
    assert "FRIDAY version:" in result.stdout


@pytest.mark.asyncio
async def test_windows_verification_pytest_fallback(tmp_path: Path):
    """Verify VerificationRunner falls back to 'python -m pytest' when 'pytest' is not in PATH."""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.pytest]\n", encoding="utf-8")

    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    mock_runner.execute.return_value = AsyncMock(success=True, output="1 passed", error=None)

    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner)

    with patch("shutil.which", return_value=None):
        status, res = await verifier.verify()
        assert status == TaskStatus.DONE
        mock_runner.execute.assert_called_once()
        called_cmd = mock_runner.execute.call_args.kwargs.get("command") or mock_runner.execute.call_args.args[0]
        assert called_cmd == "python -m pytest"


@pytest.mark.asyncio
async def test_verification_runner_uses_config_command(tmp_path: Path):
    """Verify VerificationRunner honors custom verification_command passed at initialization."""
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    mock_runner.execute.return_value = AsyncMock(success=True, output="Tests ok", error=None)

    verifier = VerificationRunner(
        workspace=guard,
        command_runner=mock_runner,
        verification_command="cargo test",
    )

    status, res = await verifier.verify()
    assert status == TaskStatus.DONE
    mock_runner.execute.assert_called_once()
    called_cmd = mock_runner.execute.call_args.kwargs.get("command") or mock_runner.execute.call_args.args[0]
    assert called_cmd == "cargo test"


@pytest.mark.asyncio
async def test_repl_records_and_persists_turn(tmp_path: Path):
    """Verify FridayREPL records turn into Session and persists JSON to disk."""
    guard = WorkspaceGuard(tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    mock_agent = AsyncMock()
    mock_agent.run_turn.return_value = TaskStatus.DONE

    session_mgr = SessionManager()
    session = session_mgr.create_session(tmp_path)

    repl = FridayREPL(
        agent=mock_agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
        session=session,
        session_manager=session_mgr,
    )

    cont = await repl.handle_input("Add user authentication")
    assert cont is True
    assert len(session.turns) == 1
    assert session.turns[0].user_prompt == "Add user authentication"
    assert session.turns[0].status == "DONE"

    # Verify JSON file was written
    session_file = tmp_path / ".friday" / "sessions" / f"{session.session_id}.json"
    assert session_file.exists()
    saved_data = json.loads(session_file.read_text(encoding="utf-8"))
    assert len(saved_data["turns"]) == 1
    assert saved_data["turns"][0]["user_prompt"] == "Add user authentication"


@pytest.mark.asyncio
async def test_repl_reset_persists_cleared_session(tmp_path: Path):
    """Verify /reset in FridayREPL updates the persisted session file."""
    guard = WorkspaceGuard(tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    session_mgr = SessionManager()
    session = session_mgr.create_session(tmp_path)
    session_mgr.record_turn(session, "Prompt 1", [], [], "DONE")
    session_file = session_mgr.save_session(session, target_dir=tmp_path)

    # Initial check
    initial_data = json.loads(session_file.read_text(encoding="utf-8"))
    assert len(initial_data["turns"]) == 1

    repl = FridayREPL(
        agent=None,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
        session=session,
        session_manager=session_mgr,
    )

    cont = await repl.handle_input("/reset")
    assert cont is True
    assert len(session.turns) == 0

    # Verify updated JSON on disk has empty turns
    updated_data = json.loads(session_file.read_text(encoding="utf-8"))
    assert len(updated_data["turns"]) == 0


def test_cli_setup_runtime_wiring(tmp_path: Path):
    """Verify setup_runtime loads config, registers tools, configures LLM, and sets up session."""
    # Write custom config
    cfg = FridayConfig(
        model="claude-3-5-sonnet",
        temperature=0.5,
        yolo_mode=True,
        verification_command="pytest -x",
        max_repair_retries=2,
        max_steps=7,
    )
    save_config(tmp_path, cfg)

    runtime = setup_runtime(target_dir=tmp_path, yolo=False)

    # 1. Config loaded
    assert runtime["config"].model == "claude-3-5-sonnet"
    assert runtime["config"].verification_command == "pytest -x"

    # 2. Permissions reflect effective YOLO mode
    assert runtime["perms"].yolo_mode is True

    # 3. All 8 tools registered on agent
    agent = runtime["agent"]
    tool_names = [t.name for t in agent.tools]
    expected_tools = [
        "view_file",
        "write_file",
        "edit_file",
        "run_command",
        "search_code",
        "git_status",
        "git_diff",
        "git_commit",
    ]
    for expected in expected_tools:
        assert expected in tool_names, f"Missing tool: {expected}"

    # 4. LLM provider and context manager wired
    from friday.core.router import MultiLLMRouter

    assert agent.llm is not None
    assert isinstance(agent.llm, MultiLLMRouter)
    assert agent.llm.config.model == "claude-3-5-sonnet"
    assert agent.context_manager is not None
    assert agent.max_steps == 7
    assert agent.max_repair_retries == 2

    # 5. Session and SessionManager wired to REPL
    repl = runtime["repl"]
    assert repl.session is not None
    assert repl.session_manager is not None
    assert repl.session.workspace_path == str(tmp_path)


def test_cli_single_prompt_saves_session(tmp_path: Path):
    """Verify running a single prompt via CLI runner creates and saves session."""
    from typer.testing import CliRunner
    from friday.agent.llm import LLMResponse
    runner = CliRunner()

    mock_resp = LLMResponse(model="gemini-2.5-pro", content="I analyzed the project status.", finish_reason="stop")
    with patch("friday.agent.llm.litellm_provider.LiteLLMProvider.complete", new=AsyncMock(return_value=mock_resp)):
        result = runner.invoke(app, ["run", str(tmp_path), "--prompt", "status check", "--yolo"])
        assert result.exit_code == 0

    sessions_dir = tmp_path / ".friday" / "sessions"
    assert sessions_dir.exists()
    session_files = list(sessions_dir.glob("*.json"))
    assert len(session_files) == 1

    saved = json.loads(session_files[0].read_text(encoding="utf-8"))
    assert len(saved["turns"]) == 1
    assert saved["turns"][0]["user_prompt"] == "status check"
    assert saved["turns"][0]["status"] == "DONE"


def test_cli_setup_runtime_ollama_wiring(tmp_path: Path):
    """Verify setup_runtime configures OllamaProvider with default api_base when ollama model is used."""
    from friday.core.router import MultiLLMRouter
    from friday.agent.llm import OllamaProvider

    runtime = setup_runtime(target_dir=tmp_path, model="ollama/qwen2.5-coder:1.5b")
    agent = runtime["agent"]
    assert isinstance(agent.llm, MultiLLMRouter)
    assert agent.llm.active_profile == "local"
    assert isinstance(agent.llm.active_provider, OllamaProvider)
    assert agent.llm.config.model == "ollama/qwen2.5-coder:1.5b"
    assert agent.llm.config.api_base == "http://localhost:11434"


def test_cli_setup_runtime_router_wiring(tmp_path: Path):
    """Verify MultiLLMRouter is wired into runtime with event bus and subagent delegation."""
    from friday.core.router import MultiLLMRouter

    runtime = setup_runtime(target_dir=tmp_path, profile="groq")
    router: MultiLLMRouter = runtime["llm"]
    assert isinstance(router, MultiLLMRouter)
    assert router.active_profile == "groq"
    assert router.bus is runtime["bus"]

    # Verify DelegateSubagentTool shares the same router
    subagent_tool = next(t for t in runtime["tools"] if t.name == "delegate_subagent")
    assert subagent_tool.llm is router

    # Verify all profiles are registered
    for expected in ["local", "gemini-free", "gemini-paid", "groq", "deepseek", "claude"]:
        assert router.has_profile(expected)


def test_cli_run_profile_flags(tmp_path: Path):
    """Verify --profile and --provider flags on friday run."""
    from typer.testing import CliRunner
    from friday.agent.llm import LLMResponse
    runner = CliRunner()

    mock_resp = LLMResponse(model="mock", content="Done", finish_reason="stop")
    with patch("friday.core.router.MultiLLMRouter.complete", new=AsyncMock(return_value=mock_resp)):
        # Test --profile local
        res1 = runner.invoke(app, ["run", str(tmp_path), "--profile", "local", "--prompt", "status", "--yolo"])
        assert res1.exit_code == 0

        # Test --provider claude
        res2 = runner.invoke(app, ["run", str(tmp_path), "--provider", "claude", "--prompt", "status", "--yolo"])
        assert res2.exit_code == 0


def test_cli_use_and_setup_runtime_integration(tmp_path: Path):
    """Verify switching profiles via friday use reflects in subsequent setup_runtime calls."""
    from typer.testing import CliRunner
    runner = CliRunner()

    # 1. Switch to local
    r1 = runner.invoke(app, ["use", "local", "--workspace", str(tmp_path)])
    assert r1.exit_code == 0
    rt1 = setup_runtime(tmp_path)
    assert rt1["llm"].active_profile == "local"
    assert rt1["config"].model == "ollama/qwen2.5-coder"

    # 2. Switch to gemini-free
    r2 = runner.invoke(app, ["use", "gemini-free", "--workspace", str(tmp_path)])
    assert r2.exit_code == 0
    rt2 = setup_runtime(tmp_path)
    assert rt2["llm"].active_profile == "gemini-free"
    assert rt2["config"].model == "gemini/gemini-3.8-flash"


def test_cli_config_set_key_runtime_sync(tmp_path: Path):
    """Verify setting API key via CLI syncs into os.environ in setup_runtime."""
    from typer.testing import CliRunner
    runner = CliRunner()

    r = runner.invoke(app, ["config", "set-key", "CUSTOM_TEST_KEY", "xyz-val-987", "--workspace", str(tmp_path)])
    assert r.exit_code == 0

    # Ensure key wasn't in os.environ or is updated
    setup_runtime(tmp_path)
    assert os.environ.get("CUSTOM_TEST_KEY") == "xyz-val-987"

