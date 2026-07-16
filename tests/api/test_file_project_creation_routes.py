import json
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects as file_project_routes
from apps.api.routes import stories as story_routes
from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.novel_type_library import NovelTypeLibrary
from packages.story_core.opening_directions import LLMOpeningDirectionGenerator
from packages.story_core.runtime_config import StageRuntimeSettings


@pytest.fixture
def creation_api(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "exported-projects"
    legacy_create = Mock(side_effect=AssertionError("legacy SQLite project creation called"))
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    monkeypatch.setattr(story_routes.store, "create_project", legacy_create)
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, export_root, legacy_create


def test_blank_file_project_creation_returns_201_and_is_readable(creation_api):
    client, export_root, legacy_create = creation_api

    response = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Blank Route Project", "novel_type_id": "urban"},
    )

    assert response.status_code == 201
    project = response.json()
    assert project["project_id"].startswith("file:p-")
    assert project["storage_source"] == "file"
    assert project["next_path"] == f"/projects/{quote(project['project_id'], safe='')}/outline"
    assert Path(project["source_path"]).parent == export_root
    assert client.get(f"/file-projects/{project['project_id']}").json() == {
        key: value for key, value in project.items() if key != "next_path"
    }
    legacy_create.assert_not_called()


def test_file_project_settings_update_syncs_runtime_genre_id_to_state(
    creation_api,
    monkeypatch,
    tmp_path,
):
    client, _, _ = creation_api
    monkeypatch.setenv(
        "NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH",
        str(tmp_path / "settings-novel-types.json"),
    )
    NovelTypeLibrary().create(
        {
            "id": "sports",
            "name": "竞技体育",
            "core_promises": ["设置页竞技承诺"],
            "rulebook": {"chapter_formula": ["设置页竞技规则"]},
        }
    )
    created = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Settings Type Switch", "novel_type_id": "xuanhuan"},
    ).json()
    store = FileProjectStore(Path(created["source_path"]))
    state_path = store.webnovel_dir / "state.json"
    initial_state = store.state()
    initial_state["world_facts"] = [
        "保留事实：联赛周末开场。",
        "  小说类型：东方玄幻",
        "小说类型:xianxia",
        "小说类型：角色口中的分类并不可靠",
    ]
    state_path.write_text(json.dumps(initial_state, ensure_ascii=False), encoding="utf-8")

    response = client.put(
        f"/file-projects/{created['project_id']}",
        json={"world_blueprint": {"genre_plugin_ids": [" SPORTS "]}},
    )

    assert response.status_code == 200
    project = store.project()
    state = store.state()
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(state, project, 1)
    )
    seed = build_chapter_seed(story, 1)
    assert project["world_blueprint"]["genre_plugin_ids"] == ["sports"]
    assert state["genre_plugin_ids"] == ["sports"]
    assert state["world_facts"] == [
        "保留事实：联赛周末开场。",
        "小说类型：角色口中的分类并不可靠",
        "小说类型：sports",
    ]
    assert seed["genre_plugins"] == ["generic_webnovel", "sports"]
    assert "设置页竞技承诺" in seed["core_promises"]
    assert "设置页竞技规则" in seed["rulebook"]["chapter_formula"]

    cleared = client.put(
        f"/file-projects/{created['project_id']}",
        json={"world_blueprint": {"genre_plugin_ids": []}},
    )
    assert cleared.status_code == 200
    cleared_project = store.project()
    cleared_state = store.state()
    cleared_story = StoryState.model_validate(
        store._story_state_payload_for_direction(cleared_state, cleared_project, 1)
    )
    cleared_seed = build_chapter_seed(cleared_story, 1)
    assert cleared_state["genre_plugin_ids"] == []
    assert cleared_state["world_facts"] == [
        "保留事实：联赛周末开场。",
        "小说类型：角色口中的分类并不可靠",
    ]
    assert cleared_seed["genre_plugins"] == ["generic_webnovel"]
    assert "xuanhuan" not in cleared_seed["genre_plugins"]
    assert "eastern_fantasy" not in cleared_seed["genre_plugins"]


