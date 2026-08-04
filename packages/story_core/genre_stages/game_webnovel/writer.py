from __future__ import annotations

import json
from dataclasses import replace
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.dual_state import project_character_for_scene, scene_kind_for_cards
from packages.story_core.genre_stages.common_writer import (
    WriterContext,
    build_common_writer_sections,
    prompt_json,
)
from packages.story_core.genre_types.game_webnovel import select_game_language_cards
from packages.story_core.memory import build_character_cards
from packages.story_core.prompt_templates import get_effective_prompt_template, render_prompt_template
from packages.story_core.web_game_author_craft import plain_writer_phrase, web_game_writer_method_lines
from packages.story_core.web_game_economy import normalize_legacy_economy_prompt_value
from packages.story_core.writing_packet import writing_power_system_context
from packages.story_core.writing_taskbook import first_chapter_whole_body_contract


def _game_genre_defaults(story: Any) -> dict[str, str]:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    protagonist_ledger = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
    protagonist = next(
        (
            character
            for character in story.characters
            if str(character.role or "").strip().lower() in {"protagonist", "主角"}
            or str(getattr(character, "character_tier", "") or "").strip().lower() == "protagonist"
        ),
        None,
    )
    game_id = str(protagonist_ledger.get("game_id") or "").strip()
    if not game_id and protagonist is not None:
        game_id = str(getattr(protagonist, "game_id", "") or "").strip()
    class_path = str(protagonist_ledger.get("class_path") or "").strip()
    if not class_path and protagonist is not None:
        class_path = str(getattr(getattr(protagonist, "game_panel", None), "profession", "") or "").strip()
    return {"game_id": game_id or "未命名角色", "class_path": class_path or "当前职业"}


def _planned_inventory_items(value: Any) -> set[str]:
    items: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            if key in {"inventory", "inventory_delta"} and isinstance(child, dict):
                items.update(str(name).strip() for name in child if str(name).strip())
            items.update(_planned_inventory_items(child))
    elif isinstance(value, list):
        for child in value:
            items.update(_planned_inventory_items(child))
    return items


def _monster_context_for_prompt(story: Any, plan: dict[str, Any], *, max_items: int = 3) -> list[dict[str, Any]]:
    relevance_text = json.dumps(plan if isinstance(plan, dict) else {}, ensure_ascii=False)
    planned_inventory = _planned_inventory_items(plan)
    selected: list[dict[str, Any]] = []
    for profile in story.monster_profiles if isinstance(story.monster_profiles, list) else []:
        if not isinstance(profile, dict):
            continue
        name = str(profile.get("name") or "").strip()
        if not name or name not in relevance_text:
            continue
        card = {
            key: profile.get(key)
            for key in ("name", "category", "rank", "level", "hp", "attack_mode", "skills", "traits", "habitats", "drops")
            if profile.get(key) not in (None, "", [], {})
        }
        if planned_inventory and isinstance(card.get("drops"), list):
            card["drops"] = [
                item
                for item in card["drops"]
                if str(item).split("：", 1)[0].split(":", 1)[0].strip() in planned_inventory
                or str(item).split("：", 1)[0].split(":", 1)[0].strip() in relevance_text
            ]
            if not card["drops"]:
                card.pop("drops")
        selected.append(card)
        if len(selected) >= max_items:
            break
    return selected


def _writer_monster_card_line(profile: dict[str, Any]) -> str:
    labels = {
        "category": "类别",
        "rank": "品阶",
        "level": "等级",
        "hp": "生命",
        "attack_mode": "攻击方式",
        "skills": "技能",
        "traits": "特性",
        "habitats": "出没地点",
        "drops": "可能掉落",
    }
    parts: list[str] = []
    for key, label in labels.items():
        value = profile.get(key)
        if value in (None, "", [], {}):
            continue
        rendered = "、".join(str(item) for item in value[:4]) if isinstance(value, list) else str(value)
        parts.append(f"{label}：{compact_text(rendered, 90)}")
    return f"{profile.get('name') or '未命名怪物'}（{'；'.join(parts)}）"


def _web_game_writing_method_lines(chapter_number: int, plan: dict[str, Any] | None = None) -> list[str]:
    normalized_plan = plan if isinstance(plan, dict) else {}
    return web_game_writer_method_lines(
        chapter_number,
        plan=normalized_plan,
        language_cards=select_game_language_cards(normalized_plan, max_cards=3),
    )


