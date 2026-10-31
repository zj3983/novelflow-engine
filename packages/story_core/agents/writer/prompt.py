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

from packages.story_core.book_style import render_book_writing_preferences
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
    ]
    contract = artifact.outline_contract
    if contract is not None:
        lines.extend(
            [
                "",
                "## 上游章节执行合同（必须落实，不得擅自改写）",
                f"核心冲突：{contract.core_conflict or '（未提供）'}",
                f"开场承接：{contract.opening_carry or '（未提供）'}",
                f"本章收益：{contract.gain or '（未提供）'}",
                f"本章代价：{contract.cost or '（未提供）'}",
                f"目标状态变化：{contract.state_delta or '（未提供）'}",
                f"中段反馈：{contract.mid_feedback or '（未提供）'}",
                f"计划转折：{contract.planned_turn or '（未提供）'}",
                f"计划章末钩子：{contract.planned_hook or '（未提供）'}",
            ]
        )
        if contract.payoff_contract:
            lines.append(
                "收益合同："
                + "；".join(
                    f"{key}={value}"
                    for key, value in contract.payoff_contract.items()
                )
            )
        if contract.must_not_write:
            lines.append("禁止提前写：" + "；".join(contract.must_not_write))
        lines.extend(
            [
                "合同规则：必须兑现收益与代价，落地目标状态变化；不得提前写入禁止事项；"
                "章末必须让计划钩子在正文末段出现。",
                "下方人物意图只包括 Director 最终保留或改写的 scene-level intents；"
                "不要从其他角色提案补回已删除、延后、阻断或被要求保持沉默的行为。",
            ]
        )
    lines.extend(["", "## 场景节拍"])
    for beat in artifact.scene_beats:
        lines.append(
            f"- 顺序{beat.order} · 地点：{beat.location} · 目的：{beat.purpose} · 冲突：{beat.conflict} · "
            f"参与者：{', '.join(beat.participants)} · 动作：{beat.action} · 结果：{beat.result}"
        )
        if beat.purpose:
            lines.append(f"  场景目的：{beat.purpose}")
        if beat.conflict:
            lines.append(f"  冲突：{beat.conflict}")
        if beat.participants:
            lines.append(f"  参与人物：{'、'.join(beat.participants)}")
        for intent in beat.character_intents:
            parts = [
                f"{intent.name}想要：{intent.want}" if intent.want else intent.name,
                f"对象：{intent.target}" if intent.target else "",
                f"情绪：{intent.emotion}" if intent.emotion else "",
                f"行动：{intent.move}" if intent.move else "",
                f"说话策略：{intent.speech_strategy}" if intent.speech_strategy else "",
                f"不说出口：{intent.withhold}" if intent.withhold else "",
                f"受阻后：{intent.reaction}" if intent.reaction else "",
                f"戏剧功能：{intent.dramatic_function}" if intent.dramatic_function else "",
            ]
            lines.append("  人物意图：" + "；".join(part for part in parts if part))
        if beat.emotional_turn:
            lines.append(f"  情绪转折：{beat.emotional_turn}")
        if beat.relationship_shift:
            lines.append(f"  关系变化：{beat.relationship_shift}")
        if beat.ending_pressure:
            lines.append(f"  收尾压力：{beat.ending_pressure}")
        if beat.next_pressure:
            lines.append(f"  下一步（如有）：{beat.next_pressure}")
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


