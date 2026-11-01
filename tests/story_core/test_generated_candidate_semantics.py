"""Real extraction and confirmation around the generated-candidate review."""

import json
from types import SimpleNamespace

import pytest

from packages.story_core.agents.pipeline import run_modular_pipeline
from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.model_gateway.preflight import ModelPreflightBlockedError
from packages.story_core.modular_bundle_adapter import adapt_modular_bundle_to_legacy


@pytest.mark.parametrize("sentence,verdict", [
    ("林照没有获得铜钱。", "unsupported"),
    ("林照打算获得铜钱。", "unsupported"),
    ("林照梦见获得铜钱。", "unsupported"),
    ("林照没有到达码头。", "unsupported"),
    ("林照获得铜钱。", "uncertain"),
])
@pytest.mark.parametrize("accept_quality_warnings", [False, True])
def test_generated_unsupported_delta_stays_pending(tmp_path, sentence, verdict, accept_quality_warnings):
    store, candidate, review, before = generate_candidate(tmp_path, sentence, verdict=verdict)

    with pytest.raises(ValueError, match=f"generate_quality_failed:candidate.semantic_{verdict}"):
        store.confirm_candidate(candidate.candidate_id, accept_quality_warnings=accept_quality_warnings)

    assert_unconfirmed(store, candidate, before)
    assert len(review.calls) == 1
    assert "## 拟提交变更" in review.calls[0].prompt
    assert candidate.quality_report["candidate_semantic_review"]["status"] == "completed"
    assert candidate.quality_report["candidate_semantic_review"]["decisions"][0]["verdict"] == verdict


@pytest.mark.parametrize("failure", ["missing", "duplicate", "wrong_review", "wrong_id", "malformed_issues", "unavailable"])
@pytest.mark.parametrize("accept_quality_warnings", [False, True])
def test_generated_unverified_delta_preserves_body_and_blocks_confirm(tmp_path, failure, accept_quality_warnings):
    store, candidate, review, before = generate_candidate(tmp_path, "林照获得铜钱。", failure=failure)

    with pytest.raises(ValueError, match="candidate_review_required|candidate_blocking_consistency"):
        store.confirm_candidate(candidate.candidate_id, accept_quality_warnings=accept_quality_warnings)

    assert_unconfirmed(store, candidate, before)
    assert len(review.calls) == 1
    assert candidate.review_binding["state"] == "unchecked"
    assert candidate.quality_report["candidate_semantic_review"]["status"] == "unavailable"
    assert any(f["code"] == "candidate.semantic_unverified"
               for f in candidate.quality_report["writing_review"]["blocking"])
    with pytest.raises(ValueError, match="generate_quality_failed:candidate.semantic_unverified"):
        store.persist_bundle(candidate.submission_payload, operation="generate", accept_quality_warnings=True)
    assert_unconfirmed(store, candidate, before)