@pytest.mark.parametrize(
    "genre_plugin_ids",
    [["unknown-runtime-type"], ["xuanhuan", "unknown-runtime-type"]],
)
def test_file_project_settings_reject_invalid_genre_ids_atomically(
    creation_api,
    genre_plugin_ids,
):
    client, _, _ = creation_api
    created = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Atomic Settings", "novel_type_id": "xuanhuan"},
    ).json()
    store = FileProjectStore(Path(created["source_path"]))
    project_path = store.webnovel_dir / "project.json"
    state_path = store.webnovel_dir / "state.json"
    before = (project_path.read_bytes(), state_path.read_bytes())

    response = client.put(
        f"/file-projects/{created['project_id']}",
        json={
            "title": "Must Not Persist",
            "world_blueprint": {"genre_plugin_ids": genre_plugin_ids},
        },
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid_novel_type"
    assert (project_path.read_bytes(), state_path.read_bytes()) == before


def test_file_project_list_ignores_in_progress_dot_directories(creation_api):
    client, _, _ = creation_api
    response = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Hidden Temp", "novel_type_id": "urban"},
    )
    assert response.status_code == 201

    root = Path(response.json()["source_path"])
    root.rename(root.with_name(f".{root.name}.tmp-in-progress"))

    assert client.get("/file-projects").json() == []


def test_inspiration_file_project_creation_returns_setup_path_and_opening_brief(creation_api):
    client, _, legacy_create = creation_api

    response = client.post(
        "/file-projects",
        json={
            "mode": "inspiration",
            "novel_type_id": "xianxia",
            "idea": "A courier discovers every sealed letter predicts tomorrow.",
        },
    )

    assert response.status_code == 201
    project = response.json()
    assert project["project_id"].startswith("file:p-")
    assert project["storage_source"] == "file"
    assert project["next_path"] == f"/projects/{quote(project['project_id'], safe='')}/setup"
    opening_brief = json.loads(
        (Path(project["source_path"]) / ".webnovel" / "opening_brief.json").read_text(encoding="utf-8")
    )
    assert opening_brief["idea"] == "A courier discovers every sealed letter predicts tomorrow."
    assert opening_brief["novel_type_id"] == "xianxia"
    legacy_create.assert_not_called()


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "blank", "title": "", "novel_type_id": "urban"},
        {"mode": "inspiration", "novel_type_id": "urban", "idea": ""},
        {"mode": "blank", "title": "Unknown Type", "novel_type_id": "not-a-type"},
    ],
)
def test_invalid_file_project_creation_returns_422_without_leaving_a_project(creation_api, payload):
    client, export_root, legacy_create = creation_api

    response = client.post("/file-projects", json=payload)

    assert response.status_code == 422
    assert not export_root.exists() or list(export_root.iterdir()) == []
    legacy_create.assert_not_called()


def test_file_project_creation_rejects_extra_fields(creation_api):
    client, export_root, legacy_create = creation_api

    response = client.post(
        "/file-projects",
        json={
            "mode": "blank",
            "title": "Strict Contract",
            "novel_type_id": "urban",
            "source_path": "ignored-by-contract",
        },
    )

    assert response.status_code == 422
    assert not export_root.exists() or list(export_root.iterdir()) == []
    legacy_create.assert_not_called()


def test_file_project_creation_maps_file_conflict_to_422(creation_api, monkeypatch):
    client, export_root, legacy_create = creation_api

    def raise_conflict(*args, **kwargs):
        raise FileExistsError("project_id_conflict")

    monkeypatch.setattr(file_project_routes, "create_file_project", raise_conflict, raising=False)
    response = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Conflict", "novel_type_id": "urban"},
    )

    assert response.status_code == 422
    assert response.json()["detail"] == "project_id_conflict"
    assert not export_root.exists() or list(export_root.iterdir()) == []
    legacy_create.assert_not_called()


