from __future__ import annotations

from collections import Counter
import json
import re
from dataclasses import dataclass, field
from typing import Any

from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.prose_rule_review import review_critical_prose_rules
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.reader_feel_review import review_reader_feel
from packages.story_core.web_game_author_craft import format_web_game_director_card, plain_writer_phrase
from packages.story_core.writing_taskbook import (
    ensure_writing_taskbook,
    format_taskbook_brief_section,
    taskbook_segment_specs,
)
# Compatibility exports for older integrations; production code imports the
# whole-chapter style pass from style_adaptation directly.
from packages.story_core.style_adaptation import build_style_adapt_prompt, style_adapt_safety_check


@dataclass(frozen=True)
class SegmentSpec:
    key: str
    title: str
    goal: str
    required_surface: str
    forbidden_surface: str = ""
    entry_state: str = ""
    exit_state: str = ""
    handoff: str = ""
    target_chars: int = 1000
    context_budget: int = 900
    checks: tuple[str, ...] = field(default_factory=tuple)


FIRST_CHAPTER_FORBIDDEN = (
    "寄售",
    "成交",
    "到账",
    "手续费",
    "挂单",
    "商人",
    "赵胖子",
    "白袍",
    "公会追查",
    "论坛热帖",
    "锁定坐标",
)

FIRST_CHAPTER_FORBIDDEN_PROMPT = (
    "不要把材料换成钱",
    "不要写任何交易已经完成",
    "不要写扣费或收款反馈",
    "不要写市场玩家盯上主角",
    "不要写公共频道或玩家势力追过来",
    "交易行只能作为门口价牌/入口弱钩子，不操作、不成交",
)


def build_segment_specs(chapter_number: int, plan: dict[str, Any] | None = None) -> list[SegmentSpec]:
    """Return segment responsibilities compiled from the writing taskbook."""

    specs: list[SegmentSpec] = []
    for scene in taskbook_segment_specs(chapter_number, plan):
        specs.append(
            SegmentSpec(
                key=str(scene.get("key") or f"scene_{len(specs) + 1}"),
                title=str(scene.get("title") or "???"),
                goal=str(scene.get("goal") or "????????"),
                required_surface=str(scene.get("required_surface") or "???????????"),
                forbidden_surface=str(scene.get("forbidden_surface") or ""),
                entry_state=str(scene.get("entry_state") or ""),
                exit_state=str(scene.get("exit_state") or ""),
                handoff=str(scene.get("handoff") or ""),
                target_chars=int(scene.get("target_chars") or 1000),
                checks=tuple(scene.get("checks") or ()),
            )
        )
    return specs

