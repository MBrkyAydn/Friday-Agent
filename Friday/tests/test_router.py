"""Unit tests for MultiLLMRouter and Auto-Fallback Engine."""

import pytest
from unittest.mock import AsyncMock

from friday.agent.llm import (
    LLMAuthError,
    LLMConfig,
    LLMConnectionError,
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    OllamaProvider,
    LiteLLMProvider,
)
from friday.core.bus import EventBus, LLMFallbackEvent
from friday.core.router import MultiLLMRouter, FallbackRecord


from typing import Any, Dict, List, Optional

class StubProvider(LLMProvider):
    """Stub LLM provider for unit testing."""

    def __init__(self, name: str = "stub", model: str = "stub-model") -> None:
        self.name = name
        self.model = model
        self.config = LLMConfig(model=model)
        self.mock_complete = AsyncMock()

    async def complete(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        return await self.mock_complete(
            messages=messages, tools=tools, tool_choice=tool_choice, **kwargs
        )


def test_router_inherits_llm_provider():
    """Verify MultiLLMRouter is an instance of abstract LLMProvider."""
    router = MultiLLMRouter(init_defaults=False)
    assert isinstance(router, LLMProvider)


def test_router_default_profiles_registration():
    """Verify default profiles are properly registered on initialization:

    'local', 'gemini-free', 'gemini-paid', 'groq', 'deepseek', 'claude'.
    """
    router = MultiLLMRouter()
    profiles = router.list_profiles()

    expected_profiles = [
        "local",
        "gemini-free",
        "gemini-paid",
        "groq",
        "deepseek",
        "claude",
    ]
    for p in expected_profiles:
        assert p in profiles, f"Expected default profile '{p}' to be registered"

    # Verify 'local' is OllamaProvider with qwen2.5-coder
    local_provider = router.get_provider("local")
    assert isinstance(local_provider, OllamaProvider)
    assert "qwen2.5-coder" in local_provider.config.model

    # Verify cloud profiles are LiteLLMProvider instances
    assert isinstance(router.get_provider("gemini-free"), LiteLLMProvider)
    assert router.get_provider("gemini-free").config.model == "gemini/gemini-3.8-flash"

    assert isinstance(router.get_provider("gemini-paid"), LiteLLMProvider)
    assert router.get_provider("gemini-paid").config.model == "gemini/gemini-2.5-pro"

    assert isinstance(router.get_provider("groq"), LiteLLMProvider)
    assert router.get_provider("groq").config.model == "groq/openai/gpt-oss-120b"

    assert isinstance(router.get_provider("deepseek"), LiteLLMProvider)
    assert router.get_provider("deepseek").config.model == "deepseek/deepseek-chat"

    assert isinstance(router.get_provider("claude"), LiteLLMProvider)
    assert "claude" in router.get_provider("claude").config.model

    # Verify default active and fallback profiles
    assert router.get_active_profile() == "gemini-free"
    assert router.get_fallback_profile() == "local"
    assert router.is_fallback_enabled is True


def test_profile_switching():
    """Verify dynamic switching between profiles via set_active_profile and properties."""
    p_local = StubProvider("local", "qwen2.5-coder")
    p_groq = StubProvider("groq", "llama-3.3")
    p_gemini = StubProvider("gemini-free", "gemini-2.5-flash")

    router = MultiLLMRouter(
        providers={"local": p_local, "groq": p_groq, "gemini-free": p_gemini},
        active_profile="gemini-free",
    )

    assert router.get_active_profile() == "gemini-free"
    assert router.active_profile == "gemini-free"
    assert router.active_provider is p_gemini

    # Switch to groq
    router.set_active_profile("groq")
    assert router.get_active_profile() == "groq"
    assert router.active_profile == "groq"
    assert router.active_provider is p_groq

    # Switch via property setter
    router.active_profile = "local"
    assert router.get_active_profile() == "local"
    assert router.active_provider is p_local

    # Nonexistent profile raises KeyError
    with pytest.raises(KeyError) as exc_info:
        router.set_active_profile("unknown-profile")
    assert "unknown-profile" in str(exc_info.value)


@pytest.mark.asyncio
async def test_successful_primary_completion_without_fallback():
    """Verify that when primary provider succeeds, fallback is not triggered."""
    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    expected_resp = LLMResponse(content="Success from cloud", model="gemini-flash")
    p_cloud.mock_complete.return_value = expected_resp

    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
    )

    messages = [LLMMessage(role="user", content="Hello")]
    resp = await router.complete(messages=messages)

    assert resp == expected_resp
    assert resp.content == "Success from cloud"
    p_cloud.mock_complete.assert_called_once_with(
        messages=messages, tools=None, tool_choice=None
    )
    p_local.mock_complete.assert_not_called()
    assert router.last_fallback is None


