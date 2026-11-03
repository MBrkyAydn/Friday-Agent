import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from friday.core.bus import (
    EventBus,
    AgentThoughtEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
)
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import TaskStatus, VerificationResult
from friday.agent.lead import LeadAgent


@pytest.mark.asyncio
async def test_lead_agent_runs_turn_and_verifies(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="All 3 passed"))

    agent = LeadAgent(bus=bus, workspace=guard, verifier=verifier)
    status = await agent.run_turn("Refactor login controller")

    assert status == TaskStatus.DONE
    verifier.verify.assert_called_once()


@pytest.mark.asyncio
async def test_lead_agent_verification_failure_blocks(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    verifier = AsyncMock()
    verifier.verify.return_value = (
        TaskStatus.IN_PROGRESS,
        VerificationResult(passed=False, stdout="", stderr="2 tests failed"),
    )

    agent = LeadAgent(bus=bus, workspace=guard, verifier=verifier)

    blocked_events: list[TaskBlockedEvent] = []

    async def on_blocked(e: TaskBlockedEvent):
        blocked_events.append(e)

    bus.subscribe(TaskBlockedEvent, on_blocked)

    status = await agent.run_turn("Fix buggy query")

    assert status == TaskStatus.BLOCKED
    assert len(blocked_events) == 1
    assert "2 tests failed" in blocked_events[0].diagnostics


@pytest.mark.asyncio
async def test_lead_agent_emits_thought_and_done_events(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="Coverage 100%"))

    agent = LeadAgent(bus=bus, workspace=guard, verifier=verifier)

    thoughts: list[AgentThoughtEvent] = []
    done_events: list[TaskDoneEvent] = []

    bus.subscribe(AgentThoughtEvent, lambda e: thoughts.append(e))
    bus.subscribe(TaskDoneEvent, lambda e: done_events.append(e))

    status = await agent.run_turn("Add payment gateway")

    assert status == TaskStatus.DONE
    assert len(thoughts) == 1
    assert "Add payment gateway" in thoughts[0].thought
    assert len(done_events) == 1
    assert done_events[0].evidence == "Coverage 100%"
