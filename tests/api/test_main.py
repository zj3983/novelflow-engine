from fastapi.testclient import TestClient

from apps.api.main import app


def test_backend_root_redirects_to_workbench(monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FRONTEND_URL", "http://localhost:3100/")

    response = TestClient(app).get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "http://localhost:3100/projects"


def test_health_endpoint_remains_available():
    response = TestClient(app).get("/health")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