def _writer_state_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        metadata_keys = {"updated_chapter", "chapter_number", "revision", "schema_version"}
        return [
            item
            for key, nested in value.items()
            if key not in metadata_keys
            for item in _writer_state_values(nested)
        ]
    if isinstance(value, list):
        return [item for nested in value for item in _writer_state_values(nested)]
    return [] if value in (None, "", [], {}) else [compact_text(str(value), 80)]


def _augment_game_character_section(
    lines: list[str],
    character_context: dict[str, Any],
) -> list[str]:
    augmented = list(lines)
    cards = character_context.get("cards") if isinstance(character_context, dict) else []
    game_lines: list[str] = []
    for card in cards[:4] if isinstance(cards, list) else []:
        if not isinstance(card, dict):
            continue
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        name = str(identity.get("name") or identity.get("game_id") or "本章人物").strip()
        state_context = card.get("state_context") if isinstance(card.get("state_context"), dict) else {}
        for state_name, label in (("real_state", "现实状态"), ("game_state", "游戏状态")):
            state = state_context.get(state_name)
            current = state.get("current") if isinstance(state, dict) else None
            if isinstance(current, dict) and (values := _writer_state_values(current)):
                game_lines.append(f"{name}{label}：{'；'.join(values[:6])}")
    if game_lines:
        augmented = [augmented[0], *game_lines, *augmented[1:]]
    return augmented


def _raw_game_character_context(context: WriterContext, *, max_items: int = 4) -> dict[str, Any]:
    story, plan = context.story, context.plan
    raw_cards = {
        character.name: character.model_dump(mode="json")
        for character in story.characters
        if character.name
    }
    built_cards = build_character_cards(story)
    generic_by_name = {
        str((card.get("identity") or {}).get("name") or ""): card
        for card in context.character_context.get("cards", [])
        if isinstance(card, dict)
    }
    plan_text = json.dumps(plan, ensure_ascii=False, default=str)
    requested_names = {
        character.name
        for character in story.characters
        if character.name
        and (
            character.name in plan_text
            or (character.game_id and character.game_id in plan_text)
        )
    }
    chapter_intent = plan.get("chapter_intent") if isinstance(plan.get("chapter_intent"), dict) else {}
    governance = plan.get("governance") if isinstance(plan.get("governance"), dict) else {}
    governed_intent = governance.get("chapter_intent") if isinstance(governance.get("chapter_intent"), dict) else {}
    approved_new: set[str] = set()
    for source in (chapter_intent.get("approved_new_characters"), governed_intent.get("approved_new_characters")):
        for item in source if isinstance(source, list) else []:
            approved_new.add(str(item.get("name") if isinstance(item, dict) else item).strip())
    eligible_cards = [
        card
        for card in built_cards
        if (
            str(raw_cards.get(str((card.get("identity") or {}).get("name") or ""), {}).get("lifecycle_state") or "active")
            != "proposed"
            or str((card.get("identity") or {}).get("name") or "") in approved_new
        )
    ]
    selected = [
        card
        for card in eligible_cards
        if (
            not requested_names
            or str((card.get("identity") or {}).get("name") or "") in requested_names
        )
    ][:max_items]
    if not selected:
        selected = eligible_cards[:max_items]

    scene_cards = plan.get("scene_cards") if isinstance(plan.get("scene_cards"), list) else []
    scene_kind = scene_kind_for_cards(scene_cards, is_game_story=True)
    compact_cards: list[dict[str, Any]] = []
    for card in selected:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        name = str(identity.get("name") or "").strip()
        raw = raw_cards.get(name, {})
        base = dict(generic_by_name.get(name, {}))
        if not base:
            profile = card.get("webnovel_profile") if isinstance(card.get("webnovel_profile"), dict) else {}
            usage = card.get("story_usage") if isinstance(card.get("story_usage"), dict) else {}
            chapter_usage = usage.get("this_chapter_usage") if isinstance(usage.get("this_chapter_usage"), dict) else {}
            voice = card.get("voice_and_action") if isinstance(card.get("voice_and_action"), dict) else {}
            base = {
                "identity": {
                    "name": name,
                    "role": identity.get("role", ""),
                    "location": compact_text(str(identity.get("location", "")), 60),
                },
                "motivation": compact_text(str(profile.get("core_motivation", "")), 120),
                "behavior_logic": compact_text(str(profile.get("behavior_logic", "")), 120),
                "interaction_mode": compact_text(str(profile.get("interaction_mode", "")), 120),
                "goals": compact_list(raw.get("goals", []), max_items=2, item_chars=120),
                "speech_tendency": compact_text(str(chapter_usage.get("speech_tendency", "")), 100),
                "action_tendency": compact_text(str(chapter_usage.get("action_tendency", "")), 100),
                "risk_posture": compact_text(str(voice.get("risk_posture", "")), 100),
                "speech_style": compact_text(str(voice.get("speech_style", "")), 100),
            }
        base_identity = dict(base.get("identity") or {})
        base_identity["game_id"] = identity.get("game_id") or raw.get("game_id") or ""
        base["identity"] = base_identity
        source = dict(card)
        for key in ("real_state", "game_state", "game_panel", "secrets", "story_drive", "relationship_notes"):
            if key in raw:
                source[key] = raw[key]
        base["state_context"] = project_character_for_scene(source, scene_kind=scene_kind)["state_context"]
        compact_cards.append(base)
    return {"cards": compact_cards, "scene_kind": scene_kind}


