import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest

from friday.cli import setup_runtime
from friday.visual.pixel_bridge import PixelAgentsBridge


@pytest.mark.asyncio
async def test_setup_runtime_initializes_pixel_bridge(tmp_path):
    runtime = setup_runtime(tmp_path)
    assert "pixel_bridge" in runtime
    bridge = runtime["pixel_bridge"]
    assert isinstance(bridge, PixelAgentsBridge)
    assert bridge.workspace_path == str(tmp_path)
    
    # Clean up
    await bridge.stop()


@pytest.mark.asyncio
async def test_runtime_events_propagate_to_bridge(tmp_path):
    from friday.core.bus import UserPromptEvent, ToolCallRequestedEvent

    runtime = setup_runtime(tmp_path)
    bridge = runtime["pixel_bridge"]
    bus = runtime["bus"]

    received = []
    bridge._send_http_event = AsyncMock(side_effect=lambda p: received.append(p))
    await bridge.start()

    # Publish UserPromptEvent
    await bus.publish(UserPromptEvent(prompt="test prompt"))
    await asyncio.sleep(0.05)

    assert any(e["hook_event_name"] == "SessionStart" for e in received)

    # Publish ToolCallRequestedEvent
    await bus.publish(ToolCallRequestedEvent(
        tool_call_id="call-123",
        tool_name="execute_command",
        arguments={"command": "dir"}
    ))
    await asyncio.sleep(0.05)

    assert any(e["hook_event_name"] == "PreToolUse" for e in received)

    await bridge.stop()
