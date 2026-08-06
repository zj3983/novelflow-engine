from __future__ import annotations

from typing import Any

from packages.story_core.review.contracts import ReviewResult
from packages.story_core.review.legacy_adapter import build_legacy_simplified_review


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _is_v2_payload(payload: Any) -> bool:
    return isinstance(payload, dict) and payload.get("schema_version") == "review-result/v2"


def project_review_result_dict(payload: dict[str, Any], *, issue_limit: int = 3) -> dict[str, Any]:
    """Return a v2 review result payload, trimming `issues` to `issue_limit`.

    This helper never reclassifies findings, never alters blocking flags, and
    never recomputes status. It is used to expose canonical review results to
    callers that still expect a flat dictionary shape.
    """

    if not _is_v2_payload(payload):
        raise ValueError("project_review_result_dict requires a review-result/v2 payload")
    projected = dict(payload)
    issues = projected.get("issues")
    if isinstance(issues, list):
        projected["issues"] = list(issues)[: max(1, issue_limit)]
    return projected


def user_facing_generation_error(exc: Exception) -> str:
    from packages.story_core.file_project_store import ChapterQualityError

    text = str(exc or "").strip()
    if isinstance(exc, ChapterQualityError):
        review = build_simplified_review(exc.quality_report or {})
        categories = review.get("categories") if isinstance(review.get("categories"), dict) else {}
        parts = []
        for key in ("hard", "dialogue", "ai_flavor", "prose"):
            info = categories.get(key) if isinstance(categories.get(key), dict) else {}
            count = int(info.get("count") or 0)
            if count:
                parts.append(f"{info.get('label') or key}{count}项")
        suggestion = ""
        for issue in review.get("issues") or []:
            if isinstance(issue, dict) and str(issue.get("suggestion") or "").strip():
                suggestion = str(issue["suggestion"]).strip()
                break
        summary = f"：{'、'.join(parts)}" if parts else ""
        advice = f"建议：{suggestion}" if suggestion else "建议：修正后重试生成。"
        return f"章节质量检查未通过{summary}。{advice}本章未保存，可直接重试。"
    if "Missing OPENAI_API_KEY" in text or "api_key" in text.lower() and "missing" in text.lower():
        return "模型 API Key 未配置，请先在设置页完成配置后重试。"
    if "模型 HTTP" in text or "model_request_failed" in text:
        return "模型请求失败，请检查模型设置（模型名、接口地址、额度）后重试。"
    if "timeout" in text.lower() or "超时" in text:
        return "生成超时，请重试。"
    if text.startswith(("generate_length_failed", "regenerate_length_failed")):
        return "生成的章节字数不达标，本章未保存，请重试生成。"
    if text.startswith(("generate_failed:", "regenerate_failed:")):
        reason = text.split(":", 1)[1].strip()
        if reason == "body" or reason == "empty_body":
            return "生成失败：正文为空，请重试。"
        return "生成失败，请重试。"
    return "生成失败，请重试。"


def build_simplified_review(quality_report: Any, *, limit: int = 3) -> dict[str, Any]:
    report = _as_dict(quality_report)
    explicit = report.get("review_result")
    if _is_v2_payload(explicit):
        return project_review_result_dict(explicit, issue_limit=limit)
    return build_legacy_simplified_review(report, limit=limit)
