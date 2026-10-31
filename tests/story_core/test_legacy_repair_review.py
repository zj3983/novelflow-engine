"""Issue #48 legacy repair tests use disposable projects and fixed responses."""

from copy import deepcopy
import json

import pytest

from packages.story_core.agents import pipeline
from packages.story_core.candidate_editing import candidate_authority, recheck
from tests.story_core.test_file_project_store import _make_minimal_file_project


class PatchWriter:
    def _timed_chat(self, story, prompt, **kwargs):
        return json.dumps({"edits": [{"before": "林照拿到铜钥匙。", "after": "林照接过铜钥匙。",
                                      "reason": "动作结果与本章安排一致"}]}), ""


class UnavailableReview:
    def complete(self, request):
        raise RuntimeError("synthetic review unavailable")


class PassingReview:
    def complete(self, request):
        if request.metadata.get("operation") == "candidate_delta_semantics":
            proposals = json.loads(request.prompt.split("## 拟提交变更\n", 1)[1])
            return {"issues": [], "review_id": request.metadata["review_id"], "decisions": [
                {"change_id": p["change_id"], "verdict": "supported", "reason_code": "actual_event"} for p in proposals]}
        return {"issues": []}


class SemanticReview:
    def __init__(self, verdict="supported"):
        self.verdict = verdict
        self.calls = 0

    def complete(self, request):
        self.calls += 1
        if request.metadata.get("operation") != "candidate_delta_semantics":
            return {"issues": []}
        proposals = json.loads(request.prompt.split("## 拟提交变更\n", 1)[1])
        return {"review_id": request.metadata["review_id"], "issues": [],
                "decisions": [{"change_id": p["change_id"], "verdict": self.verdict,
                               "reason": "引文是对取得钥匙的否定。"} for p in proposals]}


class NegatedGainExtractor:
    def extract(self, context):
        from packages.story_core.continuity.delta import ContinuityDelta, InventoryChange
        return ContinuityDelta(chapter_number=context.chapter_number, inventory_changes=[
            InventoryChange(chapter_number=context.chapter_number, source_sentence="林照没有拿到铜钥匙。",
                            entity_id="char-lin", item="铜钥匙", delta=1),
        ])


def legacy_store(tmp_path):
    store = _make_minimal_file_project(tmp_path / "legacy", state={"current_chapter": 1})
    body = "门外没有动静。" * 500 + "\n林照拿到铜钥匙。\n他关好门。"
    store.write_chapter(chapter_number=1, title="旧锁", body=body, summary="旧事件标记：钥匙已经取得。")
    path = store.story_system_dir / "chapters" / "0001.json"
    payload = store._read_json(path)
    payload["chapter_summary"] = {"chapter_number": 1, "summary": "旧事件标记：钥匙已经取得。",
                                  "facts": ["旧事件标记：钥匙已经取得。"]}
    payload["updated_story"] = {**store.state(), "world_facts": ["旧事件标记：钥匙已经取得。"]}
    store._write_json(path, payload)
    return store


def confirmed_files(store):
    return {str(p.relative_to(store.root)): p.read_bytes() for folder in
            (store.webnovel_dir, store.chapters_dir, store.story_system_dir / "chapters", store.story_system_dir / "canon")
            if folder.exists() for p in folder.rglob("*") if p.is_file()}


def test_repair_preserves_specific_preflight_failure_without_writing(tmp_path):
    from types import SimpleNamespace
    from packages.story_core.model_gateway.preflight import ModelPreflightBlockedError
    from packages.story_core.simplified_review import user_facing_generation_error

    store = legacy_store(tmp_path)
    before = confirmed_files(store)
    class BlockedWriter:
        _last_model_response = SimpleNamespace(preflight_report={
            "status": "BLOCKED", "reason": "required_input_over_limit",
            "estimates": {"required_input_tokens": 50914, "reserved_output_tokens": 6200,
                          "safety_margin_tokens": 7638},
            "effective_preflight_guards": {"input_guard": 32768, "context_guard": 32768},
        })
        def _timed_chat(self, story, prompt, **kwargs):
            return "", "model_preflight_blocked"

    with pytest.raises(ModelPreflightBlockedError) as caught:
        store.repair_chapter_review(1, orchestrator=BlockedWriter())
    message = user_facing_generation_error(caught.value)
    assert "50914" in message and "32768" in message
    assert "未调用模型" in message and "原稿和已有候选稿未改动" in message
    assert confirmed_files(store) == before
    assert not store.candidate_store.list()


