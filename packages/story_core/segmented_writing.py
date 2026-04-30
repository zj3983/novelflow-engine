from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from packages.story_core.prose_style_review import review_prose_style


@dataclass(frozen=True)
class SegmentSpec:
    key: str
    title: str
    goal: str
    required_surface: str
    forbidden_surface: str = ""
    target_chars: int = 1000
    context_budget: int = 900
    checks: tuple[str, ...] = field(default_factory=tuple)


FIRST_CHAPTER_FORBIDDEN = (
    "寄售",
    "成交",
    "到账",
    "手续费",
    "挂单",
    "交易行",
    "商人",
    "赵胖子",
    "白袍",
    "公会追查",
    "论坛热帖",
    "锁定坐标",
)


def build_segment_specs(chapter_number: int, plan: dict[str, Any] | None = None) -> list[SegmentSpec]:
    """Return the on-page responsibilities for a chapter-level segmented draft."""

    if chapter_number == 1:
        forbidden = "、".join(FIRST_CHAPTER_FORBIDDEN)
        return [
            SegmentSpec(
                key="setup",
                title="现实入口",
                goal="建立现实压力、主角职业/技能来源和进入游戏的理由，只聚焦读者能立刻理解的困境。",
                required_surface="现实压力、工作/技能来源、旧头盔或登录入口、主角克制的行动细节",
                forbidden_surface=f"交易成交、公会追查、论坛扩散、商人盯盘、{forbidden}",
                target_chars=950,
                checks=("motivation", "real_background"),
            ),
            SegmentSpec(
                key="trigger",
                title="登录建号",
                goal="写出登录、游戏ID、职业选择和短角色面板，让网游身份落地。",
                required_surface="游戏ID、职业选择、职业、Lv.1、经验、生命/法力、基础属性或装备",
                forbidden_surface=f"完整交易线、公会压力、多NPC巡礼、{forbidden}",
                target_chars=1050,
                checks=("game_id", "class_panel"),
            ),
            SegmentSpec(
                key="validation",
                title="首次验证",
                goal="用一次小规模刷怪验证金手指，只展示低级收益和代价，不扩大到市场风暴。",
                required_surface="第一次战斗、掉落反馈、千倍爆率、体感代价、背包变化",
                forbidden_surface=f"交易成交、公会追查、商人锁定、论坛爆帖、{forbidden}",
                target_chars=1150,
                checks=("goldfinger_validation", "fight_cost"),
            ),
            SegmentSpec(
                key="landing",
                title="落点留白",
                goal="让主角回到灰烬村，和一个NPC服务点发生短交互，留下下一章目标。",
                required_surface="一个命名NPC服务点、服务边界、任务/修理/补给门槛、章节结尾目标",
                forbidden_surface=f"实际寄售、到账、手续费、公会正面登场、{forbidden}",
                target_chars=1050,
                checks=("npc_service", "next_goal"),
            ),
        ]

    return [
        SegmentSpec(
            key="opening",
            title="承接与目标",
            goal="承接上一章状态，明确本章目标、主角当前资源和可见风险。",
            required_surface="上一章结果、当前目标、角色面板或关键账本、场景入口",
            target_chars=900,
            checks=("continuity",),
        ),
        SegmentSpec(
            key="pressure",
            title="压力推进",
            goal="让世界根据主角行动产生可见反应，形成具体阻力。",
            required_surface="NPC/玩家/市场/任务之一的反应、可观察痕迹、主角判断",
            target_chars=1100,
            checks=("world_reaction",),
        ),
        SegmentSpec(
            key="choice",
            title="选择与代价",
            goal="写主角做选择，兑现收益，同时让代价或风险落到账本。",
            required_surface="选择过程、行动细节、收益、代价、账本变化",
            target_chars=1200,
            checks=("choice_cost",),
        ),
        SegmentSpec(
            key="hook",
            title="收束与新门槛",
            goal="收住本章事件，更新面板/任务/装备/库存，并留下下一章门槛。",
            required_surface="结果回收、面板或账本更新、未解问题、下一章目标",
            target_chars=900,
            checks=("closing_hook",),
        ),
    ]


def _compact_context(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[-limit:]


def _compact_items(value: Any, *, max_items: int = 6) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()][:max_items]


