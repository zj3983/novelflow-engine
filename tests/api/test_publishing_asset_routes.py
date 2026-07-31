import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from packages.story_core.cover_image_provider import CoverImageError
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.publishing_assets import FanqieSynopsis


@pytest.fixture
def publishing_api(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path / "projects"))
    with TestClient(app, raise_server_exceptions=False) as client:
        created = client.post(
            "/file-projects",
            json={"mode": "blank", "title": "Publishing Route Novel", "novel_type_id": "urban"},
        )
        assert created.status_code == 201
        yield client, created.json()


def _synopsis() -> FanqieSynopsis:
    return FanqieSynopsis(
        tags=["urban", "growth", "mystery", "power"],
        body="A young courier finds a hidden ledger that names tomorrow's disasters. " * 5,
        pattern="conflict",
        visual_hook="A rain-soaked neon station and a glowing ledger.",
    )


def test_publishing_routes_generate_and_edit_synopsis_without_exposing_visual_hook(publishing_api, monkeypatch):
    client, created = publishing_api

    class FakeSynopsis:
        def generate(self, context, runtime, guidance=""):
            assert context.title == "Publishing Route Novel"
            assert guidance == "focus the stakes"
            return _synopsis()

    monkeypatch.setattr(file_projects, "synopsis_generator", FakeSynopsis())
    generated = client.post(
        f"/file-projects/{created['project_id']}/publishing/synopsis",
        json={"guidance": " focus the stakes "},
    )

    assert generated.status_code == 200, generated.text
    assert generated.json()["synopsis"] == {
        "tags": ["urban", "growth", "mystery", "power"],
        "body": _synopsis().body,
        "format": "fanqie",
        "updated_at": generated.json()["synopsis"]["updated_at"],
    }
    assert "visual_hook" not in generated.json()["synopsis"]

    edited = client.put(
        f"/file-projects/{created['project_id']}/publishing/synopsis",
        json={"tags": ["one", "two", "three", "four"], "body": " short manual copy "},
    )
    assert edited.status_code == 200
    assert edited.json()["synopsis"]["body"] == "short manual copy"
    assert edited.json()["synopsis"]["tags"] == ["one", "two", "three", "four"]
    assert client.put(
        f"/file-projects/{created['project_id']}/publishing/synopsis",
        json={"tags": ["one", "one", "three", "four"], "body": "x"},
    ).status_code == 422


def test_cover_prompt_ready_and_asset_download_are_isolated(publishing_api, monkeypatch):
    client, created = publishing_api

    class FakePrompt:
        def generate(self, context, runtime, visual_hook="", guidance=""):
            return "cinematic city in rain"

    monkeypatch.setattr(file_projects, "cover_prompt_generator", FakePrompt())
    response = client.post(f"/file-projects/{created['project_id']}/publishing/cover", json={})
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "prompt_ready"
    assert response.json()["reason"] == "image_provider_not_configured"
    assert response.json()["cover"]["prompt"] == "cinematic city in rain"
    assert client.get(f"/file-projects/{created['project_id']}/publishing/cover.png").status_code == 404

    store = FileProjectStore(Path(created["source_path"]))
    store.save_cover(prompt="old", base_image=b"base-old", rendered_image=b"png-final", model="m")
    image = client.get(f"/file-projects/{created['project_id']}/publishing/cover.png")
    assert image.status_code == 200
    assert image.content == b"png-final"
    assert image.headers["content-type"].startswith("image/png")
    assert image.headers["etag"].startswith('"')
    assert client.get(
        f"/file-projects/{created['project_id']}/publishing/cover.png",
        headers={"If-None-Match": image.headers["etag"]},
    ).status_code == 304
    download = client.get(f"/file-projects/{created['project_id']}/publishing/cover.png?download=1")
    assert "attachment" in download.headers["content-disposition"]


