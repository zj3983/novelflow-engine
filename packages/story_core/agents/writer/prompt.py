"""Writer prompt assembly for the modular agent.

The prompt is rendered from the typed ``WriterRequest`` only —
it never reaches back into the story state, the project root,
or the orchestrator's bag of helpers. The result is a stable
string the runtime can send to whichever transport is plugged
in.
"""

from __future__ import annotations

from typing import Any

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


def _render_character_cards(request: WriterRequest) -> str:
    active_cards = [card for card in request.character_cards if card.get("lifecycle") != "retired"]
    if not active_cards:
        return ""
    blocks: list[str] = ["## 角色卡（仅活动角色）"]
    for card in active_cards:
        name = card.get("name", "未命名")
        role = card.get("role", "")
        location = card.get("location", "")
        state = card.get("current_state", "")
        notes = card.get("behavioral_notes", "")
        header = f"- **{name}**（{role or '?'}）"
        if location:
            header += f" · 位置：{location}"
        if state:
            header += f" · 状态：{state}"
        blocks.append(header)
        if notes:
            blocks.append(f"  行为习惯：{notes}")
        if card.get("knowledge_boundary"):
            boundary = "、".join(str(item) for item in card["knowledge_boundary"])
            blocks.append(f"  知情边界：{boundary}")
    return "\n".join(blocks)


def _render_entity_cards(request: WriterRequest) -> str:
    active_entities = [card for card in request.entity_cards if card.get("lifecycle") != "retired"]
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
    sections: list[str] = [
        "你是小说写手。只能输出连续小说正文，不要输出标题、提纲、检查说明。",
        "",
        _render_director_artifact(request),
    ]
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
    sections.append(
        "只输出正文（控制在目标篇幅内），不要复述提示词，不要输出修改说明。"
    )
    return "\n\n".join(sections)


__all__ = ["build_writer_prompt"]
