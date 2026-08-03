import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import ForeshadowingState


client = TestClient(app)


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _create_project(tmp_path: Path, monkeypatch, project_id: str, state: dict) -> Path:
    export_root = tmp_path / "exported-projects"
    project_root = export_root / project_id
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    _write_json(
        project_root / ".story-system" / "MASTER_SETTING.json",
        {"project": {"title": project_id}},
    )
    _write_json(project_root / ".webnovel" / "project.json", {"project_id": project_id})
    _write_json(project_root / ".webnovel" / "state.json", state)
    return project_root


def test_get_foreshadowing_reads_canonical_state_ledger(tmp_path: Path, monkeypatch) -> None:
    _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-get",
        {
            "story_id": "story-get",
            "foreshadowing": [
                {
                    "text": "The sealed letter",
                    "first_chapter": 2,
                    "last_touched_chapter": 4,
                    "status": "reinforced",
                    "payoff_plan": "Open it at the tribunal.",
                    "resolved_chapter": None,
                }
            ],
        },
    )

    response = client.get("/file-projects/file:foreshadowing-get/foreshadowing")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["version"]) == 64
    assert payload["items"] == [
            {
                "text": "The sealed letter",
                "first_chapter": 2,
                "last_touched_chapter": 4,
                "status": "reinforced",
                "payoff_plan": "Open it at the tribunal.",
                "resolved_chapter": None,
            }
        ]


def test_put_foreshadowing_rejects_stale_page_version(tmp_path: Path, monkeypatch) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-version",
        {
            "story_id": "story-version",
            "foreshadowing": [
                {"text": "Original clue", "first_chapter": 1, "status": "open"}
            ],
        },
    )
    url = "/file-projects/file:foreshadowing-version/foreshadowing"
    stale_version = client.get(url).json()["version"]
    store = FileProjectStore(project_root)
    store.update_foreshadowing_ledger(
        [ForeshadowingState(text="New chapter clue", first_chapter=2)],
        expected_version=stale_version,
    )

    response = client.put(
        url,
        json={"items": [], "base_version": stale_version},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "foreshadowing_version_conflict"
    assert [item.text for item in store.foreshadowing_ledger()] == ["New chapter clue"]


def test_versionless_put_merges_instead_of_overwriting_current_threads(tmp_path: Path, monkeypatch) -> None:
    _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-legacy-merge",
        {
            "story_id": "story-legacy-merge",
            "foreshadowing": [
                {"text": "Generated clue", "first_chapter": 2, "status": "open"}
            ],
        },
    )

    response = client.put(
        "/file-projects/file:foreshadowing-legacy-merge/foreshadowing",
        json={
            "items": [
                {
                    "text": "Generated clue",
                    "first_chapter": 2,
                    "last_touched_chapter": 2,
                    "status": "expired",
                },
                {"text": "Legacy client clue", "first_chapter": 3, "status": "open"}
            ]
        },
    )

    assert response.status_code == 200
    assert [item["text"] for item in response.json()["items"]] == [
        "Generated clue",
        "Legacy client clue",
    ]
    assert response.json()["items"][0]["status"] == "open"


def test_get_foreshadowing_canonical_expired_clears_duplicate_resolution(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-get-terminal",
        {
            "story_id": "story-get-terminal",
            "foreshadowing": [
                {
                    "text": "The sealed letter",
                    "first_chapter": 1,
                    "last_touched_chapter": 2,
                    "status": "resolved",
                    "resolved_chapter": 2,
                },
                {
                    "text": "the sealed letter",
                    "first_chapter": 1,
                    "last_touched_chapter": 10,
                    "status": "expired",
                    "resolved_chapter": None,
                },
            ],
        },
    )

    response = client.get(
        "/file-projects/file:foreshadowing-get-terminal/foreshadowing"
    )

    assert response.status_code == 200
    assert response.json()["items"] == [
        {
            "text": "The sealed letter",
            "first_chapter": 1,
            "last_touched_chapter": 10,
            "status": "expired",
            "payoff_plan": "",
            "resolved_chapter": None,
        }
    ]


def test_get_foreshadowing_skips_bad_legacy_entries_and_sorts_without_visible_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-tolerant",
        {
            "story_id": "story-tolerant",
            "characters": [{"name": "Raw State Character"}],
            "foreshadowing": [
                {"text": "Later clue", "first_chapter": 8, "status": "open"},
                {"text": "missing chapter"},
                "not-an-object",
                {"text": "   ", "first_chapter": 2, "status": "open"},
                {"text": "negative chapter", "first_chapter": -1, "status": "open"},
                {
                    "text": "backward touch",
                    "first_chapter": 4,
                    "last_touched_chapter": 3,
                    "status": "open",
                },
                {
                    "text": "early resolution",
                    "first_chapter": 2,
                    "last_touched_chapter": 6,
                    "status": "resolved",
                    "resolved_chapter": 5,
                },
                {"text": "  EARLY\tClue  ", "first_chapter": 1, "status": "open"},
            ],
        },
    )
    _write_json(
        project_root / ".story-system" / "chapters" / "0001.json",
        {
            "chapter_number": 1,
            "updated_story": {
                "characters": [{"name": "Derived Character"}],
                "foreshadowing": [
                    {"text": "Derived clue", "first_chapter": 1, "status": "open"}
                ],
            },
        },
    )

    response = client.get("/file-projects/file:foreshadowing-tolerant/foreshadowing")

    assert response.status_code == 200
    assert [item["text"] for item in response.json()["items"]] == ["EARLY Clue", "Later clue"]


