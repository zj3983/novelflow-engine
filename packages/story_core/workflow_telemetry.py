from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


WORKFLOW_LOG_PATH_ENV = "NOVEL_AUTOGROWTH_WORKFLOW_LOG_PATH"
DEFAULT_WORKFLOW_LOG_PATH = Path("chapter_exports") / "workflow_log.jsonl"


def workflow_log_path() -> Path:
    override = os.getenv(WORKFLOW_LOG_PATH_ENV, "").strip()
    return Path(override) if override else DEFAULT_WORKFLOW_LOG_PATH


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _score_map(*sections: dict[str, Any]) -> dict[str, float]:
    scores: dict[str, float] = {}
    for section in sections:
        raw_scores = _as_dict(section.get("scores"))
        for key, value in raw_scores.items():
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                scores[str(key)] = float(value)
    return scores


def _issue_count(*sections: dict[str, Any]) -> int:
    return sum(len(_as_list(section.get("issues"))) for section in sections)


def _completion_from_beats(beats_review: dict[str, Any]) -> float | None:
    diagnostics = _as_dict(beats_review.get("diagnostics"))
    completion = diagnostics.get("completion")
    if isinstance(completion, (int, float)):
        return round(float(completion), 3)
    scores = _as_dict(beats_review.get("scores"))
    for key in ("beats_completion", "required_beats_completion"):
        value = scores.get(key)
        if isinstance(value, (int, float)):
            return round(float(value), 3)
    if not diagnostics:
        return None
    covered = diagnostics.get("covered")
    partial = diagnostics.get("partial")
    total = diagnostics.get("total_beats")
    if all(isinstance(value, (int, float)) for value in (covered, partial, total)) and total:
        return round((float(covered) + 0.5 * float(partial)) / float(total), 3)
    return None


def _hook_type(hook_review: dict[str, Any]) -> str:
    hook_meta = _as_dict(hook_review.get("hook_meta"))
    value = hook_meta.get("type") or hook_review.get("hook_type") or ""
    return str(value) if value else ""


def _profile_id(*sections: dict[str, Any]) -> str:
    for section in sections:
        value = section.get("profile_id") or section.get("profile") or section.get("genre_profile_id")
        if value:
            return str(value)
    return ""


def _revision_required(quality_report: dict[str, Any], writing_review: dict[str, Any], scores: dict[str, float]) -> bool:
    if quality_report.get("ok") is False:
        return True
    if writing_review.get("pass") is False:
        return True
    return any(value < 8 for value in scores.values())


def workflow_telemetry_record(
    *,
    chapter: int,
    quality_report: dict[str, Any] | None,
    chapter_title: str = "",
    operation: str = "generate",
    project_id: str = "",
    story_id: str = "",
    timestamp: str | None = None,
) -> dict[str, Any]:
    quality = _as_dict(quality_report)
    critical_review = _as_dict(quality.get("critical_review"))
    hook_review = _as_dict(quality.get("hook_review"))
    pacing_review = _as_dict(quality.get("pacing_review"))
    beats_review = _as_dict(quality.get("beats_review"))
    ai_flavor_review = _as_dict(quality.get("ai_flavor_review"))
    writing_review = _as_dict(quality.get("writing_review"))
    nested_quality = _as_dict(quality.get("quality_report"))

    scores = _score_map(critical_review, hook_review, pacing_review, beats_review, ai_flavor_review, writing_review)
    failed_scores = sorted(key for key, value in scores.items() if value < 8)
    hard_count = sum(1 for value in scores.values() if value < 6)
    soft_count = sum(1 for value in scores.values() if 6 <= value < 8)
    issue_total = _issue_count(quality, nested_quality, critical_review, hook_review, pacing_review, beats_review, ai_flavor_review, writing_review)
    ai_metrics = _as_dict(ai_flavor_review.get("metrics"))
    ai_score = _as_dict(ai_flavor_review.get("scores")).get("ai_flavor")

    return {
        "schema_version": "workflow-log/v1",
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "chapter": int(chapter),
        "chapter_title": chapter_title,
        "operation": operation,
        "project_id": project_id,
        "story_id": story_id,
        "profile": _profile_id(critical_review, hook_review, pacing_review, writing_review),
        "ok": bool(quality.get("ok", writing_review.get("pass", True))),
        "writing_pass": bool(writing_review.get("pass", quality.get("ok", True))),
        "requires_revision": _revision_required(quality, writing_review, scores),
        "issue_count": issue_total,
        "hard_count": hard_count,
        "soft_count": soft_count,
        "failed_scores": failed_scores,
        "beats_completion": _completion_from_beats(beats_review),
        "hook_type": _hook_type(hook_review),
        "hook_strength": _as_dict(hook_review.get("hook_meta")).get("strength") or "",
        "ai_flavor_score": ai_score if isinstance(ai_score, (int, float)) else None,
        "ai_formula_count": int(ai_metrics.get("formula_count") or 0),
        "ai_abstract_count": int(ai_metrics.get("abstract_count") or 0),
        "ai_concrete_density": ai_metrics.get("concrete_density"),
    }


def append_workflow_telemetry(
    *,
    chapter: int,
    quality_report: dict[str, Any] | None,
    chapter_title: str = "",
    operation: str = "generate",
    project_id: str = "",
    story_id: str = "",
    output_path: Path | None = None,
) -> Path | None:
    """Append one JSON line for a chapter workflow event.

    Observability must never block writing chapters, so failures are swallowed.
    """
    try:
        record = workflow_telemetry_record(
            chapter=chapter,
            chapter_title=chapter_title,
            operation=operation,
            project_id=project_id,
            story_id=story_id,
            quality_report=quality_report,
        )
        path = output_path or workflow_log_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        return path
    except Exception:
        return None