def test_file_project_creation_leaves_unexpected_disk_errors_as_500(creation_api, monkeypatch):
    client, export_root, legacy_create = creation_api

    def raise_disk_error(*args, **kwargs):
        raise OSError("disk unavailable")

    monkeypatch.setattr(file_project_routes, "create_file_project", raise_disk_error, raising=False)
    response = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "Disk Failure", "novel_type_id": "urban"},
    )

    assert response.status_code == 500
    assert not export_root.exists() or list(export_root.iterdir()) == []
    assert client.get("/file-projects").json() == []
    legacy_create.assert_not_called()


def _opening_direction(direction_id: str, title: str) -> dict[str, str]:
    return {
        "id": direction_id,
        "title": title,
        "hook": f"Hook {direction_id}",
        "protagonist_goal": f"Goal {direction_id}",
        "main_conflict": f"Conflict {direction_id}",
        "growth_path": f"Growth {direction_id}",
        "opening_promise": f"Promise {direction_id}",
    }


def _opening_direction_payload() -> dict:
    return {
        "schema_version": "opening-directions/v1",
        "directions": [
            _opening_direction("direction-1", "First direction"),
            _opening_direction("direction-2", "Second direction"),
            _opening_direction("direction-3", "Third direction"),
        ],
        "selected_id": "",
    }


class _FakeOpeningDirectionGenerator:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else _opening_direction_payload()
        self.calls = 0
        self.guidance_calls = []

    def generate(self, brief, *, guidance=""):
        self.calls += 1
        self.guidance_calls.append(guidance)
        return self.payload


def _create_inspiration_project(client) -> tuple[dict, Path]:
    response = client.post(
        "/file-projects",
        json={
            "mode": "inspiration",
            "novel_type_id": "urban",
            "idea": "A night-shift courier receives tomorrow's missing-person report.",
            "title": "Working title",
        },
    )
    assert response.status_code == 201
    project = response.json()
    return project, Path(project["source_path"])


def _file_snapshot(root: Path) -> dict[str, bytes]:
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_get_opening_directions_has_no_generation_or_file_side_effects(creation_api, monkeypatch):
    client, _, _ = creation_api
    project, root = _create_inspiration_project(client)
    generator = _FakeOpeningDirectionGenerator()
    monkeypatch.setattr(file_project_routes, "opening_direction_generator", generator)
    before = _file_snapshot(root)

    response = client.get(f"/file-projects/{project['project_id']}/opening-directions")

    assert response.status_code == 200
    assert response.json()["brief"]["idea"].startswith("A night-shift courier")
    assert response.json()["directions"] == []
    assert response.json()["selected_id"] == ""
    assert response.json()["pipeline_stage"] == "idea_pending"
    assert response.json()["next_path"].endswith("/setup")
    assert generator.calls == 0
    assert _file_snapshot(root) == before


