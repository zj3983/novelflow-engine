from __future__ import annotations

from typing import Any


HARD_TOKENS = (
    "body_too_short",
    "body_too_long",
    "套路节点未兑现",
    "正文为空",
    "字数不足",
    "章节字数偏少",
    "字数超出",
    "缺少带身份栏的角色面板",
    "缺少简洁怪物面板",
    "题材污染",
    "设定冲突",
    "人物错位",
    "人物状态",
    "角色状态",
    "时间线",
    "数值冲突",
    "连续性冲突",
    "推进过快",
    "提前展开交易闭环",
    "开篇余额不一致",
    "大纲金额不一致",
    "章末余额不一致",
    "现实余额出现顺序错误",
    "交易金额流水矛盾",
)

AI_FLAVOR_TOKENS = (
    "AI味",
    "模型腔",
    "报告腔",
    "套话",
    "公式句",
    "抽象总结",
    "重复句式",
    "段首",
)

DIALOGUE_TOKENS = (
    "对话",
    "台词",
    "口语",
    "说话",
    "语气",
    "接话",
    "短句装高手",
)

NESTED_REVIEW_KEYS = (
    "reader_agent_review",
    "editor_agent_review",
    "reviewer_agent_review",
    "ai_flavor_review",
    "cold_reader_review",
    "reader_feel_review",
    "prose_style_review",
    "style_review",
    "prose_quality_review",
    "web_game_review",
    "consistency_review",
    "critical_review",
    "progression_lead_review",
    "plot_spine_review",
)

INTERNAL_ISSUES = {"writing_review", "primary_conflict", "secondary_conflict", "event_beat"}


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _issue_text(issue: Any) -> str:
    if isinstance(issue, str):
        return issue.strip()
    if isinstance(issue, dict):
        for key in ("reason", "message", "issue", "type"):
            text = str(issue.get(key) or "").strip()
            if text:
                return text
    return ""


def _review_sources(report: dict[str, Any]) -> list[tuple[dict[str, Any], int]]:
    sources: list[tuple[dict[str, Any], int]] = [(report, 0)]
    writing = _as_dict(report.get("writing_review"))
    sources.append((writing, 0))
    for key in NESTED_REVIEW_KEYS:
        sources.append((_as_dict(report.get(key)), 1))
        sources.append((_as_dict(writing.get(key)), 1))
    return sources


def _issue_suggestion(issue: Any) -> str:
    if not isinstance(issue, dict):
        return ""
    return str(issue.get("suggestion") or "").strip()


def _collect_issue_records(report: dict[str, Any]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for source, source_specificity in _review_sources(report):
        plans = source.get("revision_plan") if isinstance(source.get("revision_plan"), list) else []
        for index, issue in enumerate(source.get("issues") or []):
            message = _issue_text(issue)
            if not message or message in INTERNAL_ISSUES:
                continue
            suggestion = _issue_suggestion(issue)
            suggestion_priority = 3 if suggestion else 0
            if not suggestion and index < len(plans):
                suggestion = str(plans[index] or "").strip()
                suggestion_priority = 1 + source_specificity if suggestion else 0
            records.append(
                {
                    "message": message,
                    "suggestion": suggestion,
                    "suggestion_priority": suggestion_priority,
                }
            )
    return records


def _category(message: str) -> str:
    if "场景卡必写内容缺失" in message and any(
        marker in message
        for marker in (
            "s2-c1-",
            "s3-c1-",
            "s4-c1-",
            "s6-c1-",
            "现实职业/技能来源",
            "真实到账",
            "现实急账处理",
        )
    ):
        return "hard"
    if any(token in message for token in HARD_TOKENS):
        return "hard"
    if any(token in message for token in AI_FLAVOR_TOKENS):
        return "ai_flavor"
    if any(token in message for token in DIALOGUE_TOKENS):
        return "dialogue"
    return "prose"


def _suggestion(category: str) -> str:
    if category == "hard":
        return "先修正设定、状态或篇幅问题，再继续生成后续章节。"
    if category == "ai_flavor":
        return "删除抽象判断和固定套话，改成角色动作、对白或现场结果。"
    if category == "dialogue":
        return "按人物关系和当时情绪重写对话，让来回接话完整、自然，并保留必要动作。"
    return "只修改对应段落，保留已经成立的剧情和人物状态。"


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
    unique_records: list[dict[str, Any]] = []
    records_by_key: dict[str, dict[str, Any]] = {}
    grouped: dict[str, list[dict[str, str]]] = {
        "hard": [],
        "dialogue": [],
        "ai_flavor": [],
        "prose": [],
    }

    for record in _collect_issue_records(report):
        message = record["message"]
        key = "".join(message.split()).rstrip("。；;！!")
        if not key:
            continue
        existing = records_by_key.get(key)
        if existing:
            if int(record["suggestion_priority"]) > int(existing["suggestion_priority"]):
                existing["suggestion"] = record["suggestion"]
                existing["suggestion_priority"] = record["suggestion_priority"]
            continue
        records_by_key[key] = record
        unique_records.append(record)

    for record in unique_records:
        message = record["message"]
        category = _category(message)
        grouped[category].append(
            {
                "category": category,
                "severity": "blocking" if category == "hard" else "advisory",
                "message": message,
                "suggestion": record["suggestion"] or _suggestion(category),
            }
        )

    ordered = [*grouped["hard"], *grouped["dialogue"], *grouped["ai_flavor"], *grouped["prose"]]
    selected = ordered[: min(3, max(1, limit))]
    has_hard_errors = bool(grouped["hard"])
    needs_revision = has_hard_errors or bool(grouped["dialogue"]) or bool(grouped["ai_flavor"])
    status = "blocked" if has_hard_errors else ("needs_revision" if needs_revision else "passed")
    revision_plan = [item["suggestion"] for item in selected]
    return {
        "schema_version": "simplified-review/v1",
        "agent_label": "综合审稿",
        "status": status,
        "pass": not has_hard_errors,
        "has_hard_errors": has_hard_errors,
        "needs_revision": needs_revision,
        "summary": "存在必须修复的硬伤" if has_hard_errors else (
            "发现需要定向改写的问题" if needs_revision else ("可以继续，建议局部修改" if ordered else "未发现需要处理的问题")
        ),
        "categories": {
            "hard": {"label": "硬伤", "count": len(grouped["hard"])},
            "dialogue": {"label": "对话", "count": len(grouped["dialogue"])},
            "prose": {"label": "正文", "count": len(grouped["prose"])},
            "ai_flavor": {"label": "AI味", "count": len(grouped["ai_flavor"])},
        },
        "issues": selected,
        "revision_plan": revision_plan,
        "total_issues": len(ordered),
    }
