import asyncio
import logging
from typing import Any, Dict, List
from fastapi import WebSocket

from friday.core.bus import (
    EventBus,
    ToolCallRequestedEvent,
    ToolResultEvent,
    AgentThoughtEvent,
    PermissionPromptEvent,
    TaskDoneEvent,
    TaskBlockedEvent,
    LLMFallbackEvent,
)

logger = logging.getLogger("friday.dashboard.bus_bridge")


class ConnectionManager:
    """Manages active WebSocket connections for live browser updates."""

    def __init__(self) -> None:
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: Dict[str, Any]) -> None:
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception:
                self.disconnect(connection)


class DashboardBusBridge:
    """Translates FRIDAY EventBus events into live WebSocket JSON broadcasts."""

    def __init__(self, bus: EventBus, manager: ConnectionManager) -> None:
        self.bus = bus
        self.manager = manager
        self._unsubscribers: list = []
        self._setup_listeners()

    def _setup_listeners(self) -> None:
        self._unsubscribers.append(
            self.bus.subscribe(ToolCallRequestedEvent, self._handle_tool_requested)
        )
        self._unsubscribers.append(
            self.bus.subscribe(ToolResultEvent, self._handle_tool_result)
        )
        self._unsubscribers.append(
            self.bus.subscribe(AgentThoughtEvent, self._handle_thought)
        )
        self._unsubscribers.append(
            self.bus.subscribe(PermissionPromptEvent, self._handle_permission_prompt)
        )
        self._unsubscribers.append(
            self.bus.subscribe(TaskDoneEvent, self._handle_task_done)
        )
        self._unsubscribers.append(
            self.bus.subscribe(TaskBlockedEvent, self._handle_task_blocked)
        )
        self._unsubscribers.append(
            self.bus.subscribe(LLMFallbackEvent, self._handle_llm_fallback)
        )

    async def _handle_tool_requested(self, event: ToolCallRequestedEvent) -> None:
        await self.manager.broadcast({
            "type": "tool_start",
            "tool": event.tool_name,
            "tool_name": event.tool_name,
            "args": event.arguments,
            "arguments": event.arguments,
            "call_id": event.tool_call_id,
        })

    async def _handle_tool_result(self, event: ToolResultEvent) -> None:
        await self.manager.broadcast({
            "type": "tool_result",
            "tool": event.tool_name,
            "tool_name": event.tool_name,
            "success": event.success,
            "output": event.output,
            "error": event.error,
            "call_id": event.tool_call_id,
        })

    async def _handle_thought(self, event: AgentThoughtEvent) -> None:
        await self.manager.broadcast({
            "type": "thought",
            "thought": event.thought,
        })

    async def _handle_permission_prompt(self, event: PermissionPromptEvent) -> None:
        await self.manager.broadcast({
            "type": "permission_prompt",
            "prompt_id": event.prompt_id,
            "description": event.description,
            "action_type": event.action_type,
            "details": event.details,
        })

    async def _handle_task_done(self, event: TaskDoneEvent) -> None:
        await self.manager.broadcast({
            "type": "task_done",
            "task_id": event.task_id,
            "summary": event.summary,
            "evidence": event.evidence,
        })

    async def _handle_task_blocked(self, event: TaskBlockedEvent) -> None:
        await self.manager.broadcast({
            "type": "task_blocked",
            "task_id": event.task_id,
            "reason": event.reason,
            "diagnostics": event.diagnostics,
        })

    async def _handle_llm_fallback(self, event: LLMFallbackEvent) -> None:
        await self.manager.broadcast({
            "type": "llm_fallback",
            "from_profile": event.from_profile,
            "to_profile": event.to_profile,
            "reason": event.reason,
            "error": event.error,
        })

    def close(self) -> None:
        for unsub in self._unsubscribers:
            try:
                unsub()
            except Exception:
                pass
        self._unsubscribers.clear()
