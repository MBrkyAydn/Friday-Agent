import pytest
from io import StringIO
from pathlib import Path
from rich.console import Console
from unittest.mock import AsyncMock

from friday.core.config import FridayConfig, load_config, save_config
from friday.core.session import Session, SessionTurn, SessionManager
from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController
from friday.ui.renderer import UIRenderer
from friday.ui.repl import FridayREPL


def test_config_defaults_and_validation():
    config = FridayConfig()
    assert config.model == "gemini/gemini-3.8-flash"
    assert config.temperature == 0.2
    assert config.max_context_tokens == 8192
    assert config.yolo_mode is False
    assert config.verification_command is None
    assert config.max_repair_retries == 3
    assert config.max_steps == 10

    custom = FridayConfig(
        model="claude-3-5-sonnet",
        verification_command="pytest -x",
        yolo_mode=True,
    )
    assert custom.model == "claude-3-5-sonnet"
    assert custom.verification_command == "pytest -x"
    assert custom.yolo_mode is True


def test_save_and_load_config_yaml(tmp_path: Path):
    custom_config = FridayConfig(
        model="openai/gpt-4o",
        temperature=0.7,
        verification_command="npm test",
        yolo_mode=True,
    )

    saved_path = save_config(tmp_path, custom_config)
    assert saved_path.exists()
    assert saved_path == tmp_path / ".friday" / "config.yaml"

    loaded = load_config(tmp_path)
    assert loaded.model == "openai/gpt-4o"
    assert loaded.temperature == 0.7
    assert loaded.verification_command == "npm test"
    assert loaded.yolo_mode is True


def test_load_config_missing_file_returns_defaults(tmp_path: Path):
    # No config file in tmp_path
    loaded = load_config(tmp_path)
    assert loaded.model == "gemini/gemini-3.8-flash"
    assert loaded.verification_command is None


def test_session_create_record_turn_and_save(tmp_path: Path):
    mgr = SessionManager()
    session = mgr.create_session(workspace_path=tmp_path)

    assert session.session_id.startswith("session-")
    assert session.workspace_path == str(tmp_path)
    assert len(session.turns) == 0

    mgr.record_turn(
        session=session,
        prompt="Fix calculation bug",
        thoughts=["Identified off-by-one error"],
        tool_calls=[{"name": "edit_file", "path": "calc.py"}],
        status="DONE",
    )

    assert len(session.turns) == 1
    assert session.turns[0].user_prompt == "Fix calculation bug"
    assert session.turns[0].status == "DONE"

    saved_file = mgr.save_session(session, target_dir=tmp_path)
    assert saved_file.exists()
    assert saved_file.suffix == ".json"


def test_session_load_and_list_sessions(tmp_path: Path):
    mgr = SessionManager()

    s1 = mgr.create_session(workspace_path=tmp_path)
    mgr.record_turn(s1, "Prompt 1", ["Thought 1"], [], "DONE")
    f1 = mgr.save_session(s1, target_dir=tmp_path)

    s2 = mgr.create_session(workspace_path=tmp_path)
    mgr.record_turn(s2, "Prompt 2", ["Thought 2"], [], "BLOCKED")
    f2 = mgr.save_session(s2, target_dir=tmp_path)

    sessions_list = mgr.list_sessions(target_dir=tmp_path)
    assert len(sessions_list) == 2
    session_ids = [s["session_id"] for s in sessions_list]
    assert s1.session_id in session_ids
    assert s2.session_id in session_ids

    loaded_s1 = mgr.load_session(f1)
    assert loaded_s1.session_id == s1.session_id
    assert loaded_s1.turns[0].user_prompt == "Prompt 1"


def test_session_reset_clears_turns(tmp_path: Path):
    mgr = SessionManager()
    session = mgr.create_session(workspace_path=tmp_path)
    mgr.record_turn(session, "Prompt", ["Thought"], [], "DONE")
    assert len(session.turns) == 1

    mgr.reset_session(session)
    assert len(session.turns) == 0


@pytest.mark.asyncio
async def test_repl_reset_command_clears_session(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    agent = AsyncMock()
    string_io = StringIO()
    console = Console(file=string_io, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    mgr = SessionManager()
    session = mgr.create_session(workspace_path=tmp_path)
    mgr.record_turn(session, "Step 1", ["Thought"], [], "DONE")

    repl = FridayREPL(
        agent=agent,
        workspace=guard,
        bus=bus,
        perms=perms,
        renderer=renderer,
        console=console,
        session=session,
    )

    assert len(repl.session.turns) == 1
    cont = await repl.handle_input("/reset")
    assert cont is True
    assert len(repl.session.turns) == 0
    assert "reset" in string_io.getvalue().lower()
