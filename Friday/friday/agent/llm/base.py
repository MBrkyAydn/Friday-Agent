from abc import ABC, abstractmethod
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


class FunctionCall(BaseModel):
    name: str
    arguments: Dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str
    type: Literal["function"] = "function"
    function: FunctionCall


class LLMMessage(BaseModel):
    role: Literal["system", "user", "assistant", "tool"]
    content: Optional[str] = ""
    name: Optional[str] = None
    tool_call_id: Optional[str] = None
    tool_calls: Optional[List[ToolCall]] = None


class TokenUsage(BaseModel):
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: List[ToolCall] = Field(default_factory=list)
    model: str
    finish_reason: Optional[str] = None
    usage: Optional[TokenUsage] = None


class LLMConfig(BaseModel):
    model: str = "gemini/gemini-3.8-flash"
    temperature: float = 0.2
    max_tokens: Optional[int] = 4096
    api_base: Optional[str] = None
    api_key: Optional[str] = None
    timeout_seconds: float = 60.0
    extra_params: Dict[str, Any] = Field(default_factory=dict)


class LLMError(Exception):
    """Base error for LLM provider exceptions."""
    pass


class LLMAuthError(LLMError):
    """Authentication or invalid API key error."""
    pass


class LLMRateLimitError(LLMError):
    """Rate limit or quota exceeded error."""
    pass


class LLMTimeoutError(LLMError):
    """Network or execution timeout error."""
    pass


class LLMConnectionError(LLMError):
    """Network connection or unreachable server error."""
    pass


class LLMProvider(ABC):
    @abstractmethod
    async def complete(
        self,
        messages: List[LLMMessage],
        tools: Optional[List[Dict[str, Any]]] = None,
        tool_choice: Optional[str] = None,
        **kwargs: Any,
    ) -> LLMResponse:
        """Asynchronously call the LLM and return a typed LLMResponse."""
        pass
