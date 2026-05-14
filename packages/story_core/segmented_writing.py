from __future__ import annotations

from collections import Counter
import json
import re
from dataclasses import dataclass, field
from typing import Any

from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.prose_rule_review import review_critical_prose_rules
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.web_game_author_craft import format_web_game_director_card, plain_writer_phrase
from packages.story_core.writing_taskbook import ensure_writing_taskbook, format_taskbook_prompt_section, taskbook_segment_specs


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
        return plain_writer_phrase(value)
    if isinstance(value, list):
        return [plain_writer_phrase(str(item)) for item in value if str(item).strip()]
    if isinstance(value, dict):
        return {str(key): _plain_prompt_value(item) for key, item in value.items() if item not in (None, "", [], {})}
    return value


def _compact_segment_plan(plan: dict[str, Any]) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    cards = plan.get("scene_cards") if isinstance(plan.get("scene_cards"), list) else []
    return {
        "simulation_variant": simulation_plan.get("simulation_variant"),
        "chapter_goal": plain_writer_phrase(str(simulation_plan.get("chapter_goal") or "")) or None,
        "chapter_title": plain_writer_phrase(str(event_plan.get("chapter_title") or "")) or None,
        "next_focus": plain_writer_phrase(str(event_plan.get("next_focus") or "")) or None,
        "ordered_actions": [plain_writer_phrase(item) for item in _compact_items(event_plan.get("ordered_actions"), max_items=5)],
        "world_reactions": [plain_writer_phrase(item) for item in _compact_items(event_plan.get("world_reactions"), max_items=5)],
        "visible_scenes": [
            {
                key: _plain_prompt_value(card.get(key))
                for key in ("location", "purpose", "conflict", "must_show", "ending_pressure")
                if isinstance(card, dict) and card.get(key) not in (None, "", [], {})
            }
            for card in cards[:5]
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
            f"诊断词禁止入正文：{'；'.join(diagnostic_only) if diagnostic_only else '后台词不得入正文'}",
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
    taskbook_section = format_taskbook_prompt_section(taskbook, segment_key=spec.key)
    return "\n".join(
        [
            "OUTPUT CONTRACT: prose only",
            "写手身份：你只负责把本段写成可读正文，不输出片段标题、编号、解释或大纲。",
            "番茄白话风：用普通读者一眼能懂的话写，少用比喻和华丽修辞，少解释，多写动作、对话、面板、背包、耐久、药水和直接后果。",
            "后台词翻译：不要在正文或标题里写后台硬词；把它们改成“试一把、问一嘴、柜台能不能办、先别卖、包快满、药水不够、法杖快断”。",
            "第一章目标口语化：不要把目标写成后台硬词，要写成苏叶先试清楚这东西靠不靠谱、亏不亏、能不能带回去。",
            "第一章领先流：材料只是通行券，不是高潮；章末要指向任务、装备、技能或路线门槛上的提前一步，不要写成交任务、领取铜币、扣费修理或购买药水。",
            "情绪暗线：本段必须让角色有可感的担心、试探、隐瞒或欲望。",
            "职业背景落地：苏叶做过风控/测试，只能体现为先看余额、数铜币、看蓝耗、摸法杖耐久、停一下再问价；不要把职业背景直接写成数据模型、现金流、可量化、概率、止损线、变量、算法或后台数据异常。",
            "报告腔禁用：不要写“意味着、这说明、规则被撬开、常规掉落池、系统把溢出部分折算、模型跑不动”。发现异常时，写成背包格变满、提示闪一下、手指停住、旁人看不懂或主角先收东西。",
            "写法施工单",
            "进入压力 -> 尝试动作 -> 即时反馈 -> 选择代价 -> 余波/小钩子",
            "抽象判断必须落到具体物件或动作；对话必须改变筹码、知道的信息、价格、信任或能办的事。",
            taskbook_section,
            "硬性质量闸门",
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
            f"目标篇幅：约{spec.target_chars}字；短句为主，少解释腔，少套话。",
            "分段写作规则：本段只完成自己的戏剧职责，不要提前替后续片段收束，不要把设定写成条目。",
            "事实锁定：沿用本章计划里的怪物、地点、职业、面板数值和背包账本；不得把计划中的怪物、材料、NPC改名，也不要让生命/法力/属性无原因跳变。",
            f"变体事实锁：{'；'.join(fact_locks) if fact_locks else '沿用导演卡和推演计划，不新增背景病费、前世或新怪物。'}",
            "硬禁表达：不得使用报告腔词；改成手指停顿、余额栏、耐久红字、NPC报价、疼痛和路线选择。",
            "文风规则：拒绝华丽辞藻堆砌、拒绝成语套话、拒绝流水账、不要模板化心理描写，用动作、对话和具体细节写。",
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
    for key, score in critical_review.get("scores", {}).items():
        scores[f"segment_critical_{key}"] = int(score)
    for key, score in ai_flavor_review.get("scores", {}).items():
        scores[f"segment_ai_flavor_{key}"] = int(score)
    for issue in critical_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for issue in ai_flavor_review.get("issues", []):
        if issue not in issues:
            issues.append(issue)
    for item in critical_review.get("revision_plan", []):
        if item not in revision_plan:
            revision_plan.append(item)
    for item in ai_flavor_review.get("revision_plan", []):
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


_SEGMENT_LABEL_RE = re.compile(r"^\s*(?:#{1,6}\s*)?(?:【)?(?:setup|trigger|validation|landing|entry_login|small_verification|decision_hook|boundary_test|service_hook|opening|pressure|choice|hook|现实入口|登录建号|首次验证|落点留白|现实压力与登录建号|低级怪小验证|先不卖，留个问题|催租后登录|灰狼坡试一把|回村问一嘴|现实入口与登录建号|灰狼坡边界验证|NPC边界与章末钩子|承接与目标|压力推进|选择与代价|收束与新门槛)(?:】)?\s*[:：]?\s*$", re.I)


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


# ---------------------------------------------------------------------------
# Stage 2B: whole-chapter style adaptation (facts-frozen)
# ---------------------------------------------------------------------------
# Inspired by lingfengQAQ/webnovel-writer Step 2B. Drafting (2A) and style
# adaptation (2B) are deliberately separated so that drafting can stay
# fact-focused while style work has a single dedicated pass that is explicitly
# forbidden from changing facts. Step 4 (review/polish) remains downstream and
# only fixes issues flagged by reviewers.


def _style_brief(plan: dict[str, Any]) -> dict[str, Any]:
    """Pluck the small subset of craft/voice fields the 2B pass actually needs."""
    plan = plan if isinstance(plan, dict) else {}
    craft = plan.get("craft_pack")
    if not isinstance(craft, dict):
        sim = plan.get("simulation_plan")
        if isinstance(sim, dict):
            craft = sim.get("craft_pack")
    if not isinstance(craft, dict):
        craft = {}

    show_tell = craft.get("show_vs_tell") if isinstance(craft.get("show_vs_tell"), dict) else {}
    sentence_craft = craft.get("sentence_craft") if isinstance(craft.get("sentence_craft"), dict) else {}
    paragraph_rhythm = craft.get("paragraph_rhythm") if isinstance(craft.get("paragraph_rhythm"), dict) else {}
    transition_limits = craft.get("transition_crutch_limits") if isinstance(craft.get("transition_crutch_limits"), dict) else {}

    voices: list[dict[str, Any]] = []
    protagonist = plan.get("protagonist") if isinstance(plan.get("protagonist"), dict) else None
    if protagonist:
        voice = protagonist.get("voice") if isinstance(protagonist.get("voice"), dict) else None
        if voice:
            voices.append({"name": protagonist.get("name") or "主角", "voice": voice})
    for card in plan.get("character_cards") if isinstance(plan.get("character_cards"), list) else []:
        if not isinstance(card, dict):
            continue
        voice = card.get("voice") if isinstance(card.get("voice"), dict) else None
        if voice:
            voices.append({"name": card.get("name") or "?", "voice": voice})
        if len(voices) >= 3:
            break

    brief = {
        "show_vs_tell_conversions": show_tell.get("conversions", []),
        "sentence_craft": sentence_craft,
        "paragraph_rhythm": paragraph_rhythm,
        "transition_crutch_limits": transition_limits,
        "voice_guidance": voices,
    }
    return {key: value for key, value in brief.items() if value not in (None, "", [], {})}


def build_style_adapt_prompt(body: str, plan: dict[str, Any]) -> str:
    """Build a whole-chapter style-adaptation prompt.

    Strict contract: only expression-layer rewrites allowed. Names, numbers,
    panel data, currency, inventory, dialogue content, event order, and
    setting rules must be preserved verbatim.
    """
    brief_json = json.dumps(_plain_prompt_value(_style_brief(plan)), ensure_ascii=False, separators=(",", ":"))
    return "\n".join(
        [
            "请对下面这章中文网文正文做**风格适配（不改事实）**。",
            "",
            "唯一目的：把模板腔/说明腔/机械腔改成可读场面，不动任何事实。",
            "",
            "允许的改写（只能改'怎么说'，不能改'说什么'）：",
            "1. 模板腔 → 具象动作：'他很谨慎'→具体动作；'他很疲惫'→具体身体细节",
            "2. 说明腔 → 场面：把作者宣告/百科段改成主角能看见、听见、触到的物件、价格、对话、面板反馈",
            "3. 机械腔 → 人感：连续段首主语相同时换成动作/物件/对话/环境开头；判断句拐杖换成具体反应",
            "4. 比喻配额：删减明显堆砌的'像/仿佛'，但保留 1-2 个有效比喻",
            "5. 段落推进：在重要短句前后补 4-6 句的连续动作块",
            "6. 报告腔禁词必须清零：不要保留模型拆规则时常用的抽象判断词",
            "",
            "硬禁止（违反任一就视作失败）：",
            "- 改名字、地名、ID、职业、装备、技能、道具、NPC 名",
            "- 改数字（等级/经验/血量/法力/铜银金/耐久/库存数量/价格/距离）",
            "- 改面板数据（任何形如 【X：Y】的系统标签内容）",
            "- 改 NPC 台词的事实内容（'十份。'不能改成'八份。'；'5铜'不能改成'3铜'）",
            "- 改事件顺序、场景顺序、章节结构",
            "- 删除整个场景或新增整个场景",
            "- 改主角的关键决策（接/拒任务、出/不出村、买/不买药）",
            "- 保留报告腔词和后台判断词",
            "",
            "执行原则：保守改写。能不改就不改。改一句也是 OK 的，关键是不动事实。",
            "如果原章已经写得不错，可以原样输出。",
            "",
            f"风格参考（只看这些字段，不要展开 craft_pack 全部）：{brief_json}",
            "",
            "原章正文：",
            body,
            "",
            "只输出适配后的完整正文，不要加任何说明、标题、前言或评论。",
        ]
    )


_NUMBER_PATTERN = re.compile(r"\d+")
_PANEL_TAG_PATTERN = re.compile(r"【[^】]{1,40}】")


def style_adapt_safety_check(original: str, candidate: str) -> dict[str, Any]:
    """Verify the 2B candidate didn't violate the facts-frozen contract.

    Returns dict with ``accept: bool``, ``reason: str``, and optional
    ``mismatch`` detail. Caller should fall back to the original draft when
    accept=False — never block generation on a failed style pass.
    """
    if not candidate or not candidate.strip():
        return {"accept": False, "reason": "candidate_empty"}

    orig_compact_len = len("".join(original.split()))
    cand_compact_len = len("".join(candidate.split()))
    if cand_compact_len < orig_compact_len * 0.7:
        return {
            "accept": False,
            "reason": "candidate_too_short",
            "mismatch": {"original_chars": orig_compact_len, "candidate_chars": cand_compact_len},
        }
    if cand_compact_len > orig_compact_len * 1.4:
        return {
            "accept": False,
            "reason": "candidate_too_long",
            "mismatch": {"original_chars": orig_compact_len, "candidate_chars": cand_compact_len},
        }

    orig_numbers = _NUMBER_PATTERN.findall(original)
    cand_numbers = _NUMBER_PATTERN.findall(candidate)
    orig_number_counts = Counter(orig_numbers)
    cand_number_counts = Counter(cand_numbers)
    invented = sorted((cand_number_counts - orig_number_counts).elements())
    missing = sorted((orig_number_counts - cand_number_counts).elements())
    if invented:
        return {
            "accept": False,
            "reason": "invented_numbers",
            "mismatch": {"invented": invented[:8]},
        }
    if missing:
        return {
            "accept": False,
            "reason": "deleted_numbers",
            "mismatch": {"missing": missing[:8]},
        }

    orig_tags = sorted(_PANEL_TAG_PATTERN.findall(original))
    cand_tags = sorted(_PANEL_TAG_PATTERN.findall(candidate))
    if orig_tags and orig_tags != cand_tags:
        return {
            "accept": False,
            "reason": "panel_tags_changed",
            "mismatch": {
                "original_tag_count": len(orig_tags),
                "candidate_tag_count": len(cand_tags),
            },
        }

    return {
        "accept": True,
        "reason": "ok",
        "stats": {
            "original_chars": orig_compact_len,
            "candidate_chars": cand_compact_len,
            "panel_tag_count": len(orig_tags),
            "number_count": len(orig_numbers),
        },
    }