def test_cover_generation_persists_base_when_font_rendering_fails(publishing_api, monkeypatch):
    client, created = publishing_api

    class FakePrompt:
        def generate(self, *args, **kwargs):
            return "new cover prompt"

    class FakeImage:
        def generate(self, prompt, runtime):
            assert prompt == "new cover prompt"
            return b"new-base"

    monkeypatch.setattr(file_projects, "cover_prompt_generator", FakePrompt())
    monkeypatch.setattr(file_projects, "cover_image_provider", FakeImage())
    monkeypatch.setattr(file_projects, "resolve_image_runtime", lambda: SimpleNamespace(model="image-model"))
    monkeypatch.setattr(file_projects, "render_cover", lambda *_args: (_ for _ in ()).throw(ValueError("cover_font_unavailable")))
    store = FileProjectStore(Path(created["source_path"]))
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-final", model="old-model")

    response = client.post(f"/file-projects/{created['project_id']}/publishing/cover", json={})
    assert response.status_code == 503
    assert response.json()["detail"] == "cover_font_unavailable"
    assert store.cover_base_path.read_bytes() == b"new-base"
    assert store.rendered_cover_path.read_bytes() == b"old-final"
    assert store.publishing_assets()["cover"]["prompt"] == "new cover prompt"


def test_configured_cover_generation_prompt_edits_and_title_rerender(publishing_api, monkeypatch):
    client, created = publishing_api
    calls = []

    class FakePrompt:
        def generate(self, *args, **kwargs):
            return "generated prompt"

    class FakeImage:
        def generate(self, prompt, runtime):
            calls.append(prompt)
            return b"base-art"

    rendered_titles = []

    def fake_render(base, title):
        rendered_titles.append((base, title))
        return f"rendered:{title}".encode()

    monkeypatch.setattr(file_projects, "cover_prompt_generator", FakePrompt())
    monkeypatch.setattr(file_projects, "cover_image_provider", FakeImage())
    monkeypatch.setattr(file_projects, "resolve_image_runtime", lambda: SimpleNamespace(model="image-model"))
    monkeypatch.setattr(file_projects, "render_cover", fake_render)

    ready = client.post(f"/file-projects/{created['project_id']}/publishing/cover", json={})
    assert ready.status_code == 200, ready.text
    assert ready.json()["status"] == "ready"
    assert calls == ["generated prompt"]
    assert ready.json()["cover"]["model"] == "image-model"

    edited = client.put(
        f"/file-projects/{created['project_id']}/publishing/cover-prompt",
        json={"prompt": " manual prompt "},
    )
    assert edited.status_code == 200
    assert edited.json()["cover"]["prompt"] == "manual prompt"
    assert edited.json()["cover"]["base_path"] == "assets/cover-base.png"

    assert client.put(f"/file-projects/{created['project_id']}", json={"title": "Renamed Cover Novel"}).status_code == 200
    rerendered = client.post(f"/file-projects/{created['project_id']}/publishing/cover/render-title")
    assert rerendered.status_code == 200, rerendered.text
    assert rerendered.json()["cover"]["rendered_title"] == "Renamed Cover Novel"
    assert rendered_titles[-1] == (b"base-art", "Renamed Cover Novel")
    assert calls == ["generated prompt"]


def test_publishing_validation_and_missing_base_errors_are_stable(publishing_api):
    client, created = publishing_api
    base = f"/file-projects/{created['project_id']}/publishing"

    assert client.post(f"{base}/synopsis", json={"guidance": 3}).status_code == 422
    assert client.post(f"{base}/synopsis", json={"unknown": "x"}).status_code == 422
    assert client.put(
        f"{base}/synopsis", json={"tags": ["a", "b", "c", "c"], "body": "manual"}
    ).status_code == 422
    assert client.put(f"{base}/cover-prompt", json={"prompt": "   "}).status_code == 422
    missing = client.post(f"{base}/cover/render-title")
    assert missing.status_code == 404
    assert missing.json()["detail"] == "cover_base_not_found"


def test_known_invalid_synopsis_result_preserves_existing_assets(publishing_api, monkeypatch):
    client, created = publishing_api
    store = FileProjectStore(Path(created["source_path"]))
    store.save_synopsis({"tags": ["old"], "body": "old body"})
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-final", model="old-model")
    before = store.publishing_assets()

    class InvalidSynopsis:
        def generate(self, *args, **kwargs):
            raise ValueError("synopsis_generation_invalid")

    monkeypatch.setattr(file_projects, "synopsis_generator", InvalidSynopsis())
    response = client.post(f"/file-projects/{created['project_id']}/publishing/synopsis", json={})

    assert response.status_code == 502
    assert response.json()["detail"] == "synopsis_generation_invalid"
    assert store.publishing_assets() == before


