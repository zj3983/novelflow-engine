from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from apps.api.services.continuous_generation import ContinuousGenerationJobStore
from packages.story_core.engine import ChapterBundle
from packages.story_core.file_project_store import FileProjectStore
# The Python environment has an unrelated installed ``tests`` package;
# include this repository's tests directory so we can reuse its synthetic
# project builders without copying their setup logic.
import tests as installed_tests_package

installed_tests_package.__path__.append(str(Path(__file__).resolve().parents[1]))
from tests.api.test_story_routes import _make_file_project, _seed_generation_outline
from tests.story_core.test_candidate_confirmation_transaction import _long_body
from tests.story_core.test_opening_prose import prepared_store


class FakeEngine:
    """Provider-free engine that returns a deterministic synthetic chapter."""

    instances: list["FakeEngine"] = []

    def __init__(self, **_kwargs):
        self.calls = 0
        self.instances.append(self)

    def generate_next_chapter(self, story):
        self.calls += 1
        chapter_number = int(story.current_chapter or 0) + 1
        return ChapterBundle(
            chapter_number=chapter_number,
            chapter_title=f"合成章节{chapter_number}",
            body=_long_body(f"合成章节{chapter_number}"),
            next_outline="继续追查可验证的线索。",
            updated_story=story,
            quality_report={"ok": True},
            context_snapshot_id=f"synthetic-context-{chapter_number}",
        )


@pytest.fixture
def api(tmp_path: Path, monkeypatch):
    export_root = tmp_path / "projects"
    export_root.mkdir()
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    monkeypatch.setattr("packages.story_core.engine.StoryEngine", FakeEngine)
    monkeypatch.setattr(file_projects, "_user_facing_generation_error", lambda exc: str(exc))
    FakeEngine.instances.clear()
    file_projects._file_generation_jobs.clear()
    file_projects._active_file_generation_jobs.clear()
    file_projects._active_continuous_generation_jobs.clear()
    submitted_generation: list[tuple[object, tuple[object, ...], dict[str, object]]] = []
    submitted_continuous: list[tuple[object, tuple[object, ...], dict[str, object]]] = []

    def run_generation_inline(fn, *args, **kwargs):
        submitted_generation.append((fn, args, kwargs))
        fn(*args, **kwargs)

    monkeypatch.setattr(file_projects._file_generation_executor, "submit", run_generation_inline)
    monkeypatch.setattr(
        file_projects._continuous_generation_executor,
        "submit",
        lambda fn, *args, **kwargs: submitted_continuous.append((fn, args, kwargs)),
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client, export_root, submitted_generation, submitted_continuous
    file_projects._file_generation_jobs.clear()
    file_projects._active_file_generation_jobs.clear()
    file_projects._active_continuous_generation_jobs.clear()


def _opening_project(export_root: Path):
    setup_root = export_root / ".opening-fixture"
    setup_root.mkdir()
    prepared = prepared_store(setup_root)
    project_root = export_root / "generic_webnovel"
    prepared.root.rename(project_root)
    store = FileProjectStore(project_root)
    return store, "generic_webnovel"


def _seed_old_project(export_root: Path) -> tuple[FileProjectStore, str]:
    root = export_root / "p-standard"
    root.mkdir()
    _make_file_project(root, project_id="p-standard", state={"story_id": "s-standard", "current_chapter": 0, "world_facts": []})
    _seed_generation_outline(root, 1)
    return FileProjectStore(root), "p-standard"


def test_opening_generation_job_saves_pending_candidate_without_persisting_chapter(
    api, monkeypatch
) -> None:
    client, export_root, submitted, _continuous = api
    store, project_id = _opening_project(export_root)
    original = FileProjectStore.generate_next_chapter
    calls: list[tuple[bool, bool]] = []

    def record_generation(self, *args, **kwargs):
        calls.append((kwargs.get("persist", True), kwargs.get("accept_quality_warnings", False)))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileProjectStore, "generate_next_chapter", record_generation)

    started = client.post(f"/file-projects/{project_id}/generation-jobs", json={})

    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    completed = client.get(f"/file-projects/{project_id}/generation-jobs/{job_id}")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed", completed.json()
    assert calls == [(False, False)]
    assert len(submitted) == 1
    candidates = store.candidate_store.list(project_id=str(store.project()["project_id"]), chapter_number=1)
    assert len(candidates) == 1
    assert candidates[0].status == "pending"
    assert store.chapter_numbers() == []
    assert int(store.state().get("current_chapter") or 0) == 0
    assert store._candidate_canon_view() == {"by_id": {}, "by_kind": {}, "by_alias": {}}
    assert not (store.story_system_dir / "canon" / "registry.json").exists()
    assert "file:generic_webnovel" not in file_projects._active_file_generation_jobs


