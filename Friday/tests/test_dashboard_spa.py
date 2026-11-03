from pathlib import Path
from fastapi.testclient import TestClient

from friday.dashboard.server import create_dashboard_app


def test_dashboard_spa_serves_html(tmp_path):
    app = create_dashboard_app(workspace_path=tmp_path)
    client = TestClient(app)

    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    text = resp.text
    assert "FRIDAY" in text
    assert "JARVIS" in text
    assert "Observability" in text or "Dashboard" in text
    assert "terminal-log" in text or "console" in text.lower()
