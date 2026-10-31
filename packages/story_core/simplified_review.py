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
    from packages.story_core.model_gateway.preflight import ModelPreflightBlockedError

    text = str(exc or "").strip()
    if text.startswith("writer_length_not_converged:"):
        return "写手多次自动修订后，字数仍未达标，已停止生成，原稿和现有候选稿未改动。可重试生成。"
    if text.startswith("automatic_context_revision_not_converged"):
        return "上下文问题经自动精修后仍未通过复审，已停止生成，原稿和现有候选稿未改动。"
    if text.startswith("automatic_context_revision_invalid_patch"):
        return "自动精修的局部修改无法准确验证，已停止生成，原稿和现有候选稿未改动。"
    if text.startswith("automatic_context_review_"):
        return "自动上下文审稿未完成，不能判定通过；原稿和现有候选稿未改动，请重试或检查审稿模型。"
    if text.startswith("context_review_"):
        return "上下文审稿未完成，原文未改动。请重试或检查审稿模型配置。"
    if text.startswith("review_repair_"):
        if text.startswith("review_repair_model_failed:"):
            reason = text.rsplit(":", 1)[-1].strip()
            advice = {
                "model_not_found": "当前账号或 CLI 对所选模型不支持，请检查模型选择和 CLI 版本。",
                "authentication_failed": "模型登录已失效或权限不足，请重新登录并检查账号权限。",
                "quota_exhausted": "模型额度已用尽，请等待额度恢复或调整模型配置。",
                "rate_limited": "模型请求频率受限，请稍后重试。",
                "cli_cache_incompatible": "CLI 与模型缓存格式不兼容，请更新 CLI 并检查缓存兼容性。",
                "cli_not_found": "找不到配置的 CLI 程序，请检查安装及程序路径。",
                "request_timed_out": "模型调用超时，请稍后重试。",
                "invalid_provider_response": "模型没有返回有效回复，请检查 CLI 输出或模型配置。",
                "provider_unavailable": "模型服务暂时不可用，请检查连接或稍后重试。",
            }.get(reason)
            if advice:
                return f"审查精修失败，原稿未改动。{advice}"
        if "no_edits" in text or "no_change" in text:
            return "模型没有返回有效的局部修改，原稿未改动。可调整要求后重试。"
        if "scope" in text:
            return "这次修改范围过大，已停止精修，原稿未改动。请缩小问题范围或使用重新生成。"
        if "length_out_of_range" in text:
            return "精修稿经一次自动退修仍未达到3000–4500字，已停止保存新候选；原稿和现有候选稿未改动，不会为凑字数强行扩写。"
        if any(code in text for code in ("original_not_found", "ambiguous", "overlap", "invalid")):
            return "局部修改无法准确定位到原文，已停止精修，原稿未改动。请重试。"
        return "审查精修失败，原稿未改动。请查看模型配置或稍后重试。"
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
    if isinstance(exc, ModelPreflightBlockedError):
        report = exc.report
        reason = str(report.get("reason") or "能力或预算检查未通过")
        if reason in {"required_input_over_limit", "input_over_limit", "required_context_over_limit",
                      "context_limit_unknown_or_optional_context_not_declared"}:
            estimates = report.get("estimates") or {}
            limits = report.get("effective_preflight_guards") or {}
            input_limit = limits.get("input_token_limit") or limits.get("input_guard")
            context_limit = limits.get("context_window") or limits.get("context_guard")
            return (f"模型预检阻断：上下文预算超限（{reason}）。"
                    f"估算输入{estimates.get('required_input_tokens', '?')} token，"
                    f"预留输出{estimates.get('reserved_output_tokens', '?')} token，"
                    f"安全余量{estimates.get('safety_margin_tokens', '?')} token；"
                    f"当前预检输入阈值{input_limit or '?'}、总上下文阈值{context_limit or '?'} token。"
                    "未调用模型，原稿和已有候选稿未改动。请减少无关上下文，或核实并配置当前模型容量后重试；未配置容量时使用保守阈值。")
        actions = report.get("repair_actions")
        action = (
            str(actions[0]).strip()
            if isinstance(actions, list) and actions and str(actions[0]).strip()
            else "检查当前阶段的 provider、模型能力声明和上下文限额后重试。"
        )
        return f"模型预检阻断（{reason}），未生成或保存本章。修复：{action}"
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
