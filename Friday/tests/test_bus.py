import pytest
from datetime import datetime
from friday.core.bus import (
    Event,
    EventBus,
    UserPromptEvent,
    AgentThoughtEvent,
    StreamChunkEvent,
    ToolCallRequestedEvent,
    ToolResultEvent,
    PermissionPromptEvent,
    SubagentProgressEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
)


@pytest.mark.asyncio
async def test_event_bus_publish_and_subscribe():
    bus = EventBus()
    received = []

    async def on_chunk(event: StreamChunkEvent):
        received.append(event.chunk)

    bus.subscribe(StreamChunkEvent, on_chunk)
    await bus.publish(StreamChunkEvent(chunk="hello "))
    await bus.publish(StreamChunkEvent(chunk="world"))

    assert received == ["hello ", "world"]


@pytest.mark.asyncio
async def test_event_bus_unsubscribe():
    bus = EventBus()
    received = []

    async def on_event(event: Event):
        received.append(event)

    unsubscribe = bus.subscribe(TaskDoneEvent, on_event)
    await bus.publish(TaskDoneEvent(task_id="t1", summary="success"))
    assert len(received) == 1

    unsubscribe()
    await bus.publish(TaskDoneEvent(task_id="t2", summary="again"))
    assert len(received) == 1


@pytest.mark.asyncio
async def test_event_bus_polymorphic_subscription():
    bus = EventBus()
    all_events = []
    thought_events = []

    async def on_any_event(event: Event):
        all_events.append(event)

    async def on_thought(event: AgentThoughtEvent):
        thought_events.append(event)

    bus.subscribe(Event, on_any_event)
    bus.subscribe(AgentThoughtEvent, on_thought)

    thought = AgentThoughtEvent(thought="planning next step")
    user_prompt = UserPromptEvent(prompt="run tests")

    await bus.publish(thought)
    await bus.publish(user_prompt)

    # Base event subscriber should receive both events
    assert len(all_events) == 2
    assert all_events[0] == thought
    assert all_events[1] == user_prompt

    # Specific subscriber should receive only thought events
    assert len(thought_events) == 1
    assert thought_events[0] == thought


@pytest.mark.asyncio
async def test_event_bus_sync_and_async_handlers():
    bus = EventBus()
    received = []

    def sync_handler(event: StreamChunkEvent):
        received.append(f"sync:{event.chunk}")

    async def async_handler(event: StreamChunkEvent):
        received.append(f"async:{event.chunk}")

    bus.subscribe(StreamChunkEvent, sync_handler)
    bus.subscribe(StreamChunkEvent, async_handler)

    await bus.publish(StreamChunkEvent(chunk="data"))

    assert "sync:data" in received
    assert "async:data" in received
    assert len(received) == 2


@pytest.mark.asyncio
async def test_event_bus_multiple_unsubscribes():
    bus = EventBus()
    received = []

    async def on_event(event: TaskDoneEvent):
        received.append(event)

    unsubscribe = bus.subscribe(TaskDoneEvent, on_event)
    unsubscribe()
    # Unsubscribing again should be idempotent and not raise an error
    unsubscribe()

    await bus.publish(TaskDoneEvent(task_id="t1", summary="done"))
    assert len(received) == 0


def test_event_taxonomy_models():
    # Base Event has UTC timestamp
    event = Event()
    assert isinstance(event.timestamp, datetime)
    assert event.timestamp.tzinfo is not None

    # UserPromptEvent
    user_prompt = UserPromptEvent(prompt="fix the bug")
    assert user_prompt.prompt == "fix the bug"
    assert isinstance(user_prompt.timestamp, datetime)

    # AgentThoughtEvent
    thought = AgentThoughtEvent(thought="analyzing code")
    assert thought.thought == "analyzing code"

    # StreamChunkEvent
    chunk = StreamChunkEvent(chunk="streaming response")
    assert chunk.chunk == "streaming response"

    # ToolCallRequestedEvent
    tool_req = ToolCallRequestedEvent(
        tool_call_id="call_1",
        tool_name="view_file",
        arguments={"path": "main.py"},
    )
    assert tool_req.tool_name == "view_file"
    assert tool_req.arguments == {"path": "main.py"}

    # ToolResultEvent
    tool_res = ToolResultEvent(
        tool_call_id="call_1",
        tool_name="view_file",
        success=True,
        output="file content",
    )
    assert tool_res.output == "file content"
    assert tool_res.error is None

    # PermissionPromptEvent
    perm = PermissionPromptEvent(
        prompt_id="p1",
        description="write file",
        action_type="file_edit",
        details={"path": "main.py"},
    )
    assert perm.action_type == "file_edit"

    # SubagentProgressEvent
    sub_prog = SubagentProgressEvent(
        subagent_id="sub_1",
        role="tester",
        message="tests running",
    )
    assert sub_prog.role == "tester"

    # TaskDoneEvent with default evidence
    done = TaskDoneEvent(task_id="t1", summary="completed")
    assert done.task_id == "t1"
    assert done.summary == "completed"
    assert done.evidence == ""

    # TaskDoneEvent with explicit evidence
    done_with_ev = TaskDoneEvent(task_id="t2", summary="completed", evidence="5 passed")
    assert done_with_ev.evidence == "5 passed"

    # TaskBlockedEvent with default diagnostics
    blocked = TaskBlockedEvent(task_id="b1", reason="test failure")
    assert blocked.reason == "test failure"
    assert blocked.diagnostics == ""

    # TaskBlockedEvent with explicit diagnostics
    blocked_with_diag = TaskBlockedEvent(
        task_id="b2",
        reason="timeout",
        diagnostics="timed out after 60s",
    )
    assert blocked_with_diag.diagnostics == "timed out after 60s"