@pytest.mark.asyncio
async def test_auto_fallback_on_rate_limit_error():
    """Verify automatic fallback to local provider on LLMRateLimitError (429)."""
    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    p_cloud.mock_complete.side_effect = LLMRateLimitError("429 Resource has been exhausted (quota exceeded)")
    local_resp = LLMResponse(content="Response from local Ollama", model="qwen2.5-coder")
    p_local.mock_complete.return_value = local_resp

    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
    )

    messages = [LLMMessage(role="user", content="Write code")]
    resp = await router.complete(messages=messages)

    assert resp == local_resp
    assert resp.content == "Response from local Ollama"
    p_cloud.mock_complete.assert_called_once()
    p_local.mock_complete.assert_called_once()

    # Verify fallback audit record
    assert router.last_fallback is not None
    assert router.last_fallback.from_profile == "cloud"
    assert router.last_fallback.to_profile == "local"
    assert "LLMRateLimitError" in router.last_fallback.reason


@pytest.mark.asyncio
async def test_auto_fallback_on_timeout_error():
    """Verify automatic fallback to local provider on LLMTimeoutError."""
    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    p_cloud.mock_complete.side_effect = LLMTimeoutError("LLM request timed out after 60s")
    local_resp = LLMResponse(content="Local response after timeout", model="qwen2.5-coder")
    p_local.mock_complete.return_value = local_resp

    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
    )

    messages = [LLMMessage(role="user", content="Write tests")]
    resp = await router.complete(messages=messages)

    assert resp == local_resp
    assert resp.content == "Local response after timeout"
    p_cloud.mock_complete.assert_called_once()
    p_local.mock_complete.assert_called_once()

    assert router.last_fallback is not None
    assert router.last_fallback.from_profile == "cloud"
    assert router.last_fallback.to_profile == "local"
    assert "LLMTimeoutError" in router.last_fallback.reason


@pytest.mark.asyncio
async def test_auto_fallback_on_connection_error():
    """Verify automatic fallback on LLMConnectionError."""
    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    p_cloud.mock_complete.side_effect = LLMConnectionError("Network unreachable")
    local_resp = LLMResponse(content="Local answer on connection drop", model="qwen2.5-coder")
    p_local.mock_complete.return_value = local_resp

    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
    )

    resp = await router.complete(messages=[LLMMessage(role="user", content="hi")])
    assert resp.content == "Local answer on connection drop"
    p_cloud.mock_complete.assert_called_once()
    p_local.mock_complete.assert_called_once()


@pytest.mark.asyncio
async def test_auto_fallback_on_auth_error():
    """Verify automatic fallback on LLMAuthError."""
    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    p_cloud.mock_complete.side_effect = LLMAuthError("Invalid API Key provided")
    local_resp = LLMResponse(content="Local answer on auth failure", model="qwen2.5-coder")
    p_local.mock_complete.return_value = local_resp

    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
    )

    resp = await router.complete(messages=[LLMMessage(role="user", content="hi")])
    assert resp.content == "Local answer on auth failure"
    p_cloud.mock_complete.assert_called_once()
    p_local.mock_complete.assert_called_once()