def test_oversized_review_patch_gets_one_budgeted_retry(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)
    before = confirmed_files(store)
    prompts = []

    class OversizedThenLocal(PatchWriter):
        def _timed_chat(self, story, prompt, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 1:
                return json.dumps({"edits": [{"before": "门外没有动静。" * 200,
                    "after": "门外安静。", "reason": "局部表达"}]}), ""
            return super()._timed_chat(story, prompt, **kwargs)

    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    result = store.repair_chapter_review(1, orchestrator=OversizedThenLocal())
    assert len(prompts) == 2
    assert "review_repair_scope_exceeded" in prompts[1]
    assert str(int(max(600, len(store.chapter(1)["body"]) * 0.4))) in prompts[1]
    assert "林照接过铜钥匙。" in result["candidate"]["body"]
    assert confirmed_files(store) == before


@pytest.mark.parametrize(("before_text", "after_text", "expected", "calls"), [
    ("门外没有动静。" * 200, "修正。", "review_repair_scope_exceeded", 2),
    ("原稿中不存在的句子。", "修正。", "review_repair_original_not_found", 1),
    ("林照拿到铜钥匙。", "林照拿到铜钥匙。", "review_repair_no_change", 2),
    ("林照拿到铜钥匙。", "", "review_repair_no_change", 2),
])
def test_failed_review_patch_never_saves_or_retries_indefinitely(tmp_path, before_text, after_text, expected, calls):
    store = legacy_store(tmp_path)
    before = confirmed_files(store)
    candidates_before = list(store.candidate_store.list())
    prompts = []

    class InvalidPatch:
        def _timed_chat(self, story, prompt, **kwargs):
            prompts.append(prompt)
            return json.dumps({"edits": [{"before": before_text, "after": after_text}]}), ""

    with pytest.raises(ValueError, match=expected):
        store.repair_chapter_review(1, orchestrator=InvalidPatch())
    assert len(prompts) == calls
    assert confirmed_files(store) == before
    assert list(store.candidate_store.list()) == candidates_before


def test_legacy_patch_drops_old_facts_and_requires_factual_recheck(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)
    before = confirmed_files(store)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    result = store.repair_chapter_review(1, orchestrator=PatchWriter())
    candidate = store.candidate_store.get(result["candidate"]["candidate_id"])

    assert "林照接过铜钥匙。" in candidate.body
    assert candidate.review_binding.get("state") == "unchecked"
    assert "旧事件标记" not in str(candidate.submission_payload)
    with pytest.raises(ValueError, match="candidate_review_required"):
        store.confirm_candidate(candidate.candidate_id, accept_quality_warnings=True)
    assert confirmed_files(store) == before


def test_legacy_recheck_rebuilds_history_from_repaired_body(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)
    before = confirmed_files(store)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    result = store.repair_chapter_review(1, orchestrator=PatchWriter())
    candidate = store.candidate_store.get(result["candidate"]["candidate_id"])
    reviewed = recheck(store, candidate.candidate_id, expected=candidate_authority(candidate),
                       consistency_runtime=PassingReview())

    assert reviewed.review_binding["state"] == "checked"
    assert "旧事件标记" not in str(reviewed.submission_payload)
    assert reviewed.submission_payload["chapter_summary"]["summary"].startswith("正文摘录：")
    assert confirmed_files(store) == before
    store.confirm_candidate(reviewed.candidate_id, accept_quality_warnings=True)
    assert "林照接过铜钥匙。" in store.chapter(1)["body"]
    assert "旧事件标记" not in str(store.persisted_state())
    assert "旧事件标记" not in str(store.state())
    assert "旧事件标记" not in str(store.project())


@pytest.mark.parametrize("include_delta", [True, False])
def test_recheck_rejects_semantically_false_delta_despite_exact_quote(tmp_path, monkeypatch, include_delta):
    store = legacy_store(tmp_path)
    before = confirmed_files(store)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    class IncorrectPatch:
        def _timed_chat(self, story, prompt, **kwargs):
            return json.dumps({"edits": [{"before": "林照拿到铜钥匙。", "after": "林照没有拿到铜钥匙。"}]}), ""

    result = store.repair_chapter_review(1, orchestrator=IncorrectPatch())
    candidate = store.candidate_store.get(result["candidate"]["candidate_id"])
    runtime = SemanticReview("unsupported")

    class EmptyExtractor:
        def extract(self, context):
            from packages.story_core.continuity.delta import ContinuityDelta
            return ContinuityDelta(chapter_number=context.chapter_number)

    reviewed = recheck(store, candidate.candidate_id, expected=candidate_authority(candidate),
                       consistency_runtime=runtime, fact_extractor=NegatedGainExtractor() if include_delta else EmptyExtractor())
    assert "candidate.semantic_unsupported" in str(reviewed.quality_report)
    assert any(f.get("code") == "candidate.semantic_unsupported" and f.get("blocking")
               for f in reviewed.quality_report["writing_review"]["blocking"])
    assert runtime.calls == 1
    if not include_delta:
        assert [d["change_id"] for d in reviewed.quality_report["candidate_semantic_review"]["decisions"]] == ["repair_equivalence:0"]
    with pytest.raises(ValueError):
        store.confirm_candidate(reviewed.candidate_id, accept_quality_warnings=True)
    assert confirmed_files(store) == before


def test_old_context_review_retries_factual_review_and_keeps_binding_current(tmp_path, monkeypatch):
    from tests.story_core.test_contextual_prose_review import Gateway
    from packages.story_core.candidate_editing import assert_review_current

    store = legacy_store(tmp_path)
    before = confirmed_files(store)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    result = store.repair_chapter_review(1, orchestrator=PatchWriter())
    candidate_id = result["candidate"]["candidate_id"]
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: PassingReview())
    store.run_contextual_prose_review(1, source_candidate_id=candidate_id,
                                     model_gateway=Gateway({"summary": "无需修改。", "issues": []}))
    reviewed = store.candidate_store.get(candidate_id)
    assert reviewed.review_binding["state"] == "checked"
    assert_review_current(store, reviewed)
    assert "旧事件标记" not in str(reviewed.submission_payload)
    assert confirmed_files(store) == before


