"""Writer prompt assembly for the modular agent.

The prompt is rendered from the typed ``WriterRequest`` only —
it never reaches back into the story state, the project root,
or the orchestrator's bag of helpers. The result is a stable
string the runtime can send to whichever transport is plugged
in.
"""

from __future__ import annotations

import json
from typing import Any

from packages.story_core.chapter_length_policy import (
    CHAPTER_HARD_MAX_CHARS,
    CHAPTER_HARD_MIN_CHARS,
    CHAPTER_TARGET_MAX_CHARS,
    CHAPTER_TARGET_MIN_CHARS,
)

from ..contracts import WriterRequest


def _render_director_artifact(request: WriterRequest) -> str:
    artifact = request.director_artifact
    lines: list[str] = [
        f"## 章节目标（第{artifact.chapter_number}章）",
        artifact.chapter_goal,
        "",
        "## 开场状态",
        artifact.opening_state,
        "",
        "## 场景节拍",
    ]
    for beat in artifact.scene_beats:
        lines.append(
            f"- 顺序{beat.order} · 地点：{beat.location} · 动作：{beat.action} · 结果：{beat.result}"
        )
    lines.extend(["", "## 收尾状态", artifact.ending_state])
    if artifact.hook:
        lines.extend(["", "## 章末钩子", artifact.hook])
    if artifact.entity_requirements:
        lines.extend(["", "## 实体要求"])
        for requirement in artifact.entity_requirements:
            lines.append(
                f"- {requirement.kind}：{requirement.name}"
                f"{'（次要行内人物）' if requirement.inline_minor else ''}"
            )
    return "\n".join(lines)


def _render_previous_handoff(request: WriterRequest) -> str:
    if not request.previous_tail and not request.continuity_facts:
        return ""
    sections: list[str] = []
    if request.previous_tail:
        sections.append(f"## 上章末尾\n{request.previous_tail}")
    if request.continuity_facts:
        facts = "\n".join(
            f"- {fact.get('subject', '?')} · {fact.get('field', '?')}：{fact.get('value', '?')}"
            for fact in request.continuity_facts
        )
        sections.append(f"## 连续性事实\n{facts}")
    return "\n".join(sections)


def _current_character_state(card: dict[str, Any]) -> dict[str, Any]:
    """Project only the *current* state of a character.

    The writer prompt must not see the full role card
    (personality dumps, memory arrays, old chapter histories,
    or unrelated characters). The model needs identity, role,
    location, and the current ``real_state`` / ``game_state``
    namespaces so the prose can stay consistent with the
    established facts without re-deriving them.
    """
    state: dict[str, Any] = {}
    for namespace in ("current_state", "real_state", "game_state"):
        value = card.get(namespace)
        if isinstance(value, dict):
            current = value.get("current") if isinstance(value.get("current"), dict) else value
            if current:
                state[namespace] = current
    # These fields are already chapter-bounded by the writer context builder.
    # Keep them in the same explicit state slice so the prompt cannot confuse
    # author-only canon with what a character actually knows.
    for field in ("progression", "equipment", "relationships"):
        value = card.get(field)
        if value not in (None, "", [], {}):
            state[field] = value
    return state


def _relevant_character_names(request: WriterRequest) -> set[str]:
    artifact = request.director_artifact
    text_parts = [
        artifact.chapter_goal,
        artifact.opening_state,
        artifact.ending_state,
        artifact.hook,
    ]
    for beat in artifact.scene_beats:
        text_parts.extend((beat.location, beat.action, beat.result))
    text_parts.extend(item.name for item in artifact.entity_requirements)
    artifact_text = "\n".join(text_parts)

    relevant: set[str] = set()
    for card in request.character_cards:
        name = str(card.get("name") or "").strip()
        role = str(card.get("role") or "").strip().casefold()
        tier = str(card.get("character_tier") or "").strip().casefold()
        if name and (
            name in artifact_text
            or tier == "protagonist"
            or role in {"主角", "protagonist"}
        ):
            relevant.add(name)
    return relevant


def _compact_character_direction(card: dict[str, Any]) -> list[str]:
    details: list[str] = []
    identity = card.get("identity_profile")
    if isinstance(identity, dict):
        current_identity = str(identity.get("current_identity") or "").strip()
        occupation = str(identity.get("occupation") or "").strip()
        identity_text = current_identity or occupation
        if identity_text:
            details.append(f"身份：{identity_text}")

    performance = card.get("performance_profile")
    if not isinstance(performance, dict):
        performance = {}
    speech_style = str(
        performance.get("speech_style") or card.get("speech_style") or ""
    ).strip()
    action_style = str(performance.get("action_style") or "").strip()
    if speech_style:
        details.append(f"说话：{speech_style}")
    if action_style:
        details.append(f"行动：{action_style}")
    decision_rules = performance.get("decision_rules")
    if isinstance(decision_rules, list):
        rules = [str(item).strip() for item in decision_rules if str(item).strip()][:2]
        if rules:
            details.append("决定依据：" + "；".join(rules))
    return details