@pytest.mark.asyncio
async def test_auto_fallback_emits_bus_notice():
    """Verify fallback notice is emitted on EventBus when provided."""
    bus = EventBus()
    received_events = []

    async def on_fallback(event: LLMFallbackEvent):
        received_events.append(event)

    bus.subscribe(LLMFallbackEvent, on_fallback)

    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    p_cloud.mock_complete.side_effect = LLMRateLimitError("429 rate limit exceeded")
    p_local.mock_complete.return_value = LLMResponse(content="local ok", model="qwen2.5-coder")

    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
        bus=bus,
    )

    await router.complete(messages=[LLMMessage(role="user", content="hello")])

    assert len(received_events) == 1
    event = received_events[0]
    assert event.from_profile == "cloud"
    assert event.to_profile == "local"
    assert "LLMRateLimitError" in event.reason
    assert "429 rate limit" in event.error


@pytest.mark.asyncio
async def test_fallback_disabled_mode():
    """Verify that when fallback is disabled, errors are raised directly."""
    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    p_cloud.mock_complete.side_effect = LLMRateLimitError("429 Quota Exceeded")
    p_local.mock_complete.return_value = LLMResponse(content="fallback", model="qwen2.5-coder")

    # Disabled via parameter
    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
        fallback_enabled=False,
    )
    assert router.is_fallback_enabled is False

    with pytest.raises(LLMRateLimitError) as exc_info:
        await router.complete(messages=[LLMMessage(role="user", content="ping")])
    assert "429 Quota Exceeded" in str(exc_info.value)
    p_local.mock_complete.assert_not_called()

    # Re-enable and verify it works
    router.enable_fallback()
    assert router.is_fallback_enabled is True
    resp = await router.complete(messages=[LLMMessage(role="user", content="ping")])
    assert resp.content == "fallback"
    p_local.mock_complete.assert_called_once()

    # Disable dynamically
    router.disable_fallback()
    p_local.mock_complete.reset_mock()
    with pytest.raises(LLMRateLimitError):
        await router.complete(messages=[LLMMessage(role="user", content="ping")])
    p_local.mock_complete.assert_not_called()