def test_foreshadowing_ledger_does_not_swallow_internal_type_error(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-type-error",
        {
            "story_id": "story-type-error",
            "foreshadowing": [
                {"text": "Valid persisted clue", "first_chapter": 1, "status": "open"}
            ],
        },
    )

    def fail_model_validate(value: object) -> ForeshadowingState:
        raise TypeError("internal validation bug")

    monkeypatch.setattr(
        ForeshadowingState,
        "model_validate",
        staticmethod(fail_model_validate),
    )

    with pytest.raises(TypeError, match="internal validation bug"):
        FileProjectStore(project_root).foreshadowing_ledger()


def test_put_foreshadowing_normalizes_duplicates_sorts_and_only_changes_ledger(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-put",
        {
            "story_id": "story-put",
            "current_chapter": 12,
            "characters": [{"name": "Keep Me", "role": "protagonist"}],
            "custom_legacy_data": {"nested": [1, 2, 3]},
            "foreshadowing": [{"text": "Old clue", "first_chapter": 1, "status": "open"}],
        },
    )
    state_path = project_root / ".webnovel" / "state.json"
    before = json.loads(state_path.read_text(encoding="utf-8"))
    base_version = client.get(
        "/file-projects/file:foreshadowing-put/foreshadowing"
    ).json()["version"]

    response = client.put(
        "/file-projects/file:foreshadowing-put/foreshadowing",
        json={
            "base_version": base_version,
            "items": [
                {
                    "text": "Later clue",
                    "first_chapter": 9,
                    "last_touched_chapter": 10,
                    "status": "resolved",
                    "payoff_plan": "Newest plan",
                    "resolved_chapter": 10,
                },
                {
                    "text": "  SEALED\tLetter ",
                    "first_chapter": 4,
                    "last_touched_chapter": 5,
                    "status": "open",
                    "payoff_plan": "",
                    "resolved_chapter": None,
                },
                {
                    "text": "sealed letter",
                    "first_chapter": 2,
                    "last_touched_chapter": 7,
                    "status": "reinforced",
                    "payoff_plan": "Reveal the sender.",
                    "resolved_chapter": None,
                },
            ]
        },
    )

    assert response.status_code == 200
    items = response.json()["items"]
    assert [item["text"] for item in items] == ["sealed letter", "Later clue"]
    assert items[0] == {
        "text": "sealed letter",
        "first_chapter": 2,
        "last_touched_chapter": 7,
        "status": "reinforced",
        "payoff_plan": "Reveal the sender.",
        "resolved_chapter": None,
    }
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["foreshadowing"] == items
    assert persisted["manual_foreshadowing"] == items
    assert {
        key: value
        for key, value in persisted.items()
        if key not in {"foreshadowing", "manual_foreshadowing"}
    } == {
        key: value
        for key, value in before.items()
        if key not in {"foreshadowing", "manual_foreshadowing"}
    }


def test_put_foreshadowing_canonical_resolved_covers_duplicate_last_touch(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-put-terminal",
        {"story_id": "story-put-terminal", "foreshadowing": []},
    )
    state_path = project_root / ".webnovel" / "state.json"

    response = client.put(
        "/file-projects/file:foreshadowing-put-terminal/foreshadowing",
        json={
            "items": [
                {
                    "text": "The sealed letter",
                    "first_chapter": 1,
                    "last_touched_chapter": 2,
                    "status": "resolved",
                    "resolved_chapter": 2,
                },
                {
                    "text": "the sealed letter",
                    "first_chapter": 1,
                    "last_touched_chapter": 10,
                    "status": "reinforced",
                    "resolved_chapter": None,
                },
            ]
        },
    )

    assert response.status_code == 200
    item = response.json()["items"][0]
    assert item["status"] == "resolved"
    assert item["last_touched_chapter"] == 10
    assert item["resolved_chapter"] == 10
    assert json.loads(state_path.read_text(encoding="utf-8"))["foreshadowing"] == [item]


