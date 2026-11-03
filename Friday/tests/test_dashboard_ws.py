import asyncio
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from friday.core.bus import (
    EventBus,
    ToolCallRequestedEvent,
    ToolResultEvent,
    TaskDoneEvent,
    PermissionPromptEvent,
)
from friday.dashboard.server import create_dashboard_app


def test_websocket_broadcasts_events(tmp_path):
    bus = EventBus()
    app = create_dashboard_app(workspace_path=tmp_path, bus=bus)
    client = TestClient(app)

    with client.websocket_connect("/ws") as ws:
        # Publish tool requested event
        asyncio.run(bus.publish(ToolCallRequestedEvent(
            tool_call_id="c-1",
            tool_name="execute_command",
            arguments={"command": "ls -la"}
        )))

        msg = ws.receive_json()
        assert msg["type"] == "tool_start"
        assert msg["tool_name"] == "execute_command"
        assert msg["arguments"]["command"] == "ls -la"

        # Publish tool result event
        asyncio.run(bus.publish(ToolResultEvent(
            tool_call_id="c-1",
            tool_name="execute_command",
            success=True,
            output="file.txt"
        )))
        msg2 = ws.receive_json()
        assert msg2["type"] == "tool_result"
        assert msg2["success"] is True

        # Publish task done event
        asyncio.run(bus.publish(TaskDoneEvent(
            task_id="t-100",
            summary="Verification passed"
        )))
        msg3 = ws.receive_json()
        assert msg3["type"] == "task_done"
        assert msg3["summary"] == "Verification passed"