def _render_outline_contract(request: WriterRequest) -> str:
    contract = request.director_artifact.outline_contract
    if contract is None:
        return ""
    return "\n".join(
        [
            "## 上游章节执行合同",
            f"开场必须承接：{contract.opening_carry}",
            f"核心冲突：{contract.core_conflict}",
            f"本章必须推进：{contract.state_delta}",
            f"本章必须获得：{contract.gain}",
            f"本章已确定的成本：{contract.cost or '无新增代价'}",
            f"本章情绪方向：{contract.emotional_change or '依人物处境自然变化，不默认升级紧张'}",
            f"本章最终状态变化：{contract.state_delta}",
            f"中段反馈：{contract.mid_feedback}",
            f"计划转折：{contract.planned_turn}",
            f"本章禁止提前解决：{'；'.join(contract.must_not_write)}",
            f"章末必须交出：{contract.planned_hook}",
            f"收益合同：{contract.payoff_contract}",
            "Director scene beats 是执行步骤；本合同是剧情边界。planned_hook 需自然落地，不能机械照抄，"
            "也不能越过本章 ending boundary 去解决后续内容。",
            "若导演的动作强度、人物意图、情绪或下一步压力与本合同冲突，以本合同为准：保留事件和结果，"
            "自行纠正不相符的表达方式。导演新增的喝令、恐吓、暴力扣腕或反复伤痛不是必须执行的事实。"
            "原有险情与真实战斗后果仍需兑现，不能将所有章节一律写得轻松。",
            "已有伤势只需保持连续，不强制恶化；正常时间和资源消耗不自动升级为生死危机。未规划新增成本时不得额外追加损失。按本章情绪方向呈现耐心、缓和、信任或满足，不用反复呵斥、惊惧和伤痛证明情节有分量。",
        ]
    )


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
    return state


