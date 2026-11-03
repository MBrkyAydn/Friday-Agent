import asyncio
import json
import pytest
from pathlib import Path
from typer.testing import CliRunner

from jarvis.shared_bus import SharedBusProtocol
from jarvis.worker import JarvisWorker
from jarvis.cli import app


@pytest.fixture
def test_env(tmp_path: Path):
    shared_root = tmp_path / "Shared"
    logs_root = tmp_path / "Logs"
    shared_root.mkdir(parents=True, exist_ok=True)
    logs_root.mkdir(parents=True, exist_ok=True)
    return shared_root, logs_root


def test_shared_bus_protocol_send_and_read(test_env):
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    bus_jarvis = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Jarvis")

    msg_id = bus_friday.send_message(
        recipient="Jarvis",
        action="execute_task",
        payload={"task": "Build feature X"},
    )

    inbox = bus_jarvis.read_inbox()
    assert len(inbox) == 1
    assert inbox[0]["message_id"] == msg_id
    assert inbox[0]["sender"] == "Friday"
    assert inbox[0]["recipient"] == "Jarvis"
    assert inbox[0]["action"] == "execute_task"
    assert inbox[0]["payload"]["task"] == "Build feature X"


def test_worker_process_empty_inbox(test_env):
    shared_root, logs_root = test_env
    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root)
    result = worker.process_next_task()
    assert result is None


def test_worker_process_success_task_and_reply(test_env):
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    bus_jarvis = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Jarvis")

    msg_id = bus_friday.send_message(
        recipient="Jarvis",
        action="execute_task",
        payload={"task": "Implement module auth.py"},
    )

    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root, enable_coder=False)
    result = worker.process_next_task()

    assert result is not None
    assert result["message_id"] == msg_id
    assert result["success"] is True
    assert result["reply_action"] == "task_completed"
    assert "Implement module auth.py" in result["output"]

    # Check that jarvis_inbox is now empty and message was archived
    assert len(bus_jarvis.read_inbox()) == 0
    archive_files = list((shared_root / "mailboxes" / "archive").glob("*.json"))
    assert len(archive_files) == 1

    # Check Friday's inbox has the reply
    friday_messages = bus_friday.read_inbox()
    assert len(friday_messages) == 1
    reply = friday_messages[0]
    assert reply["sender"] == "Jarvis"
    assert reply["recipient"] == "Friday"
    assert reply["action"] == "task_completed"
    assert reply["payload"]["in_reply_to"] == msg_id
    assert reply["payload"]["success"] is True

    # Check logs
    log_file = logs_root / "jarvis.log"
    assert log_file.exists()
    log_content = log_file.read_text(encoding="utf-8")
    assert "TASK_RECEIVED" in log_content
    assert "TASK_FINISHED" in log_content


def test_worker_process_failed_task(test_env):
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")

    msg_id = bus_friday.send_message(
        recipient="Jarvis",
        action="execute_task",
        payload={"simulate_fail": True, "error": "Disk quota exceeded"},
    )

    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root)
    result = worker.process_next_task()

    assert result is not None
    assert result["success"] is False
    assert result["reply_action"] == "task_failed"
    assert "Disk quota exceeded" in result["error"]

    friday_messages = bus_friday.read_inbox()
    assert len(friday_messages) == 1
    assert friday_messages[0]["action"] == "task_failed"
    assert friday_messages[0]["payload"]["error"] == "Disk quota exceeded"


def test_worker_process_ping_task(test_env):
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")

    msg_id = bus_friday.send_message(
        recipient="Jarvis",
        action="ping",
        payload={},
    )

    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root)
    result = worker.process_next_task()

    assert result is not None
    assert result["success"] is True
    assert "pong" in result["output"]

    friday_messages = bus_friday.read_inbox()
    assert len(friday_messages) == 1
    assert friday_messages[0]["action"] == "task_completed"


