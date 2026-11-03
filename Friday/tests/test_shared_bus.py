import json
import pytest
from pathlib import Path
from friday.core.shared_bus import SharedBusProtocol


def test_shared_bus_sends_and_reads_mail(tmp_path: Path):
    shared_root = tmp_path / "Shared"
    logs_root = tmp_path / "Logs"

    bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    bus.send_message(recipient="Jarvis", action="review_pr", payload={"pr_id": 42})

    # Read from Jarvis's inbox perspective
    jarvis_bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Jarvis")
    messages = jarvis_bus.read_inbox()

    assert len(messages) == 1
    assert messages[0]["sender"] == "Friday"
    assert messages[0]["recipient"] == "Jarvis"
    assert messages[0]["action"] == "review_pr"
    assert messages[0]["payload"]["pr_id"] == 42


def test_shared_bus_logs_events(tmp_path: Path):
    shared_root = tmp_path / "Shared"
    logs_root = tmp_path / "Logs"

    bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    bus.log_event("TEST_EVENT", {"detail": "something happened"})

    log_file = logs_root / "friday.log"
    assert log_file.exists()
    lines = log_file.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["agent"] == "Friday"
    assert entry["event_type"] == "TEST_EVENT"
    assert entry["data"]["detail"] == "something happened"


def test_shared_bus_corrupted_message_skipped(tmp_path: Path):
    shared_root = tmp_path / "Shared"
    logs_root = tmp_path / "Logs"

    bus = SharedBusProtocol(shared_root=shared_root, logs_root=logs_root, agent_name="Friday")
    # Write valid message and corrupted message in inbox
    bus.send_message(recipient="Friday", action="ping", payload={})
    (bus.inbox / "bad_msg.json").write_text("{not-valid-json", encoding="utf-8")

    messages = bus.read_inbox()
    assert len(messages) == 1
    assert messages[0]["action"] == "ping"
