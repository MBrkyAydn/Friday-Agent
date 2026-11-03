"""FRIDAY LLM Provider Abstraction Layer."""

from friday.agent.llm.base import (
    FunctionCall,
    LLMConfig,
    LLMError,
    LLMAuthError,
    LLMConnectionError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    TokenUsage,
    ToolCall,
)
from friday.agent.llm.litellm_provider import LiteLLMProvider, DEFAULT_OLLAMA_API_BASE
from friday.agent.llm.ollama_provider import OllamaProvider
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from friday.core.router import (
        MultiLLMRouter,
        LLMFallbackEvent,
        FallbackRecord,
        FALLBACK_TRIGGER_EXCEPTIONS,
    )

__all__ = [
    "FunctionCall",
    "LLMConfig",
    "LLMError",
    "LLMAuthError",
    "LLMConnectionError",
    "LLMMessage",
    "LLMProvider",
    "LLMRateLimitError",
    "LLMResponse",
    "LLMTimeoutError",
    "TokenUsage",
    "ToolCall",
    "LiteLLMProvider",
    "OllamaProvider",
    "DEFAULT_OLLAMA_API_BASE",
    "MultiLLMRouter",
    "LLMFallbackEvent",
    "FallbackRecord",
    "FALLBACK_TRIGGER_EXCEPTIONS",
]


def __getattr__(name: str):
    if name in (
        "MultiLLMRouter",
        "LLMFallbackEvent",
        "FallbackRecord",
        "FALLBACK_TRIGGER_EXCEPTIONS",
    ):
        from friday.core.router import (
            MultiLLMRouter,
            LLMFallbackEvent,
            FallbackRecord,
            FALLBACK_TRIGGER_EXCEPTIONS,
        )

        return {
            "MultiLLMRouter": MultiLLMRouter,
            "LLMFallbackEvent": LLMFallbackEvent,
            "FallbackRecord": FallbackRecord,
            "FALLBACK_TRIGGER_EXCEPTIONS": FALLBACK_TRIGGER_EXCEPTIONS,
        }[name]
    raise AttributeError(f"module '{__name__}' has no attribute '{name}'")


def __dir__():
    return __all__

