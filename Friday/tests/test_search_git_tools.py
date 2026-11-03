import pytest
import subprocess
from pathlib import Path

from friday.core.workspace import WorkspaceGuard, SecurityError
from friday.core.permissions import (
    PermissionController,
    PermissionTier,
    PermissionDecision,
)
from friday.tools.search import SearchCodeTool
from friday.tools.git import GitStatusTool, GitDiffTool, GitCommitTool


def test_search_code_finds_exact_string_with_line_numbers(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    tool = SearchCodeTool(workspace=guard, permissions=perms)

    src_dir = tmp_path / "src"
    src_dir.mkdir()
    (src_dir / "calc.py").write_text(
        "def add(a, b):\n    # Special calculation\n    return a + b\n",
        encoding="utf-8",
    )

    res = tool.execute_sync(query="Special calculation")
    assert res.success is True
    assert "calc.py:2" in res.output
    assert "Special calculation" in res.output


def test_search_code_regex_matching(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    tool = SearchCodeTool(workspace=guard, permissions=perms)

    (tmp_path / "version.py").write_text('APP_VERSION = "2.14.0"\n', encoding="utf-8")

    res = tool.execute_sync(query=r'APP_VERSION\s*=\s*"[0-9.]+"', regex=True)
    assert res.success is True
    assert "version.py:1" in res.output
    assert 'APP_VERSION = "2.14.0"' in res.output


def test_search_code_respects_workspace_jail_and_security_error(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    tool = SearchCodeTool(workspace=guard, permissions=perms)

    res = tool.execute_sync(query="findme", path="../outside")
    assert res.success is False
    assert "securityerror" in res.error.lower() or "jail" in res.error.lower() or "traversal" in res.error.lower()


def test_search_code_ignores_git_and_pycache(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)
    tool = SearchCodeTool(workspace=guard, permissions=perms)

    git_dir = tmp_path / ".git"
    git_dir.mkdir()
    (git_dir / "config").write_text("secret_token = 123\n", encoding="utf-8")

    pycache_dir = tmp_path / "__pycache__"
    pycache_dir.mkdir()
    (pycache_dir / "cache.py").write_text("secret_token = 123\n", encoding="utf-8")

    src_file = tmp_path / "app.py"
    src_file.write_text("secret_token = 123\n", encoding="utf-8")

    res = tool.execute_sync(query="secret_token")
    assert res.success is True
    assert "app.py" in res.output
    assert ".git" not in res.output
    assert "__pycache__" not in res.output


@pytest.mark.asyncio
async def test_git_status_and_diff_tools(tmp_path: Path):
    # Initialize a clean git repo in tmp_path
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)

    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)

    status_tool = GitStatusTool(workspace=guard, permissions=perms)
    diff_tool = GitDiffTool(workspace=guard, permissions=perms)

    test_file = tmp_path / "file.txt"
    test_file.write_text("initial content\n", encoding="utf-8")

    # Status check should report untracked file.txt
    res_status = await status_tool.execute()
    assert res_status.success is True
    assert "file.txt" in res_status.output

    # Commit initial file
    subprocess.run(["git", "add", "file.txt"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=str(tmp_path), check=True)

    # Modify file and verify diff
    test_file.write_text("modified content\n", encoding="utf-8")
    res_diff = await diff_tool.execute()
    assert res_diff.success is True
    assert "-initial content" in res_diff.output
    assert "+modified content" in res_diff.output


@pytest.mark.asyncio
async def test_git_commit_tool_guarded_permission(tmp_path: Path):
    subprocess.run(["git", "init"], cwd=str(tmp_path), capture_output=True, check=True)
    subprocess.run(["git", "config", "user.name", "TestUser"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=str(tmp_path), check=True)

    guard = WorkspaceGuard(target_dir=tmp_path)
    (tmp_path / "demo.txt").write_text("demo data\n", encoding="utf-8")

    # In YOLO mode -> allowed
    perms_yolo = PermissionController(yolo_mode=True)
    commit_tool_yolo = GitCommitTool(workspace=guard, permissions=perms_yolo)
    res = await commit_tool_yolo.execute(message="feat: add demo file")
    assert res.success is True
    assert "add demo file" in res.output or "commit" in res.output.lower()

    # In guarded mode with DENY prompter -> denied
    (tmp_path / "demo.txt").write_text("new demo data\n", encoding="utf-8")
    perms_guarded = PermissionController(
        yolo_mode=False,
        prompter=lambda details: PermissionDecision.DENY,
    )
    commit_tool_guarded = GitCommitTool(workspace=guard, permissions=perms_guarded)
    res_denied = await commit_tool_guarded.execute(message="rejected commit")
    assert res_denied.success is False
    assert "denied" in res_denied.error.lower()


def test_tools_generate_valid_function_schemas(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    perms = PermissionController(yolo_mode=True)

    search_tool = SearchCodeTool(workspace=guard, permissions=perms)
    status_tool = GitStatusTool(workspace=guard, permissions=perms)
    diff_tool = GitDiffTool(workspace=guard, permissions=perms)
    commit_tool = GitCommitTool(workspace=guard, permissions=perms)

    for tool in [search_tool, status_tool, diff_tool, commit_tool]:
        schema = tool.to_schema()
        assert schema["type"] == "function"
        fn = schema["function"]
        assert fn["name"] == tool.name
        assert fn["description"] == tool.description
        assert "parameters" in fn
        assert fn["parameters"]["type"] == "object"
