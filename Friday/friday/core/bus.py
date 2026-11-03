import asyncio
from datetime import datetime, timezone
from typing import Any, Callable, Coroutine, Dict, List, Type
from pydantic import BaseModel, Field


class Event(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserPromptEvent(Event):
    prompt: str


class AgentThoughtEvent(Event):
    thought: str


class StreamChunkEvent(Event):
    chunk: str


class ToolCallRequestedEvent(Event):
    tool_call_id: str
    tool_name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolResultEvent(Event):
    tool_call_id: str
    tool_name: str
    success: bool
    output: str
    error: str | None = None


class PermissionPromptEvent(Event):
    prompt_id: str
    description: str
    action_type: str
    details: Dict[str, Any] = Field(default_factory=dict)


class SubagentProgressEvent(Event):
    subagent_id: str
    role: str
    message: str


class TaskDoneEvent(Event):
    task_id: str
    summary: str
    evidence: str = ""


class TaskBlockedEvent(Event):
    task_id: str
    reason: str
    diagnostics: str = ""


class LLMFallbackEvent(Event):
    """Event emitted when MultiLLMRouter auto-falls back to another LLM provider."""
    from_profile: str
    to_profile: str
    reason: str
    error: str = ""


EventHandler = Callable[[Any], Coroutine[Any, Any, None] | None]


class EventBus:
    def __init__(self) -> None:
        self._listeners: Dict[Type[Event], List[EventHandler]] = {}

    def subscribe(self, event_type: Type[Event], handler: EventHandler) -> Callable[[], None]:
        if event_type not in self._listeners:
            self._listeners[event_type] = []
        self._listeners[event_type].append(handler)

        def unsubscribe() -> None:
            if event_type in self._listeners and handler in self._listeners[event_type]:
                self._listeners[event_type].remove(handler)

        return unsubscribe

    async def publish(self, event: Event) -> None:
        handlers: List[EventHandler] = list(self._listeners.get(type(event), []))
        # Also invoke handlers for parent Event classes
        for event_cls, cls_handlers in self._listeners.items():
            if event_cls != type(event) and isinstance(event, event_cls):
                handlers.extend(cls_handlers)

        if handlers:
            async def _invoke(h: EventHandler) -> None:
                res = h(event)
                if asyncio.iscoroutine(res):
                    await res

            await asyncio.gather(*(_invoke(h) for h in handlers))


__all__ = [
    "Event",
    "UserPromptEvent",
    "AgentThoughtEvent",
    "StreamChunkEvent",
    "ToolCallRequestedEvent",
    "ToolResultEvent",
    "PermissionPromptEvent",
    "SubagentProgressEvent",
    "TaskDoneEvent",
    "TaskBlockedEvent",
    "LLMFallbackEvent",
    "EventHandler",
    "EventBus",
]
