from copy import deepcopy

import pytest

from packages.story_core.candidate_editing import candidate_authority, review_digest, save_edit
from packages.story_core.opening_build.execution import source_fingerprint
from tests.story_core.test_opening_prose import FakeEngine, prepared_store


def test_manual_revision_preserves_old_body_and_cannot_reuse_old_review(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    result = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    old = store.candidate_store.get(result["candidate_id"])
    original = deepcopy(old.to_dict())
    from packages.story_core.model_gateway.runtime_gateway import RuntimeModelGateway

    monkeypatch.setattr(RuntimeModelGateway, "complete", lambda *_a, **_k: pytest.fail("Manual save called model"))
    revised = save_edit(store, old.candidate_id, body=old.body + "\n林照留下核对日期。",
                        expected=candidate_authority(old), expected_source=source_fingerprint(store))
    assert revised.candidate_id != old.candidate_id
    assert store.candidate_store.get(old.candidate_id).body == original["body"]
    assert revised.quality_report == {}
    assert revised.review_binding["state"] == "unchecked"
    with pytest.raises(ValueError, match="candidate_review_required"):
        store.confirm_candidate(revised.candidate_id, accept_quality_warnings=True)
    assert store.chapter_numbers() == []
    assert store.candidate_store.get(revised.candidate_id).body == revised.body
    with pytest.raises(ValueError):
        store.confirm_candidate(old.candidate_id, accept_quality_warnings=True)


def test_confirmation_rejects_body_changed_after_checked_binding(tmp_path):
    store = prepared_store(tmp_path)
    result = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    candidate = store.candidate_store.get(result["candidate_id"])
    candidate.review_binding = {"state": "checked", "source": source_fingerprint(store),
                                "result": review_digest(candidate)}
    candidate.body += "\n未经检查的新内容。"
    store.candidate_store.save(candidate)
    with pytest.raises(ValueError, match="candidate_review_required"):
        store.confirm_candidate(candidate.candidate_id, accept_quality_warnings=True)
    assert store.chapter_numbers() == []