def prepare_game_writer_context(*, context: WriterContext) -> WriterContext:
    return replace(context, character_context=_raw_game_character_context(context))


def _augment_game_direction_section(lines: list[str], context: WriterContext) -> list[str]:
    lines = list(lines)
    plan = context.plan
    director_card = plan.get("web_game_director_card")
    simulation_plan = plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}
    if not isinstance(director_card, dict):
        director_card = simulation_plan.get("web_game_director_card")
    if isinstance(director_card, dict):
        fact_locks = director_card.get("fact_locks") if isinstance(director_card.get("fact_locks"), list) else []
        bans = director_card.get("boundary_chapter_bans") if isinstance(director_card.get("boundary_chapter_bans"), list) else []
        if director_card.get("one_line") or director_card.get("read_feel"):
            lines.append(compact_text(plain_writer_phrase(str(director_card.get("one_line") or director_card.get("read_feel"))), 120))
        if fact_locks:
            lines.append(f"事实锁：{'；'.join(str(item) for item in fact_locks[:4])}")
        if bans:
            lines.append(f"本章先不写：{'、'.join(str(item) for item in bans[:5])}")
    if context.chapter_number == 1:
        governance = plan.get("governance") if isinstance(plan.get("governance"), dict) else {}
        intent = governance.get("chapter_intent") if isinstance(governance.get("chapter_intent"), dict) else {}
        contract = first_chapter_whole_body_contract(
            game_genre=True,
            trade_authorized=bool(intent.get("first_chapter_trade_authorized")),
        )
        lines.extend(["本章按连续正文一次完成。", f"整章顺序：{contract['beat_map']}。"])
    return lines


