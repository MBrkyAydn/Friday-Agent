import pytest
from pathlib import Path
from friday.core.workspace import WorkspaceGuard, SecurityError

def test_workspace_allows_child_paths(tmp_path: Path):
    guard = WorkspaceGuard(target_dir=tmp_path)
    safe = guard.resolve_path("src/app.py")
    assert safe == (tmp_path / "src" / "app.py").resolve()

def test_workspace_rejects_parent_traversal(tmp_path: Path):
    target = tmp_path / "my_project"
    target.mkdir()
    guard = WorkspaceGuard(target_dir=target)

    with pytest.raises(SecurityError) as exc_info:
        guard.resolve_path("../other_folder/file.txt")
    assert "escapes target workspace" in str(exc_info.value)

def test_workspace_blocks_neighbor_agent_access(tmp_path: Path):
    agents_root = tmp_path / "AI-Agents"
    friday_dir = agents_root / "Friday"
    jarvis_dir = agents_root / "Jarvis"
    project_dir = agents_root / "UserProject"

    for d in (friday_dir, jarvis_dir, project_dir):
        d.mkdir(parents=True)

    guard = WorkspaceGuard(target_dir=project_dir)
    with pytest.raises(SecurityError) as exc_info:
        guard.resolve_path(str(jarvis_dir / "secret.py"))
    assert "escapes target workspace" in str(exc_info.value)

def test_workspace_is_safe_check(tmp_path: Path):
    target = tmp_path / "project"
    target.mkdir()
    guard = WorkspaceGuard(target_dir=target)

    assert guard.is_safe("sub/dir/file.txt") is True
    assert guard.is_safe(target / "file.txt") is True
    assert guard.is_safe("../../outside.txt") is False

def test_workspace_creates_target_dir_if_not_exists(tmp_path: Path):
    target = tmp_path / "non_existent" / "dir"
    assert not target.exists()
    guard = WorkspaceGuard(target_dir=target)
    assert target.exists()
    assert guard.target_dir == target.resolve()
