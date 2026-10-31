from copy import deepcopy
from types import SimpleNamespace

from apps.api.routes.file_project_candidates import _candidate_payload
from apps.api.routes.file_projects import _file_chapter_payload


def test_pending_modular_candidate_backfills_prose_checks_without_mutating_source():
    original = {
        "status": "pending", "body": "不是胆怯，而是谨慎。他推开门。不是退让，而是等待。他握住刀。",
        "quality_report": {"modular_pipeline": {}, "writing_review": {"pass": True}},
    }
    before = deepcopy(original)
    candidate = SimpleNamespace(to_dict=lambda: original)
    payload = _candidate_payload(candidate)
    assert payload["quality_report"]["ai_flavor_review"]["issues"] == []
    assert payload["quality_report"]["ai_flavor_review"]["rule_signals"]
    assert payload["quality_report"]["simplified_review"]["diagnostics"]["requires_contextual_prose_review"] is True
    assert original == before


def test_candidate_with_authoritative_v2_review_is_not_reclassified():
    quality = {"modular_pipeline": {}, "review_result": {"schema_version": "review-result/v2", "issues": [], "total_issues": 0}}
    payload = _candidate_payload(SimpleNamespace(to_dict=lambda: {"status": "pending", "body": "原文", "quality_report": quality}))
    assert payload["quality_report"]["review_result"] == quality["review_result"]
    assert "ai_flavor_review" not in payload["quality_report"]


def test_confirmed_modular_chapter_keeps_read_only_review_evidence_after_confirmation():
    original = {"body": "此刻他记下基准。", "quality_report": {"modular_pipeline": {}, "ok": True}}
    before = deepcopy(original)
    payload = _file_chapter_payload(SimpleNamespace(chapter=lambda number: original), 307)
    assert payload["body"] == original["body"]
    assert payload["quality_report"]["prose_style_review"]["annotations"] == []
    assert payload["quality_report"]["prose_style_review"]["rule_signals"]
    assert original == before
