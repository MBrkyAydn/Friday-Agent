import asyncio
import json
from typing import Any, Dict, List, Optional
import litellm

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

DEFAULT_OLLAMA_API_BASE: str = "http://localhost:11434"


class LiteLLMProvider(LLMProvider):
    def __init__(self, config: Optional[LLMConfig] = None) -> None:
        self.config = config or LLMConfig()

    def _format_messages(self, messages: List[LLMMessage]) -> List[Dict[str, Any]]:
        formatted = []
        for msg in messages:
            entry: Dict[str, Any] = {"role": msg.role, "content": msg.content or ""}
            if msg.name:
                entry["name"] = msg.name
            if msg.tool_call_id:
                entry["tool_call_id"] = msg.tool_call_id
            if msg.tool_calls:
                entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": json.dumps(tc.function.arguments)
                            if isinstance(tc.function.arguments, dict)
                            else str(tc.function.arguments),
                        },
                    }
                    for tc in msg.tool_calls
                ]
            formatted.append(entry)
        return formatted

    async def complete(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        formatted_messages = self._format_messages(messages)
        call_kwargs: Dict[str, Any] = {
            "model": self.config.model,
            "messages": formatted_messages,
            "temperature": self.config.temperature,
            **self.config.extra_params,
            **kwargs,
        }
        if self.config.max_tokens:
            call_kwargs["max_tokens"] = self.config.max_tokens

        # Handle API base: default to localhost Ollama endpoint for ollama models
        api_base = kwargs.get("api_base") or self.config.api_base
        model_name = str(call_kwargs.get("model", self.config.model))
        if not api_base and model_name.startswith("ollama/"):
            api_base = DEFAULT_OLLAMA_API_BASE
        if api_base:
            call_kwargs["api_base"] = api_base

        if self.config.api_key:
            call_kwargs["api_key"] = self.config.api_key
        if tools:
            call_kwargs["tools"] = tools
        if tool_choice:
            call_kwargs["tool_choice"] = tool_choice

        try:
            acompletion_fn = getattr(litellm, "acompletion", None)
            if acompletion_fn is None:
                raise LLMError("LiteLLM acompletion is not available on litellm module.")

            resp = await asyncio.wait_for(
                acompletion_fn(**call_kwargs),
                timeout=self.config.timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError) as e:
            raise LLMTimeoutError(f"LLM request timed out after {self.config.timeout_seconds}s") from e
        except Exception as e:
            err_type = type(e).__name__.lower()
            err_msg = str(e)
            effective_model = str(call_kwargs.get("model", self.config.model))
            effective_api_base = str(call_kwargs.get("api_base", self.config.api_base or DEFAULT_OLLAMA_API_BASE))

            is_ollama = (
                effective_model.startswith("ollama/")
                or "11434" in effective_api_base
                or "ollama" in err_type
                or "ollama" in err_msg.lower()
            )
            is_conn_error = (
                "connect" in err_type
                or "connection" in err_type
                or "cannot connect" in err_msg.lower()
                or "connection refused" in err_msg.lower()
                or "actively refused" in err_msg.lower()
                or "bağlantısını reddetti" in err_msg.lower()
                or "10061" in err_msg
                or "apiconnectionerror" in err_type
                or isinstance(e, ConnectionRefusedError)
            )

            if is_ollama and is_conn_error:
                raise LLMConnectionError(
                    f"Ollama server is not running or unreachable at {effective_api_base}. "
                    f"Please ensure Ollama is installed and running (e.g. run 'ollama serve'). "
                    f"Underlying error: {err_msg}"
                ) from e

            if "auth" in err_type or "authentication" in err_type:
                raise LLMAuthError(f"Authentication failed: {err_msg}") from e
            if "ratelimit" in err_type or "rate_limit" in err_type:
                raise LLMRateLimitError(f"Rate limit exceeded: {err_msg}") from e
            if "timeout" in err_type:
                raise LLMTimeoutError(f"LLM request timed out: {err_msg}") from e
            if is_conn_error:
                raise LLMConnectionError(f"Network connection failed: {err_msg}") from e
            raise LLMError(f"LLM completion error: {err_msg}") from e

        choice = resp.choices[0]
        content = choice.message.content or ""
        finish_reason = getattr(choice, "finish_reason", None)

        tool_calls: List[ToolCall] = []
        raw_tool_calls = getattr(choice.message, "tool_calls", None)
        if raw_tool_calls:
            for tc in raw_tool_calls:
                raw_args = tc.function.arguments
                if isinstance(raw_args, str):
                    try:
                        parsed_args = json.loads(raw_args)
                    except Exception:
                        parsed_args = {"raw": raw_args}
                elif isinstance(raw_args, dict):
                    parsed_args = raw_args
                else:
                    parsed_args = {}

                tool_calls.append(
                    ToolCall(
                        id=str(tc.id),
                        type="function",
                        function=FunctionCall(name=tc.function.name, arguments=parsed_args),
                    )
                )

        usage = None
        raw_usage = getattr(resp, "usage", None)
        if raw_usage:
            usage = TokenUsage(
                prompt_tokens=getattr(raw_usage, "prompt_tokens", 0) or 0,
                completion_tokens=getattr(raw_usage, "completion_tokens", 0) or 0,
                total_tokens=getattr(raw_usage, "total_tokens", 0) or 0,
            )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=getattr(resp, "model", self.config.model) or self.config.model,
            finish_reason=finish_reason,
            usage=usage,
        )
