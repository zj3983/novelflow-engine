"""Save the book voice through the real route without generating prose."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.agents.pipeline import _build_writer_request, _ensure_writer_context
from packages.story_core.agents.writer.prompt import build_writer_prompt


@pytest.fixture
def voice_api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path / "exported-projects"))
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post("/file-projects", json={"mode": "blank", "title": "写法接口验证", "novel_type_id": "generic_webnovel"})
        assert created.status_code == 201, created.text
        yield client, created.json()


def test_saved_voice_roundtrips_into_writer_and_keeps_committed_chapter(voice_api):
    client, project = voice_api
    root = Path(project["source_path"])
    chapter = root / "chapters" / "0001-original.md"
    chapter.parent.mkdir(exist_ok=True)
    chapter.write_text("原有章节不能覆盖。", encoding="utf-8")
    before = chapter.read_bytes()
    preferences = {
        "writing_style": "幽默",
        "writing_guidance": "先吐槽再找补。API-GUIDANCE",
        "writing_reference": "我超威，这给我干哪来了？API-REFERENCE",
    }
    path = f"/file-projects/{project['project_id']}"
    response = client.put(path, json={"world_blueprint": preferences})
    assert response.status_code == 200, response.text
    saved = client.get(path).json()["world_blueprint"]
    assert all(saved[key] == value for key, value in preferences.items())
    artifact = DirectorArtifact(chapter_number=2, chapter_goal="打捞", opening_state="海面", scene_beats=[], ending_state="获得木箱")
    context = _ensure_writer_context(project_root=root, chapter_number=2, director_artifact=artifact)
    prompt = build_writer_prompt(_build_writer_request(context=context, director_artifact=artifact))
    assert "API-GUIDANCE" in prompt
    assert "API-REFERENCE" in prompt
    assert chapter.read_bytes() == before
    cleared = client.put(path, json={"world_blueprint": {key: "" for key in preferences}})
    assert cleared.status_code == 200, cleared.text
    assert chapter.read_bytes() == before


@pytest.mark.parametrize("invalid", [
    {"writing_guidance": "x" * 2001},
    {"writing_reference": {"invalid": "object"}},
], ids=["too-long", "invalid-type"])
def test_voice_route_rejects_invalid_input_before_writing(voice_api, invalid):
    client, project = voice_api
    path = Path(project["source_path"]) / ".webnovel" / "project.json"
    before = path.read_bytes()
    response = client.put(f"/file-projects/{project['project_id']}", json={"world_blueprint": invalid})
    assert response.status_code == 422, response.text
    assert response.json()["detail"] == "invalid_writing_preferences"
    assert path.read_bytes() == before
