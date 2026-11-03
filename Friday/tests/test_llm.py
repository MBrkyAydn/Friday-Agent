import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from friday.agent.llm import (
    LLMProvider,
    LiteLLMProvider,
    OllamaProvider,
    LLMMessage,
    LLMResponse,
    ToolCall,
    FunctionCall,
    TokenUsage,
    LLMConfig,
    LLMError,
    LLMAuthError,
    LLMConnectionError,
    LLMRateLimitError,
    LLMTimeoutError,
    DEFAULT_OLLAMA_API_BASE,
)
from friday.agent.lead import LeadAgent
from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import TaskStatus, VerificationResult


def test_abstract_provider_cannot_instantiate():
    with pytest.raises(TypeError):
        LLMProvider()  # type: ignore


def test_llm_config_defaults():
    config = LLMConfig()
    assert config.model == "gemini/gemini-3.8-flash"
    assert config.temperature == 0.2
    assert config.timeout_seconds == 60.0
    assert config.api_key is None


@pytest.mark.asyncio
async def test_litellm_provider_async_complete_success():
    provider = LiteLLMProvider()

    # Mock LiteLLM acompletion response structure
    mock_choice = AsyncMock()
    mock_choice.message.content = "Here is the refactored code."
    mock_choice.message.tool_calls = None
    mock_choice.finish_reason = "stop"

    mock_resp = AsyncMock()
    mock_resp.choices = [mock_choice]
    mock_resp.model = "gemini/gemini-2.5-pro"
    mock_resp.usage.prompt_tokens = 15
    mock_resp.usage.completion_tokens = 25
    mock_resp.usage.total_tokens = 40

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_resp), create=True) as mock_acompletion:
        messages = [
            LLMMessage(role="system", content="You are FRIDAY."),
            LLMMessage(role="user", content="Refactor controller."),
        ]
        response = await provider.complete(messages=messages)

        assert response.content == "Here is the refactored code."
        assert response.model == "gemini/gemini-2.5-pro"
        assert response.finish_reason == "stop"
        assert response.usage is not None
        assert response.usage.total_tokens == 40
        assert len(response.tool_calls) == 0

        mock_acompletion.assert_called_once()
        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["model"] == "gemini/gemini-3.8-flash"
        assert len(call_kwargs["messages"]) == 2
        assert call_kwargs["messages"][0]["role"] == "system"


@pytest.mark.asyncio
async def test_litellm_provider_tool_calls_parsing():
    provider = LiteLLMProvider()

    # Mock tool call in response
    mock_tc = AsyncMock()
    mock_tc.id = "call_view_123"
    mock_tc.type = "function"
    mock_tc.function.name = "view_file"
    mock_tc.function.arguments = '{"path": "app.py", "start_line": 1, "end_line": 50}'

    mock_choice = AsyncMock()
    mock_choice.message.content = None
    mock_choice.message.tool_calls = [mock_tc]
    mock_choice.finish_reason = "tool_calls"

    mock_resp = AsyncMock()
    mock_resp.choices = [mock_choice]
    mock_resp.model = "gemini/gemini-2.5-pro"
    mock_resp.usage = None

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_resp), create=True):
        messages = [LLMMessage(role="user", content="Inspect app.py")]
        response = await provider.complete(messages=messages)

        assert len(response.tool_calls) == 1
        tc = response.tool_calls[0]
        assert tc.id == "call_view_123"
        assert tc.function.name == "view_file"
        assert tc.function.arguments == {"path": "app.py", "start_line": 1, "end_line": 50}


@pytest.mark.asyncio
async def test_litellm_provider_auth_error_mapping():
    class AuthenticationError(Exception):
        pass

    provider = LiteLLMProvider()

    with patch("litellm.acompletion", side_effect=AuthenticationError("Invalid API Key provided"), create=True):
        with pytest.raises(LLMAuthError) as exc_info:
            await provider.complete(messages=[LLMMessage(role="user", content="Hi")])
        assert "Authentication failed" in str(exc_info.value) or "Invalid API Key" in str(exc_info.value)


@pytest.mark.asyncio
async def test_litellm_provider_rate_limit_error_mapping():
    class RateLimitError(Exception):
        pass

    provider = LiteLLMProvider()

    with patch("litellm.acompletion", side_effect=RateLimitError("Rate limit reached"), create=True):
        with pytest.raises(LLMRateLimitError):
            await provider.complete(messages=[LLMMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_litellm_provider_timeout_mapping():
    provider = LiteLLMProvider()

    with patch("litellm.acompletion", side_effect=asyncio.TimeoutError("Request timed out"), create=True):
        with pytest.raises(LLMTimeoutError):
            await provider.complete(messages=[LLMMessage(role="user", content="Hi")])


@pytest.mark.asyncio
async def test_custom_mock_provider_implementation():
    # Downstream components can easily mock LLMProvider without litellm
    class StubLLM(LLMProvider):
        async def complete(self, messages, tools=None, tool_choice=None):
            return LLMResponse(content="Stub answer", model="stub-model")

    stub = StubLLM()
    resp = await stub.complete(messages=[LLMMessage(role="user", content="Hello")])
    assert resp.content == "Stub answer"
    assert resp.model == "stub-model"


@pytest.mark.asyncio
async def test_lead_agent_accepts_llm_provider(tmp_path):
    class StubLLM(LLMProvider):
        async def complete(self, messages, tools=None, tool_choice=None):
            return LLMResponse(content="Plan generated", model="stub")

    bus = EventBus()
    guard = WorkspaceGuard(tmp_path)
    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="Passed"))

    stub_llm = StubLLM()
    agent = LeadAgent(bus=bus, workspace=guard, verifier=verifier, llm=stub_llm)
    assert agent.llm is stub_llm

    # Existing behavior preserved
    status = await agent.run_turn("Do task")
    assert status == TaskStatus.DONE