def _segment_governance_section(governance: dict[str, Any] | None) -> str:
    if not isinstance(governance, dict) or not governance:
        return "分段输入治理：未提供；仍须遵守事实锁，不得输出后台字段或审稿术语。"
    intent = governance.get("chapter_intent", {}) if isinstance(governance.get("chapter_intent"), dict) else {}
    rules = governance.get("rule_stack", {}) if isinstance(governance.get("rule_stack"), dict) else {}
    hard_facts = _compact_items(rules.get("hard_facts"), max_items=8)
    must_avoid = _compact_items(intent.get("must_avoid"), max_items=8)
    diagnostic_only = _compact_items(rules.get("diagnostic_only"), max_items=4)
    return "\n".join(
        [
            "分段输入治理：表达权不等于事实权，本段只能把推演事实写成场景，不得新增或篡改事实。",
            f"本章禁止提前写：{'；'.join(must_avoid) if must_avoid else '无额外禁项'}",
            f"硬事实：{'；'.join(hard_facts) if hard_facts else '沿用本章计划'}",
            f"诊断词禁止入正文：{'；'.join(diagnostic_only) if diagnostic_only else '爽点/节奏/审稿/生成等后台词不得入正文'}",
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
    return "\n".join(
        [
            "请只写当前章节的一个连续正文片段，不要输出片段标题、编号、解释或大纲。",
            governance_section,
            f"章节：第{chapter_number}章",
            f"当前片段：{spec.title} / {spec.key}",
            f"片段目标：{spec.goal}",
            f"必须自然写到：{spec.required_surface}",
            f"禁止写到：{spec.forbidden_surface or '无额外禁项'}",
            f"目标篇幅：约{spec.target_chars}字；短句为主，少解释腔，少套话。",
            "分段写作规则：本段只完成自己的戏剧职责，不要提前替后续片段收束，不要把设定写成条目。",
            "事实锁定：沿用本章计划里的怪物、地点、职业、面板数值和背包账本；不要把灰鼠写成狼，也不要让生命/法力/属性无原因跳变。",
            "网游战斗规则：元素法师学徒的战斗要体现基础法术、法力消耗、冷却或技能未解锁原因，不能全程只用法杖近战敲怪。",
            "文风规则：拒绝华丽辞藻堆砌、拒绝成语套话、拒绝流水账、不要模板化心理描写，用动作、对话和具体细节写。",
            f"已写前文摘要：{previous or '无'}",
            f"本章推演计划：{plan}",
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

    forbidden_terms = [term for term in FIRST_CHAPTER_FORBIDDEN if term and term in text]
    if chapter_number == 1 and forbidden_terms:
        scores["segment_scope"] = 5
        issues.append(f"本段提前写出第一章禁用内容：{'、'.join(forbidden_terms)}。")
        revision_plan.append("只改这一段，删除或后移交易成交、商人盯盘、公会/论坛追查等越界内容。")

    style_review = review_prose_style(text)
    if not style_review.get("pass"):
        scores["segment_style"] = 5
        issues.extend(style_review.get("issues", [])[:3])
        revision_plan.extend(style_review.get("revision_plan", [])[:3])

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "segment_key": spec.key,
        "segment_title": spec.title,
    }


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
    return "\n".join(
        [
            "只重写当前段，不要重写上一段，不要续写下一段，不要输出解释。",
            governance_section,
            f"当前片段：{spec.title} / {spec.key}",
            f"片段目标：{spec.goal}",
            f"必须保留或补足：{spec.required_surface}",
            f"禁止写到：{spec.forbidden_surface or '无额外禁项'}",
            f"段落审稿：{review}",
            f"上一段参考：{previous or '无'}",
            f"下一段参考：{following or '无'}",
            "改稿要求：只修复审稿指出的问题，保持事实、角色状态、背包、等级、货币和任务结果不乱跳。",
            f"原当前段：\n{text}",
        ]
    )


_SEGMENT_LABEL_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:【)?(?:setup|trigger|validation|landing|opening|pressure|choice|hook|现实入口|登录建号|首次验证|落点留白|承接与目标|压力推进|选择与代价|收束与新门槛)(?:】)?\s*[:：]?\s*$", re.I)


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
