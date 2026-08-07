from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.chapter_continuity import generic_revision_fact_lock
from packages.story_core.prompt_templates import get_effective_prompt_template, render_prompt_template
from packages.story_core.scene_contract_repair import build_scene_contract_repair_plan
from packages.story_core.simplified_review import build_simplified_review
from packages.story_core.writing_taskbook import ensure_writing_taskbook


MIN_CHAPTER_CHARS = 4200
MAX_CHAPTER_CHARS = 5500
TARGET_CHAPTER_CHARS = "4200到5500字"


@dataclass(frozen=True)
class RevisionContext:
    story: Any
    chapter_number: int
    body: str
    plan: Any
    review: Any
    writer_context: Any


def chapter_char_count(text: str) -> int:
    return len("".join(str(text).split()))


def revision_char_ceiling(body: str) -> int:
    return min(MAX_CHAPTER_CHARS, max(MIN_CHAPTER_CHARS, chapter_char_count(body)))


def _plan_target_chars(plan: dict[str, Any]) -> str:
    target = plan.get("target_chars")
    if isinstance(target, dict):
        minimum = target.get("min")
        maximum = target.get("max")
        if minimum and maximum:
            return f"{minimum}到{maximum}字"
        if minimum:
            return f"不少于{minimum}字"
        if maximum:
            return f"不超过{maximum}字"
    if isinstance(target, int) and target > 0:
        return f"约{target}字"
    return TARGET_CHAPTER_CHARS


def _blocking_revision_suggestions(review: dict[str, Any]) -> list[tuple[str, str]]:
    """Extract (message, suggestion) pairs for at most three blocking findings.

    New runtime code always uses the v2 schema; only blocking findings may
    modify the chapter. Historical v1 reports that lack an explicit
    ``review_result`` fall back to ``build_simplified_review``, which
    dedupes issues across nested review keys (``reviewer_agent_review``,
    ``editor_agent_review``, ``reader_agent_review``, ``style_review``,
    ...), prefers embedded per-issue ``suggestion`` over plan-based
    fallbacks, prefers nested agent reviews over the aggregate, and
    sorts by category (hard > dialogue > ai_flavor > prose) so the
    writer sees the most actionable items first.
    """
    explicit = review.get("review_result")
    if isinstance(explicit, dict) and explicit.get("schema_version") == "review-result/v2":
        issues = explicit.get("issues") if isinstance(explicit.get("issues"), list) else []
        instructions: list[tuple[str, str]] = []
        for issue in issues:
            if not isinstance(issue, dict):
                continue
            if not issue.get("blocking"):
                continue
            message = str(issue.get("message") or "").strip()
            suggestion = str(issue.get("suggestion") or "").strip()
            if not (message or suggestion):
                continue
            instructions.append((message, suggestion))
            if len(instructions) >= 3:
                break
        return instructions
    # v1 path: delegate to build_simplified_review for categorized,
    # deduped legacy issues. The legacy adapter already implements
    # the "embedded suggestion > plan-based fallback" and
    # "nested > aggregate" priority rules the v1 storage format
    # depends on, so the writer still gets actionable instructions
    # when a chapter loads an old review payload.
    consolidated = build_simplified_review(review)
    issues = consolidated.get("issues") if isinstance(consolidated.get("issues"), list) else []
    instructions: list[tuple[str, str]] = []
    for issue in issues:
        if not isinstance(issue, dict):
            continue
        message = str(issue.get("message") or "").strip()
        suggestion = str(issue.get("suggestion") or "").strip()
        if not (message or suggestion):
            continue
        instructions.append((message, suggestion))
        if len(instructions) >= 3:
            break
    return instructions


def _slim_prompt_value(value: Any, *, depth: int = 0) -> Any:
    if depth > 5:
        return compact_text(str(value), 160)
    if isinstance(value, str):
        return compact_text(value, 180)
    if isinstance(value, list):
        return [_slim_prompt_value(item, depth=depth + 1) for item in value[:8]]
    if isinstance(value, dict):
        return {
            str(key): _slim_prompt_value(item, depth=depth + 1)
            for key, item in value.items()
            if item not in (None, "", [], {})
        }
    return value


def _review_trope_avoid_guidance(review: dict[str, Any]) -> list[str]:
    sources: list[dict[str, Any]] = [review]
    for key in ("writing_review", "plot_spine_review"):
        value = review.get(key)
        if isinstance(value, dict):
            sources.append(value)
    writing = review.get("writing_review")
    if isinstance(writing, dict) and isinstance(writing.get("plot_spine_review"), dict):
        sources.append(writing["plot_spine_review"])

    guidance: list[str] = []
    for source in sources:
        diagnostics = source.get("diagnostics") if isinstance(source.get("diagnostics"), dict) else {}
        avoid = diagnostics.get("trope_avoid") if isinstance(diagnostics, dict) else []
        items = [avoid] if isinstance(avoid, str) else avoid if isinstance(avoid, list) else []
        for item in items:
            text = str(item).strip()
            if text and text not in guidance:
                guidance.append(text)
    return guidance[:8]