def test_ollama_provider_defaults():
    provider = OllamaProvider()
    assert provider.config.model == "ollama/qwen2.5-coder:7b"
    assert provider.config.api_base == "http://localhost:11434"
    assert provider.DEFAULT_API_BASE == "http://localhost:11434"


def test_ollama_provider_model_normalization_and_custom_api_base():
    # Model without 'ollama/' prefix is normalized
    provider1 = OllamaProvider(model="qwen2.5-coder:1.5b")
    assert provider1.config.model == "ollama/qwen2.5-coder:1.5b"
    assert provider1.config.api_base == "http://localhost:11434"

    # Model with 'ollama/' prefix is preserved
    provider2 = OllamaProvider(model="ollama/qwen2.5-coder:1.5b", api_base="http://custom-host:11434")
    assert provider2.config.model == "ollama/qwen2.5-coder:1.5b"
    assert provider2.config.api_base == "http://custom-host:11434"

    # From LLMConfig
    cfg = LLMConfig(model="qwen2.5-coder:7b")
    provider3 = OllamaProvider(config=cfg)
    assert provider3.config.model == "ollama/qwen2.5-coder:7b"
    assert provider3.config.api_base == "http://localhost:11434"


@pytest.mark.asyncio
async def test_ollama_provider_complete_invokes_litellm_with_api_base():
    provider = OllamaProvider(model="ollama/qwen2.5-coder:1.5b")

    mock_choice = AsyncMock()
    mock_choice.message.content = "def add(a, b): return a + b"
    mock_choice.message.tool_calls = None
    mock_choice.finish_reason = "stop"

    mock_resp = AsyncMock()
    mock_resp.choices = [mock_choice]
    mock_resp.model = "ollama/qwen2.5-coder:1.5b"
    mock_resp.usage = None

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_resp), create=True) as mock_acompletion:
        messages = [LLMMessage(role="user", content="Write add function")]
        resp = await provider.complete(messages=messages)

        assert resp.content == "def add(a, b): return a + b"
        assert resp.model == "ollama/qwen2.5-coder:1.5b"

        mock_acompletion.assert_called_once()
        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["model"] == "ollama/qwen2.5-coder:1.5b"
        assert call_kwargs["api_base"] == "http://localhost:11434"


@pytest.mark.asyncio
async def test_litellm_provider_ollama_model_defaults_api_base():
    provider = LiteLLMProvider(config=LLMConfig(model="ollama/qwen2.5-coder:7b"))

    mock_choice = AsyncMock()
    mock_choice.message.content = "OK"
    mock_choice.message.tool_calls = None
    mock_choice.finish_reason = "stop"

    mock_resp = AsyncMock()
    mock_resp.choices = [mock_choice]
    mock_resp.model = "ollama/qwen2.5-coder:7b"
    mock_resp.usage = None

    with patch("litellm.acompletion", new=AsyncMock(return_value=mock_resp), create=True) as mock_acompletion:
        messages = [LLMMessage(role="user", content="ping")]
        resp = await provider.complete(messages=messages)

        assert resp.content == "OK"
        mock_acompletion.assert_called_once()
        assert mock_acompletion.call_args.kwargs["api_base"] == "http://localhost:11434"


@pytest.mark.asyncio
async def test_ollama_not_running_connection_refused_error_message():
    provider = OllamaProvider(model="ollama/qwen2.5-coder:1.5b")

    # Simulate connection error when Ollama daemon is offline
    class APIConnectionError(Exception):
        pass

    with patch(
        "litellm.acompletion",
        side_effect=APIConnectionError("Cannot connect to host localhost:11434: Connection refused"),
        create=True,
    ):
        with pytest.raises(LLMConnectionError) as exc_info:
            await provider.complete(messages=[LLMMessage(role="user", content="hello")])

        err = str(exc_info.value)
        assert "Ollama server is not running or unreachable at http://localhost:11434" in err
        assert "ollama serve" in err


@pytest.mark.asyncio
async def test_ollama_provider_is_available():
    provider = OllamaProvider()

    # Case 1: Reachable (HTTP 200)
    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        available = await provider.is_available()
        assert available is True

    # Case 2: Unreachable (Exception raised)
    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        available = await provider.is_available()
        assert available is False


@pytest.mark.asyncio
async def test_ollama_provider_list_local_models():
    provider = OllamaProvider()

    import json
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps({
        "models": [
            {"name": "qwen2.5-coder:1.5b"},
            {"name": "qwen2.5-coder:7b"},
        ]
    }).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp
    mock_resp.__exit__.return_value = None

    with patch("urllib.request.urlopen", return_value=mock_resp):
        models = await provider.list_local_models()
        assert models == ["qwen2.5-coder:1.5b", "qwen2.5-coder:7b"]

    # When unreachable, list_local_models raises LLMConnectionError
    with patch("urllib.request.urlopen", side_effect=OSError("Connection refused")):
        with pytest.raises(LLMConnectionError) as exc_info:
            await provider.list_local_models()
        assert "Ollama server is not running or unreachable" in str(exc_info.value)

