import hashlib
import json

import pytest

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.candidate_semantics import review_candidate_semantics
from packages.story_core.continuity.delta import ContinuityDelta
from packages.story_core.review_correction import correction_contract
from tests.story_core.test_legacy_repair_review import legacy_store, confirmed_files, UnavailableReview, PassingReview
from packages.story_core.agents import pipeline
from packages.story_core.candidate_editing import recheck, candidate_authority


def contract_fixture(store):
    store._write_json(store.webnovel_dir / "outline.json", {"chapters": [{"chapter_number": 1,
        "goal": "林照只拿到一把铁钥匙，不是铜钥匙。"}]})
    path = store.story_system_dir / "chapters" / "0001.json"
    data = store._read_json(path)
    data["quality_report"] = {"writing_review": {"blocking": [{"code": "outline.wrong_item",
        "message": "钥匙材质写错，按章纲修正为铁钥匙。"}]}}
    store._write_json(path, data)
    return correction_contract(store.root, 1, data["quality_report"], store.chapter(1)["body"])


class CorrectionRuntime:
    def __init__(self, verdict="supported", refs=None, reason="authorized_correction"):
        self.verdict, self.refs, self.reason = verdict, refs, reason

    def complete(self, request):
        self.prompt = request.prompt
        proposals = json.loads(request.prompt.split("## 拟提交变更\n", 1)[1])
        return {"issues": [], "review_id": request.metadata["review_id"], "decisions": [
            {"change_id": p["change_id"], "verdict": self.verdict, "reason_code": self.reason,
             "source_refs": self.refs, "changed_quote": "林照拿到铁钥匙。", "source_quote": "林照拿到铜钥匙。",
             "detail": "需核对钥匙材质的改动是否属于审查授权。"} for p in proposals]}


def run_correction(store, contract, runtime):
    return review_candidate_semantics(body="林照拿到铁钥匙。", source_body=store.chapter(1)["body"],
        chapter_number=1, director=DirectorArtifact(chapter_number=1, chapter_goal="检查", opening_state="门口",
        ending_state="门口", scene_beats=[]), snapshot={"facts": []}, delta=ContinuityDelta(chapter_number=1),
        runtime=runtime, repair_contract=contract)


@pytest.mark.parametrize("refs", [None, [], ["review:0"], ["plan:goal"], ["review:0", "plan:forged"], [{}]])
def test_correction_requires_both_real_permission_and_content_sources(tmp_path, refs):
    store = legacy_store(tmp_path)
    with pytest.raises(ValueError, match="candidate_review_unavailable"):
        run_correction(store, contract_fixture(store), CorrectionRuntime(refs=refs))


@pytest.mark.parametrize("verdict,reason,blocked", [("supported", "authorized_correction", False),
    ("unsupported", "correction_out_of_scope", True), ("uncertain", "unproven", True)])
def test_supported_correction_and_out_of_scope_remain_distinct(tmp_path, verdict, reason, blocked):
    store = legacy_store(tmp_path)
    runtime = CorrectionRuntime(verdict, ["review:0", "plan:goal"], reason)
    findings, report = run_correction(store, contract_fixture(store), runtime)
    assert bool(findings) == blocked
    assert report["decisions"][0]["change_id"] == "repair_correction:0"
    assert "不能仅凭新正文自证纠错合法" in runtime.prompt


@pytest.mark.parametrize("quote,valid", [("林照拿到铜钥匙。", True), ("不存在的动作。", False), ("", False)])
def test_internal_contradiction_requires_verbatim_original_evidence(tmp_path, quote, valid):
    store = legacy_store(tmp_path)
    class Runtime(CorrectionRuntime):
        def complete(self, request):
            response = super().complete(request)
            response["decisions"][0]["source_quote"] = quote
            return response
    runtime = Runtime(refs=["review:0", "original:body"])
    if valid:
        _, report = run_correction(store, contract_fixture(store), runtime)
        assert report["decisions"][0]["source_quote"] == quote
    else:
        with pytest.raises(ValueError, match="candidate_review_unavailable"):
            run_correction(store, contract_fixture(store), runtime)


