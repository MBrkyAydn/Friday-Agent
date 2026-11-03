import pytest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from friday.core.bus import EventBus
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionTier
from friday.agent.subagents.pool import SubagentPool
from friday.agent.subagents.base import SubagentResult
from friday.agent.llm import LLMResponse
from friday.tools.subagent import DelegateSubagentTool


def test_delegate_tool_schema_and_properties(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    bus = EventBus()
    pool = SubagentPool(bus=bus, workspace=guard)

    tool = DelegateSubagentTool(workspace=guard, permissions=perms, pool=pool)

    assert tool.name == "delegate_subagent"
    assert tool.tier == PermissionTier.TIER_0_SAFE
    assert "role" in tool.parameters["properties"]
    assert "task_description" in tool.parameters["properties"]
    assert tool.parameters["required"] == ["role", "task_description"]
    assert tool.parameters["properties"]["role"]["enum"] == ["researcher", "coder", "tester"]


@pytest.mark.asyncio
async def test_delegate_tool_executes_researcher(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    bus = EventBus()
    pool = SubagentPool(bus=bus, workspace=guard)
    mock_llm = MagicMock()

    tool = DelegateSubagentTool(workspace=guard, permissions=perms, pool=pool, llm=mock_llm, bus=bus)

    with patch("friday.tools.subagent.ResearcherSubagent") as mock_researcher_cls:
        mock_worker = MagicMock()
        mock_worker.role = "researcher"
        mock_worker.run = AsyncMock(
            return_value=SubagentResult(success=True, summary="Explored 4 files in repository.")
        )
        mock_researcher_cls.return_value = mock_worker

        result = await tool.execute(role="researcher", task_description="Inspect core files")

        assert result.success is True
        assert "Explored 4 files" in result.output
        mock_worker.run.assert_awaited_once_with("Inspect core files")


@pytest.mark.asyncio
async def test_delegate_tool_handles_invalid_role(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    bus = EventBus()
    pool = SubagentPool(bus=bus, workspace=guard)

    tool = DelegateSubagentTool(workspace=guard, permissions=perms, pool=pool)
    result = await tool.execute(role="architect", task_description="Design architecture")

    assert result.success is False
    assert "Unsupported subagent role" in result.error
