"""Shared, model-free prose checks for generation and exact-match repair."""
from __future__ import annotations

from typing import Any
from copy import deepcopy
from hashlib import sha256

from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.prose_style_review import review_prose_style


def run_prose_checks(body: str, *, genre_context: Any = None) -> dict[str, Any]:
    return contextualize_rule_checks({
        "ai_flavor_review": review_ai_flavor(body),
        "prose_style_review": review_prose_style(body, genre_context=genre_context),
    })


def contextualize_rule_checks(quality: dict[str, Any]) -> dict[str, Any]:
    """Keep lexical/style counts as signals, never as contextual verdicts."""
    result = deepcopy(quality)
    result["requires_contextual_prose_review"] = True
    for envelope in (result, result.get("writing_review") or {}, result.get("complete_writing_review") or {}):
        for key in ("ai_flavor_review", "prose_style_review"):
            review = envelope.get(key)
            if not isinstance(review, dict):
                continue
            issues = review.get("issues") or []
            plans = review.get("revision_plan") or []
            annotations = review.get("annotations") or []
            kept, kept_plans = [], []
            signals = list(review.get("rule_signals") or [])
            for index, issue in enumerate(issues):
                message = str(issue.get("message") or "") if isinstance(issue, dict) else str(issue)
                if message.startswith("[必须修复]"):
                    kept.append(issue)
                    kept_plans.append(plans[index] if index < len(plans) else "")
                elif not any(item.get("message") == message for item in signals):
                    signals.append({"message": message, "suggestion": plans[index] if index < len(plans) else "",
                                    "quotes": [quote for item in annotations if item.get("message") == message for quote in item.get("quotes", [])]})
            review.update(issues=kept, revision_plan=kept_plans, rule_signals=signals, mode="rules",
                          annotations=[item for item in annotations if item.get("message") in {str(i.get("message") or "") if isinstance(i, dict) else str(i) for i in kept}],
                          **{"pass": not kept})
    writing = result.get("writing_review")
    if isinstance(writing, dict):
        def is_simile(item: Any) -> bool:
            return (item.get("code") if isinstance(item, dict) else item) == "style.simile_stacking"
        removed = any(is_simile(item) for key in ("issues", "blocking", "warnings") for item in writing.get(key, []))
        if removed:
            result.setdefault("style_rule_signals", []).append({"code": "style.simile_stacking", "message": "比喻密度线索，需结合上下文审稿。"})
            for key in ("issues", "blocking", "warnings"):
                writing[key] = [item for item in writing.get(key, []) if not is_simile(item)]
            other_failures = [item for item in writing.get("issues", []) if str(item) not in {"chapter.length_above_target", "chapter.length_below_target"}]
            if not writing.get("blocking") and not writing.get("hard_issues") and not other_failures:
                writing.update({"pass": True, "requires_revision": False})
                result["issues"] = [item for item in result.get("issues", []) if item != "writing_review"]
                result["ok"] = not result["issues"]
    return result


def with_prose_annotation_evidence(body: str, quality: dict[str, Any], *, backfill_missing_checks: bool = False) -> dict[str, Any]:
    """Backfill exact evidence for existing issues, without changing verdicts."""
    result = deepcopy(quality)
    context_review = result.get("contextual_prose_review")
    if isinstance(context_review, dict) and context_review.get("body_sha256") and context_review["body_sha256"] != sha256(body.encode("utf-8")).hexdigest():
        result.pop("contextual_prose_review", None)
    checks: dict[str, Any] | None = None
    if (backfill_missing_checks and "modular_pipeline" in result
        and (result.get("review_result") or {}).get("schema_version") != "review-result/v2"
        and any(not isinstance(result.get(key), dict) for key in ("ai_flavor_review", "prose_style_review"))):
        checks = run_prose_checks(body)
        for key, review in checks.items():
            if not isinstance(result.get(key), dict):
                result[key] = review
        result["prose_checks_backfilled_on_read"] = True
    containers = [result, result.get("writing_review") or {}]
    if (result.get("review_result") or {}).get("schema_version") != "review-result/v2":
        containers.append(result.get("complete_writing_review") or {})
    for envelope in (result, result.get("review_result") or {}):
        raw = (envelope.get("diagnostics") or {}).get("raw_reports") or {}
        containers.append(raw)
    for container in containers:
        for key, check_key in (("ai_flavor_review", "ai_flavor_review"), ("ai_flavor", "ai_flavor_review"),
                               ("prose_style_review", "prose_style_review"), ("style", "prose_style_review")):
            review = container.get(key)
            if not isinstance(review, dict) or "annotations" in review or not review.get("issues"):
                continue
            checks = checks or run_prose_checks(body)
            messages = {
                str(item.get("message") or item.get("reason") or "") if isinstance(item, dict) else str(item)
                for item in review["issues"]
            }
            review["annotations"] = [item for item in checks[check_key]["annotations"] if item["message"] in messages]
    return contextualize_rule_checks(result)
