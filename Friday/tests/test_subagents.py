import pytest
from pathlib import Path
from friday.core.bus import EventBus, SubagentProgressEvent
from friday.core.workspace import WorkspaceGuard
from friday.agent.subagents.pool import SubagentPool
from friday.agent.subagents.base import SubagentResult


@pytest.mark.asyncio
async def test_subagent_pool_spawns_and_completes(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    pool = SubagentPool(bus=bus, workspace=guard)

    async def dummy_worker(prompt: str) -> SubagentResult:
        return SubagentResult(success=True, summary=f"Processed: {prompt}")

    task_id = await pool.spawn(role="researcher", prompt="find all routes", runner=dummy_worker)
    assert task_id in pool.active_tasks

    result = await pool.wait_for(task_id)
    assert result.success is True
    assert "Processed: find all routes" in result.summary
    assert task_id not in pool.active_tasks


@pytest.mark.asyncio
async def test_subagent_pool_wait_for_nonexistent(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    pool = SubagentPool(bus=bus, workspace=guard)

    result = await pool.wait_for("nonexistent-id")
    assert result.success is False
    assert "not found" in result.error.lower()


@pytest.mark.asyncio
async def test_subagent_pool_publishes_progress_events(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    pool = SubagentPool(bus=bus, workspace=guard)

    events: list[SubagentProgressEvent] = []

    async def on_progress(event: SubagentProgressEvent):
        events.append(event)

    bus.subscribe(SubagentProgressEvent, on_progress)

    async def dummy_worker(prompt: str) -> SubagentResult:
        return SubagentResult(success=True, summary="All done")

    task_id = await pool.spawn(role="coder", prompt="write helper function", runner=dummy_worker)
    await pool.wait_for(task_id)

    assert len(events) == 2
    assert "Starting:" in events[0].message
    assert events[1].message == "Completed"
    assert events[0].role == "coder"
    assert events[1].role == "coder"


@pytest.mark.asyncio
async def test_subagent_pool_concurrent_tasks(tmp_path: Path):
    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    pool = SubagentPool(bus=bus, workspace=guard)

    async def worker_1(prompt: str) -> SubagentResult:
        return SubagentResult(success=True, summary="Result 1")

    async def worker_2(prompt: str) -> SubagentResult:
        return SubagentResult(success=False, summary="", error="Error 2")

    t1 = await pool.spawn(role="tester", prompt="run tests", runner=worker_1)
    t2 = await pool.spawn(role="debugger", prompt="debug fail", runner=worker_2)

    assert len(pool.active_tasks) == 2

    r1 = await pool.wait_for(t1)
    r2 = await pool.wait_for(t2)

    assert r1.success is True
    assert r2.success is False
    assert r2.error == "Error 2"
    assert len(pool.active_tasks) == 0