def _game_fact_lines(context: WriterContext) -> list[str]:
    story, plan = context.story, context.plan
    lines: list[str] = []
    corpus = "\n".join(
        [
            *[str(item) for item in story.world_facts],
            *[str(item) for item in story.author_constraints],
            str(story.outline or ""),
            json.dumps(story.outline_context or {}, ensure_ascii=False),
        ]
    )
    anomaly_anchors: list[str] = []
    if "底层协议校验" in corpus:
        anomaly_anchors.append("底层协议校验通过")
    if "千倍爆率" in corpus or "掉落判定×1000" in corpus:
        anomaly_anchors.append("千倍爆率")
    if "混沌之种" in corpus and "未解析" in corpus:
        anomaly_anchors.append("混沌之种：未解析")
    if anomaly_anchors:
        lines.append(f"本章异常锚点（按项目原文露出）：{'、'.join(anomaly_anchors)}。")
        if context.chapter_number == 1:
            lines.append(
                "异常露出顺序：登录时只出现短暂协议异常或乱码，不能显示优势名称和倍率；"
                "首次有效掉落后，再显示底层协议校验、掉落判定×1000和混沌之种未解析，并让主角先惊讶、再怀疑、再验证。"
            )

    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    numeric_plan = event_plan.get("numeric_plan") if isinstance(event_plan.get("numeric_plan"), dict) else {}
    if numeric_plan:
        lines.append(
            "本章数值账本（只用于保证正文前后一致，不要解释规则）："
            f"{prompt_json(numeric_plan)}。正文不得另编经验、生命、伤害、成交、兑换、手续费、到账或余额；"
            "只写角色能看到的关键结算结果，不要把乘加算式写进正文，也不要逐项复述账本。"
        )
    allocation = event_plan.get("attribute_allocation_decision") if isinstance(event_plan.get("attribute_allocation_decision"), dict) else {}
    mode = str(allocation.get("mode") or "").strip().lower()
    if mode == "allocate":
        allocations = allocation.get("allocations") if isinstance(allocation.get("allocations"), dict) else {}
        rendered = "、".join(f"{name}+{value}" for name, value in allocations.items() if str(name).strip() and str(value).strip())
        if rendered:
            ending = "，可用点归零" if allocation.get("remaining") in (0, "0") else ""
            reason = compact_text(str(allocation.get("reason") or ""), 60)
            lines.append(
                f"本章属性点决定：{rendered}{ending}。正文写出角色打开属性面板并确认加点{'，目的为' + reason if reason else ''}。"
                "用正常动作写成‘把五点都加到智力上’一类完整表达，不要写成“自由分配属性”或用抽象说明代替操作结果。"
                "全章只执行一次加点，必须发生在章节计划安排的升级或属性处理节点；不得在建号或接任务时提前获得属性点。"
            )
    elif mode == "carry":
        reason = compact_text(str(allocation.get("reason") or ""), 60)
        lines.append(f"本章属性点决定：暂不分配，保留{allocation.get('remaining')}点。正文写出角色主动保留的决定{'，原因是' + reason if reason else ''}。")

    power_system = plan.get("power_system") if isinstance(plan.get("power_system"), dict) and plan.get("power_system") else writing_power_system_context(story)
    if power_system:
        lines.append(f"本章力量体系契约：{prompt_json(power_system)}")
        lines.append("力量连续性检查：不得虚构技能或装备，不得免费晋升，不得制造不可能的等级差；解锁、消耗和状态变化必须与连续性账本一致。")
    monster_cards = _monster_context_for_prompt(story, plan)
    if monster_cards:
        lines.append("本章怪物卡：" + "；".join(_writer_monster_card_line(card) for card in monster_cards))
    inventory = sorted(_planned_inventory_items(plan))
    if inventory:
        lines.append(f"本章普通掉落账本：{'、'.join(inventory)}。未列入账本的普通材料不要新增或带到章末。")
    defaults = _game_genre_defaults(story)
    protagonist = []
    if defaults["game_id"] != "未命名角色":
        protagonist.append(f"游戏ID为{defaults['game_id']}")
    if defaults["class_path"] != "当前职业":
        protagonist.append(f"当前身份为{defaults['class_path']}")
    if protagonist:
        lines.append(f"游戏主角：{'，'.join(protagonist)}。")
    anchors = context.chapter_seed.get("本章硬锚点") if isinstance(context.chapter_seed.get("本章硬锚点"), dict) else {}
    opening = str(anchors.get("opening_balance") or "").strip()
    arrival = str(anchors.get("trade_arrival") or "").strip()
    ending = str(anchors.get("ending_balance") or "").strip()
    if opening and arrival and ending:
        lines.append(
            f"金额顺序：登录前现实余额{opening}；交易完成后净到账{arrival}；先完成本章安排的现实支出，"
            f"支付完成后才写章末余额{ending}。净到账{arrival}不能同时写成成交总价；如果另写手续费，成交总价必须等于净到账加手续费。"
        )
    return lines


def augment_game_writer_sections(
    context: WriterContext,
    sections: dict[str, list[str]],
) -> dict[str, list[str]]:
    augmented = {key: list(lines) for key, lines in sections.items()}
    game_context = prepare_game_writer_context(context=context)
    augmented["chapter_direction"] = _augment_game_direction_section(
        augmented["chapter_direction"],
        context,
    )
    augmented["chapter_facts"][1:1] = _game_fact_lines(context)
    augmented["character_context"] = _augment_game_character_section(
        augmented["character_context"],
        game_context.character_context,
    )
    augmented["prose_method"][10:10] = _web_game_writing_method_lines(
        context.chapter_number,
        context.plan,
    )
    return augmented


def render_game_writer_prompt_raw(*, context: WriterContext) -> str:
    common_sections = build_common_writer_sections(
        replace(context, include_genre_method=False)
    )
    sections = augment_game_writer_sections(context, common_sections)
    return render_prompt_template(
        get_effective_prompt_template("writer"),
        {key: "\n".join(lines) for key, lines in sections.items()},
    ).strip()


def render_game_writer_prompt(*, context: WriterContext) -> str:
    rendered = render_game_writer_prompt_raw(context=context)
    return normalize_legacy_economy_prompt_value(rendered, game_context=True, chapter_number=context.chapter_number)
