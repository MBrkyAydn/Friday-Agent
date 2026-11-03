from pathlib import Path
from fastapi.testclient import TestClient
from friday.core.memory import AgencyMemory
from friday.dashboard.server import create_dashboard_app


def test_dashboard_memory_api(tmp_path: Path):
    db_file = tmp_path / "memory.db"
    mem = AgencyMemory(db_path=db_file)
    mem.seed_defaults()

    app = create_dashboard_app(workspace_path=tmp_path, memory=mem)
    client = TestClient(app)

    # 1. GET /api/memory
    resp = client.get("/api/memory")
    assert resp.status_code == 200
    items = resp.json()
    assert len(items) >= 4
    keys = [i["key"] for i in items]
    assert "groq_model_preference" in keys

    # 2. POST /api/memory
    post_resp = client.post(
        "/api/memory",
        json={
            "category": "tip",
            "key": "git_safe_push",
            "content": "Always run full test suite before committing.",
        },
    )
    assert post_resp.status_code == 200
    data = post_resp.json()
    assert data["status"] == "ok"
    assert data["key"] == "git_safe_push"

    # Verify added
    resp2 = client.get("/api/memory")
    assert len(resp2.json()) == len(items) + 1