def test_generate_and_select_direction_only_updates_allowed_fields(creation_api, monkeypatch):
    client, _, _ = creation_api
    project_response, root = _create_inspiration_project(client)
    project_path = root / ".webnovel" / "project.json"
    outline_path = root / ".webnovel" / "outline.json"
    state_path = root / ".webnovel" / "state.json"
    master_path = root / ".story-system" / "MASTER_SETTING.json"
    original_project = json.loads(project_path.read_text(encoding="utf-8"))
    original_state = state_path.read_bytes()
    original_master = master_path.read_bytes()
    monkeypatch.setattr(
        file_project_routes,
        "opening_direction_generator",
        _FakeOpeningDirectionGenerator(),
    )

    generated = client.post(f"/file-projects/{project_response['project_id']}/opening-directions")

    assert generated.status_code == 200
    assert len(generated.json()["directions"]) == 3
    generated_project = json.loads(project_path.read_text(encoding="utf-8"))
    assert generated_project == {**original_project, "pipeline_stage": "direction_ready"}

    selected = client.post(
        f"/file-projects/{project_response['project_id']}/opening-directions/direction-2/select"
    )

    assert selected.status_code == 200
    assert selected.json()["selected_id"] == "direction-2"
    assert selected.json()["next_path"].endswith("/outline")
    persisted_project = json.loads(project_path.read_text(encoding="utf-8"))
    assert persisted_project == {
        **original_project,
        "title": "Second direction",
        "pipeline_stage": "outlining",
    }
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    assert outline == {
        "schema_version": "project-outline/v1",
        "overall": {
            "story": "Hook direction-2",
            "protagonist_goal": "Goal direction-2",
            "main_conflict": "Conflict direction-2",
            "growth_path": "Growth direction-2",
            "ending_direction": "Promise direction-2",
        },
        "arcs": [],
        "chapters": [],
    }
    directions = json.loads(
        (root / ".webnovel" / "opening_directions.json").read_text(encoding="utf-8")
    )
    assert directions["selected_id"] == "direction-2"
    assert persisted_project["world_summary"] == ""
    assert persisted_project["character_profiles"] == []
    assert state_path.read_bytes() == original_state
    assert master_path.read_bytes() == original_master
    persisted_state = json.loads(state_path.read_text(encoding="utf-8"))
    assert persisted_state["characters"] == []
    assert persisted_state["world_facts"] == []


def test_generate_opening_directions_accepts_trimmed_one_time_guidance(
    creation_api, monkeypatch
):
    client, _, _ = creation_api
    project, root = _create_inspiration_project(client)
    generator = _FakeOpeningDirectionGenerator()
    monkeypatch.setattr(file_project_routes, "opening_direction_generator", generator)
    secret = "ONLY_FOR_THIS_REQUEST"
    secret_bytes = secret.encode("utf-8")
    files_before = {path for path in root.rglob("*") if path.is_file()}
    assert all(secret_bytes not in path.read_bytes() for path in files_before)

    response = client.post(
        f"/file-projects/{project['project_id']}/opening-directions",
        json={"guidance": f"  {secret}  "},
    )

    assert response.status_code == 200
    assert generator.guidance_calls == [secret]
    files_after = {path for path in root.rglob("*") if path.is_file()}
    assert root / ".webnovel" / "opening_directions.json" in files_after - files_before
    assert all(secret_bytes not in path.read_bytes() for path in files_after)


def test_generate_opening_directions_without_body_uses_empty_guidance(creation_api, monkeypatch):
    client, _, _ = creation_api
    project, _ = _create_inspiration_project(client)
    generator = _FakeOpeningDirectionGenerator()
    monkeypatch.setattr(file_project_routes, "opening_direction_generator", generator)

    response = client.post(f"/file-projects/{project['project_id']}/opening-directions")

    assert response.status_code == 200
    assert generator.guidance_calls == [""]


def test_generate_file_project_plan_passes_mode_and_trimmed_guidance(creation_api, monkeypatch):
    client, _, _ = creation_api
    project = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "断香炉", "novel_type_id": "xuanhuan"},
    ).json()
    calls = []

    def fake_generate(store, generator, *, mode, guidance):
        calls.append((generator, mode, guidance))
        return {
            "schema_version": "generated-outline-plan/v1",
            "mode": mode,
            "outline": {"chapters": [{"chapter_number": 1}]},
            "characters": [{"name": "林照", "character_tier": "protagonist"}],
            "source": "generated",
        }

    monkeypatch.setattr(file_project_routes.FileProjectStore, "generate_outline_plan", fake_generate)

    response = client.post(
        f"/file-projects/{project['project_id']}/outline/generate",
        json={"mode": "regenerate", "guidance": "  阶段对手要有现实利益  "},
    )

    assert response.status_code == 200
    assert response.json()["outline"]["chapters"][0]["chapter_number"] == 1
    assert calls[0][1:] == ("regenerate", "阶段对手要有现实利益")


