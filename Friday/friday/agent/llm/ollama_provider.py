"""FRIDAY Local Ollama LLM Provider."""

import asyncio
import json
import urllib.request
from typing import Any, List, Optional

from friday.agent.llm.base import (
    LLMConfig,
    LLMConnectionError,
    LLMError,
    LLMMessage,
    LLMResponse,
)
from friday.agent.llm.litellm_provider import DEFAULT_OLLAMA_API_BASE, LiteLLMProvider


class OllamaProvider(LiteLLMProvider):
    """Dedicated provider for local Ollama models (e.g. ollama/qwen2.5-coder:1.5b, ollama/qwen2.5-coder:7b).

    Defaults to api_base='http://localhost:11434' and provides clear error diagnostics if
    the Ollama server is not running or unreachable.
    """

    DEFAULT_API_BASE: str = DEFAULT_OLLAMA_API_BASE
    DEFAULT_MODEL: str = "ollama/qwen2.5-coder:7b"

    def __init__(
        self,
        config: Optional[LLMConfig] = None,
        model: Optional[str] = None,
        api_base: Optional[str] = None,
        **kwargs: Any,
    ) -> None:
        if config is None:
            chosen_model = model or self.DEFAULT_MODEL
            if not chosen_model.startswith("ollama/"):
                chosen_model = f"ollama/{chosen_model}"
            chosen_api_base = api_base or self.DEFAULT_API_BASE
            config = LLMConfig(
                model=chosen_model,
                api_base=chosen_api_base,
                timeout_seconds=180.0,
                **kwargs,
            )
        else:
            if not config.model.startswith("ollama/"):
                config.model = f"ollama/{config.model}"
            if not config.api_base:
                config.api_base = api_base or self.DEFAULT_API_BASE
        super().__init__(config=config)

    async def is_available(self) -> bool:
        """Check if local Ollama daemon is reachable at the configured api_base."""
        base = (self.config.api_base or self.DEFAULT_API_BASE).rstrip("/")
        url = f"{base}/api/tags"
        loop = asyncio.get_running_loop()

        def _ping() -> bool:
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "FRIDAY"})
                with urllib.request.urlopen(req, timeout=2.0) as resp:
                    return resp.status == 200
            except Exception:
                return False

        return await loop.run_in_executor(None, _ping)

    async def list_local_models(self) -> List[str]:
        """Fetch list of model tags currently available in the local Ollama instance."""
        base = (self.config.api_base or self.DEFAULT_API_BASE).rstrip("/")
        url = f"{base}/api/tags"
        loop = asyncio.get_running_loop()

        def _fetch() -> List[str]:
            req = urllib.request.Request(url, headers={"User-Agent": "FRIDAY"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                models = data.get("models", [])
                return [m.get("name", "") for m in models if "name" in m]

        try:
            return await loop.run_in_executor(None, _fetch)
        except Exception as e:
            raise LLMConnectionError(
                f"Ollama server is not running or unreachable at {base}. "
                f"Please ensure Ollama is installed and running (e.g. run 'ollama serve'). "
                f"Error: {e}"
            ) from e
