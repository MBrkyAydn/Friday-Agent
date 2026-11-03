import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pytest

from friday.core.bus import (
    EventBus,
    ToolCallRequestedEvent,
    ToolResultEvent,
    PermissionPromptEvent,
    TaskDoneEvent,
    UserPromptEvent,
)
from friday.visual.pixel_bridge import PixelAgentsBridge


@pytest.fixture
def mock_pixel_config(tmp_path, monkeypatch):
    pixel_dir = tmp_path / ".pixel-agents"
    pixel_dir.mkdir(parents=True, exist_ok=True)
    server_json = pixel_dir / "server.json"
    server_json.write_text(json.dumps({"port": 3100, "token": "test-token-123"}))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    return server_json


@pytest.mark.asyncio
async def test_server_config_discovery(mock_pixel_config):
    bus = EventBus()
    bridge = PixelAgentsBridge(bus=bus, workspace_path="/workspace/test")
    config = bridge.read_server_config()
    assert config is not None
    port, token = config
    assert port == 3100
    assert token == "test-token-123"


@pytest.mark.asyncio
async def test_server_config_missing_returns_none(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bus = EventBus()
    bridge = PixelAgentsBridge(bus=bus, workspace_path="/workspace/test")
    config = bridge.read_server_config()
    assert config is None


@pytest.mark.asyncio
async def test_event_translation_tool_and_subagent(mock_pixel_config):
    bus = EventBus()
    bridge = PixelAgentsBridge(bus=bus, workspace_path="/workspace/test", session_id="test-session")
    
    posted_events = []
    
    async def mock_post(payload):
        posted_events.append(payload)
        return True

    bridge._send_http_event = mock_post
    await bridge.start()

    # 1. Generic tool call
    await bus.publish(ToolCallRequestedEvent(
        tool_call_id="call-1",
        tool_name="execute_command",
        arguments={"command": "pytest -q"}
    ))
    await asyncio.sleep(0.05)

    assert len(posted_events) >= 1
    pre_tool = next(e for e in posted_events if e["hook_event_name"] == "PreToolUse")
    assert pre_tool["tool_name"] == "Bash"
    assert pre_tool["tool_input"]["command"] == "pytest -q"

    # 2. Tool completed
    await bus.publish(ToolResultEvent(
        tool_call_id="call-1",
        tool_name="execute_command",
        success=True,
        output="passed"
    ))
    await asyncio.sleep(0.05)
    post_tool = next(e for e in posted_events if e["hook_event_name"] == "PostToolUse")
    assert post_tool is not None

    # 3. JARVIS delegation (Subagent spawn)
    await bus.publish(ToolCallRequestedEvent(
        tool_call_id="call-2",
        tool_name="delegate_jarvis",
        arguments={"task": "Create module"}
    ))
    await asyncio.sleep(0.05)
    subagent_start = next(e for e in posted_events if e["hook_event_name"] == "SubagentStart")
    assert subagent_start["agent_type"] == "Jarvis"
    assert subagent_start["run_in_background"] is True

    # 4. JARVIS completed
    await bus.publish(ToolResultEvent(
        tool_call_id="call-2",
        tool_name="delegate_jarvis",
        success=True,
        output="done"
    ))
    await asyncio.sleep(0.05)
    subagent_stop = next(e for e in posted_events if e["hook_event_name"] == "SubagentStop")
    assert subagent_stop is not None

    await bridge.stop()


@pytest.mark.asyncio
async def test_event_translation_permission(mock_pixel_config):
    bus = EventBus()
    bridge = PixelAgentsBridge(bus=bus, workspace_path="/workspace/test", session_id="test-session")
    
    posted_events = []
    bridge._send_http_event = AsyncMock(side_effect=lambda p: posted_events.append(p))
    await bridge.start()

    await bus.publish(PermissionPromptEvent(
        prompt_id="p-1",
        description="Delete database",
        action_type="destructive"
    ))
    await asyncio.sleep(0.05)

    perm_req = next(e for e in posted_events if e["hook_event_name"] == "PermissionRequest")
    assert perm_req["session_id"] == "test-session"

    await bridge.stop()


@pytest.mark.asyncio
async def test_event_translation_task_done(mock_pixel_config):
    bus = EventBus()
    bridge = PixelAgentsBridge(bus=bus, workspace_path="/workspace/test", session_id="test-session")
    
    posted_events = []
    bridge._send_http_event = AsyncMock(side_effect=lambda p: posted_events.append(p))
    await bridge.start()

    await bus.publish(TaskDoneEvent(task_id="t-1", summary="All green"))
    await asyncio.sleep(0.05)

    stop_event = next(e for e in posted_events if e["hook_event_name"] == "Stop")
    assert stop_event["session_id"] == "test-session"

    await bridge.stop()


@pytest.mark.asyncio
async def test_fail_open_when_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    bus = EventBus()
    bridge = PixelAgentsBridge(bus=bus, workspace_path="/workspace/test")
    await bridge.start()

    # Publishing events when server is offline must NEVER raise an exception
    await bus.publish(ToolCallRequestedEvent(
        tool_call_id="call-fail",
        tool_name="execute_command",
        arguments={"command": "ls"}
    ))
    await bus.publish(PermissionPromptEvent(
        prompt_id="p-fail",
        description="test",
        action_type="safe"
    ))
    await bus.publish(TaskDoneEvent(task_id="t-fail", summary="done"))
    await asyncio.sleep(0.05)

    await bridge.stop()
