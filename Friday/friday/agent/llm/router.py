"""Expose MultiLLMRouter and fallback engine via friday.agent.llm."""

from friday.core.router import (
    FALLBACK_TRIGGER_EXCEPTIONS,
    FallbackRecord,
    LLMFallbackEvent,
    MultiLLMRouter,
)

__all__ = [
    "MultiLLMRouter",
    "LLMFallbackEvent",
    "FallbackRecord",
    "FALLBACK_TRIGGER_EXCEPTIONS",
]
