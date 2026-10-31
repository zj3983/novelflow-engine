from types import SimpleNamespace

import pytest

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.candidate_semantics import review_candidate_semantics
from packages.story_core.continuity.delta import ContinuityDelta, InventoryChange


@pytest.mark.parametrize("verdict,blocking", [("supported", False), ("unsupported", True), ("uncertain", True)])
def test_semantic_review_preserves_each_verdict_and_uses_one_call(verdict, blocking):
    runtime = ReviewRuntime(verdict=verdict)
    findings, report = run_review(runtime)
    assert report["status"] == "completed"
    assert report["decisions"][0]["verdict"] == verdict
    assert any(f.blocking for f in findings) is blocking
    assert runtime.calls == 1


@pytest.mark.parametrize("corruption", ["missing", "duplicate", "wrong_id", "wrong_review", "unknown_verdict", "missing_issues", "bad_id_type", "bad_verdict_type", "bad_reason_type"])
def test_incomplete_semantic_decisions_cannot_become_review_pass(corruption):
    with pytest.raises(ValueError, match="candidate_review_unavailable"):
        run_review(ReviewRuntime(corruption=corruption))


def test_quoted_evidence_is_checked_before_semantic_runtime():
    runtime = ReviewRuntime()
    with pytest.raises(ValueError, match="candidate_delta_evidence_mismatch"):
        run_review(runtime, evidence="正文里没有这段话。")
    assert runtime.calls == 0


def test_semantic_prompt_has_a_valid_json_response_example():
    import json
    runtime = ReviewRuntime()
    run_review(runtime)
    example = runtime.prompt.split("只返回JSON：", 1)[1].split("。以下全部", 1)[0]
    payload = json.loads(example)
    assert payload["decisions"][0]["reason_code"] == "actual_event"


class ReviewRuntime:
    def __init__(self, *, verdict="supported", corruption=None):
        self.verdict, self.corruption, self.calls = verdict, corruption, 0

    def complete(self, request):
        self.calls += 1
        self.prompt = request.prompt
        payload = {"issues": [], "review_id": request.metadata["review_id"],
                   "decisions": [{"change_id": "inventory_changes:0", "verdict": self.verdict, "reason": "核对实际结果。"}]}
        if self.corruption == "missing":
            payload["decisions"] = []
        elif self.corruption == "duplicate":
            payload["decisions"] *= 2
        elif self.corruption == "wrong_id":
            payload["decisions"][0]["change_id"] = "inventory_changes:99"
        elif self.corruption == "wrong_review":
            payload["review_id"] = "another_body"
        elif self.corruption == "unknown_verdict":
            payload["decisions"][0]["verdict"] = "probably"
        elif self.corruption == "missing_issues":
            payload.pop("issues")
        elif self.corruption == "bad_id_type":
            payload["decisions"][0]["change_id"] = {}
        elif self.corruption == "bad_verdict_type":
            payload["decisions"][0]["verdict"] = []
        elif self.corruption == "bad_reason_type":
            payload["decisions"][0]["reason_code"] = {}
        return SimpleNamespace(ok=True, payload=payload)


def run_review(runtime, *, evidence="林照拿到铜钥匙。"):
    return review_candidate_semantics(body="林照拿到铜钥匙。", chapter_number=1,
        director=DirectorArtifact(chapter_number=1, chapter_goal="核对实物", opening_state="店内",
                                  ending_state="店内", scene_beats=[]),
        snapshot={"schema_version": "canon-review-snapshot/v1", "facts": []},
        delta=ContinuityDelta(chapter_number=1, inventory_changes=[InventoryChange(chapter_number=1,
            source_sentence=evidence, entity_id="char-lin", item="铜钥匙", delta=1)]), runtime=runtime)
