import io
import pytest
from pathlib import Path
from unittest.mock import AsyncMock, patch
from rich.console import Console

from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController
from friday.core.verifier import TaskStatus, VerificationResult
from friday.core.session import SessionManager, Session, SessionTurn
from friday.agent.lead import LeadAgent
from friday.agent.llm import LLMProvider, LLMMessage, LLMResponse
from friday.ui.renderer import UIRenderer
from friday.ui.repl import FridayREPL


class DummyLLM(LLMProvider):
    def __init__(self):
        self.call_history = []

    async def complete(self, messages, tools=None) -> LLMResponse:
        self.call_history.append(list(messages))
        return LLMResponse(
            model="dummy-model",
            content="I completed the task.",
            finish_reason="stop",
        )


@pytest.mark.asyncio
async def test_lead_agent_ingests_friday_md(tmp_path: Path):
    """Verify LeadAgent reads FRIDAY.md from workspace and includes it in system prompt."""
    friday_md = tmp_path / "FRIDAY.md"
    friday_md.write_text("Rule 1: Always write type annotations.\nRule 2: Keep functions short.", encoding="utf-8")

    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    dummy_llm = DummyLLM()
    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="All tests passed"))

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=mock_verifier,
        llm=dummy_llm,
    )

    status = await agent.run_turn("Implement feature")
    assert status == TaskStatus.DONE
    assert len(dummy_llm.call_history) == 1

    messages = dummy_llm.call_history[0]
    system_msg = messages[0]
    assert system_msg.role == "system"
    assert "## Target Project Instructions (from FRIDAY.md):" in system_msg.content
    assert "Rule 1: Always write type annotations." in system_msg.content
    assert "Rule 2: Keep functions short." in system_msg.content


@pytest.mark.asyncio
async def test_lead_agent_truncates_large_friday_md(tmp_path: Path):
    """Verify LeadAgent caps FRIDAY.md ingestion at 4000 characters."""
    friday_md = tmp_path / "FRIDAY.md"
    large_content = "A" * 6000
    friday_md.write_text(large_content, encoding="utf-8")

    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    dummy_llm = DummyLLM()
    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="ok"))

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=mock_verifier,
        llm=dummy_llm,
    )

    await agent.run_turn("Check instructions")
    messages = dummy_llm.call_history[0]
    system_msg = messages[0]
    assert "## Target Project Instructions (from FRIDAY.md):" in system_msg.content
    # Truncated to 4000 chars
    assert ("A" * 4000) in system_msg.content
    assert ("A" * 4001) not in system_msg.content


@pytest.mark.asyncio
async def test_lead_agent_without_friday_md(tmp_path: Path):
    """Verify LeadAgent system prompt remains standard when no FRIDAY.md is present."""
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    dummy_llm = DummyLLM()
    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="ok"))

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=mock_verifier,
        llm=dummy_llm,
    )

    await agent.run_turn("Clean turn")
    messages = dummy_llm.call_history[0]
    system_msg = messages[0]
    assert "## Target Project Instructions (from FRIDAY.md):" not in system_msg.content


@pytest.mark.asyncio
async def test_lead_agent_injects_past_session_turns(tmp_path: Path):
    """Verify LeadAgent injects past session turns into LLM messages for conversational memory."""
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    dummy_llm = DummyLLM()
    mock_verifier = AsyncMock()
    mock_verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="ok"))

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=mock_verifier,
        llm=dummy_llm,
    )

    session_mgr = SessionManager()
    session = session_mgr.create_session(tmp_path)
    session.turns.append(
        SessionTurn(
            user_prompt="Create user model",
            thoughts=["Created User class in models.py"],
            status="DONE",
        )
    )
    session.turns.append(
        SessionTurn(
            user_prompt="Add user repository",
            thoughts=["Created UserRepository in repo.py"],
            status="DONE",
        )
    )

    await agent.run_turn("Now add user controller", session=session)

    messages = dummy_llm.call_history[0]
    # system message + 2 past turns (user, assistant each) + current user prompt = 6 messages
    assert len(messages) == 6
    assert messages[0].role == "system"
    assert messages[1].role == "user"
    assert messages[1].content == "Create user model"
    assert messages[2].role == "assistant"
    assert "Created User class in models.py" in messages[2].content
    assert messages[3].role == "user"
    assert messages[3].content == "Add user repository"
    assert messages[4].role == "assistant"
    assert "Created UserRepository in repo.py" in messages[4].content
    assert messages[5].role == "user"
    assert messages[5].content == "Now add user controller"


@pytest.mark.asyncio
async def test_repl_maintains_conversational_history(tmp_path: Path):
    """Verify FridayREPL passes session into agent.run_turn and records turns."""
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

    await repl.handle_input("Turn 1 prompt")
    mock_agent.run_turn.assert_called_with("Turn 1 prompt", session=session)

    await repl.handle_input("Turn 2 prompt")
    mock_agent.run_turn.assert_called_with("Turn 2 prompt", session=session)

    assert len(session.turns) == 2
    assert session.turns[0].user_prompt == "Turn 1 prompt"
    assert session.turns[1].user_prompt == "Turn 2 prompt"


@pytest.mark.asyncio
async def test_repl_history_command(tmp_path: Path):
    """Verify /history command in FridayREPL renders formatted history of past turns."""
    guard = WorkspaceGuard(tmp_path)
    bus = EventBus()
    perms = PermissionController(yolo_mode=True)
    out_buf = io.StringIO()
    console = Console(file=out_buf, force_terminal=False, color_system=None)
    renderer = UIRenderer(bus=bus, console=console)

    session_mgr = SessionManager()
    session = session_mgr.create_session(tmp_path)
    session_mgr.record_turn(session, "First instruction", ["Plan verified"], [], "DONE")
    session_mgr.record_turn(session, "Second instruction", ["Syntax error"], [], "BLOCKED")

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

    cont = await repl.handle_input("/history")
    assert cont is True

    output = out_buf.getvalue()
    assert "First instruction" in output
    assert "Second instruction" in output
    assert "DONE" in output
    assert "BLOCKED" in output
