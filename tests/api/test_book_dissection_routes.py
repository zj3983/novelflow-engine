from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


def test_book_dissection_reference_returns_report():
    response = client.post(
        "/book-dissection/reference",
        json={
            "text": "夜烬绕开人群，先观察任务牌。短发玩家问他为什么不接任务，他说还差两份材料。",
            "genre": "网游",
            "focus": "爽点",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "book-dissection/v1"
    assert payload["mode"] == "reference"
    assert "爽点来源" in payload["sections"]


def test_book_dissection_reference_empty_text_returns_422():
    response = client.post("/book-dissection/reference", json={"text": "   "})

    assert response.status_code == 422
    assert response.json()["detail"] == "text_required"


def test_file_project_book_dissection_chapter_uses_store():
    projects_response = client.get("/file-projects")
    assert projects_response.status_code == 200
    projects = projects_response.json()
    if not projects:
        return

    response = client.post(
        f"/file-projects/{projects[0]['project_id']}/book-dissection/chapter",
        json={"chapter_number": 1},
    )

    assert response.status_code in {200, 404}
    if response.status_code == 200:
        payload = response.json()
        assert payload["schema_version"] == "book-dissection/v1"
        assert payload["mode"] == "project"
        assert "下一版改法" in payload["sections"]
