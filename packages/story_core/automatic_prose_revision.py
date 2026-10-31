"""Bounded model revision before facts are extracted; no confirmed prose writes."""
from __future__ import annotations

from hashlib import sha256
from typing import Any, Callable

from packages.story_core.agents.contracts import WriterRequest, WriterResult
from packages.story_core.contextual_prose_review import review_contextual_prose
from packages.story_core.generation_progress import report_generation_progress


def revise_contextually(
    agent: Any, request: WriterRequest, result: WriterResult, context: dict[str, Any],
    *, reviewer: Callable | None = None,
) -> tuple[WriterResult, dict[str, Any], list[dict[str, Any]]]:
    """Review fresh text after every edit. Two edits, three reviews at most."""
    reviewer = reviewer or review_contextual_prose
    history = []
    for attempt in range(3):
        report_generation_progress({"message": f"第{request.chapter_number}章：上下文审稿（第{attempt + 1}轮）",
                                    "stage": "review", "status": "running"})
        report = reviewer(result.body, {**context, "enforce_narrative_alignment": True})
        digest = sha256(result.body.encode()).hexdigest()
        history.append({"round": attempt + 1, "chars": result.word_count, "body_sha256": digest,
                        "length_revisions": list(getattr(result, "revision_history", []) or []),
                        "review": report})
        report_generation_progress({"message": f"第{request.chapter_number}章：本轮上下文审稿{'通过' if report.get('pass') else '需要处理'}",
                                    "stage": "review", "status": "running",
                                    "artifact": {"reason": "automatic_context_review",
                                                 "inputs": {"body_sha256": digest}, "outputs": {"review": report}}})
        if not (report.get("executed") and report.get("status") == "completed"
                and report.get("body_sha256") == digest):
            raise RuntimeError("automatic_context_review_incomplete")
        if report.get("pass"):
            return result, report, history
        if attempt == 2:
            raise RuntimeError("automatic_context_revision_not_converged")
        feedback = [{key: item.get(key) for key in ("message", "evidence", "suggestion")}
                    for item in report.get("issues") or []]
        for item, annotation in zip(feedback, report.get("annotations") or []):
            item["related_quotes"] = annotation.get("quotes") or []
        if not feedback:
            raise RuntimeError("automatic_context_review_without_evidence")
        report_generation_progress({"message": f"第{request.chapter_number}章：写手按上下文问题自动精修",
                                    "stage": "revision", "status": "running"})
        result = agent.revise_from_review(request, result, feedback)
    raise AssertionError("unreachable")
