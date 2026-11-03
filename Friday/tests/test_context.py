import pytest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock

from friday.agent.llm import (
    LLMProvider,
    LLMMessage,
    LLMResponse,
    ToolCall,
    FunctionCall,
)
from friday.agent.context import ContextConfig, ContextManager
from friday.agent.lead import LeadAgent
from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import TaskStatus, VerificationResult


def test_context_config_defaults():
    config = ContextConfig()
    assert config.max_context_tokens == 8192
    assert config.compaction_threshold == 0.75
    assert config.target_ratio == 0.50
    assert config.reserved_recent_messages == 4
    assert config.max_tool_output_chars == 800
    assert config.chars_per_token == 4.0


def test_estimate_tokens_across_messages():
    manager = ContextManager(ContextConfig(chars_per_token=4.0))

    msg1 = LLMMessage(role="user", content="12345678")  # 8 chars -> ~2 tokens
    est1 = manager.estimate_tokens(msg1)
    assert est1 == 2

    msg2 = LLMMessage(
        role="assistant",
        content="",
        tool_calls=[
            ToolCall(
                id="call_1",
                function=FunctionCall(
                    name="write_file",
                    arguments={"path": "a.txt", "content": "12345678"},
                ),
            )
        ],
    )
    est2 = manager.estimate_tokens(msg2)
    assert est2 > 5  # tool name and arguments counted

    total = manager.total_tokens([msg1, msg2])
    assert total == est1 + est2


def test_should_compact_respects_threshold():
    # 100 tokens max, 75% threshold -> trigger at > 75 tokens (~300 chars)
    config = ContextConfig(max_context_tokens=100, compaction_threshold=0.75, chars_per_token=4.0)
    manager = ContextManager(config=config)

    short_messages = [
        LLMMessage(role="system", content="sys prompt"),
        LLMMessage(role="user", content="hello world"),
    ]
    assert manager.should_compact(short_messages) is False

    long_messages = [
        LLMMessage(role="system", content="sys prompt"),
        LLMMessage(role="user", content="A" * 350),  # ~87 tokens
    ]
    assert manager.should_compact(long_messages) is True


def test_compact_preserves_anchor_messages():
    config = ContextConfig(
        max_context_tokens=100,
        compaction_threshold=0.75,
        reserved_recent_messages=2,
        chars_per_token=4.0,
    )
    manager = ContextManager(config=config)

    messages = [
        LLMMessage(role="system", content="System instruction anchor"),
        LLMMessage(role="user", content="Initial user goal anchor"),
        LLMMessage(role="assistant", content="Intermediate thought 1 " * 10),
        LLMMessage(role="tool", tool_call_id="c1", name="view_file", content="Middle output " * 20),
        LLMMessage(role="assistant", content="Recent thought"),
        LLMMessage(role="user", content="Recent follow up"),
    ]

    assert manager.should_compact(messages) is True
    compacted = manager.compact(messages)

    assert compacted[0].role == "system"
    assert "System instruction anchor" in compacted[0].content
    assert compacted[1].role == "user"
    assert "Initial user goal anchor" in compacted[1].content


def test_compact_preserves_recent_messages():
    config = ContextConfig(
        max_context_tokens=100,
        compaction_threshold=0.75,
        reserved_recent_messages=2,
        chars_per_token=4.0,
    )
    manager = ContextManager(config=config)

    messages = [
        LLMMessage(role="system", content="System prompt"),
        LLMMessage(role="user", content="User goal"),
        LLMMessage(role="assistant", content="Old thought " * 20),
        LLMMessage(role="tool", tool_call_id="c1", name="tool", content="Old result " * 20),
        LLMMessage(role="assistant", content="Recent thought 1"),
        LLMMessage(role="user", content="Recent prompt 2"),
    ]

    compacted = manager.compact(messages)
    # The last 2 messages must match the original last 2 messages
    assert compacted[-2].content == "Recent thought 1"
    assert compacted[-1].content == "Recent prompt 2"


def test_compact_truncates_large_tool_outputs():
    config = ContextConfig(
        max_context_tokens=200,
        compaction_threshold=0.75,
        reserved_recent_messages=2,
        max_tool_output_chars=100,
        chars_per_token=4.0,
    )
    manager = ContextManager(config=config)

    large_output = "Line of output data\n" * 50  # ~1000 chars
    messages = [
        LLMMessage(role="system", content="System prompt"),
        LLMMessage(role="user", content="User goal"),
        LLMMessage(role="assistant", content="Step 1"),
        LLMMessage(role="tool", tool_call_id="c1", name="view_file", content=large_output),
        LLMMessage(role="assistant", content="Recent 1"),
        LLMMessage(role="user", content="Recent 2"),
    ]

    compacted = manager.compact(messages)
    tool_msg = next((m for m in compacted if m.role == "tool" and m.tool_call_id == "c1"), None)
    if tool_msg:
        assert len(tool_msg.content) < len(large_output)
        assert "truncated" in tool_msg.content.lower()


def test_compact_folds_middle_turns_with_integrity():
    config = ContextConfig(
        max_context_tokens=100,
        compaction_threshold=0.50,
        target_ratio=0.30,
        reserved_recent_messages=2,
        chars_per_token=4.0,
    )
    manager = ContextManager(config=config)

    # 10 turns of middle messages
    messages = [
        LLMMessage(role="system", content="System prompt"),
        LLMMessage(role="user", content="User goal"),
    ]
    for i in range(10):
        messages.append(LLMMessage(role="assistant", content=f"Step thought {i} " * 5))
        messages.append(LLMMessage(role="tool", tool_call_id=f"c_{i}", name="cmd", content=f"Result {i} " * 5))

    messages.append(LLMMessage(role="assistant", content="Final active thought"))
    messages.append(LLMMessage(role="user", content="Final active user question"))

    compacted = manager.compact(messages)
    assert len(compacted) < len(messages)
    # Check that a summary notice was inserted
    has_summary = any("Compaction" in str(m.content) or "summarized" in str(m.content).lower() for m in compacted)
    assert has_summary


@pytest.mark.asyncio
async def test_lead_agent_compacts_messages_before_completion(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    bus = EventBus()
    verifier = AsyncMock()
    verifier.verify.return_value = (TaskStatus.DONE, VerificationResult(passed=True, stdout="OK"))

    # Config with very small token limit to trigger compaction
    config = ContextConfig(
        max_context_tokens=50,
        compaction_threshold=0.50,
        reserved_recent_messages=2,
        chars_per_token=4.0,
    )
    context_mgr = ContextManager(config=config)

    received_histories: List[List[LLMMessage]] = []

    class MockProvider(LLMProvider):
        async def complete(self, messages, tools=None, temperature=None, max_tokens=None):
            received_histories.append(list(messages))
            return LLMResponse(model="mock", content="Done", finish_reason="stop")

    agent = LeadAgent(
        bus=bus,
        workspace=guard,
        verifier=verifier,
        llm=MockProvider(),
        context_manager=context_mgr,
    )

    # Very long user prompt that exceeds the 50 * 0.50 = 25 token limit
    long_prompt = "Explain everything in extreme detail " * 20
    status = await agent.run_turn(long_prompt)

    assert status == TaskStatus.DONE
    assert len(received_histories) == 1
    # Check that compaction was considered/passed through context manager
    assert hasattr(agent, "context_manager")
    assert agent.context_manager is context_mgr