def _compact_context(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    separator = " ... "
    if limit <= len(separator) + 2:
        return cleaned[:limit]
    half = max(1, (limit - len(separator)) // 2)
    tail_len = max(1, limit - len(separator) - half)
    return f"{cleaned[:half]}{separator}{cleaned[-tail_len:]}"


def _compact_items(value: Any, *, max_items: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:max_items]


def _plain_prompt_value(value: Any) -> Any:
    if isinstance(value, str):
        return _compact_context(plain_writer_phrase(value), 180)
    if isinstance(value, list):
        return [_compact_context(plain_writer_phrase(str(item)), 160) for item in value if str(item).strip()][:6]
    if isinstance(value, dict):
        return {str(key): _plain_prompt_value(item) for key, item in value.items() if item not in (None, "", [], {})}
    return value


def _compact_segment_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    plot = simulation_plan.get("plot_simulation") if isinstance(simulation_plan.get("plot_simulation"), dict) else {}
    cards = plan.get("scene_cards") if isinstance(plan.get("scene_cards"), list) else []
    plot_spine = []
    for key in ("reader_hook", "chapter_desire", "choice_point", "payoff", "cost", "ending_hook"):
        value = plain_writer_phrase(str(plot.get(key) or "")) if plot else ""
        if value:
            plot_spine.append(_compact_context(value, 120))
    simulation_variant = simulation_plan.get("simulation_variant") if isinstance(simulation_plan.get("simulation_variant"), dict) else {}
    return {
        "simulation_variant": simulation_variant.get("id") if isinstance(simulation_variant, dict) else None,
        "chapter_goal": _compact_context(plain_writer_phrase(str(simulation_plan.get("chapter_goal") or "")), 180) or None,
        "剧情主线": plot_spine,
        "chapter_title": _compact_context(plain_writer_phrase(str(event_plan.get("chapter_title") or "")), 80) or None,
        "next_focus": _compact_context(plain_writer_phrase(str(event_plan.get("next_focus") or "")), 140) or None,
        "ordered_actions": [_compact_context(plain_writer_phrase(item), 120) for item in _compact_items(event_plan.get("ordered_actions"), max_items=4)],
        "world_reactions": [_compact_context(plain_writer_phrase(item), 120) for item in _compact_items(event_plan.get("world_reactions"), max_items=3)],
        "visible_scenes": [
            {
                key: _plain_prompt_value(card.get(key))
                for key in ("location", "purpose", "conflict", "must_show", "ending_pressure")
                if isinstance(card, dict) and card.get(key) not in (None, "", [], {})
            }
            for card in cards[:3]
            if isinstance(card, dict)
        ],
    }


def _scene_state_terms(value: str) -> list[str]:
    candidates: list[str] = []
    normalized = re.sub(r"[，,]\s*但", "；但", value or "")
    for clause in re.split(r"[；;。！？!?]", normalized):
        for item in (part.strip() for part in re.split(r"[、,，：:\s/]+", clause) if part.strip()):
            if any(marker in item for marker in ("不得", "不能", "尚未", "没有", "仍无", "无寄售", "无交易", "无外部")):
                continue
            candidates.append(item)
    result: list[str] = []
    for item in candidates:
        if len(item) < 2:
            continue
        if item in {"已经", "尚未", "可见", "明确", "结束", "下一章", "下一场", "不得", "只能"}:
            continue
        if re.search(r"[\u4e00-\u9fffA-Za-z0-9]", item):
            result.append(item)
    return result[:10]


def _segment_governance_section(governance: dict[str, Any] | None) -> str:
    if not isinstance(governance, dict) or not governance:
        return "本段事实边界：按已有事实写，不输出工作流字段或说明文字。"
    intent = governance.get("chapter_intent", {}) if isinstance(governance.get("chapter_intent"), dict) else {}
    rules = governance.get("rule_stack", {}) if isinstance(governance.get("rule_stack"), dict) else {}
    hard_facts = _compact_items(rules.get("hard_facts"), max_items=8)
    must_avoid = _compact_items(intent.get("must_avoid"), max_items=8)
    return "\n".join(
        [
            "本段事实边界：本段只把已确认事实写成场景，不新增或篡改事实。",
            f"不要提前写：{'；'.join(must_avoid) if must_avoid else '无额外禁项'}",
            f"不能改的事实：{'；'.join(hard_facts) if hard_facts else '沿用本章计划'}",
        ]
    )


def build_segment_prompt(
    *,
    chapter_number: int,
    spec: SegmentSpec,
    plan: dict[str, Any],
    previous_segments: list[str] | None = None,
) -> str:
    previous = "\n".join(_compact_context(item, spec.context_budget // 2) for item in (previous_segments or [])[-2:])
    governance_section = _segment_governance_section(plan.get("governance") if isinstance(plan, dict) else None)
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    director_card = plan.get("web_game_director_card") or simulation_plan.get("web_game_director_card")
    director_card_text = format_web_game_director_card(director_card)
    fact_locks = []
    if isinstance(director_card, dict):
        fact_locks = [str(item).strip() for item in director_card.get("fact_locks", []) if str(item).strip()]
    compact_plan = _compact_segment_plan(plan)
    taskbook = ensure_writing_taskbook(chapter_number, plan)
    taskbook_section = format_taskbook_brief_section(taskbook, max_scenes=1, segment_key=spec.key)
    return "\n".join(
        [
            "输出要求：只写连续小说正文",
            "把这一场写成白话小说，顺着人物当下的目标和动作往前走。旁白少做抽象解释，对话不能省略连接词和因果。",
            "现代中文对话：话题先摆出来，再接判断和行动；要有完整来回，人物把理由说清楚。提纲句、翻译腔和系统腔改成普通说法，情绪放进动作、停顿和回答里。",
            taskbook_section,
            "写作保护线",
            governance_section,
            f"章节：第{chapter_number}章",
            f"当前片段：{spec.title} / {spec.key}",
            f"片段目标：{spec.goal}",
            f"入场状态：{spec.entry_state or '沿用上一段交接状态'}",
            f"出场状态：{spec.exit_state or '完成本段目标并形成下一段可承接状态'}",
            f"交接约束：{spec.handoff or '下一段必须承接本段结果，不得重置。'}",
            f"必须自然写到：{spec.required_surface}",
            f"禁止写到：{spec.forbidden_surface or '无额外禁项'}",
            director_card_text,
            f"目标篇幅：约{spec.target_chars}字；句子按场面自然长短，少套话。",
            "分段规则：本段收住自己的场面，后续内容留给下一段；设定要落成动作和对话。",
            "事实锁定：沿用本章计划里的怪物、地点、职业、面板数值和背包账本，不得改名或让数值无原因跳变。",
            f"变体事实锁：{'；'.join(fact_locks) if fact_locks else '沿用导演卡和推演计划，不新增背景病费、前世或新怪物。'}",
            f"已写前文摘要：{previous or '无'}",
            f"本章可见导演简表：{json.dumps(compact_plan, ensure_ascii=False)}",
        ]
    )


def review_segment_output(spec: SegmentSpec, text: str, *, chapter_number: int) -> dict[str, Any]:
    issues: list[str] = []
    revision_plan: list[str] = []
    scores = {
        "segment_scope": 8,
        "segment_surface": 8,
        "segment_style": 8,
    }
    compact = "".join(text.split())

    if len(compact) < max(360, int(spec.target_chars * 0.68)):
        scores["segment_surface"] = 5
        issues.append(f"当前片段偏短：约{len(compact)}字，无法承担“{spec.title}”职责。")
        revision_plan.append("只改这一段，补足行动过程、对话、环境细节和人物判断。")

    required_parts = [part.strip() for part in re.split(r"[、,/，]", spec.required_surface) if part.strip()]
    missing = [part for part in required_parts if part not in text]
    if len(missing) >= max(2, len(required_parts) // 2):
        scores["segment_surface"] = 5
        issues.append(f"当前片段缺少必要表面信息：{'、'.join(missing[:4])}。")
        revision_plan.append("只改这一段，把缺失信息写成场景、面板、对话或动作，不要列设定。")

    exit_terms = [term for term in _scene_state_terms(spec.exit_state) if term not in {"无", "没有"}]
    missing_exit_terms = [term for term in exit_terms if term not in text]
    if exit_terms and len(missing_exit_terms) >= max(1, len(exit_terms) // 2):
        scores["segment_surface"] = 5
        issues.append(f"当前片段没有完成出场状态：缺少 {'、'.join(missing_exit_terms[:4])}。")
        revision_plan.append("只改这一段，把出场状态写成可见动作、面板、NPC回答或背包/资源变化；不要靠总结句糊过去。")

    forbidden_terms = [term for term in FIRST_CHAPTER_FORBIDDEN if term and term in text]
    if chapter_number == 1 and forbidden_terms:
        scores["segment_scope"] = 5
        issues.append(f"本段提前写出第一章禁用内容：{'、'.join(forbidden_terms)}。")
        revision_plan.append("只改这一段，删除或后移材料处理、市场玩家盯盘、大公会或公共频道追过来等越界内容。")

    style_review = review_prose_style(text)
    if not style_review.get("pass"):
        scores["segment_style"] = 5
        issues.extend(style_review.get("issues", [])[:3])
        revision_plan.extend(style_review.get("revision_plan", [])[:3])

    # Layered HARD/SOFT critical rules at segment level. Chapter-level checks
    # (protagonist_speech, emotion_quota) are gated behind protagonist_names
    # and won't fire here — segments aren't expected to carry the full
    # protagonist arc on their own.
    critical_review = review_critical_prose_rules(text, protagonist_names=())
    ai_flavor_review = review_ai_flavor(text)
    reader_feel_review = review_reader_feel(text)
    for key, score in critical_review.get("scores", {}).items():
        scores[f"segment_critical_{key}"] = int(score)
    for key, score in ai_flavor_review.get("scores", {}).items():
        scores[f"segment_ai_flavor_{key}"] = int(score)
    for key, score in reader_feel_review.get("scores", {}).items():
        scores[f"segment_reader_feel_{key}"] = int(score)
    for issue in critical_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for issue in ai_flavor_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for issue in reader_feel_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in critical_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for item in ai_flavor_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for item in reader_feel_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "segment_key": spec.key,
        "segment_title": spec.title,
        "critical_review": critical_review,
        "ai_flavor_review": ai_flavor_review,
        "reader_feel_review": reader_feel_review,
    }


def _segment_hard_callouts(review: dict[str, Any]) -> list[str]:
    """Pull HARD-tier issues from a segment review for explicit promotion in
    the rewrite prompt. Falls back to the review's top-level issues only when
    the layered critical_review is missing (legacy reviews)."""
    callouts: list[str] = []
    critical = review.get("critical_review") if isinstance(review, dict) else None
    if isinstance(critical, dict):
        for item in critical.get("hard_issues", []) or []:
            text_item = str(item).strip()
            if text_item and text_item not in callouts:
                callouts.append(text_item)
    return callouts[:6]


def build_segment_revision_prompt(
    spec: SegmentSpec,
    text: str,
    review: dict[str, Any],
    *,
    previous_segments: list[str] | None = None,
    next_segments: list[str] | None = None,
    governance: dict[str, Any] | None = None,
) -> str:
    previous = "\n".join(_compact_context(item, 450) for item in (previous_segments or [])[-2:])
    following = "\n".join(_compact_context(item, 450) for item in (next_segments or [])[:2])
    governance_section = _segment_governance_section(governance)
    hard_callouts = _segment_hard_callouts(review)
    hard_block = (
        "🔴 必须优先修复（HARD 违规，不修则改稿不通过）：\n  - "
        + "\n  - ".join(hard_callouts)
        if hard_callouts
        else "🔴 HARD 违规：本段无（按段落审稿处理 SOFT 项即可）。"
    )
    return "\n".join(
        [
            "只重写当前段，不要重写上一段，不要续写下一段，不要输出解释。",
            governance_section,
            f"当前片段：{spec.title} / {spec.key}",
            hard_block,
            f"片段目标：{spec.goal}",
            f"入场状态：{spec.entry_state or '沿用上一段交接状态'}",
            f"出场状态：{spec.exit_state or '完成本段目标并形成下一段可承接状态'}",
            f"交接约束：{spec.handoff or '下一段必须承接本段结果，不得重置。'}",
            f"必须保留或补足：{spec.required_surface}",
            f"禁止写到：{spec.forbidden_surface or '无额外禁项'}",
            f"段落审稿：{plain_writer_phrase(str(review))}",
            f"上一段参考：{previous or '无'}",
            f"下一段参考：{following or '无'}",
            "改稿要求：只修复审稿指出的问题，保持事实、角色状态、背包、等级、货币和任务结果不乱跳。",
            f"原当前段：\n{text}",
        ]
    )


_SEGMENT_LABEL_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:【)?(?:setup|trigger|validation|landing|entry_login|small_verification|decision_hook|boundary_test|service_hook|opening|pressure|choice|hook|现实入口|登录建号|首次验证|落点留白|现实压力与登录建号|低级怪小验证|暗中吃下第一笔|先不卖，留个问题|催租后登录|灰狼坡试一把|回村问一嘴|现实入口与登录建号|灰狼坡边界验证|NPC边界与章末钩子|承接与目标|压力推进|选择与代价|收束与新前置|收束与新门槛)(?:】)?\s*[:：]?\s*$", re.I)


def _strip_segment_labels(text: str) -> str:
    lines = []
    for line in text.replace("\r", "\n").splitlines():
        if _SEGMENT_LABEL_RE.match(line.strip()):
            continue
        lines.append(line.rstrip())
    return "\n".join(lines).strip()


def merge_segment_outputs(segments: list[str]) -> str:
    cleaned = [_strip_segment_labels(item) for item in segments if item and item.strip()]
    return "\n\n".join(item for item in cleaned if item).strip()


def _paragraphs(text: str) -> list[str]:
    normalized = text.replace("\r", "\n")
    parts = [part.strip() for part in re.split(r"\n\s*\n+", normalized) if part.strip()]
    if parts:
        return parts
    return [line.strip() for line in normalized.splitlines() if line.strip()]


def _slice_paragraphs(paragraphs: list[str], *, start_markers: tuple[str, ...] = (), stop_markers: tuple[str, ...] = ()) -> list[str]:
    start = 0
    if start_markers:
        for index, paragraph in enumerate(paragraphs):
            if any(marker in paragraph for marker in start_markers):
                start = index
                break
    end = len(paragraphs)
    if stop_markers:
        for index in range(start + 1, len(paragraphs)):
            if any(marker in paragraphs[index] for marker in stop_markers):
                end = index
                break
    return paragraphs[start:end]


def trim_segment_to_contract(spec: SegmentSpec, text: str, *, chapter_number: int) -> str:
    """Keep a generated segment inside its scene responsibility.

    The writer model sometimes restarts the chapter inside later segments.  The
    prompt tells it not to, but this boundary trim makes the split useful even
    when the model drifts: scene 1 owns setup, scene 2 owns the first test, and
    scene 3 owns the decision hook.
    """

    paragraphs = _paragraphs(_strip_segment_labels(text))
    if not paragraphs or chapter_number != 1:
        return "\n\n".join(paragraphs).strip()

    key = str(spec.key or "")
    if key == "entry_login":
        kept = _slice_paragraphs(paragraphs, stop_markers=("灰狼坡", "第一只灰狼", "第二只", "击杀灰狼"))
    elif key == "small_verification":
        kept = _slice_paragraphs(
            paragraphs,
            start_markers=("灰狼坡", "第一只灰狼", "风里带着", "灰狼从", "他贴着坡"),
            stop_markers=("交易行", "仓库", "铁栓", "先别卖", "现实里的", "转身"),
        )
    elif key == "decision_hook":
        kept = _slice_paragraphs(
            paragraphs,
            start_markers=("背包", "五只狼", "村口", "交易行", "仓库", "先别卖", "夜烬没往"),
        )
    else:
        kept = paragraphs

    return "\n\n".join(kept or paragraphs).strip()