def test_legacy_repair_rejects_source_changed_during_writer_call(tmp_path):
    store = legacy_store(tmp_path)

    class ConcurrentWriter(PatchWriter):
        def _timed_chat(self, story, prompt, **kwargs):
            next(store.chapters_dir.glob("*.md")).write_text("另一份正文。" * 500, encoding="utf-8")
            return super()._timed_chat(story, prompt, **kwargs)

    with pytest.raises(ValueError, match="candidate_review_source_changed"):
        store.repair_chapter_review(1, orchestrator=ConcurrentWriter())
    assert store.candidate_store.list() == []


def test_arbitrary_historical_candidate_still_cannot_use_edit_recheck(tmp_path):
    from tests.story_core.test_candidate_confirmation_transaction import _seed_candidate
    store = legacy_store(tmp_path)
    draft = _seed_candidate(store, chapter_number=1, title="旧锁", body="另一份正文。" * 500, operation="regenerate")
    with pytest.raises(ValueError, match="candidate_historical_edit_locked"):
        recheck(store, draft.candidate_id, expected=candidate_authority(draft), consistency_runtime=PassingReview())


def test_historical_generated_repair_can_be_reviewed_but_not_confirmed(tmp_path):
    from packages.story_core.candidate_editing import _pending, assert_review_current
    from packages.story_core.opening_build.execution import source_fingerprint
    from tests.story_core.test_candidate_confirmation_transaction import _seed_candidate
    store = legacy_store(tmp_path)
    draft = _seed_candidate(store, chapter_number=1, title="旧锁", body="另一份正文。" * 500, operation="generate")
    draft.project_id = store.project()["project_id"]
    draft.review_binding = {"kind": "legacy-review-repair/v1", "chapter_number": 1,
                            "parent": "cd-123", "repair_contract": {"schema": "review-correction/v1"},
                            "source": source_fingerprint(store), "state": "unchecked"}
    store.candidate_store.save(draft)
    assert _pending(store, draft.candidate_id, candidate_authority(draft), allow_legacy_repair=True).candidate_id == draft.candidate_id
    with pytest.raises(ValueError, match="candidate_historical_edit_locked"):
        assert_review_current(store, draft)
    draft.review_binding["source"] = "stale"
    store.candidate_store.save(draft)
    with pytest.raises(ValueError, match="candidate_historical_edit_locked"):
        _pending(store, draft.candidate_id, allow_legacy_repair=True)


def test_preexisting_unbound_repair_requires_explicit_recheck_without_migration(tmp_path, monkeypatch):
    from tests.story_core.test_candidate_confirmation_transaction import _seed_candidate
    from tests.story_core.test_contextual_prose_review import Gateway
    from packages.story_core.candidate_editing import assert_review_current
    store = legacy_store(tmp_path)
    draft = _seed_candidate(store, chapter_number=1, title="旧锁",
                            body=store.chapter(1)["body"].replace("拿到", "接过"), operation="regenerate")
    draft.quality_report["review_repair"] = {"edits": [{"before": "旧句", "after": "新句"}]}
    draft.project_id = store.project()["project_id"]
    store.candidate_store.save(draft)
    path = store.candidate_store.directory / f"{draft.candidate_id}.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="candidate_review_required"):
        store.confirm_candidate(draft.candidate_id, accept_quality_warnings=True)
    assert path.read_bytes() == before
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: PassingReview())
    store.run_contextual_prose_review(1, source_candidate_id=draft.candidate_id,
                                     model_gateway=Gateway({"summary": "无需修改。", "issues": []}))
    assert_review_current(store, store.candidate_store.get(draft.candidate_id))