def _scene_repair_writer_summary(repair_plan: dict[str, Any]) -> dict[str, Any]:
    if not repair_plan:
        return {}
    scenes = repair_plan.get("failed_scenes") if isinstance(repair_plan.get("failed_scenes"), list) else []
    failed_scenes: list[dict[str, Any]] = []
    for scene in scenes[:4]:
        if not isinstance(scene, dict):
            continue
        missing = scene.get("missing_visible_consequences")
        missing_items: list[str] = []
        if isinstance(missing, list):
            for item in missing[:5]:
                if isinstance(item, dict):
                    text = str(item.get("revision") or item.get("description") or item.get("id") or "").strip()
                else:
                    text = str(item).strip()
                if text:
                    missing_items.append(compact_text(text, 110))
        failed_scenes.append(
            {
                "场景": compact_text(str(scene.get("scene_id") or scene.get("template_id") or ""), 60),
                "地点": compact_text(str(scene.get("location") or ""), 60),
                "需要补出来": missing_items,
            }
        )
    if not failed_scenes:
        return {}
    return {"范围": "只补这些场景，其他场景保持原顺序和事实", "场景": failed_scenes}


def _neutral_forbidden_terms(plan: dict[str, Any], extra_terms: Iterable[str]) -> list[str]:
    terms: list[str] = []
    scene_cards = plan.get("scene_cards") if isinstance(plan.get("scene_cards"), list) else []
    for card in scene_cards:
        if not isinstance(card, dict):
            continue
        raw_terms = card.get("must_not_explain")
        if isinstance(raw_terms, list):
            terms.extend(str(term).strip() for term in raw_terms if str(term).strip())
    for term in extra_terms:
        text = str(term).strip()
        if text and text not in terms:
            terms.append(text)
    return terms


def render_common_revision_prompt(
    *,
    context: RevisionContext,
    base_prompt: str,
    fact_lock: str | None = None,
    extra_forbidden_terms: Iterable[str] = (),
) -> str:
    body = str(context.body)
    plan = context.plan if isinstance(context.plan, dict) else {}
    plan = {
        **plan,
        "writing_taskbook": ensure_writing_taskbook(
            context.chapter_number,
            plan,
            genre=context.story.genre,
            style=context.story.style,
        ),
    }
    review = context.review if isinstance(context.review, dict) else {}
    blocking_instructions = _blocking_revision_suggestions(review)
    manual_instructions = compact_list(review.get("manual_instructions", []), max_items=3, item_chars=150)
    style_guidance = plan.get("style_guidance") if isinstance(plan.get("style_guidance"), dict) else {}
    scene_repair_plan = review.get("scene_repair_plan") if isinstance(review.get("scene_repair_plan"), dict) else {}
    if not scene_repair_plan:
        scene_repair_plan = build_scene_contract_repair_plan(review, plan.get("scene_cards", []))
    scene_repair_summary = _scene_repair_writer_summary(scene_repair_plan)
    forbidden_terms = compact_list(
        _neutral_forbidden_terms(plan, extra_forbidden_terms),
        max_items=32,
        item_chars=24,
    )

    modification_lines = [
        "## 综合审稿修改",
        "在不改变本章核心事实、事件顺序和人物关系的前提下，把原文改得更顺。",
    ]
    if manual_instructions:
        modification_lines.append(f"用户要求：{'；'.join(manual_instructions)}")
    if blocking_instructions:
        modification_lines.append("修改意见（综合后，必须改到以下三项以内）：")
        for index, (message, suggestion) in enumerate(blocking_instructions, start=1):
            label = compact_text(message, 100) or compact_text(suggestion, 120)
            action = compact_text(suggestion, 120) if message else ""
            if action:
                modification_lines.append(f"{index}. 问题：{label} 修改：{action}")
            else:
                modification_lines.append(f"{index}. {label}")
    trope_avoid_guidance = _review_trope_avoid_guidance(review)
    if trope_avoid_guidance:
        modification_lines.append(f"套路避让：{'；'.join(trope_avoid_guidance)}")
    if style_guidance:
        modification_lines.append(
            f"表达提醒：{json.dumps(_slim_prompt_value(style_guidance), ensure_ascii=False)}"
        )
    if scene_repair_summary:
        modification_lines.append(
            f"局部补写范围：{json.dumps(scene_repair_summary, ensure_ascii=False)}"
        )
        modification_lines.append("只补这些场景缺少的可见后果，其他场景只做必要衔接。")
    if forbidden_terms:
        modification_lines.append(f"需要删掉的词：{'、'.join(forbidden_terms)}")
    modification_lines.extend(
        [
            f"篇幅要求：修订后控制在{_plan_target_chars(plan)}，当前原文约{chapter_char_count(body)}字，"
            f"本轮修订硬上限：{revision_char_ceiling(body)}字。",
            "只能通过替换、合并、删除和必要的局部补写完成；不要因为补问题而扩写整章。",
            f"事实锁硬规则：{fact_lock or generic_revision_fact_lock()}；不确定时保留原文事实。",
            "改完后检查：修改目标逐项完成，删词清零，缺失场面已经正面写出；不要输出检查说明。",
        ]
    )
    return render_prompt_template(
        get_effective_prompt_template("revision"),
        {
            "body_prompt": base_prompt,
            "revision_instructions": "\n".join(modification_lines),
            "source_body": body,
        },
    )
