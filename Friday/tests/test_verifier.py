import pytest
from pathlib import Path
from unittest.mock import AsyncMock
from friday.core.workspace import WorkspaceGuard
from friday.core.verifier import VerificationRunner, TaskStatus, VerificationResult


@pytest.mark.asyncio
async def test_verification_detects_clean_pass(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    mock_runner.execute.return_value = AsyncMock(success=True, output="1 passed", error=None)

    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner, max_retries=3)
    status, result = await verifier.verify(custom_command="pytest")

    assert status == TaskStatus.DONE
    assert result.passed is True
    assert "1 passed" in result.stdout


@pytest.mark.asyncio
async def test_verification_retries_exhausted_reports_blocked(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    # Always fail
    mock_runner.execute.return_value = AsyncMock(success=False, output="", error="AssertionError")

    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner, max_retries=2)

    status, result = await verifier.run_repair_loop(
        custom_command="pytest",
        repair_fn=AsyncMock(return_value="Applied repair attempt"),
    )

    assert status == TaskStatus.BLOCKED
    assert result.passed is False
    assert result.attempts == 2


@pytest.mark.asyncio
async def test_verification_self_repair_succeeds_on_second_attempt(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    # Fail first, pass second
    mock_runner.execute.side_effect = [
        AsyncMock(success=False, output="", error="NameError: name 'x' is not defined"),
        AsyncMock(success=True, output="2 passed", error=None),
    ]

    repair_mock = AsyncMock(return_value="Defined variable x")

    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner, max_retries=3)
    status, result = await verifier.run_repair_loop(
        custom_command="pytest",
        repair_fn=repair_mock,
    )

    assert status == TaskStatus.DONE
    assert result.passed is True
    assert result.attempts == 2
    assert repair_mock.call_count == 1


def test_detect_verification_command_rules(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    verifier = VerificationRunner(workspace=guard, command_runner=AsyncMock())

    # None initially
    assert verifier.detect_verification_command() is None

    # Python
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text("[tool.pytest]", encoding="utf-8")
    assert verifier.detect_verification_command() == "pytest"
    pyproject.unlink()

    # Node
    pkg = tmp_path / "package.json"
    pkg.write_text("{}", encoding="utf-8")
    assert verifier.detect_verification_command() == "npm test"
    pkg.unlink()

    # Rust
    cargo = tmp_path / "Cargo.toml"
    cargo.write_text("", encoding="utf-8")
    assert verifier.detect_verification_command() == "cargo test"
    cargo.unlink()

    # Go
    gomod = tmp_path / "go.mod"
    gomod.write_text("", encoding="utf-8")
    assert verifier.detect_verification_command() == "go test ./..."
    gomod.unlink()


@pytest.mark.asyncio
async def test_fallback_when_no_suite_detected(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    mock_runner.execute.return_value = AsyncMock(success=True, output="", error=None)
    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner)

    status, result = await verifier.verify()
    assert status == TaskStatus.DONE
    assert result.passed is True
    # Verify that it actually called command_runner with python syntax compilation
    mock_runner.execute.assert_called_once()
    called_cmd = mock_runner.execute.call_args.kwargs.get("command") or mock_runner.execute.call_args.args[0]
    assert "compileall" in called_cmd


@pytest.mark.asyncio
async def test_fallback_syntax_check_detects_error(tmp_path: Path):
    guard = WorkspaceGuard(tmp_path)
    mock_runner = AsyncMock()
    mock_runner.execute.return_value = AsyncMock(
        success=False, output="", error="*** Error compiling 'main.py'...\nSyntaxError: invalid syntax"
    )
    verifier = VerificationRunner(workspace=guard, command_runner=mock_runner)

    status, result = await verifier.verify()
    assert status != TaskStatus.DONE
    assert result.passed is False
    assert "SyntaxError" in result.stderr
