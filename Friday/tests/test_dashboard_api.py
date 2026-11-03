import json
from pathlib import Path
import pytest
from fastapi.testclient import TestClient

from friday.dashboard.server import create_dashboard_app


@pytest.fixture
def test_workspace(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir(parents=True, exist_ok=True)
    (ws / "main.py").write_text("print('hello world')", encoding="utf-8")
    return ws


@pytest.fixture
def mock_shared(tmp_path, monkeypatch):
    shared = tmp_path / "Shared"
    shared.mkdir(parents=True, exist_ok=True)
    inbox = shared / "mailboxes" / "friday_inbox"
    inbox.mkdir(parents=True, exist_ok=True)
    msg = {
        "message_id": "msg-123",
        "sender": "Jarvis",
        "recipient": "Friday",
        "action": "task_completed",
        "payload": {"result": "ok"}
    }
    (inbox / "msg-123.json").write_text(json.dumps(msg), encoding="utf-8")
    return shared


def test_status_endpoint(test_workspace):
    app = create_dashboard_app(workspace_path=test_workspace)
    client = TestClient(app)
    resp = client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["workspace"] == str(test_workspace)
    assert "friday_state" in data
    assert "jarvis_state" in data


def test_mailbox_endpoint(test_workspace, mock_shared, monkeypatch):
    monkeypatch.setattr("friday.dashboard.server.SHARED_ROOT", mock_shared)
    app = create_dashboard_app(workspace_path=test_workspace)
    client = TestClient(app)
    resp = client.get("/api/mailbox")
    assert resp.status_code == 200
    messages = resp.json()
    assert len(messages) >= 1
    assert messages[0]["sender"] == "Jarvis"


def test_files_endpoint(test_workspace):
    app = create_dashboard_app(workspace_path=test_workspace)
    client = TestClient(app)
    resp = client.get("/api/files")
    assert resp.status_code == 200
    files = resp.json()
    assert any(f["name"] == "main.py" for f in files)

    # Test file content reading
    content_resp = client.get("/api/files/content?path=main.py")
    assert content_resp.status_code == 200
    assert "print('hello world')" in content_resp.text