@pytest.mark.asyncio
async def test_fallback_failure_raises_descriptive_error():
    """Verify that if fallback provider also fails, a descriptive LLMError is raised."""
    p_cloud = StubProvider("cloud", "gemini-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    p_cloud.mock_complete.side_effect = LLMRateLimitError("429 primary quota exhausted")
    p_local.mock_complete.side_effect = LLMConnectionError("Ollama server unreachable at http://localhost:11434")

    router = MultiLLMRouter(
        providers={"cloud": p_cloud, "local": p_local},
        active_profile="cloud",
        fallback_profile="local",
    )

    with pytest.raises(LLMError) as exc_info:
        await router.complete(messages=[LLMMessage(role="user", content="ping")])

    err_msg = str(exc_info.value)
    assert "Auto-fallback to 'local' failed" in err_msg
    assert "LLMRateLimitError" in err_msg
    assert "LLMConnectionError" in err_msg


@pytest.mark.asyncio
async def test_no_fallback_when_active_is_already_fallback_provider():
    """Verify that when active profile is already the fallback profile, it raises directly without loop."""
    p_local = StubProvider("local", "qwen2.5-coder")
    p_local.mock_complete.side_effect = LLMTimeoutError("Ollama timeout after 60s")

    router = MultiLLMRouter(
        providers={"local": p_local},
        active_profile="local",
        fallback_profile="local",
    )

    with pytest.raises(LLMTimeoutError):
        await router.complete(messages=[LLMMessage(role="user", content="ping")])

    # Called once, no recursive fallback
    p_local.mock_complete.assert_called_once()


@pytest.mark.asyncio
async def test_per_call_profile_override():
    """Verify specifying profile argument overrides active profile for single complete() call."""
    p_gemini = StubProvider("gemini-free", "gemini-2.5-flash")
    p_groq = StubProvider("groq", "llama-3.3")

    p_gemini.mock_complete.return_value = LLMResponse(content="gemini response", model="gemini-2.5-flash")
    p_groq.mock_complete.return_value = LLMResponse(content="groq response", model="llama-3.3")

    router = MultiLLMRouter(
        providers={"gemini-free": p_gemini, "groq": p_groq},
        active_profile="gemini-free",
    )

    # Call with profile='groq' override
    resp = await router.complete(messages=[LLMMessage(role="user", content="hi")], profile="groq")
    assert resp.content == "groq response"
    p_groq.mock_complete.assert_called_once()
    p_gemini.mock_complete.assert_not_called()

    # Active profile remains untouched
    assert router.get_active_profile() == "gemini-free"


def test_custom_provider_registration_and_unregistration():
    """Verify register_provider, unregister_provider, has_profile and list_profiles."""
    router = MultiLLMRouter(init_defaults=False)
    assert len(router.list_profiles()) == 0

    custom = StubProvider("custom", "custom-model")
    router.register_provider("custom", custom)

    assert router.has_profile("custom") is True
    assert router.get_provider("custom") is custom
    assert "custom" in router.list_profiles()

    # Registering non-provider raises TypeError
    with pytest.raises(TypeError):
        router.register_provider("invalid", "not-a-provider")  # type: ignore

    # Unregister
    router.unregister_provider("custom")
    assert router.has_profile("custom") is False
    with pytest.raises(KeyError):
        router.get_provider("custom")


def test_router_exports_across_packages():
    """Verify MultiLLMRouter and LLMFallbackEvent can be imported from all intended namespaces."""
    from friday.core.router import MultiLLMRouter as R1, LLMFallbackEvent as E1
    from friday.core import MultiLLMRouter as R2, LLMFallbackEvent as E2
    from friday.agent.llm import MultiLLMRouter as R3, LLMFallbackEvent as E3
    from friday.agent.llm.router import MultiLLMRouter as R4, LLMFallbackEvent as E4

    assert R1 is R2 is R3 is R4
    assert E1 is E2 is E3 is E4


@pytest.mark.asyncio
async def test_fallback_on_not_found_404():
    """Verify fallback triggers when cloud provider returns 404 Not Found (e.g. deprecated model)."""
    p_primary = StubProvider("gemini-free", "gemini-3.8-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    err = Exception("GeminiException: 404 This model is no longer available to new users")
    setattr(err, "status_code", 404)
    p_primary.mock_complete.side_effect = err
    p_local.mock_complete.return_value = LLMResponse(content="offline answer", model="qwen2.5-coder")

    bus = EventBus()
    router = MultiLLMRouter(
        providers={"gemini-free": p_primary, "local": p_local},
        active_profile="gemini-free",
        fallback_profile="local",
        bus=bus,
    )

    resp = await router.complete(messages=[LLMMessage(role="user", content="hello")])
    assert resp.content == "offline answer"
    assert router.last_fallback is not None
    assert router.last_fallback.from_profile == "gemini-free"


@pytest.mark.asyncio
async def test_fallback_on_unavailable_503():
    """Verify fallback triggers when cloud provider returns 503 High Demand / Service Unavailable."""
    p_primary = StubProvider("gemini-free", "gemini-3.8-flash")
    p_local = StubProvider("local", "qwen2.5-coder")

    err = Exception("GeminiException: 503 This model is currently experiencing high demand")
    setattr(err, "status_code", 503)
    p_primary.mock_complete.side_effect = err
    p_local.mock_complete.return_value = LLMResponse(content="fallback answer", model="qwen2.5-coder")

    bus = EventBus()
    router = MultiLLMRouter(
        providers={"gemini-free": p_primary, "local": p_local},
        active_profile="gemini-free",
        fallback_profile="local",
        bus=bus,
    )

    resp = await router.complete(messages=[LLMMessage(role="user", content="hello")])
    assert resp.content == "fallback answer"
    assert router.last_fallback is not None
    assert router.last_fallback.from_profile == "gemini-free"

