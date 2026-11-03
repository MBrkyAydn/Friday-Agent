import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock
import pytest
from fastapi.testclient import TestClient

from friday.core.bus import EventBus
from friday.core.permissions import PermissionDecision
from friday.dashboard.server import create_dashboard_app
from friday.dashboard.prompter import DashboardPrompter


def test_api_profile_switch(tmp_path: Path):
    app = create_dashboard_app(workspace_path=tmp_path)
    client = TestClient(app)

    # Valid profile switch
    resp = client.post("/api/profile", json={"profile": "local"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["active_profile"] == "local"

    # Status reflects new profile
    status_resp = client.get("/api/status")
    assert status_resp.status_code == 200
    assert status_resp.json()["active_profile"] == "local"

    # Invalid profile rejected
    bad_resp = client.post("/api/profile", json={"profile": "invalid-model"})
    assert bad_resp.status_code == 400


def test_api_task_dispatch(tmp_path: Path):
    bus = EventBus()
    app = create_dashboard_app(workspace_path=tmp_path, bus=bus)
    client = TestClient(app)

    # Missing prompt
    bad_resp = client.post("/api/task", json={"prompt": ""})
    assert bad_resp.status_code == 400

    # Valid prompt
    resp = client.post("/api/task", json={"prompt": "Run integration check"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "started"
    assert data["task"] == "Run integration check"


@pytest.mark.asyncio
async def test_dashboard_prompter_flow(tmp_path: Path):
    prompter = DashboardPrompter()
    app = create_dashboard_app(workspace_path=tmp_path, prompter=prompter)
    client = TestClient(app)

    # Simulate permission request in background
    details = {"tool": "run_command", "command": "rm -rf temp"}
    
    task = asyncio.create_task(prompter(details))
    # Give the task a brief moment to register
    await asyncio.sleep(0.01)

    # Verify pending
    pending_resp = client.get("/api/permission/pending")
    assert pending_resp.status_code == 200
    pending = pending_resp.json()
    assert len(pending) == 1
    req_id = pending[0]["request_id"]
    assert pending[0]["details"]["tool"] == "run_command"

    # Approve permission via API
    resp = client.post("/api/permission", json={"request_id": req_id, "decision": "allow"})
    assert resp.status_code == 200
    assert resp.json()["decision"] == "allow"

    # Verify prompter future resolved with ALLOW
    decision = await task
    assert decision == PermissionDecision.ALLOW