@pytest.mark.parametrize("title_length", [41, 50, 120])
def test_cover_uses_authoritative_long_title_and_if_none_match_is_standard_compliant(publishing_api, monkeypatch, title_length):
    client, created = publishing_api
    title = "T" * title_length
    assert client.put(f"/file-projects/{created['project_id']}", json={"title": title}).status_code == 200

    class FakePrompt:
        def generate(self, *args, **kwargs):
            return "prompt"

    class FakeImage:
        def generate(self, _prompt, runtime):
            return b"base"

    titles = []
    monkeypatch.setattr(file_projects, "cover_prompt_generator", FakePrompt())
    monkeypatch.setattr(file_projects, "cover_image_provider", FakeImage())
    monkeypatch.setattr(file_projects, "resolve_image_runtime", lambda: SimpleNamespace(model="image-model"))
    monkeypatch.setattr(file_projects, "render_cover", lambda _base, current_title: titles.append(current_title) or b"final")
    ready = client.post(f"/file-projects/{created['project_id']}/publishing/cover", json={})
    assert ready.status_code == 200
    assert titles == [title]
    assert ready.json()["cover"]["rendered_title"] == title

    image = client.get(f"/file-projects/{created['project_id']}/publishing/cover.png")
    etag = image.headers["etag"]
    endpoint = f"/file-projects/{created['project_id']}/publishing/cover.png"
    assert client.get(endpoint, headers={"If-None-Match": f'"other", W/{etag}'}).status_code == 304
    assert client.get(endpoint, headers={"If-None-Match": "*"}).status_code == 304
    assert client.get(endpoint, headers={"If-None-Match": f"broken{etag}suffix"}).status_code == 200


def test_unsupported_image_model_preserves_prompt_and_existing_final_cover(publishing_api, monkeypatch):
    client, created = publishing_api
    store = FileProjectStore(Path(created["source_path"]))
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-final", model="old-model")

    class FakePrompt:
        def generate(self, *args, **kwargs):
            return "new prompt"

    class UnsupportedImage:
        def generate(self, _prompt, runtime):
            raise CoverImageError("image_model_unsupported")

    monkeypatch.setattr(file_projects, "cover_prompt_generator", FakePrompt())
    monkeypatch.setattr(file_projects, "cover_image_provider", UnsupportedImage())
    monkeypatch.setattr(file_projects, "resolve_image_runtime", lambda: SimpleNamespace(model="missing-model"))
    response = client.post(f"/file-projects/{created['project_id']}/publishing/cover", json={})

    assert response.status_code == 502
    assert response.json()["detail"] == "image_model_unsupported"
    assert store.publishing_assets()["cover"]["prompt"] == "new prompt"
    assert store.rendered_cover_path.read_bytes() == b"old-final"


def test_image_provider_type_error_is_called_once_and_preserves_prompt(publishing_api, monkeypatch):
    client, created = publishing_api
    calls = []

    class FakePrompt:
        def generate(self, *args, **kwargs):
            return "type error prompt"

    class FailingImage:
        def generate(self, prompt, runtime):
            calls.append((prompt, runtime.model))
            raise TypeError("internal argument failure")

    monkeypatch.setattr(file_projects, "cover_prompt_generator", FakePrompt())
    monkeypatch.setattr(file_projects, "cover_image_provider", FailingImage())
    monkeypatch.setattr(file_projects, "resolve_image_runtime", lambda: SimpleNamespace(model="image-model"))
    response = client.post(f"/file-projects/{created['project_id']}/publishing/cover", json={})
    assert response.status_code == 502
    assert response.json()["detail"] == "cover_generation_failed"
    assert calls == [("type error prompt", "image-model")]
    assert FileProjectStore(Path(created["source_path"])).publishing_assets()["cover"]["prompt"] == "type error prompt"


def test_cover_rejects_titles_over_the_publishing_limit(publishing_api, monkeypatch):
    client, created = publishing_api
    assert client.put(f"/file-projects/{created['project_id']}", json={"title": "T" * 121}).status_code == 200

    class UnexpectedPrompt:
        def generate(self, *args, **kwargs):
            raise AssertionError("title should be checked before prompt generation")

    monkeypatch.setattr(file_projects, "cover_prompt_generator", UnexpectedPrompt())
    response = client.post(f"/file-projects/{created['project_id']}/publishing/cover", json={})
    assert response.status_code == 422
    assert response.json()["detail"] == "cover_title_too_long"