def _relevant_character_names(request: WriterRequest) -> set[str]:
    artifact = request.director_artifact
    text_parts = [
        artifact.chapter_goal,
        artifact.opening_state,
        artifact.ending_state,
        artifact.hook,
    ]
    explicit_intent_names: set[str] = set()
    for beat in artifact.scene_beats:
        text_parts.extend(
            (
                beat.location,
                beat.action,
                beat.result,
                beat.purpose,
                beat.conflict,
                beat.emotional_turn,
                beat.relationship_shift,
                beat.ending_pressure,
                beat.next_pressure,
            )
        )
        text_parts.extend(beat.participants)
        for intent in beat.character_intents:
            explicit_intent_names.add(str(intent.name or "").strip())
            text_parts.extend(
                (
                    intent.name,
                    intent.target,
                    intent.want,
                    intent.move,
                    intent.speech_strategy,
                )
            )
    text_parts.extend(item.name for item in artifact.entity_requirements)
    artifact_text = "\n".join(text_parts)

    relevant: set[str] = set()
    for card in request.character_cards:
        name = str(card.get("name") or "").strip()
        role = str(card.get("role") or "").strip().casefold()
        tier = str(card.get("character_tier") or "").strip().casefold()
        if name and (
            name in explicit_intent_names
            or name in artifact_text
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

    drive = card.get("story_drive")
    if isinstance(drive, dict):
        immediate_goal = str(drive.get("immediate_goal") or "").strip()
        if immediate_goal:
            details.append(f"当前追求：{immediate_goal[:120]}")

    portrait = card.get("personality_portrait")
    if isinstance(portrait, dict):
        behavior = portrait.get("behavior") if isinstance(portrait.get("behavior"), dict) else {}
        voice = portrait.get("voice") if isinstance(portrait.get("voice"), dict) else {}
        pressure = str(behavior.get("pressure_mode") or "").strip()
        conflict = str(behavior.get("conflict_response") or "").strip()
        sentence_habit = str(voice.get("sentence_habit") or "").strip()
        anger_style = str(voice.get("anger_style") or "").strip()
        if pressure:
            details.append(f"受压反应：{pressure[:100]}")
        if conflict:
            details.append(f"冲突反应：{conflict[:100]}")
        if sentence_habit:
            details.append(f"句式习惯：{sentence_habit[:100]}")
        if anger_style:
            details.append(f"生气时：{anger_style[:100]}")
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


def _render_writing_preferences(request: WriterRequest) -> str:
    return render_book_writing_preferences(
        request.writing_style, request.writing_guidance, request.writing_reference
    )


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
        "- 对话服从人物当前目的和关系，不要求每个人完整表达逻辑；人物可以打断、沉默、回避、反问、故意误解、答非所问、转移话题、用动作回应或不回应。需要交代事实时，仍要使用自然完整的中文。\n"
        "- 禁止为了体现群像而让出场人物依次发表观点。\n"
        "- character_intents 是作者侧写作控制，不是角色公开说出的事实；want、withhold、emotional_turn 不得直接改写成旁白解释。优先通过动作、停顿、措辞、答非所问、回避、抢话、距离变化、关注点和选择让读者看出来。\n"
        "- 优先级：上游章节执行合同 > 导演公开场景计划 > Director 最终 scene-level character intents；只执行场景节拍中最终保留或改写的人物意图。\n"
        "- Director 最终人物意图只能控制行动、台词、停顿、潜台词和受阻后的反应；不得改写收益、代价、状态变化、禁止事项或章末钩子。\n"
        "- 描写只保留会影响人物判断、情绪或后续行动的细节；整章只在必要处保留一两处比喻，其余直接写动作和结果。\n"
        "- 文书、面板或记录最多摘三行，只保留会改变人物判断的字段；不照抄完整经过、后台字段和处理说明。\n"
        "- 除非本章明确要求恐怖细节，不细写暴露的器官、体液或尸体状态，用人物反应和现场后果呈现危险。\n"
        "- 不要替读者总结人物心理、手段效果或场面意义，让正文中的行动和反应自行说明。\n"
        "- 动作之后不要追加作者判词；删掉“可谓……”“这就是……”或“世界观被击碎”一类替读者下结论的句子。\n"
        "- 按场景节拍分配篇幅，核心异常和章末钩子必须在目标篇幅内完整出现。\n"
        "- 严格停在导演给出的收尾状态，不自行推进到下一时间、地点或下一章行动。",
    ]
    preferences = _render_writing_preferences(request)
    if preferences:
        sections.append(preferences)
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
    contract = _render_outline_contract(request)
    if contract:
        sections.append(contract)
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
    token_budget = getattr(request, "draft_token_budget", None) or {}
    planning_chars = int(token_budget.get("planned_chars") or (target_min + target_max) // 2)
    beat_budget = max(1, planning_chars // beat_count) if token_budget else max(1, target_max // beat_count)
    sections.append(
        f"## 篇幅\n"
        f"正文目标{target_min}至{target_max}字；"
        f"低于{hard_min}字或超过{hard_max}字不能交稿。\n"
        "计数按去除空白后的字符数：汉字、标点、数字和英文字母均各计1个字符；空格、换行不计。"
        "token数不能代替字符数，分词方式不同；没有当前模型实测数据时不使用固定比例换算，已有校准也仅用于规划。\n"
        f"先按约{planning_chars}个字符安排整章，不把{target_max}字上限当作必须写满的目标。"
        "达到最低字数后，情节已经完整就收尾，不为靠近目标或上限补写。"
        "对白、环境、动作、转场和收尾都包含在同一份篇幅预算内。\n"
        f"本章共{beat_count}个节拍，每个节拍平均不超过{beat_budget}字；"
        "一个节拍的结果写清后立即转入下一节拍，不重复解释同一判断。"
    )
    if token_budget:
        tokens = int(token_budget["tokens"])
        sections.append(
            "## 当前模型实测的首稿输出预算\n"
            f"本章可见正文按约{tokens}个输出token规划，来自当前模型{token_budget['sample_count']}次中文正文实测。"
            "这份预算只用于最终可见正文，不包含输入及内部思考token。"
            f"按约{planning_chars}字收束，少写重复反应、解释和文书；优先确保场景结果与章末钩子写完。"
            f"{beat_count}个节拍平均约{max(1,tokens//beat_count)} token，"
            f"其中至少预留{max(1,int(tokens*.12))} token给最终转折和收尾，全部合计包含在{tokens} token预算中。"
            "这是当前模型的估算规划，最终仍按程序实测字符验收。只输出正文，不输出预算或计数说明。"
        )
    return "\n\n".join(sections)


__all__ = ["build_writer_prompt"]