def test_worker_command_execution_and_verification(test_env, tmp_path: Path):
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")

    # Command that creates a file, verification checks file exists
    test_file = tmp_path / "hello.txt"
    create_cmd = f'python -c "from pathlib import Path; Path(r\'{test_file}\').write_text(\'hello\')"'
    verif_cmd = f'python -c "from pathlib import Path; assert Path(r\'{test_file}\').read_text() == \'hello\'"'

    msg_id = bus_friday.send_message(
        recipient="Jarvis",
        action="execute_task",
        payload={
            "command": create_cmd,
            "verification_command": verif_cmd,
        },
    )

    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root, workspace_root=tmp_path)
    result = worker.process_next_task()

    assert result["success"] is True
    assert result["reply_action"] == "task_completed"
    assert "Verification Passed" in result["output"]
    assert test_file.exists()


def test_worker_verification_failure(test_env, tmp_path: Path):
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")

    # Command succeeds but verification fails
    verif_cmd = 'python -c "raise SystemExit(2)"'

    msg_id = bus_friday.send_message(
        recipient="Jarvis",
        action="execute_task",
        payload={
            "command": "python -c \"print('ran')\"",
            "verification_command": verif_cmd,
        },
    )

    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root, workspace_root=tmp_path)
    result = worker.process_next_task()

    assert result["success"] is False
    assert result["reply_action"] == "task_failed"
    assert "Verification failed" in result["error"]


@pytest.mark.asyncio
async def test_worker_listen_run_once(test_env):
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    bus_friday.send_message(
        recipient="Jarvis",
        action="execute_task",
        payload={"task": "Run once test"},
    )

    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root, enable_coder=False)
    await worker.listen(interval=0.01, run_once=True)

    friday_messages = bus_friday.read_inbox()
    assert len(friday_messages) == 1
    assert friday_messages[0]["action"] == "task_completed"


@pytest.mark.asyncio
async def test_worker_listen_loop_and_stop(test_env):
    shared_root, logs_root = test_env
    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root)

    task = asyncio.create_task(worker.listen(interval=0.02, run_once=False))
    await asyncio.sleep(0.05)
    worker.stop()
    await task
    assert not worker.running


def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == 0
    assert "JARVIS Worker version" in result.output


def test_cli_run_once_empty(test_env):
    shared_root, logs_root = test_env
    runner = CliRunner()
    result = runner.invoke(app, ["run-once", "--shared-root", str(shared_root), "--logs-root", str(logs_root)])
    assert result.exit_code == 0
    assert "No pending tasks" in result.output


def test_cli_run_once_with_task(test_env):
    shared_root, logs_root = test_env
    bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    bus.send_message(recipient="Jarvis", action="ping", payload={})

    runner = CliRunner()
    result = runner.invoke(app, ["run-once", "--shared-root", str(shared_root), "--logs-root", str(logs_root)])
    assert result.exit_code == 0
    assert "Task Processed" in result.output


def test_cli_ping(test_env):
    shared_root, logs_root = test_env
    runner = CliRunner()
    result = runner.invoke(app, ["ping", "--shared-root", str(shared_root), "--logs-root", str(logs_root)])
    assert result.exit_code == 0
    assert "Ping sent to Friday inbox" in result.output

    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    msgs = bus_friday.read_inbox()
    assert len(msgs) == 1
    assert msgs[0]["action"] == "ping"


def test_worker_process_with_coder_creates_files(test_env, tmp_path: Path):
    from unittest.mock import patch
    shared_root, logs_root = test_env
    bus_friday = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")

    mock_llm_response = """
FILE: main.py
```python
def multiply(a: int, b: int) -> int:
    return a * b
```
"""

    msg_id = bus_friday.send_message(
        recipient="Jarvis",
        action="execute_task",
        payload={
            "task": "Create multiplication function in main.py",
            "workspace_path": str(tmp_path),
        },
    )

    worker = JarvisWorker(shared_root=shared_root, logs_root=logs_root)
    with patch.object(worker.coder, "_call_llm", return_value=mock_llm_response):
        result = worker.process_next_task()

    assert result is not None
    assert result["success"] is True
    assert (tmp_path / "main.py").exists()
    assert "multiply" in (tmp_path / "main.py").read_text(encoding="utf-8")
    assert "main.py" in result["output"]