def test_changed_contract_or_missing_plan_cannot_grant_permission(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)
    assert correction_contract(store.root, 1, {}, "原文")["mode"] == "expression_only"
    contract_fixture(store)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    class Writer:
        def _timed_chat(self, story, prompt, **kwargs):
            assert "章前Canon" in prompt and "plan:goal" in prompt and "review:0" in prompt
            return json.dumps({"edits": [{"before": "林照拿到铜钥匙。", "after": "林照拿到铁钥匙。"}]}), ""
    protected = confirmed_files(store)
    candidate = store.repair_chapter_review(1, orchestrator=Writer())["candidate"]
    assert confirmed_files(store) == protected
    saved = store.candidate_store.get(candidate["candidate_id"])
    # A changed chapter plan invalidates even an otherwise passing model response.
    store._write_json(store.webnovel_dir / "outline.json", {"chapters": [{"chapter_number": 1, "goal": "另一个计划"}]})
    with pytest.raises(ValueError, match="candidate_review_source_changed"):
        recheck(store, saved.candidate_id, expected=candidate_authority(saved), consistency_runtime=PassingReview())


def test_length_failure_retries_without_padding_and_preserves_parent(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    prompts = []
    class Writer:
        def _timed_chat(self, story, prompt, **kwargs):
            prompts.append(prompt)
            if len(prompts) == 1:
                return json.dumps({"edits": [{"before": "林照拿到铜钥匙。", "after": "字" * 999}]}), ""
            assert "review_repair_length_out_of_range" in prompt and "不要为了字数硬扩写" in prompt
            return json.dumps({"edits": [{"before": "林照拿到铜钥匙。", "after": "林照接过铜钥匙。"}]}), ""
    protected = confirmed_files(store)
    result = store.repair_chapter_review(1, orchestrator=Writer())
    assert len(prompts) == 2
    assert 3000 <= sum(not c.isspace() for c in result["candidate"]["body"]) <= 4500
    parent_id = result["candidate"]["candidate_id"]
    parent_path = store.candidate_store.directory / f"{parent_id}.json"
    parent_before = parent_path.read_bytes()
    class ChildWriter:
        def _timed_chat(self, story, prompt, **kwargs):
            return json.dumps({"edits": [{"before": "林照接过铜钥匙。", "after": "林照收起铜钥匙。"}]}), ""
    store.repair_chapter_review(1, source_candidate_id=parent_id, orchestrator=ChildWriter())
    assert parent_path.read_bytes() == parent_before
    assert confirmed_files(store) == protected


def test_factual_recheck_keeps_only_context_review_of_exact_body(tmp_path, monkeypatch):
    from tests.story_core.test_legacy_repair_review import PatchWriter
    store = legacy_store(tmp_path)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    result = store.repair_chapter_review(1, orchestrator=PatchWriter())
    candidate = store.candidate_store.get(result["candidate"]["candidate_id"])
    candidate.quality_report["contextual_prose_review"] = {"status": "completed", "executed": True,
        "pass": True, "issues": [], "body_sha256": hashlib.sha256(candidate.body.encode()).hexdigest()}
    store.candidate_store.save(candidate)
    reviewed = recheck(store, candidate.candidate_id, expected=candidate_authority(candidate), consistency_runtime=PassingReview())
    assert reviewed.quality_report["contextual_prose_review"]["status"] == "completed"
    reviewed.quality_report["contextual_prose_review"]["body_sha256"] = "stale"
    store.candidate_store.save(reviewed)
    fresh = recheck(store, reviewed.candidate_id, expected=candidate_authority(reviewed), consistency_runtime=PassingReview())
    assert "contextual_prose_review" not in fresh.quality_report


@pytest.mark.parametrize("chars", [2999, 3000, 4500, 4501])
def test_actual_character_count_overrides_model_guess_without_bypassing_gate(tmp_path, monkeypatch, chars):
    from tests.story_core.test_legacy_repair_review import PatchWriter
    store = legacy_store(tmp_path)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    result = store.repair_chapter_review(1, orchestrator=PatchWriter())
    candidate = store.candidate_store.get(result["candidate"]["candidate_id"])
    candidate.body = "字" * chars
    store.candidate_store.save(candidate)
    class WrongCount(PassingReview):
        def complete(self, request):
            result = super().complete(request)
            result["issues"] = [{"code": "author_requirement.length", "message": "模型猜测字数不足。", "blocking": True}]
            return result
    reviewed = recheck(store, candidate.candidate_id, expected=candidate_authority(candidate), consistency_runtime=WrongCount())
    assert "模型猜测" not in str(reviewed.quality_report)
    assert reviewed.quality_report["length_review"]["acceptance_pass"] == (3000 <= chars <= 4500)


def test_child_review_traces_material_changes_to_confirmed_original(tmp_path, monkeypatch):
    store = legacy_store(tmp_path)
    contract_fixture(store)
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda root: UnavailableReview())
    class Writer:
        def __init__(self, before, after):
            self.before, self.after = before, after
        def _timed_chat(self, story, prompt, **kwargs):
            return json.dumps({"edits": [{"before": self.before, "after": self.after}]}), ""
    parent = store.repair_chapter_review(1, orchestrator=Writer("林照拿到铜钥匙。", "林照拿到铁钥匙。"))["candidate"]
    parent_path = store.candidate_store.directory / f"{parent['candidate_id']}.json"
    protected = parent_path.read_bytes()
    child = store.repair_chapter_review(1, source_candidate_id=parent['candidate_id'],
        orchestrator=Writer("林照拿到铁钥匙。", "林照收好铁钥匙。"))["candidate"]
    candidate = store.candidate_store.get(child["candidate_id"])
    class RejectInheritedChange:
        def complete(self, request):
            proposals = json.loads(request.prompt.split("## 拟提交变更\n", 1)[1])
            repair = next(p for p in proposals if p["change_id"] == "repair_correction:0")
            assert "林照拿到铜钥匙。" in repair["change"]["source_body"]
            assert "林照拿到铁钥匙。" not in repair["change"]["source_body"]
            return {"review_id": request.metadata["review_id"], "issues": [], "decisions": [
                {"change_id": p["change_id"], "verdict": "unsupported", "reason_code": "correction_out_of_scope",
                 "changed_quote": "林照收好铁钥匙。", "source_quote": "林照拿到铜钥匙。",
                 "detail": "模拟拒绝继承的材质变化，不能通过多轮精修绕过。"} for p in proposals]}
    reviewed = recheck(store, candidate.candidate_id, expected=candidate_authority(candidate),
                       consistency_runtime=RejectInheritedChange())
    assert any(f["code"] == "candidate.semantic_unsupported" for f in reviewed.quality_report["writing_review"]["blocking"])
    with pytest.raises(ValueError):
        store.confirm_candidate(reviewed.candidate_id, accept_quality_warnings=True)
    assert parent_path.read_bytes() == protected


def test_prose_evidence_reads_only_previous_confirmed_chapter(tmp_path):
    from packages.story_core.review_correction import with_previous_confirmed_prose
    store = legacy_store(tmp_path)
    store.write_chapter(chapter_number=2, title="未来", body="不能作为第一章末事实。" * 400, summary="未来")
    source = {"as_of_chapter": 1, "facts": []}
    result = with_previous_confirmed_prose(store, source, 2)
    fact = result["facts"][0]
    assert fact["source"] == "confirmed_chapter_body:0001:tail"
    assert store.chapter(1)["body"].endswith(fact["value"])
    assert len(fact["value"]) <= 600
    assert "不能作为" not in fact["value"]
    assert source["facts"] == []
    assert with_previous_confirmed_prose(store, {**source, "stale_base_state": True}, 2)["facts"] == []