def _render_character_cards(request: WriterRequest) -> str:
    relevant_names = _relevant_character_names(request)
    active_cards = [
        card
        for card in request.character_cards
        if card.get("lifecycle") != "retired"
        and str(card.get("name") or "").strip() in relevant_names
    ]
    if not active_cards:
        return ""
    blocks: list[str] = ["## 角色当前状态（仅活动角色）"]
    for card in active_cards:
        name = card.get("name", "未命名")
        role = card.get("role", "")
        header = f"- **{name}**（{role or '?'}）"
        current_state = _current_character_state(card)
        if current_state:
            header += " · 状态：" + json.dumps(
                current_state, ensure_ascii=False, separators=(",", ":")
            )
        blocks.append(header)
        for detail in _compact_character_direction(card):
            blocks.append(f"  {detail}")
        knowledge = card.get("knowledge")
        if knowledge:
            blocks.append(
                "  角色已知（仅结构化事实，不等同于作者隐藏信息）："
                + json.dumps(knowledge, ensure_ascii=False, separators=(",", ":"))
            )
        boundary = card.get("knowledge_boundary")
        if boundary:
            boundary_text = "、".join(str(item) for item in boundary)
            blocks.append(f"  知情边界：{boundary_text}")
    return "\n".join(blocks)


def _render_entity_cards(request: WriterRequest) -> str:
    active_entities = [
        card
        for card in request.entity_cards
        if card.get("lifecycle") != "retired"
        and (
            str(card.get("kind") or "").strip() not in {"", "entity"}
            or bool(str(card.get("summary") or "").strip())
        )
    ]
    if not active_entities:
        return ""
    blocks: list[str] = ["## 活动实体卡"]
    for card in active_entities:
        kind = card.get("kind", "entity")
        name = card.get("name", "未命名")
        summary = card.get("summary", "")
        blocks.append(f"- {kind} **{name}**：{summary}")
    return "\n".join(blocks)


def _render_world_rules(request: WriterRequest) -> str:
    if not request.world_rules:
        return ""
    return "## 世界规则\n" + "\n".join(f"- {rule}" for rule in request.world_rules)


def _render_craft_modules(request: WriterRequest) -> str:
    if not request.craft_modules:
        return ""
    blocks: list[str] = ["## 写手 Craft 模块"]
    for module in request.craft_modules:
        mid = module.get("id", "?")
        content = module.get("content", "")
        blocks.append(f"- {mid}：{content}")
    return "\n".join(blocks)


def build_writer_prompt(request: WriterRequest) -> str:
    """Render a self-contained writer prompt from a ``WriterRequest``.

    The prompt contains exactly the slices the director approved:
    the director artifact, the previous chapter handoff, the
    active character and entity cards, the scene-tagged world
    rules, and the selected craft modules. Internal trace
    markers, retired entities, and unrelated cards must never
    leak in.
    """
    target_min = int(request.target_chars.get("min", CHAPTER_TARGET_MIN_CHARS))
    target_max = int(request.target_chars.get("max", CHAPTER_TARGET_MAX_CHARS))
    hard_min = int(request.acceptance_chars.get("min", CHAPTER_HARD_MIN_CHARS))
    hard_max = int(request.acceptance_chars.get("max", CHAPTER_HARD_MAX_CHARS))
    sections: list[str] = [
        "你是小说写手。只能输出连续小说正文，不要输出标题、提纲、检查说明。",
        "",
        "## 成稿要求\n"
        "- 直接写人物在场景中的行动、观察和交流，不要用报告口吻复述剧情。\n"
        "- 对话要接住对方的话并表达完整意思；不要把正常口语压成并列词组或故作高深的短句。\n"
        "- 描写只保留会影响人物判断、情绪或后续行动的细节；整章只在必要处保留一两处比喻，其余直接写动作和结果。\n"
        "- 文书、面板或记录最多摘三行，只保留会改变人物判断的字段；不照抄完整经过、后台字段和处理说明。\n"
        "- 除非本章明确要求恐怖细节，不细写暴露的器官、体液或尸体状态，用人物反应和现场后果呈现危险。\n"
        "- 不要替读者总结人物心理、手段效果或场面意义，让正文中的行动和反应自行说明。\n"
        "- 动作之后不要追加作者判词；删掉“可谓……”“这就是……”或“世界观被击碎”一类替读者下结论的句子。\n"
        "- 按场景节拍分配篇幅，核心异常和章末钩子必须在目标篇幅内完整出现。\n"
        "- 严格停在导演给出的收尾状态，不自行推进到下一时间、地点或下一章行动。",
    ]
    if request.project_title or request.genre:
        sections.append(
            "## 项目元数据"
            + (f"\n书名：{request.project_title}" if request.project_title else "")
            + (f"\n题材：{request.genre}" if request.genre else "")
        )
    if request.rewrite_guidance.strip():
        sections.append(
            "## 本次写作指导（优先执行）\n" + request.rewrite_guidance.strip()
        )
    sections.append(_render_director_artifact(request))
    handoff = _render_previous_handoff(request)
    if handoff:
        sections.append(handoff)
    characters = _render_character_cards(request)
    if characters:
        sections.append(characters)
    entities = _render_entity_cards(request)
    if entities:
        sections.append(entities)
    rules = _render_world_rules(request)
    if rules:
        sections.append(rules)
    modules = _render_craft_modules(request)
    if modules:
        sections.append(modules)
    beat_count = max(1, len(request.director_artifact.scene_beats))
    beat_budget = max(1, target_max // beat_count)
    sections.append(
        f"## 篇幅\n"
        f"正文目标{target_min}至{target_max}字；"
        f"低于{hard_min}字或超过{hard_max}字不能交稿。\n"
        f"本章共{beat_count}个节拍，每个节拍平均不超过{beat_budget}字；"
        "一个节拍的结果写清后立即转入下一节拍，不重复解释同一判断。"
    )
    return "\n\n".join(sections)


__all__ = ["build_writer_prompt"]
