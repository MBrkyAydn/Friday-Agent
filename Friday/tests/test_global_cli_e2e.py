import json
from pathlib import Path
from unittest.mock import AsyncMock, patch
import pytest
from typer.testing import CliRunner

from friday.cli import app
from friday.agent.llm import LLMResponse

runner = CliRunner()


def test_cli_defaults_to_cwd_when_no_path_provided(monkeypatch, tmp_path: Path):
    """Verify that when no path is provided, CLI defaults target_dir to Path.cwd()."""
    monkeypatch.chdir(tmp_path)

    mock_resp = LLMResponse(model="test-model", content="Done task", finish_reason="stop")
    with patch("friday.agent.llm.litellm_provider.LiteLLMProvider.complete", new=AsyncMock(return_value=mock_resp)):
        result = runner.invoke(app, ["-p", "ping", "--yolo"])
        assert result.exit_code == 0
        assert f"workspace: {tmp_path.resolve()}" in result.stdout

    # Verify session was created inside tmp_path (cwd)
    session_dir = tmp_path / ".friday" / "sessions"
    assert session_dir.exists()
    assert len(list(session_dir.glob("*.json"))) == 1


def test_cli_top_level_invocation_with_prompt(monkeypatch, tmp_path: Path):
    """Verify top-level 'friday -p \"...\"' runs single prompt without requiring 'run' subcommand."""
    monkeypatch.chdir(tmp_path)

    mock_resp = LLMResponse(model="test-model", content="Execution result", finish_reason="stop")
    with patch("friday.agent.llm.litellm_provider.LiteLLMProvider.complete", new=AsyncMock(return_value=mock_resp)):
        result = runner.invoke(app, ["--prompt", "check repo", "--yolo"])
        assert result.exit_code == 0
        assert "Executing instruction: 'check repo'" in result.stdout


def test_cli_top_level_positional_prompt(monkeypatch, tmp_path: Path):
    """Verify top-level 'friday \"check status\"' treats positional argument as prompt when without subcommand."""
    monkeypatch.chdir(tmp_path)

    mock_resp = LLMResponse(model="test-model", content="Execution result", finish_reason="stop")
    with patch("friday.agent.llm.litellm_provider.LiteLLMProvider.complete", new=AsyncMock(return_value=mock_resp)):
        result = runner.invoke(app, ["check status", "--yolo"])
        assert result.exit_code == 0
        assert "Executing instruction: 'check status'" in result.stdout


def test_e2e_external_workspace_isolation(tmp_path: Path):
    """Verify CLI execution isolates .friday artifacts strictly in the external project."""
    ext_dir = tmp_path / "external_project"
    ext_dir.mkdir()
    friday_md = ext_dir / "FRIDAY.md"
    friday_md.write_text("# Project Custom Instructions\nFollow strict TDD.", encoding="utf-8")

    mock_resp = LLMResponse(model="test-model", content="Done task", finish_reason="stop")
    with patch("friday.agent.llm.litellm_provider.LiteLLMProvider.complete", new=AsyncMock(return_value=mock_resp)):
        result = runner.invoke(app, ["run", str(ext_dir), "--prompt", "hello", "--yolo"])
        assert result.exit_code == 0, f"Error: {result.stdout}"
        assert "Initializing FRIDAY on workspace:" in result.stdout

    # Verify session is in ext_dir/.friday/sessions
    ext_sessions = ext_dir / ".friday" / "sessions"
    assert ext_sessions.exists()
    session_files = list(ext_sessions.glob("*.json"))
    assert len(session_files) == 1

    # Verify the saved session contains the turn
    session_data = json.loads(session_files[0].read_text(encoding="utf-8"))
    assert session_data["workspace_path"] == str(ext_dir.resolve())
    assert len(session_data["turns"]) == 1
    assert session_data["turns"][0]["user_prompt"] == "hello"


def test_e2e_session_resume_restores_memory(tmp_path: Path):
    """Verify resuming an existing session with --session restores prior conversation memory."""
    ext_dir = tmp_path / "resume_project"
    ext_dir.mkdir()

    mock_resp = LLMResponse(model="test-model", content="Done task", finish_reason="stop")
    with patch("friday.agent.llm.litellm_provider.LiteLLMProvider.complete", new=AsyncMock(return_value=mock_resp)):
        # Turn 1
        res1 = runner.invoke(app, ["run", str(ext_dir), "--prompt", "first instruction", "--yolo"])
        assert res1.exit_code == 0, f"Turn 1 failed: {res1.stdout}"

        session_dir = ext_dir / ".friday" / "sessions"
        session_files = list(session_dir.glob("*.json"))
        assert len(session_files) == 1
        session_file = session_files[0]
        session_id = session_file.stem

        # Turn 2 with --session
        res2 = runner.invoke(
            app,
            [
                "run",
                str(ext_dir),
                "--session",
                session_id,
                "--prompt",
                "second instruction",
                "--yolo",
            ],
        )
        assert res2.exit_code == 0, f"Turn 2 failed: {res2.stdout}"

    # Verify session file was updated and now has 2 turns
    updated_data = json.loads(session_file.read_text(encoding="utf-8"))
    assert len(updated_data["turns"]) == 2
    assert updated_data["turns"][0]["user_prompt"] == "first instruction"
    assert updated_data["turns"][1]["user_prompt"] == "second instruction"
