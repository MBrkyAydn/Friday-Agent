import json
from pathlib import Path
from unittest.mock import patch, MagicMock
import pytest
from typer.testing import CliRunner

from friday.cli import app

runner = CliRunner()


def test_office_status_when_offline(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = runner.invoke(app, ["office", "status"])
    assert result.exit_code == 0
    assert "not running" in result.output.lower() or "offline" in result.output.lower()


def test_office_status_when_online(tmp_path, monkeypatch):
    pixel_dir = tmp_path / ".pixel-agents"
    pixel_dir.mkdir(parents=True, exist_ok=True)
    server_json = pixel_dir / "server.json"
    server_json.write_text(json.dumps({"port": 3100, "token": "test-tok-999"}))
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with patch("httpx.get") as mock_get:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"ok": True, "version": "1.4.1"}
        mock_get.return_value = mock_resp

        result = runner.invoke(app, ["office", "status"])
        assert result.exit_code == 0
        assert "3100" in result.output
        assert "ONLINE" in result.output or "running" in result.output.lower()


def test_office_stop_when_no_process(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    result = runner.invoke(app, ["office", "stop"])
    assert result.exit_code == 0
    assert "no running" in result.output.lower() or "not running" in result.output.lower()


def test_office_start_spawns_process(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    with patch("subprocess.Popen") as mock_popen, patch("webbrowser.open") as mock_browser:
        mock_proc = MagicMock()
        mock_proc.pid = 98765
        mock_popen.return_value = mock_proc

        result = runner.invoke(app, ["office", "start", "--port", "3100", "--no-browser"])
        assert result.exit_code == 0
        assert "starting" in result.output.lower() or "started" in result.output.lower()
        mock_popen.assert_called_once()
        mock_browser.assert_not_called()
