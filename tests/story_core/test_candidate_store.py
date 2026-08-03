from types import SimpleNamespace

from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.generation_progress import generation_progress
from packages.story_core.persistence.candidate_store import CandidateStore
from packages.story_core.file_project_store import FileProjectStore


def test_candidate_store_persists_and_lists_candidates(tmp_path):
    store = CandidateStore(tmp_path)
    draft = CandidateDraft.create(project_id="p-1", chapter_number=2, body="候选正文")

    saved_path = store.save(draft)

    assert saved_path.exists()
    assert store.get(draft.candidate_id) == draft
    assert [item.candidate_id for item in store.list(project_id="p-1")] == [draft.candidate_id]


def test_candidate_store_does_not_return_candidates_from_other_projects(tmp_path):
    store = CandidateStore(tmp_path)
    first = CandidateDraft.create(project_id="p-1", chapter_number=1, body="一")
    second = CandidateDraft.create(project_id="p-2", chapter_number=1, body="二")
    store.save(first)
    store.save(second)

    assert [item.project_id for item in store.list(project_id="p-1")] == ["p-1"]
    assert store.get("missing") is None


def test_saving_latest_candidate_supersedes_pending_candidate_for_same_chapter(tmp_path):
    store = CandidateStore(tmp_path)
    first = CandidateDraft.create(project_id="p-1", chapter_number=3, body="旧候选稿")
    second = CandidateDraft.create(project_id="p-1", chapter_number=3, body="新候选稿")
    store.save(first)

    store.save_latest(second)

    assert store.get(first.candidate_id).status == "superseded"
    assert store.get(second.candidate_id).status == "pending"


def test_saving_latest_candidate_does_not_supersede_other_chapters_or_projects(tmp_path):
    store = CandidateStore(tmp_path)
    other_chapter = CandidateDraft.create(project_id="p-1", chapter_number=2, body="上一章")
    other_project = CandidateDraft.create(project_id="p-2", chapter_number=3, body="另一本书")
    latest = CandidateDraft.create(project_id="p-1", chapter_number=3, body="当前候选稿")
    store.save(other_chapter)
    store.save(other_project)

    store.save_latest(latest)

    assert store.get(other_chapter.candidate_id).status == "pending"
    assert store.get(other_project.candidate_id).status == "pending"


def test_file_project_store_exposes_candidate_store_at_project_root(tmp_path):
    project_store = FileProjectStore(tmp_path)

    assert project_store.candidate_store.root == tmp_path.resolve()


def test_file_project_store_can_confirm_a_saved_candidate(tmp_path):
    project_store = FileProjectStore(tmp_path)
    draft = CandidateDraft.create(
        project_id=tmp_path.name,
        chapter_number=1,
        chapter_title="第一章",
        body="候选正文" * 1000,
        submission_payload={
            "chapter_number": 1,
            "chapter_title": "第一章",
            "body": "候选正文" * 1000,
            "updated_story": {"current_chapter": 1},
            "quality_report": {"ok": True},
        },
    )
    project_store.candidate_store.save(draft)

    confirmed = project_store.confirm_candidate(draft.candidate_id)

    assert confirmed["candidate"]["status"] == "confirmed"


def test_file_project_store_confirms_regeneration_candidate_with_original_operation(tmp_path, monkeypatch):
    project_store = FileProjectStore(tmp_path)
    draft = CandidateDraft.create(
        project_id=tmp_path.name,
        chapter_number=2,
        chapter_title="第二章",
        body="重写正文",
        operation="regenerate",
        submission_payload={"chapter_number": 2, "chapter_title": "第二章", "body": "重写正文"},
    )
    project_store.candidate_store.save(draft)
    captured = {}

    def record_persist(bundle, *, operation, commit_message=None):
        captured["operation"] = operation
        return {"chapter_number": 2, "chapter_title": "第二章"}

    monkeypatch.setattr(project_store, "persist_bundle", record_persist)

    project_store.confirm_candidate(draft.candidate_id)

    assert captured["operation"] == "regenerate"


def test_saving_candidate_emits_candidate_output_pipeline_step(tmp_path):
    project_store = FileProjectStore(tmp_path)
    events = []
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="第一章",
        body="候选正文",
        quality_report={"ok": True},
        context_snapshot_id="ctx-1",
    )

    with generation_progress(events.append):
        candidate = project_store._save_candidate_from_bundle(bundle, project_id=tmp_path.name)

    event = next(item for item in events if isinstance(item, dict) and item.get("stage") == "candidate_output")
    assert event["status"] == "done"
    assert event["artifact"]["workflow_step"]["pipeline_stage"] == "candidate_output"
    assert event["artifact"]["outputs"]["candidate_id"] == candidate.candidate_id
    assert event["artifact"]["outputs"]["status"] == "pending"
