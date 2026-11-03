"""FRIDAY Multi-LLM Router and Auto-Fallback Engine.

Provides dynamic switching between multiple local and cloud LLM providers
with automatic fallback to local Ollama on rate-limit, timeout, connection,
or authentication errors.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Type

from friday.agent.llm.base import (
    LLMAuthError,
    LLMConfig,
    LLMConnectionError,
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
)
from friday.agent.llm.litellm_provider import DEFAULT_OLLAMA_API_BASE, LiteLLMProvider
from friday.agent.llm.ollama_provider import OllamaProvider
from friday.core.bus import EventBus, LLMFallbackEvent

logger = logging.getLogger(__name__)

# Exceptions that trigger automatic fallback to local Ollama provider
FALLBACK_TRIGGER_EXCEPTIONS = (
    LLMRateLimitError,
    LLMTimeoutError,
    LLMConnectionError,
    LLMAuthError,
)


@dataclass
class FallbackRecord:
    """Record of an auto-fallback occurrence."""

    from_profile: str
    to_profile: str
    reason: str
    error: str


class MultiLLMRouter(LLMProvider):
    """Router supporting multiple named LLM providers with dynamic switching

    and resilient auto-fallback to local Ollama when cloud providers encounter
    rate limits, timeouts, connection issues, or authentication failures.
    """

    def __init__(
        self,
        providers: Optional[Dict[str, LLMProvider]] = None,
        active_profile: str = "gemini-free",
        fallback_profile: str = "local",
        fallback_enabled: bool = True,
        bus: Optional[EventBus] = None,
        api_base: Optional[str] = None,
        init_defaults: bool = True,
    ) -> None:
        """Initialize MultiLLMRouter.

        Args:
            providers: Optional mapping of profile names to LLMProvider instances.
            active_profile: Name of the currently active profile (default: 'gemini-free').
            fallback_profile: Name of the fallback profile on failure (default: 'local').
            fallback_enabled: Whether auto-fallback is enabled (default: True).
            bus: Optional EventBus for publishing fallback notices.
            api_base: Optional custom API base URL for Ollama local provider.
            init_defaults: Whether to register standard default profiles when providers is None.
        """
        self.bus = bus
        self.fallback_enabled = fallback_enabled
        self._fallback_profile = fallback_profile
        self._providers: Dict[str, LLMProvider] = {}
        self._last_fallback: Optional[FallbackRecord] = None

        if providers is not None:
            self._providers.update(providers)
        elif init_defaults:
            self._providers.update(self._build_default_providers(api_base=api_base))

        if active_profile in self._providers:
            self._active_profile = active_profile
        elif self._providers:
            self._active_profile = next(iter(self._providers.keys()))
        else:
            self._active_profile = active_profile

    @staticmethod
    def _build_default_providers(
        api_base: Optional[str] = None,
    ) -> Dict[str, LLMProvider]:
        """Construct standard default provider profiles.

        - 'local': OllamaProvider with qwen2.5-coder
        - 'gemini-free': gemini/gemini-2.5-flash
        - 'gemini-paid': gemini/gemini-2.5-pro
        - 'groq': groq/openai/gpt-oss-120b
        - 'deepseek': deepseek/deepseek-chat
        - 'claude': anthropic/claude-3-5-sonnet-20241022
        """
        local_base = api_base or DEFAULT_OLLAMA_API_BASE
        return {
            "local": OllamaProvider(
                model="ollama/qwen2.5-coder",
                api_base=local_base,
            ),
            "gemini-free": LiteLLMProvider(
                config=LLMConfig(model="gemini/gemini-2.5-flash")
            ),
            "gemini-paid": LiteLLMProvider(
                config=LLMConfig(model="gemini/gemini-2.5-pro")
            ),
            "groq": LiteLLMProvider(
                config=LLMConfig(model="groq/openai/gpt-oss-120b")
            ),
            "deepseek": LiteLLMProvider(
                config=LLMConfig(model="deepseek/deepseek-chat")
            ),
            "claude": LiteLLMProvider(
                config=LLMConfig(model="anthropic/claude-3-5-sonnet-20241022")
            ),
        }

    # -------------------------------------------------------------------------
    # Profile & Provider Management
    # -------------------------------------------------------------------------

    def register_provider(self, name: str, provider: LLMProvider) -> None:
        """Register or replace a named LLM provider."""
        if not isinstance(provider, LLMProvider):
            raise TypeError(
                f"Expected instance of LLMProvider for '{name}', got {type(provider).__name__}"
            )
        self._providers[name] = provider

    def unregister_provider(self, name: str) -> None:
        """Unregister a provider by name."""
        if name in self._providers:
            del self._providers[name]

    def get_provider(self, name: Optional[str] = None) -> LLMProvider:
        """Retrieve the LLMProvider for the given profile or active profile."""
        target = name or self._active_profile
        if target not in self._providers:
            raise KeyError(
                f"LLM profile '{target}' is not registered. Registered: {list(self._providers.keys())}"
            )
        return self._providers[target]

    def list_profiles(self) -> List[str]:
        """Return list of all registered profile names."""
        return list(self._providers.keys())

    def has_profile(self, name: str) -> bool:
        """Check whether a profile name is registered."""
        return name in self._providers

    # -------------------------------------------------------------------------
    # Dynamic Profile Switching
    # -------------------------------------------------------------------------

    def set_active_profile(self, name: str) -> None:
        """Switch active LLM profile dynamically."""
        if name not in self._providers:
            raise KeyError(
                f"LLM profile '{name}' not found. Available profiles: {list(self._providers.keys())}"
            )
        self._active_profile = name

    def get_active_profile(self) -> str:
        """Get the name of currently active LLM profile."""
        return self._active_profile

    @property
    def active_profile(self) -> str:
        """Property for active profile name."""
        return self.get_active_profile()

    @active_profile.setter
    def active_profile(self, name: str) -> None:
        self.set_active_profile(name)

    @property
    def active_provider(self) -> LLMProvider:
        """Active provider instance."""
        return self.get_provider(self._active_profile)

    # -------------------------------------------------------------------------
    # Fallback Profile & State
    # -------------------------------------------------------------------------

    def set_fallback_profile(self, name: str) -> None:
        """Set fallback provider profile name."""
        if name not in self._providers:
            raise KeyError(
                f"Fallback profile '{name}' not found. Available profiles: {list(self._providers.keys())}"
            )
        self._fallback_profile = name

    def get_fallback_profile(self) -> str:
        """Get the fallback profile name."""
        return self._fallback_profile

    @property
    def fallback_profile(self) -> str:
        """Property for fallback profile name."""
        return self.get_fallback_profile()

    @fallback_profile.setter
    def fallback_profile(self, name: str) -> None:
        self.set_fallback_profile(name)

    @property
    def fallback_provider(self) -> LLMProvider:
        """Fallback provider instance."""
        return self.get_provider(self._fallback_profile)

    @property
    def is_fallback_enabled(self) -> bool:
        """Whether auto-fallback is enabled."""
        return self.fallback_enabled

    def enable_fallback(self) -> None:
        """Enable auto-fallback mode."""
        self.fallback_enabled = True

    def disable_fallback(self) -> None:
        """Disable auto-fallback mode."""
        self.fallback_enabled = False

    @property
    def last_fallback(self) -> Optional[FallbackRecord]:
        """Details of the last fallback operation, if one occurred."""
        return self._last_fallback

    @property
    def config(self) -> LLMConfig:
        """Config of the currently active provider, or default LLMConfig."""
        active = self.get_provider()
        return getattr(active, "config", LLMConfig())

    # -------------------------------------------------------------------------
    # Error Classification
    # -------------------------------------------------------------------------

    def _is_fallback_error(self, exc: Exception) -> bool:
        """Determine whether the exception warrants automatic fallback."""
        if isinstance(exc, FALLBACK_TRIGGER_EXCEPTIONS):
            return True

        orig = getattr(exc, "__cause__", None) or exc
        status_code = (
            getattr(exc, "status_code", None)
            or getattr(orig, "status_code", None)
            or getattr(orig, "http_status", None)
        )
        if status_code in (400, 401, 403, 404, 408, 429, 500, 502, 503, 504):
            return True

        exc_type = (type(exc).__name__ + " " + type(orig).__name__).lower()
        exc_str = (str(exc) + " " + str(orig)).lower()

        if any(term in exc_type or term in exc_str for term in ("ratelimit", "rate_limit", "429", "quota")):
            return True
        if "timeout" in exc_type or "timed out" in exc_str:
            return True
        if any(term in exc_type or term in exc_str for term in ("connection", "connect", "refused")):
            return True
        if any(term in exc_type or term in exc_str for term in ("auth", "authentication", "unauthorized")):
            return True
        if any(term in exc_type or term in exc_str for term in ("badrequest", "bad_request", "invalid_request", "tool call validation", "tool_use_failed")):
            return True
        if any(
            term in exc_type or term in exc_str
            for term in (
                "notfound",
                "not_found",
                "404",
                "unavailable",
                "503",
                "high demand",
                "no longer available",
                "service_unavailable",
            )
        ):
            return True

        return False

    # -------------------------------------------------------------------------
    # LLM Completion & Auto-Fallback Execution
    # -------------------------------------------------------------------------

    async def complete(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        profile: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Complete prompt asynchronously using the active profile with auto-fallback.

        If the primary provider fails with RateLimitError (429), TimeoutError,
        ConnectionError, or AuthError, it automatically falls back to the
        local Ollama provider and logs/emits a notice.

        Args:
            messages: Conversation messages.
            tools: Optional tool definitions.
            tool_choice: Optional tool choice setting.
            profile: Optional override for active profile for this single call.
            **kwargs: Extra parameters passed to the provider.

        Returns:
            LLMResponse from primary or fallback provider.

        Raises:
            Exception: Original error if fallback is disabled or error is non-qualifying,
                       or descriptive LLMError if fallback fails or is unavailable.
        """
        active_name = profile or self.get_active_profile()
        active_provider = self.get_provider(active_name)

        try:
            response = await active_provider.complete(
                messages=messages,
                tools=tools,
                tool_choice=tool_choice,
                **kwargs,
            )
            self._last_fallback = None
            return response
        except Exception as exc:
            # 1. If fallback is disabled, re-raise original error immediately
            if not self.fallback_enabled:
                raise exc

            # 2. If failing provider is already the fallback profile, cannot fallback to itself
            if active_name == self._fallback_profile:
                raise exc

            # 3. If exception does not qualify for auto-fallback, re-raise
            if not self._is_fallback_error(exc):
                raise exc

            # 4. Verify fallback provider is registered
            fallback_name = self._fallback_profile
            if fallback_name not in self._providers:
                raise LLMError(
                    f"Primary provider '{active_name}' failed with {type(exc).__name__}: {exc}, "
                    f"and fallback profile '{fallback_name}' is not registered."
                ) from exc

            fallback_provider = self._providers[fallback_name]
            reason = f"{type(exc).__name__}: {exc}"

            # 5. Log warning notice
            logger.warning(
                "Primary LLM profile '%s' failed with %s (%s). Auto-falling back to '%s'.",
                active_name,
                type(exc).__name__,
                exc,
                fallback_name,
            )

            # 6. Emit notice on event bus if provided
            if self.bus is not None:
                event = LLMFallbackEvent(
                    from_profile=active_name,
                    to_profile=fallback_name,
                    reason=reason,
                    error=str(exc),
                )
                try:
                    await self.bus.publish(event)
                except Exception as bus_err:
                    logger.debug("Failed to publish LLMFallbackEvent on bus: %s", bus_err)

            # 7. Prepare kwargs for fallback (strip cloud-specific model override if present)
            fallback_kwargs = dict(kwargs)
            if "model" in fallback_kwargs:
                del fallback_kwargs["model"]

            # 8. Execute completion on fallback provider
            try:
                fallback_response = await fallback_provider.complete(
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    **fallback_kwargs,
                )
                self._last_fallback = FallbackRecord(
                    from_profile=active_name,
                    to_profile=fallback_name,
                    reason=reason,
                    error=str(exc),
                )
                return fallback_response
            except Exception as fb_exc:
                logger.error(
                    "Auto-fallback to '%s' failed after '%s' error: %s",
                    fallback_name,
                    active_name,
                    fb_exc,
                )
                raise LLMError(
                    f"Auto-fallback to '{fallback_name}' failed after primary provider '{active_name}' "
                    f"failed with {type(exc).__name__} ({exc}). "
                    f"Fallback error ({type(fb_exc).__name__}): {fb_exc}"
                ) from fb_exc


__all__ = [
    "MultiLLMRouter",
    "LLMFallbackEvent",
    "FallbackRecord",
    "FALLBACK_TRIGGER_EXCEPTIONS",
]
