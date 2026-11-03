"""FRIDAY Core: Event bus, workspace isolation, permissions, verifier, configuration, and session persistence."""

from friday.core.config import (
    FridayConfig,
    load_config,
    save_config,
    save_env_key,
    load_env_file,
    sync_env_keys,
)
from friday.core.session import Session, SessionTurn, SessionManager


def __getattr__(name: str):
    if name in ("MultiLLMRouter", "LLMFallbackEvent", "FallbackRecord"):
        from friday.core.router import MultiLLMRouter, LLMFallbackEvent, FallbackRecord

        globals()["MultiLLMRouter"] = MultiLLMRouter
        globals()["LLMFallbackEvent"] = LLMFallbackEvent
        globals()["FallbackRecord"] = FallbackRecord
        return globals()[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "FridayConfig",
    "load_config",
    "save_config",
    "save_env_key",
    "load_env_file",
    "sync_env_keys",
    "Session",
    "SessionTurn",
    "SessionManager",
    "MultiLLMRouter",
    "LLMFallbackEvent",
    "FallbackRecord",
]


