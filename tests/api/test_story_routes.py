import urllib.error

import pytest

from fastapi.testclient import TestClient

from apps.api.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def clean_db_and_restore_runtime_settings():
    """Clean up persistent SQLite DB to ensure test isolation."""
    import os as _os
    from apps.api.storage import _get_db_path, _local
    db_path = _get_db_path()
    # Close all cached connections before deleting DB
    if hasattr(_local, "connections"):
        for conn in _local.connections.values():
            try:
                conn.close()
            except Exception:
                pass
        _local.connections.clear()
    # Remove the DB file
    if _os.path.exists(db_path):
        try:
            _os.remove(db_path)
        except PermissionError:
            # On Windows the file may still be locked; clear contents instead
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM chapter_bundles")
            conn.execute("DELETE FROM stories")
            conn.commit()
            conn.close()
    original = client.get("/runtime-settings").json()
    yield
    client.put("/runtime-settings", json=original)


def test_runtime_settings_can_be_saved_globally():
    response = client.get("/runtime-settings")
    assert response.status_code == 200
    assert response.json()["global"]["base_url"]
    assert "api_key" in response.json()["global"]

    update_resp = client.put(
        "/runtime-settings",
        json={
            "global": {
                "api_key": "sk-test-123",
                "base_url": "https://api.example.com/v1",
            },
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["global"]["api_key"] == "sk-test-123"
    assert update_resp.json()["global"]["base_url"] == "https://api.example.com/v1"

    loaded = client.get("/runtime-settings")
    assert loaded.status_code == 200
    assert loaded.json()["global"]["api_key"] == "sk-test-123"
    assert loaded.json()["global"]["base_url"] == "https://api.example.com/v1"


def test_runtime_settings_can_store_agent_overrides():
    update_resp = client.put(
        "/runtime-settings",
        json={
            "global": {
                "api_key": "sk-global",
                "base_url": "https://api.global.example/v1",
            },
            "agents": {
                "character": {
                    "api_key": "sk-character",
                    "base_url": "https://api.character.example/v1",
                },
                "director": {
                    "api_key": "sk-director",
                    "base_url": "https://api.director.example/v1",
                },
                "writer": {
                    "api_key": "sk-writer",
                    "base_url": "https://api.writer.example/v1",
                },
                "memory": {
                    "api_key": "sk-memory",
                    "base_url": "https://api.memory.example/v1",
                },
            },
        },
    )
    assert update_resp.status_code == 200

    loaded = client.get("/runtime-settings")
    assert loaded.status_code == 200
    payload = loaded.json()
    assert payload["global"]["api_key"] == "sk-global"
    assert payload["global"]["base_url"] == "https://api.global.example/v1"
    assert payload["agents"]["character"]["api_key"] == "sk-character"
    assert payload["agents"]["director"]["base_url"] == "https://api.director.example/v1"


def test_runtime_settings_connection_can_be_tested_for_one_agent(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers.get("Content-type")
        captured["body"] = request.data

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr("apps.api.routes.stories.urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "character",
            "runtime_settings": {
                "global": {
                    "api_key": "sk-global",
                    "base_url": "https://api.global.example/v1",
                },
                "agents": {
                    "character": {
                        "api_key": "sk-character",
                        "base_url": "https://api.character.example/v1",
                    }
                },
            },
            "model_name": "gpt-4.1-mini",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["agent_name"] == "character"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.character.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-character"
    assert captured["content_type"] == "application/json"
    assert b'"model": "gpt-4.1-mini"' in captured["body"]


def test_runtime_settings_connection_falls_back_to_models_when_chat_endpoint_missing(monkeypatch):
    captured_urls = []

    def fake_urlopen(request, timeout=30):
        captured_urls.append(request.full_url)
        if request.full_url.endswith("/chat/completions"):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=None,
            )

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr("apps.api.routes.stories.urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "global",
            "runtime_settings": {
                "global": {
                    "api_key": "sk-global",
                    "base_url": "https://api.global.example/v1",
                },
            },
            "model_name": "gpt-4.1",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured_urls == [
        "https://api.global.example/v1/chat/completions",
        "https://api.global.example/v1/models",
    ]


def test_runtime_settings_connection_uses_custom_global_base_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr("apps.api.routes.stories.urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "global",
            "runtime_settings": {
                "global": {
                    "api_key": "sk-global",
                    "base_url": "https://api.global.example/v1",
                },
            },
            "model_name": "gpt-4.1",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["url"] == "https://api.global.example/v1/chat/completions"


def test_story_can_be_created_and_rolled_back():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-001",
            "outline": "A detective prince uncovers palace crimes.",
            "genre": "fantasy",
            "style": "noir",
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["current_chapter"] == 0
    assert create_resp.json()["history"] == []

    gen_resp = client.post("/stories/s-001/generate")
    assert gen_resp.status_code == 200
    assert gen_resp.json()["chapter_number"] == 1

    rollback_resp = client.post("/stories/s-001/rollback")
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["current_chapter"] == 0


def test_story_can_store_characters_and_freeze_them():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-characters",
            "outline": "A palace clerk learns the truth about the treasury.",
            "genre": "fantasy",
            "style": "court intrigue",
            "characters": [
                {
                    "name": "Pei An",
                    "role": "clerk",
                    "goals": ["protect the evidence"],
                    "frozen": False,
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["characters"][0]["name"] == "Pei An"

    freeze_resp = client.post("/stories/s-characters/characters/Pei%20An/freeze")
    assert freeze_resp.status_code == 200
    assert freeze_resp.json()["characters"][0]["frozen"] is True


def test_story_can_store_global_default_model_in_agent_settings():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-global-model",
            "outline": "A court witness shifts the balance of power.",
            "genre": "mystery",
            "style": "tense",
            "agent_settings": {
                "global_model": "gpt-global",
                "character_model": "",
                "director_model": "",
                "writer_model": "",
            },
        },
    )

    assert create_resp.status_code == 200
    assert create_resp.json()["agent_settings"]["global_model"] == "gpt-global"


def test_story_serializes_character_lifecycle_fields():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-lifecycle",
            "outline": "A witness keeper enters the archive under a false name.",
            "genre": "mystery",
            "style": "tense",
            "characters": [
                {
                    "name": "Old Archivist",
                    "role": "supporting",
                    "goals": ["hide the witness"],
                    "frozen": False,
                    "lifecycle_state": "proposed",
                    "last_proposed_chapter": 2,
                    "last_approved_chapter": 0,
                    "introduced_by": "Su Wan",
                }
            ],
        },
    )

    assert create_resp.status_code == 200
    character = create_resp.json()["characters"][0]
    assert character["lifecycle_state"] == "proposed"
    assert character["last_proposed_chapter"] == 2
    assert character["last_approved_chapter"] == 0
    assert character["introduced_by"] == "Su Wan"


def test_agent_settings_influence_story_approval_flow():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-agent-settings",
            "outline": "A court witness arrives under a false name.",
            "genre": "mystery",
            "style": "tense",
            "agent_settings": {
                "mode": "LLM-assisted",
                "character_model": "gpt-5.4-mini",
                "director_model": "gpt-5.4",
                "writer_model": "gpt-5.4",
                "temperature": "0.85",
                "new_character_policy": "Auto-approve named candidates",
            },
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "protagonist",
                    "goals": ["find the witness"],
                    "secrets": ["Old archivist knows the false name."],
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["agent_settings"]["mode"] == "LLM-assisted"

    generated = client.post("/stories/s-agent-settings/generate")
    assert generated.status_code == 200

    story = generated.json()["updated_story"]
    assert story["agent_settings"]["new_character_policy"] == "Auto-approve named candidates"
    assert "Old Archivist" in generated.json()["conflict_summary"]["approved_new_characters"]


def test_lifecycle_fields_remain_present_across_generate_freeze_and_rollback():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-lifecycle-flow",
            "outline": "A clerk follows witness rumors through sealed archives.",
            "genre": "mystery",
            "style": "tense",
            "characters": [
                {
                    "name": "Pei An",
                    "role": "supporting",
                    "goals": ["hide the witness"],
                    "frozen": False,
                    "lifecycle_state": "active",
                    "last_proposed_chapter": 0,
                    "last_approved_chapter": 0,
                    "introduced_by": "",
                }
            ],
        },
    )
    assert create_resp.status_code == 200

    generated = client.post("/stories/s-lifecycle-flow/generate")
    assert generated.status_code == 200
    generated_character = generated.json()["updated_story"]["characters"][0]
    assert "lifecycle_state" in generated_character
    assert "last_proposed_chapter" in generated_character
    assert "last_approved_chapter" in generated_character
    assert "introduced_by" in generated_character

    frozen = client.post("/stories/s-lifecycle-flow/characters/Pei%20An/freeze")
    assert frozen.status_code == 200
    frozen_character = frozen.json()["characters"][0]
    assert frozen_character["frozen"] is True
    assert frozen_character["lifecycle_state"] == "frozen"

    rolled_back = client.post("/stories/s-lifecycle-flow/rollback")
    assert rolled_back.status_code == 200
    rolled_character = rolled_back.json()["characters"][0]
    assert "lifecycle_state" in rolled_character
    assert "last_proposed_chapter" in rolled_character
    assert "last_approved_chapter" in rolled_character
    assert "introduced_by" in rolled_character


def test_rollback_restores_previous_story_state():
    client.post(
        "/stories",
        json={
            "story_id": "s-rollback-state",
            "outline": "A magistrate hunts the source of forged decrees.",
            "genre": "mystery",
            "style": "tense",
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "investigator",
                    "goals": ["find the forger"],
                    "frozen": False,
                    "relationships": {
                        "Su Wan": {
                            "target": "Su Wan",
                            "trust": 0.4,
                            "tension": 0.9,
                            "bond": "uneasy alliance",
                        }
                    },
                }
            ],
        },
    )

    client.post("/stories/s-rollback-state/generate")
    client.post("/stories/s-rollback-state/generate")

    rollback_resp = client.post("/stories/s-rollback-state/rollback")
    assert rollback_resp.status_code == 200

    story = rollback_resp.json()
    assert story["current_chapter"] == 1
    assert len(story["history"]) == 1
    assert story["history"][0]["chapter_number"] == 1
    relation = story["characters"][0]["relationships"]["Su Wan"]
    assert relation["trust"] == 0.3
    assert relation["tension"] == 1.0