def test_put_foreshadowing_defaults_missing_touch_to_first_chapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-default-touch",
        {"story_id": "story-default-touch", "foreshadowing": []},
    )
    state_path = project_root / ".webnovel" / "state.json"

    response = client.put(
        "/file-projects/file:foreshadowing-default-touch/foreshadowing",
        json={"items": [{"text": "Missing touch", "first_chapter": 6}]},
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["last_touched_chapter"] == 6
    persisted = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted["foreshadowing"][0]["last_touched_chapter"] == 6


def test_put_foreshadowing_accepts_expired_without_resolved_chapter(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-expired",
        {"story_id": "story-expired", "foreshadowing": []},
    )

    response = client.put(
        "/file-projects/file:foreshadowing-expired/foreshadowing",
        json={
            "items": [
                {
                    "text": "Expired clue",
                    "first_chapter": 3,
                    "last_touched_chapter": 7,
                    "status": "expired",
                    "resolved_chapter": None,
                }
            ]
        },
    )

    assert response.status_code == 200
    assert response.json()["items"][0]["resolved_chapter"] is None


@pytest.mark.parametrize(
    "item",
    [
        {"text": "clue", "first_chapter": 1, "status": "unknown"},
        {"text": "   ", "first_chapter": 1, "status": "open"},
        {"text": "clue", "first_chapter": -1, "status": "open"},
        {"text": "clue", "first_chapter": "1", "status": "open"},
        {"text": "clue", "first_chapter": 1, "last_touched_chapter": -1, "status": "open"},
        {"text": "clue", "first_chapter": 5, "last_touched_chapter": 4, "status": "open"},
        {"text": "clue", "first_chapter": 1, "status": "resolved"},
        {
            "text": "clue",
            "first_chapter": 5,
            "status": "resolved",
            "resolved_chapter": 4,
        },
        {
            "text": "clue",
            "first_chapter": 2,
            "last_touched_chapter": 6,
            "status": "resolved",
            "resolved_chapter": 5,
        },
        {
            "text": "clue",
            "first_chapter": 5,
            "status": "expired",
            "resolved_chapter": 4,
        },
        {
            "text": "clue",
            "first_chapter": 2,
            "last_touched_chapter": 6,
            "status": "expired",
            "resolved_chapter": 5,
        },
        {
            "text": "clue",
            "first_chapter": 1,
            "status": "open",
            "resolved_chapter": 2,
        },
        {"text": "clue", "first_chapter": 1, "status": "open", "unexpected": True},
    ],
)
def test_put_foreshadowing_rejects_invalid_items_without_changing_file(
    tmp_path: Path,
    monkeypatch,
    item: dict,
) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-invalid",
        {
            "story_id": "story-invalid",
            "foreshadowing": [{"text": "Original", "first_chapter": 1, "status": "open"}],
        },
    )
    state_path = project_root / ".webnovel" / "state.json"
    original_bytes = state_path.read_bytes()

    response = client.put(
        "/file-projects/file:foreshadowing-invalid/foreshadowing",
        json={"items": [item]},
    )

    assert response.status_code == 422
    assert state_path.read_bytes() == original_bytes


def test_put_foreshadowing_forbids_extra_request_fields(tmp_path: Path, monkeypatch) -> None:
    project_root = _create_project(
        tmp_path,
        monkeypatch,
        "foreshadowing-extra",
        {"story_id": "story-extra", "foreshadowing": []},
    )
    state_path = project_root / ".webnovel" / "state.json"
    original_bytes = state_path.read_bytes()

    response = client.put(
        "/file-projects/file:foreshadowing-extra/foreshadowing",
        json={"items": [], "unexpected": True},
    )

    assert response.status_code == 422
    assert state_path.read_bytes() == original_bytes


def test_foreshadowing_routes_return_404_for_unknown_project(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path / "exported-projects"))

    get_response = client.get("/file-projects/file:missing/foreshadowing")
    put_response = client.put(
        "/file-projects/file:missing/foreshadowing",
        json={"items": []},
    )

    assert get_response.status_code == 404
    assert get_response.json()["detail"] == "file_project_not_found"
    assert put_response.status_code == 404
    assert put_response.json()["detail"] == "file_project_not_found"


def test_foreshadowing_atomic_write_failure_preserves_existing_state(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_root = tmp_path / "foreshadowing-atomic"
    state_path = project_root / ".webnovel" / "state.json"
    _write_json(
        state_path,
        {
            "story_id": "story-atomic",
            "current_chapter": 3,
            "foreshadowing": [{"text": "Original", "first_chapter": 1, "status": "open"}],
        },
    )
    original_bytes = state_path.read_bytes()
    store = FileProjectStore(project_root)

    def fail_replace(source, destination):
        raise OSError("replace failed for test")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed for test"):
        store.update_foreshadowing_ledger([])

    assert state_path.read_bytes() == original_bytes
    assert list(state_path.parent.iterdir()) == [state_path]
