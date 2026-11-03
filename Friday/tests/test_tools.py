import pytest
from pathlib import Path
from friday.core.workspace import WorkspaceGuard
from friday.core.permissions import PermissionController, PermissionDecision
from friday.tools.filesystem import ViewFileTool, WriteFileTool, EditFileTool
from friday.tools.shell import RunCommandTool


@pytest.mark.asyncio
async def test_file_tools_roundtrip(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)

    writer = WriteFileTool(workspace=guard, permissions=perms)
    viewer = ViewFileTool(workspace=guard, permissions=perms)
    editor = EditFileTool(workspace=guard, permissions=perms)

    # 1. Write file
    w_res = await writer.execute(path="greeting.txt", content="Hello World\nLine 2\n")
    assert w_res.success is True

    # 2. View file
    v_res = await viewer.execute(path="greeting.txt", start_line=1, end_line=1)
    assert "Hello World" in v_res.output
    assert "Line 2" not in v_res.output

    # 3. Edit file
    e_res = await editor.execute(path="greeting.txt", old_str="Hello World", new_str="Greetings Earth")
    assert e_res.success is True
    assert (tmp_path / "greeting.txt").read_text(encoding="utf-8").startswith("Greetings Earth")


@pytest.mark.asyncio
async def test_file_view_nonexistent(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)
    viewer = ViewFileTool(workspace=guard, permissions=perms)

    res = await viewer.execute(path="missing.txt")
    assert res.success is False
    assert "not found" in res.error.lower()


@pytest.mark.asyncio
async def test_file_edit_str_not_found(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)
    (tmp_path / "doc.txt").write_text("Alpha Beta", encoding="utf-8")

    editor = EditFileTool(workspace=guard, permissions=perms)
    res = await editor.execute(path="doc.txt", old_str="Gamma", new_str="Delta")
    assert res.success is False
    assert "target string not found" in res.error.lower()


@pytest.mark.asyncio
async def test_file_permission_denied(tmp_path: Path):
    async def deny_prompter(details: dict) -> PermissionDecision:
        return PermissionDecision.DENY

    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=False, prompter=deny_prompter)
    writer = WriteFileTool(workspace=guard, permissions=perms)

    res = await writer.execute(path="forbidden.txt", content="Blocked")
    assert res.success is False
    assert "denied" in res.error.lower()
    assert not (tmp_path / "forbidden.txt").exists()


@pytest.mark.asyncio
async def test_workspace_traversal_in_tool(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)
    writer = WriteFileTool(workspace=guard, permissions=perms)

    res = await writer.execute(path="../outside.txt", content="Escape")
    assert res.success is False
    assert "escapes target workspace" in res.error.lower()


@pytest.mark.asyncio
async def test_shell_command_success(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)
    runner = RunCommandTool(workspace=guard, permissions=perms)

    res = await runner.execute(command="python -c \"print('FRIDAY_SHELL_OK')\"")
    assert res.success is True
    assert "FRIDAY_SHELL_OK" in res.output


@pytest.mark.asyncio
async def test_shell_command_timeout(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)
    runner = RunCommandTool(workspace=guard, permissions=perms)

    # Python command that sleeps longer than timeout
    res = await runner.execute(command="python -c \"import time; time.sleep(2)\"", timeout_seconds=1)
    assert res.success is False
    assert "timed out" in res.error.lower()


@pytest.mark.asyncio
async def test_shell_command_permission_denied(tmp_path: Path):
    async def deny_prompter(details: dict) -> PermissionDecision:
        return PermissionDecision.DENY

    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=False, prompter=deny_prompter)
    runner = RunCommandTool(workspace=guard, permissions=perms)

    res = await runner.execute(command="dir")
    assert res.success is False
    assert "denied" in res.error.lower()


@pytest.mark.asyncio
async def test_file_view_caps_max_slice_lines(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    perms = PermissionController(yolo_mode=True)
    viewer = ViewFileTool(workspace=guard, permissions=perms)

    large_file = tmp_path / "large.txt"
    large_file.write_text("\n".join(f"line {i}" for i in range(1, 1001)), encoding="utf-8")

    # Request 1000 lines, but viewer must strictly enforce max slice limit of 500
    res = await viewer.execute(path="large.txt", start_line=1, end_line=1000)
    assert res.success is True
    assert "Showing lines 1 to 500 of 1000:" in res.output
    assert "500 | line 500" in res.output
    assert "501 | line 501" not in res.output