@pytest.mark.parametrize(
    "payload",
    [
        {"mode": "unknown", "guidance": ""},
        {"mode": "initial", "guidance": "x" * 1001},
        {"mode": "initial", "unexpected": True},
    ],
)
def test_generate_file_project_plan_rejects_invalid_request(creation_api, payload):
    client, _, _ = creation_api
    project = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "断香炉", "novel_type_id": "xuanhuan"},
    ).json()

    response = client.post(f"/file-projects/{project['project_id']}/outline/generate", json=payload)

    assert response.status_code == 422


def test_generate_file_project_plan_maps_model_failure_to_502(creation_api, monkeypatch):
    client, _, _ = creation_api
    project = client.post(
        "/file-projects",
        json={"mode": "blank", "title": "断香炉", "novel_type_id": "xuanhuan"},
    ).json()

    def fail_generation(store, generator, *, mode, guidance):
        raise ValueError("outline_planning_generation_failed")

    monkeypatch.setattr(file_project_routes.FileProjectStore, "generate_outline_plan", fail_generation)

    response = client.post(
        f"/file-projects/{project['project_id']}/outline/generate",
        json={"mode": "initial", "guidance": ""},
    )

    assert response.status_code == 502
    assert response.json()["detail"] == "outline_planning_generation_failed"


@pytest.mark.parametrize(
    "payload",
    [
        {"guidance": "x" * 1001},
        {"guidance": "valid", "unexpected": "field"},
        {"guidance": 123},
        {"guidance": None},
    ],
)
def test_generate_opening_directions_rejects_invalid_guidance_request(
    creation_api, monkeypatch, payload
):
    client, _, _ = creation_api
    project, _ = _create_inspiration_project(client)
    generator = _FakeOpeningDirectionGenerator()
    monkeypatch.setattr(file_project_routes, "opening_direction_generator", generator)

    response = client.post(
        f"/file-projects/{project['project_id']}/opening-directions",
        json=payload,
    )

    assert response.status_code == 422
    assert generator.calls == 0


def test_invalid_model_output_returns_502_and_preserves_previous_candidates(creation_api, monkeypatch):
    client, _, _ = creation_api
    project, root = _create_inspiration_project(client)
    monkeypatch.setattr(
        file_project_routes,
        "opening_direction_generator",
        _FakeOpeningDirectionGenerator(),
    )
    first = client.post(f"/file-projects/{project['project_id']}/opening-directions")
    assert first.status_code == 200
    directions_path = root / ".webnovel" / "opening_directions.json"
    project_path = root / ".webnovel" / "project.json"
    before = (directions_path.read_bytes(), project_path.read_bytes())
    monkeypatch.setattr(
        file_project_routes,
        "opening_direction_generator",
        _FakeOpeningDirectionGenerator({"directions": [_opening_direction("only", "Only one")]}),
    )

    response = client.post(f"/file-projects/{project['project_id']}/opening-directions")

    assert response.status_code == 502
    assert response.json()["detail"] == "opening_direction_generation_failed"
    assert (directions_path.read_bytes(), project_path.read_bytes()) == before


@pytest.mark.parametrize("brief_problem", ["missing", "corrupt", "invalid_novel_type"])
def test_invalid_local_opening_brief_returns_422_without_calling_model(
    creation_api,
    monkeypatch,
    brief_problem,
):
    client, _, _ = creation_api
    project, root = _create_inspiration_project(client)
    brief_path = root / ".webnovel" / "opening_brief.json"
    if brief_problem == "missing":
        brief_path.unlink()
    elif brief_problem == "corrupt":
        brief_path.write_text("{not-json", encoding="utf-8")
    else:
        brief = json.loads(brief_path.read_text(encoding="utf-8"))
        brief["novel_type_id"] = "unknown-type"
        brief_path.write_text(json.dumps(brief), encoding="utf-8")

    calls = {"runtime": 0, "post": 0}

    def forbidden_runtime(name):
        calls["runtime"] += 1
        raise AssertionError("runtime must not be resolved for invalid local opening data")

    def forbidden_post(*args, **kwargs):
        calls["post"] += 1
        raise AssertionError("model must not be called for invalid local opening data")

    monkeypatch.setattr(
        file_project_routes,
        "opening_direction_generator",
        LLMOpeningDirectionGenerator(
            post_json=forbidden_post,
            runtime_resolver=forbidden_runtime,
        ),
    )

    response = client.post(f"/file-projects/{project['project_id']}/opening-directions")

    assert response.status_code == 422
    if brief_problem == "invalid_novel_type":
        assert response.json()["detail"] == "invalid_novel_type"
    assert calls == {"runtime": 0, "post": 0}


