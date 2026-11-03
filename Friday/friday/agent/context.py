import json
from typing import List, Optional
from pydantic import BaseModel, Field

from friday.agent.llm import LLMMessage


class ContextConfig(BaseModel):
    """Configuration parameters for context window budgeting and compaction."""

    max_context_tokens: int = 8192
    compaction_threshold: float = 0.75
    target_ratio: float = 0.50
    reserved_recent_messages: int = 4
    max_tool_output_chars: int = 800
    chars_per_token: float = 4.0


class ContextManager:
    """Manages LLM message context window budgeting, token estimation, and compaction."""

    def __init__(self, config: Optional[ContextConfig] = None) -> None:
        self.config = config or ContextConfig()

    def estimate_tokens(self, message: LLMMessage) -> int:
        """Estimate token consumption for a single message."""
        char_count = len(message.content or "")

        if message.tool_calls:
            for tc in message.tool_calls:
                char_count += len(tc.function.name)
                args = tc.function.arguments
                if isinstance(args, dict):
                    char_count += len(json.dumps(args))
                elif isinstance(args, str):
                    char_count += len(args)

        return max(1, int(char_count / self.config.chars_per_token))

    def total_tokens(self, messages: List[LLMMessage]) -> int:
        """Calculate total estimated tokens across all messages."""
        return sum(self.estimate_tokens(m) for m in messages)

    def should_compact(self, messages: List[LLMMessage]) -> bool:
        """Check if message history exceeds the configured compaction threshold watermark."""
        return self.total_tokens(messages) > (
            self.config.max_context_tokens * self.config.compaction_threshold
        )

    def compact(self, messages: List[LLMMessage]) -> List[LLMMessage]:
        """Compact message history when approaching context limits while preserving anchors and integrity."""
        if not self.should_compact(messages):
            return list(messages)

        min_len = 2 + self.config.reserved_recent_messages
        if len(messages) <= min_len:
            # Not enough messages to drop turns; truncate large tool outputs
            trimmed: List[LLMMessage] = []
            for m in messages:
                if m.role == "tool" and m.content and len(m.content) > self.config.max_tool_output_chars:
                    new_content = (
                        m.content[: self.config.max_tool_output_chars]
                        + "\n[... Output truncated for context compaction ...]"
                    )
                    trimmed.append(m.model_copy(update={"content": new_content}))
                else:
                    trimmed.append(m)
            return trimmed

        anchors = [messages[0], messages[1]]  # System prompt + initial user instruction
        recent_window_size = self.config.reserved_recent_messages

        # Ensure recent window doesn't start with an orphaned tool response
        recent_start = len(messages) - recent_window_size
        while recent_start > 2 and messages[recent_start].role == "tool":
            recent_start -= 1

        recent = messages[recent_start:]
        middle = messages[2:recent_start]

        # Step 1: Truncate large tool outputs in middle messages
        processed_middle: List[LLMMessage] = []
        for m in middle:
            if m.role == "tool" and m.content and len(m.content) > self.config.max_tool_output_chars:
                new_content = (
                    m.content[: self.config.max_tool_output_chars]
                    + "\n[... Output truncated for context compaction ...]"
                )
                processed_middle.append(m.model_copy(update={"content": new_content}))
            else:
                processed_middle.append(m)

        candidate = anchors + processed_middle + recent
        if self.total_tokens(candidate) <= (
            self.config.max_context_tokens * self.config.compaction_threshold
        ):
            return candidate

        # Step 2: Fold middle turns into a synthetic summary message
        pruned_count = len(middle)
        summary_msg = LLMMessage(
            role="system",
            content=(
                f"[Context Compaction: {pruned_count} earlier intermediate reasoning steps and tool outputs "
                "compacted to conserve context window]"
            ),
        )

        return anchors + [summary_msg] + recent