def test_story_can_branch_from_a_previous_chapter():
    client.post(
        "/stories",
        json={
            "story_id": "s-branch-root",
            "outline": "Two rivals hunt a ledger buried under the imperial archives.",
            "genre": "fantasy",
            "style": "court intrigue",
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "investigator",
                    "goals": ["find the ledger"],
                    "frozen": False,
                }
            ],
        },
    )
    client.post("/stories/s-branch-root/generate")
    client.post("/stories/s-branch-root/generate")

    branch_resp = client.post(
        "/stories/s-branch-root/branch",
        json={"new_story_id": "s-branch-alt", "from_chapter": 1},
    )
    assert branch_resp.status_code == 200

    branch_story = branch_resp.json()
    assert branch_story["story_id"] == "s-branch-alt"
    assert branch_story["current_chapter"] == 1
    assert len(branch_story["history"]) == 1
    assert branch_story["history"][0]["chapter_number"] == 1
    assert branch_story["parent_story_id"] == "s-branch-root"
    assert branch_story["branched_from_chapter"] == 1

    original_story = client.get("/stories/s-branch-root")
    assert original_story.status_code == 200
    assert original_story.json()["current_chapter"] == 2

    list_resp = client.get("/stories")
    assert list_resp.status_code == 200
    assert {story["story_id"] for story in list_resp.json()} >= {"s-branch-root", "s-branch-alt"}


def test_branch_can_be_renamed_and_deleted():
    client.post(
        "/stories",
        json={
            "story_id": "s-branch-admin-root",
            "outline": "A censor builds three versions of the same testimony.",
            "genre": "fantasy",
            "style": "political",
        },
    )
    client.post("/stories/s-branch-admin-root/generate")
    client.post(
        "/stories/s-branch-admin-root/branch",
        json={"new_story_id": "s-branch-admin-alt", "from_chapter": 1},
    )

    rename_resp = client.post(
        "/stories/s-branch-admin-alt/rename",
        json={"new_story_id": "s-branch-admin-shadow"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["story_id"] == "s-branch-admin-shadow"
    assert rename_resp.json()["parent_story_id"] == "s-branch-admin-root"

    list_resp = client.get("/stories")
    assert list_resp.status_code == 200
    assert {story["story_id"] for story in list_resp.json()} >= {"s-branch-admin-root", "s-branch-admin-shadow"}
    assert "s-branch-admin-alt" not in {story["story_id"] for story in list_resp.json()}

    delete_resp = client.delete("/stories/s-branch-admin-shadow")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    fetch_deleted = client.get("/stories/s-branch-admin-shadow")
    assert fetch_deleted.status_code == 404
