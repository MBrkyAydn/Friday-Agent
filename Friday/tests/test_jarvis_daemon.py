import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from friday.cli import app
from friday.core.jarvis_daemon import (
    ensure_jarvis_worker,
    is_jarvis_worker_running,
    is_pid_alive,
    resolve_daemon_paths,
    start_jarvis_worker,
    stop_jarvis_worker,
)

runner = CliRunner()


def test_is_pid_alive_self_and_invalid():
    """Verify is_pid_alive returns True for current process and False for invalid PID."""
    assert is_pid_alive(os.getpid()) is True
    assert is_pid_alive(-1) is False
    assert is_pid_alive(99999999) is False


def test_is_jarvis_worker_running_no_file(tmp_path: Path):
    """Verify is_jarvis_worker_running returns False when no PID file exists."""
    shared_root = tmp_path / "Shared"
    running, pid = is_jarvis_worker_running(shared_root=shared_root)
    assert running is False
    assert pid is None


def test_is_jarvis_worker_running_active_pid(tmp_path: Path):
    """Verify is_jarvis_worker_running returns True when PID file has active process."""
    shared_root = tmp_path / "Shared"
    state_dir = shared_root / "state"
    state_dir.mkdir(parents=True)
    pid_file = state_dir / "jarvis_worker.pid"
    my_pid = os.getpid()
    pid_file.write_text(str(my_pid))

    running, pid = is_jarvis_worker_running(shared_root=shared_root)
    assert running is True
    assert pid == my_pid


def test_is_jarvis_worker_running_stale_pid_cleanup(tmp_path: Path):
    """Verify stale PID file is cleaned up automatically."""
    shared_root = tmp_path / "Shared"
    state_dir = shared_root / "state"
    state_dir.mkdir(parents=True)
    pid_file = state_dir / "jarvis_worker.pid"
    pid_file.write_text("99999999")

    running, pid = is_jarvis_worker_running(shared_root=shared_root)
    assert running is False
    assert pid is None
    assert not pid_file.exists()


def test_start_and_stop_jarvis_worker_mock(tmp_path: Path):
    """Verify start_jarvis_worker spawns detached process and records PID."""
    shared_root = tmp_path / "Shared"
    logs_root = tmp_path / "Logs"

    mock_proc = MagicMock()
    mock_proc.pid = 43210

    with patch("subprocess.Popen", return_value=mock_proc) as mock_popen, \
         patch("friday.core.jarvis_daemon.is_pid_alive", return_value=True):
        pid = start_jarvis_worker(shared_root=shared_root, logs_root=logs_root)
        assert pid == 43210
        mock_popen.assert_called_once()

        pid_file = shared_root / "state" / "jarvis_worker.pid"
        assert pid_file.exists()
        assert pid_file.read_text().strip() == "43210"

    # Stop worker mock
    with patch("subprocess.run") as mock_subrun, \
         patch("friday.core.jarvis_daemon.is_pid_alive", return_value=True):
        stopped = stop_jarvis_worker(shared_root=shared_root)
        assert stopped is True
        assert not pid_file.exists()


def test_ensure_jarvis_worker_when_already_running(tmp_path: Path):
    """Verify ensure_jarvis_worker returns active PID without re-spawning."""
    shared_root = tmp_path / "Shared"
    state_dir = shared_root / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "jarvis_worker.pid").write_text(str(os.getpid()))

    running, pid = ensure_jarvis_worker(shared_root=shared_root)
    assert running is True
    assert pid == os.getpid()


def test_cli_jarvis_status_offline(tmp_path: Path):
    """Verify 'friday jarvis status' outputs offline when no worker running."""
    shared_root = tmp_path / "Shared"
    res = runner.invoke(app, ["jarvis", "status", "--shared-root", str(shared_root)])
    assert res.exit_code == 0
    assert "OFFLINE" in res.stdout


def test_cli_jarvis_status_online(tmp_path: Path):
    """Verify 'friday jarvis status' outputs online when worker is alive."""
    shared_root = tmp_path / "Shared"
    state_dir = shared_root / "state"
    state_dir.mkdir(parents=True)
    (state_dir / "jarvis_worker.pid").write_text(str(os.getpid()))

    res = runner.invoke(app, ["jarvis", "status", "--shared-root", str(shared_root)])
    assert res.exit_code == 0
    assert "ONLINE" in res.stdout
    assert str(os.getpid()) in res.stdout