def test_existing_project_generation_job_keeps_legacy_persistence_behavior(api, monkeypatch) -> None:
    client, export_root, _submitted, _continuous = api
    store, project_id = _seed_old_project(export_root)
    original = FileProjectStore.generate_next_chapter
    calls: list[tuple[bool, bool]] = []

    def record_generation(self, *args, **kwargs):
        calls.append((kwargs.get("persist", True), kwargs.get("accept_quality_warnings", False)))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(FileProjectStore, "generate_next_chapter", record_generation)

    started = client.post(f"/file-projects/{project_id}/generation-jobs", json={})

    assert started.status_code == 200, started.text
    completed = client.get(f"/file-projects/{project_id}/generation-jobs/{started.json()['job_id']}")
    assert completed.status_code == 200, completed.text
    assert completed.json()["status"] == "completed"
    assert calls == [(True, True)]
    assert store.chapter_numbers() == [1]
    assert store.state()["current_chapter"] == 1
    assert FakeEngine.instances[-1].calls == 1


def test_opening_rejects_continuous_generation_without_creating_or_submitting_job(api) -> None:
    client, export_root, _submitted, submitted_continuous = api
    store, project_id = _opening_project(export_root)
    canon_before = store._candidate_canon_view()

    response = client.post(
        f"/file-projects/{project_id}/continuous-generation-jobs", json={"count": 2}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "opening_continuous_generation_unsupported"
    direct_generate = client.post(f"/file-projects/{project_id}/generate-next", json={})
    assert direct_generate.status_code == 409
    assert direct_generate.json()["detail"] == "opening_candidate_confirmation_required"
    assert submitted_continuous == []
    assert not (store.story_system_dir / "continuous-generation-jobs").exists()
    assert store.chapter_numbers() == []
    assert int(store.state().get("current_chapter") or 0) == 0
    assert store._candidate_canon_view() == canon_before
    assert FakeEngine.instances == []
    assert file_projects._active_continuous_generation_jobs == {}


def test_opening_safe_recovery_stops_durable_continuous_job_and_clears_active_slot(api) -> None:
    client, export_root, _submitted, submitted_continuous = api
    store, project_id = _opening_project(export_root)
    story_id = file_projects._story_id_for(store)
    jobs = ContinuousGenerationJobStore(store.root)
    job = jobs.create(
        project_id=file_projects._public_project_id(store),
        story_id=story_id,
        count=2,
        start_chapter=1,
    )
    file_projects._active_continuous_generation_jobs[story_id] = str(job["job_id"])

    response = client.get(f"/file-projects/{project_id}/continuous-generation-jobs/current")

    assert response.status_code == 200, response.text
    assert response.json()["status"] == "stopped"
    assert response.json()["stop_reason"] == "opening_continuous_generation_unsupported"
    saved = jobs.load(str(job["job_id"]))
    assert saved is not None
    assert saved["status"] == "stopped"
    assert saved["stop_reason"] == "opening_continuous_generation_unsupported"
    assert not file_projects._active_continuous_generation_jobs
    assert submitted_continuous == []
    assert FakeEngine.instances == []
    assert store.chapter_numbers() == []
    assert int(store.state().get("current_chapter") or 0) == 0


def test_opening_rewrite_and_expand_requests_do_not_change_an_accepted_chapter(api) -> None:
    client, export_root, _submitted, _continuous = api
    store, project_id = _opening_project(export_root)
    started = client.post(f"/file-projects/{project_id}/generation-jobs", json={})
    assert started.status_code == 200, started.text
    candidates = store.candidate_store.list(project_id=str(store.project()["project_id"]), chapter_number=1)
    assert candidates and candidates[-1].status == "pending", store.root
    candidate_id = candidates[-1].candidate_id
    confirmed = client.post(f"/file-projects/{project_id}/candidates/{candidate_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    assert store.chapter_numbers() == [1]
    accepted_chapter_before = store.chapter(1)
    state_before = store.state()
    canon_path = store.story_system_dir / "canon" / "registry.json"
    canon_before = canon_path.read_bytes() if canon_path.exists() else None
    submitted_before = len(_submitted)

    rewrite = client.post(
        f"/file-projects/{project_id}/generation-jobs", json={"chapter_number": 1}
    )
    expand = client.post(
        f"/file-projects/{project_id}/generation-jobs",
        json={"chapter_number": 1, "operation": "expand"},
    )
    direct_rewrite = client.post(
        f"/file-projects/{project_id}/regenerate-chapter",
        json={"chapter_number": 1},
    )

    for response in (rewrite, expand, direct_rewrite):
        assert response.status_code == 409, response.text
        assert response.json()["detail"] == "opening_prose_operation_unsupported"
    assert len(_submitted) == submitted_before
    assert store.chapter(1) == accepted_chapter_before
    assert store.state() == state_before
    assert (canon_path.read_bytes() if canon_path.exists() else None) == canon_before
    assert not file_projects._active_file_generation_jobs
