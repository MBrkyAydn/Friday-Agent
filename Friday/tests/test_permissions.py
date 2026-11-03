import pytest
from friday.core.permissions import PermissionController, PermissionTier, PermissionDecision


@pytest.mark.asyncio
async def test_permission_auto_approves_tier_0():
    controller = PermissionController(yolo_mode=False)
    decision = await controller.request_permission(
        tool_name="view_file",
        tier=PermissionTier.TIER_0_SAFE,
        details={"path": "main.py"},
    )
    assert decision == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_permission_yolo_bypasses_tier_1():
    controller = PermissionController(yolo_mode=True)
    decision = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"},
    )
    assert decision == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_permission_prompts_tier_1_in_default_mode():
    prompted = []

    async def mock_prompter(details: dict) -> PermissionDecision:
        prompted.append(details)
        return PermissionDecision.ALLOW

    controller = PermissionController(yolo_mode=False, prompter=mock_prompter)
    decision = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"},
    )
    assert decision == PermissionDecision.ALLOW
    assert len(prompted) == 1


@pytest.mark.asyncio
async def test_permission_deny_tier_1():
    async def mock_prompter(details: dict) -> PermissionDecision:
        return PermissionDecision.DENY

    controller = PermissionController(yolo_mode=False, prompter=mock_prompter)
    decision = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"},
    )
    assert decision == PermissionDecision.DENY


@pytest.mark.asyncio
async def test_permission_allow_always_whitelist():
    prompt_count = 0

    async def mock_prompter(details: dict) -> PermissionDecision:
        nonlocal prompt_count
        prompt_count += 1
        return PermissionDecision.ALLOW_ALWAYS

    controller = PermissionController(yolo_mode=False, prompter=mock_prompter)

    # First call prompts and stores in whitelist
    d1 = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"},
    )
    assert d1 == PermissionDecision.ALLOW
    assert prompt_count == 1

    # Second call with same tool and path uses whitelist
    d2 = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"},
    )
    assert d2 == PermissionDecision.ALLOW
    assert prompt_count == 1


@pytest.mark.asyncio
async def test_permission_no_prompter_defaults_to_allow():
    controller = PermissionController(yolo_mode=False, prompter=None)
    decision = await controller.request_permission(
        tool_name="edit_file",
        tier=PermissionTier.TIER_1_GUARDED,
        details={"path": "main.py"},
    )
    assert decision == PermissionDecision.ALLOW
