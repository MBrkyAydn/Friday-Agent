import pytest
from pathlib import Path
from typer.testing import CliRunner
from friday.cli import app

runner = CliRunner()


def test_cli_version():
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "FRIDAY version: 0.1.0" in result.stdout


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "FRIDAY" in result.stdout


def test_cli_run(tmp_path: Path):
    result = runner.invoke(app, ["run", str(tmp_path)])
    assert result.exit_code == 0
    assert "Initializing FRIDAY" in result.stdout
    assert "ready" in result.stdout


def test_cli_run_yolo(tmp_path: Path):
    result = runner.invoke(app, ["run", str(tmp_path), "--yolo"])
    assert result.exit_code == 0
    assert "ready" in result.stdout


def test_cli_use_local(tmp_path: Path):
    from friday.core.config import load_config

    result = runner.invoke(app, ["use", "local", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "Active profile set to 'local'" in result.stdout
    assert "ollama/qwen2.5-coder" in result.stdout

    saved = load_config(tmp_path)
    assert saved.active_profile == "local"
    assert saved.model == "ollama/qwen2.5-coder"


def test_cli_use_gemini_free(tmp_path: Path):
    from friday.core.config import load_config

    result = runner.invoke(app, ["use", "gemini-free", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "Active profile set to 'gemini-free'" in result.stdout
    assert "gemini/gemini-3.8-flash" in result.stdout

    saved = load_config(tmp_path)
    assert saved.active_profile == "gemini-free"
    assert saved.model == "gemini/gemini-3.8-flash"


def test_cli_use_all_supported_profiles(tmp_path: Path):
    from friday.core.config import load_config
    from friday.cli import SUPPORTED_PROFILES, PROFILE_MODELS

    for profile in SUPPORTED_PROFILES:
        res = runner.invoke(app, ["use", profile, "--workspace", str(tmp_path)])
        assert res.exit_code == 0
        assert f"Active profile set to '{profile}'" in res.stdout
        assert PROFILE_MODELS[profile] in res.stdout

        cfg = load_config(tmp_path)
        assert cfg.active_profile == profile
        assert cfg.model == PROFILE_MODELS[profile]


def test_cli_use_unsupported_profile(tmp_path: Path):
    result = runner.invoke(app, ["use", "unknown-profile", "--workspace", str(tmp_path)])
    assert result.exit_code != 0
    output = result.stdout + result.stderr
    assert "Unsupported profile 'unknown-profile'" in output
    assert "local" in output
    assert "gemini-free" in output


def test_cli_config_set_key(tmp_path: Path):
    from friday.core.config import load_config

    result = runner.invoke(
        app,
        ["config", "set-key", "GEMINI_API_KEY", "secret-test-key-9999", "--workspace", str(tmp_path)],
    )
    assert result.exit_code == 0
    assert "GEMINI_API_KEY" in result.stdout
    assert "saved" in result.stdout.lower()

    # Verify .env
    env_file = tmp_path / ".env"
    assert env_file.exists()
    assert "GEMINI_API_KEY=secret-test-key-9999" in env_file.read_text(encoding="utf-8")

    # Verify config.yaml
    cfg = load_config(tmp_path)
    assert cfg.api_keys.get("GEMINI_API_KEY") == "secret-test-key-9999"


def test_cli_config_show(tmp_path: Path):
    # First set a profile and key
    runner.invoke(app, ["use", "claude", "--workspace", str(tmp_path)])
    runner.invoke(app, ["config", "set-key", "ANTHROPIC_API_KEY", "claude-secret-1234", "--workspace", str(tmp_path)])

    result = runner.invoke(app, ["config", "show", "--workspace", str(tmp_path)])
    assert result.exit_code == 0
    assert "FRIDAY Workspace Configuration" in result.stdout
    assert "Active Profile:" in result.stdout
    assert "claude" in result.stdout
    assert "Model:" in result.stdout
    assert "anthropic/claude-3-5-sonnet-20241022" in result.stdout
    assert "Temperature:" in result.stdout
    assert "API Base:" in result.stdout
    assert "ANTHROPIC_API_KEY" in result.stdout

