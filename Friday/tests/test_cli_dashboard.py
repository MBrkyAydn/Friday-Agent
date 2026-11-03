from pathlib import Path
from unittest.mock import MagicMock
import pytest
from typer.testing import CliRunner
from friday.cli import app

runner = CliRunner()


def test_dashboard_status_offline(monkeypatch, tmp_path):
    # Ensure pid file points to non-existent or clean dir
    test_pid_file = tmp_path / "dashboard.pid"
    monkeypatch.setattr("friday.cli.get_dashboard_pid_file", lambda: test_pid_file)

    result = runner.invoke(app, ["dashboard", "status"])
    assert result.exit_code == 0
    assert "offline" in result.stdout.lower()


def test_dashboard_status_online(monkeypatch, tmp_path):
    test_pid_file = tmp_path / "dashboard.pid"
    test_pid_file.write_text("99999")
    monkeypatch.setattr("friday.cli.get_dashboard_pid_file", lambda: test_pid_file)

    # Mock httpx.get returning 200
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"status": "ok", "workspace": "/test"}
    monkeypatch.setattr("httpx.get", lambda url, timeout=1.5: mock_resp)

    result = runner.invoke(app, ["dashboard", "status"])
    assert result.exit_code == 0
    assert "online" in result.stdout.lower()
    assert "99999" in result.stdout


def test_dashboard_stop_inactive(monkeypatch, tmp_path):
    test_pid_file = tmp_path / "dashboard.pid"
    monkeypatch.setattr("friday.cli.get_dashboard_pid_file", lambda: test_pid_file)

    result = runner.invoke(app, ["dashboard", "stop"])
    assert result.exit_code == 0
    assert "no running" in result.stdout.lower()


def test_dashboard_stop_active(monkeypatch, tmp_path):
    test_pid_file = tmp_path / "dashboard.pid"
    test_pid_file.write_text("99999")
    monkeypatch.setattr("friday.cli.get_dashboard_pid_file", lambda: test_pid_file)

    mock_run = MagicMock()
    monkeypatch.setattr("subprocess.run", mock_run)

    result = runner.invoke(app, ["dashboard", "stop"])
    assert result.exit_code == 0
    assert "stopped" in result.stdout.lower()
    assert not test_pid_file.exists()


def test_dashboard_start(monkeypatch, tmp_path):
    test_pid_file = tmp_path / "dashboard.pid"
    monkeypatch.setattr("friday.cli.get_dashboard_pid_file", lambda: test_pid_file)

    mock_proc = MagicMock()
    mock_proc.pid = 12345
    monkeypatch.setattr("subprocess.Popen", lambda *args, **kwargs: mock_proc)
    mock_browser = MagicMock()
    monkeypatch.setattr("webbrowser.open", mock_browser)

    result = runner.invoke(app, ["dashboard", "start", "--port", "8088", "--no-browser"])
    assert result.exit_code == 0
    assert "12345" in result.stdout
    assert test_pid_file.is_file()
    assert test_pid_file.read_text().strip() == "12345"
    mock_browser.assert_not_called()