@pytest.mark.parametrize(
    ("failure_kind", "expected_post_calls"),
    [("runtime", 0), ("http", 1), ("empty_output", 1)],
)
def test_generation_failures_remain_502_with_stable_detail(
    creation_api, monkeypatch, failure_kind, expected_post_calls
):
    client, _, _ = creation_api
    project, _ = _create_inspiration_project(client)
    runtime = StageRuntimeSettings(
        provider="openai" if failure_kind == "runtime" else "codexcli",
        model="direction-test-model",
        api_key="" if failure_kind == "runtime" else "test-key",
        codex_command="codex-test",
    )
    post_calls = []

    def fake_post(*args, **kwargs):
        post_calls.append((args, kwargs))
        if failure_kind == "http":
            raise OSError("model unavailable")
        if failure_kind == "empty_output":
            return {"choices": [{"message": {"content": ""}}]}
        raise AssertionError("missing runtime must not call the model")

    monkeypatch.setattr(
        file_project_routes,
        "opening_direction_generator",
        LLMOpeningDirectionGenerator(
            post_json=fake_post,
            runtime_resolver=lambda name: runtime,
        ),
    )

    response = client.post(f"/file-projects/{project['project_id']}/opening-directions")

    assert response.status_code == 502
    assert response.json()["detail"] == "opening_direction_generation_failed"
    assert len(post_calls) == expected_post_calls


def test_select_unknown_and_repeated_direction_returns_404_then_409(creation_api, monkeypatch):
    client, _, _ = creation_api
    project, _ = _create_inspiration_project(client)
    monkeypatch.setattr(
        file_project_routes,
        "opening_direction_generator",
        _FakeOpeningDirectionGenerator(),
    )
    assert client.post(f"/file-projects/{project['project_id']}/opening-directions").status_code == 200

    unknown = client.post(
        f"/file-projects/{project['project_id']}/opening-directions/missing/select"
    )
    selected = client.post(
        f"/file-projects/{project['project_id']}/opening-directions/direction-1/select"
    )
    repeated = client.post(
        f"/file-projects/{project['project_id']}/opening-directions/direction-1/select"
    )

    assert unknown.status_code == 404
    assert unknown.json()["detail"] == "direction_not_found"
    assert selected.status_code == 200
    assert repeated.status_code == 409
    assert repeated.json()["detail"] == "direction_already_selected"


def test_selected_opening_direction_cannot_be_regenerated(creation_api, monkeypatch):
    client, _, _ = creation_api
    project, root = _create_inspiration_project(client)
    generator = _FakeOpeningDirectionGenerator()
    monkeypatch.setattr(file_project_routes, "opening_direction_generator", generator)

    assert client.post(f"/file-projects/{project['project_id']}/opening-directions").status_code == 200
    assert client.post(
        f"/file-projects/{project['project_id']}/opening-directions/direction-1/select"
    ).status_code == 200
    tracked = {
        path: path.read_bytes()
        for path in (
            root / ".webnovel" / "project.json",
            root / ".webnovel" / "outline.json",
            root / ".webnovel" / "opening_directions.json",
        )
    }

    response = client.post(f"/file-projects/{project['project_id']}/opening-directions")

    assert response.status_code == 422
    assert response.json()["detail"] == "direction_already_selected"
    assert {path: path.read_bytes() for path in tracked} == tracked