@pytest.mark.parametrize("sentence", ["林照获得铜钱。", "林照到达码头。"])
def test_generated_supported_delta_commits_once(tmp_path, sentence):
    store, candidate, review, before = generate_candidate(tmp_path, sentence)
    result = store.confirm_candidate(candidate.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    assert len(review.calls) == 1
    assert "## 拟提交变更" in review.calls[0].prompt
    entity = store._load_canon_registry().get("char-linzhao")
    if "铜钱" in sentence:
        assert entity.extensions["inventory"]["铜钱"]["quantity"] == 1
    else:
        assert entity.extensions["location"] == "码头"
    assert store.candidate_store.get(candidate.candidate_id).status == "confirmed"
    assert store.chapter_numbers() == [1]


@pytest.mark.parametrize("failure", ["blocked", "split"])
def test_semantic_preflight_rejection_creates_no_candidate(tmp_path, failure):
    with pytest.raises(ModelPreflightBlockedError) as error:
        generate_candidate(tmp_path, "林照获得铜钱。", failure=failure)
    assert error.value.report["status"] == failure.upper()
    store = FileProjectStore(tmp_path)
    assert store.candidate_store.list() == []
    assert store.chapter_numbers() == []
    assert store._load_canon_registry().get("char-linzhao").extensions == {}


def generate_candidate(root, sentence, *, verdict="supported", failure=None):
    story = StoryState(story_id="synthetic-review", outline="等雨停", genre="玄幻", style="朴素",
                       current_chapter=0, characters=[{"name": "林照", "role": "protagonist"}])
    for name, payload in {
        "project": {"project_id": "synthetic-review", "title": "合成复核",
                    "character_profiles": [{"name": "林照", "role": "protagonist"}], "enabled_skill_ids": []},
        "state": story.model_dump(mode="json"),
    }.items():
        path = root / ".webnovel" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    registry = CanonRegistry()
    registry.add(kind="character", name="林照", entity_id="char-linzhao", lifecycle="active")
    store = FileProjectStore(root)
    store._save_canon_registry(registry)
    before = {path: path.read_bytes() for path in root.rglob("*.json")}
    body = sentence + "\n" + "\n".join(
        f"雨点落在窗沿，林照望着檐下第{index}道水痕，静静听着风穿过门缝。" for index in range(115))
    review = SemanticReview(verdict, failure)
    modular = run_modular_pipeline(project_root=root, chapter_number=1, canon_registry=registry,
        director_runtime=Director(), writer_runtime=Writer(body), consistency_runtime=review)
    bundle = adapt_modular_bundle_to_legacy(story=story, modular_bundle=modular, chapter_number=1)
    candidate = store._save_candidate_from_bundle(bundle, project_id="synthetic-review",
                                                bind_review=True, emit_progress=False)
    assert candidate.body == body
    assert candidate.continuity_delta.inventory_changes or candidate.continuity_delta.location_movements
    return store, candidate, review, before


def assert_unconfirmed(store, candidate, before):
    assert store.candidate_store.get(candidate.candidate_id).status == "pending"
    assert store.candidate_store.get(candidate.candidate_id).body == candidate.body
    assert store.chapter_numbers() == []
    assert store.persisted_state()["current_chapter"] == 0
    assert store._load_canon_registry().get("char-linzhao").extensions == {}
    assert not store.continuity_store.read_snapshot(1)
    for path, content in before.items():
        assert path.read_bytes() == content


class Director:
    def complete(self, request):
        return {"chapter_number": 1, "chapter_title": "窗前", "chapter_goal": "等雨停",
                "opening_state": "屋内", "ending_state": "屋内",
                "scene_beats": [{"order": 1, "location": "屋内", "action": "望雨", "result": "窗沿有雨"},
                                {"order": 2, "location": "屋内", "action": "静候", "result": "仍在等雨停"}],
                "entity_requirements": [{"kind": "character", "name": "林照"}]}


class Writer:
    def __init__(self, body):
        self.body = body

    def complete(self, request):
        return SimpleNamespace(text=self.body, raw={})


class SemanticReview:
    def __init__(self, verdict, failure):
        self.verdict, self.failure, self.calls = verdict, failure, []

    def complete(self, request):
        self.calls.append(request)
        if self.failure in {"blocked", "split"}:
            return SimpleNamespace(ok=False, preflight_report={
                "schema_version": "model-preflight/v1", "status": self.failure.upper(),
                "reason": "required_capability_unsupported"})
        if self.failure == "unavailable":
            raise RuntimeError("synthetic unavailable review")
        if "## 拟提交变更\n" not in request.prompt:
            return {"issues": []}
        proposals = json.loads(request.prompt.split("## 拟提交变更\n", 1)[1])
        payload = {"review_id": request.metadata["review_id"], "issues": [], "decisions": [
            {"change_id": item["change_id"], "verdict": self.verdict,
             "reason_code": "actual_event" if self.verdict == "supported" else "unproven"} for item in proposals]}
        if self.failure == "missing":
            payload.pop("decisions")
        elif self.failure == "duplicate":
            payload["decisions"] *= 2
        elif self.failure == "wrong_review":
            payload["review_id"] = "another-review"
        elif self.failure == "wrong_id":
            payload["decisions"][0]["change_id"] = "inventory_changes:999"
        elif self.failure == "malformed_issues":
            payload["issues"] = [{}]
        return payload
