from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.chapter_governance import governance_quality_gate
from packages.story_core.chapter_length_policy import (
    CHAPTER_TARGET_MAX_CHARS,
    CHAPTER_TARGET_MIN_CHARS,
)
from packages.story_core.chapter_seed import build_chapter_seed
from packages.story_core.character_profiles import normalize_speech_style_for_writing
from packages.story_core.craft import is_game_story
from packages.story_core.novel_type_catalog import (
    normalize_novel_type_id,
    normalize_novel_type_ids,
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.prompt_modules import replaceable_slots
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.writing_taskbook import ensure_writing_taskbook, writer_facing_text
from packages.story_core.world_blueprint_context import flatten_selected_rules


@dataclass(frozen=True)
class WriterContext:
    story: Any
    chapter_number: int
    plan: dict[str, Any]
    style_guidance: dict[str, Any]
    character_context: dict[str, Any]
    dialogue_context: dict[str, Any]
    chapter_seed: dict[str, Any]
    skill_context: dict[str, Any]
    include_genre_method: bool
    writer_plan_for_prompt: dict[str, Any]
    world_facts_for_prompt: list[str]
    trope_guidance: list[str]
    trope_contract_for_prompt: dict[str, Any]


def _plain_writer_phrase(value: str) -> str:
    return writer_facing_text(str(value or ""))


def _prompt_payload(value: Any) -> Any:
    if isinstance(value, str):
        return _plain_writer_phrase(value)
    if isinstance(value, list):
        return [_prompt_payload(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _prompt_payload(item) for key, item in value.items()}
    return value


def prompt_json(value: Any) -> str:
    return json.dumps(_prompt_payload(value), ensure_ascii=False)


def _plain_world_rule_phrase(value: str) -> str:
    return str(value or "")


def _runtime_novel_type_for_story(story: Any) -> Any:
    for genre_id in normalize_novel_type_ids(story.genre_plugin_ids):
        record = runtime_novel_type(genre_id)
        if record is not None:
            return record
    return runtime_novel_type(story.genre)


def _genre_family(story: Any, plan: dict[str, Any] | None = None) -> str:
    record = _runtime_novel_type_for_story(story)
    if record is not None and record.builtin is False:
        return "general"
    explicit_genre = normalize_novel_type_id(story.genre)
    if explicit_genre in {"xuanhuan", "xianxia"}:
        return explicit_genre
    text = f"{story.genre} {story.style} {story.outline}".lower()
    if any(token in text for token in ("悬疑", "推理", "案", "调查", "失踪")):
        return "suspense"
    if any(token in text for token in ("都市", "职场", "现实", "家庭")):
        return "urban"
    if any(token in text for token in ("玄幻", "修仙", "仙侠", "武道", "宗门")):
        return "fantasy"
    return "general"


def _genre_context_for_prompt(story: Any, chapter_number: int, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    family = _genre_family(story, plan)
    record = _runtime_novel_type_for_story(story)
    context: dict[str, Any] = {
        "genre": story.genre,
        "style": story.style,
        "genre_family": family,
    }
    if family == "suspense":
        context.update(
            genre_method=[
                "悬疑写法：每章只解开一个小问题，同时留下一个更具体的新疑点。",
                "线索要落到物件、时间、证词、地点矛盾和人物反应上，不要靠作者直接解释。",
                "人物不能全知；新的信息要通过调查、询问、观察或误导逐步出现。",
            ],
            surface_objects=["证词", "物件", "时间点", "地点", "记录", "反应"],
        )
    elif family in {"xuanhuan", "xianxia"}:
        seed = build_chapter_seed(story, chapter_number)
        rulebook = seed.get("rulebook") if isinstance(seed.get("rulebook"), dict) else {}
        context.update(
            genre_plugins=list(seed.get("genre_plugins") or []),
            genre_method=compact_list(
                [
                    *list(rulebook.get("progression_rules") or []),
                    *list(rulebook.get("faction_rules") or []),
                    *list(rulebook.get("chapter_formula") or []),
                ],
                max_items=6,
                item_chars=150,
            ),
            surface_objects=(
                ["境界", "资源", "异常物件", "力量反馈", "势力关系", "世界秘密"]
                if family == "xuanhuan"
                else ["境界", "灵气", "功法", "丹药", "法宝", "因果"]
            ),
        )
    elif family == "fantasy":
        context.update(
            genre_method=[
                "玄幻/修仙写法：成长要有境界、资源、代价和外部压力，不要无代价顿悟。",
                "能力变化要落到身体反应、招式效果、资源消耗、旁人判断和下一层阻碍。",
                "势力反应要按信息可见性推进，不要让高层无缘无故全知。",
            ],
            surface_objects=["境界", "功法", "资源", "伤势", "法器", "势力规矩"],
        )
    else:
        context.update(
            genre_method=[
                "通用写法：本章只推进一个主要目标，冲突来自人物欲望、信息差、规则和代价。",
                "每个场景都要有动作、反馈和选择，不要写成设定说明。",
                "章末留下具体下一步，让读者知道主角马上要面对什么。",
            ],
            surface_objects=["地点", "物件", "关系", "线索", "代价", "选择"],
        )
    if record is not None and record.builtin is False:
        description = novel_type_prompt_context(record).get("genre_description", "")
        if description:
            context["genre_method"] = list(dict.fromkeys([description, *context["genre_method"]]))[:3]
    return context


def _genre_context_summary_for_prompt(context: dict[str, Any], *, include_method: bool = True) -> dict[str, Any]:
    if not isinstance(context, dict):
        return {}
    return {
        "genre_family": context.get("genre_family"),
        "surface_objects": context.get("surface_objects", [])[:6] if isinstance(context.get("surface_objects"), list) else [],
        "genre_method": context.get("genre_method", [])[:4] if include_method and isinstance(context.get("genre_method"), list) else [],
    }


def _skill_context_for_prompt(story: Any, purposes: tuple[str, ...]) -> dict[str, Any]:
    skill_ids = [str(item).strip() for item in getattr(story, "enabled_skill_ids", []) if str(item).strip()]
    if not skill_ids:
        return {}
    module_ids = [
        str(item).strip()
        for item in getattr(story, "enabled_skill_module_ids", [])
        if str(item).strip()
    ]
    if not module_ids:
        module_ids = None
    selected: dict[str, Any] = {}
    replaceable = replaceable_slots()
    replaced_defaults: list[str] = []
    for purpose in purposes:
        skill_kwargs: dict[str, Any] = {
            "purpose": purpose,
            "max_chars_per_pack": 1800,
        }
        if module_ids is not None:
            skill_kwargs["enabled_module_ids"] = module_ids
        context = skill_pack_prompt_context(skill_ids, **skill_kwargs)
        if context:
            selected[purpose] = context
            if purpose in replaceable:
                replaced_defaults.append(replaceable[purpose])
    if replaced_defaults:
        selected["_replaced_defaults"] = sorted(set(replaced_defaults))
    return selected


def _compact_prompt_text(value: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", str(value or "")).strip()
    return cleaned if len(cleaned) <= limit else f"{cleaned[: max(1, limit - 1)]}…"


def _compact_writer_taskbook_section(taskbook: dict[str, Any]) -> str:
    taskbook = taskbook if isinstance(taskbook, dict) else {}
    lines = ["## 本章方向"]
    scenes = [item for item in taskbook.get("scenes", []) if isinstance(item, dict)][:3]
    goal = _plain_writer_phrase(str(taskbook.get("chapter_goal") or ""))
    if goal in {"", "完成本章推进", "推进当前目标"} and scenes:
        goal = _plain_writer_phrase(str(scenes[0].get("goal") or "")).split("；阻力是", 1)[0].strip("。； ")
    lines.append(f"目标：{_compact_prompt_text(goal or '承接上一章结果，完成一个具体行动', 150)}")
    seen_steps = {goal}
    generic_steps = (
        "让阻碍具体出现",
        "主角做选择",
        "兑现一点收益",
        "付出可见代价",
        "形成下一场压力",
        "完成本章推进",
        "推进当前目标",
    )

    def repeats_existing(candidate: str) -> bool:
        normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", candidate)
        if not normalized:
            return True
        for existing in seen_steps:
            existing_normalized = re.sub(r"[^\w\u4e00-\u9fff]", "", str(existing or ""))
            shorter, longer = sorted((normalized, existing_normalized), key=len)
            if len(shorter) >= 16 and longer.startswith(shorter):
                return True
            shared = min(len(normalized), len(existing_normalized), 36)
            if shared >= 24 and normalized[:shared] == existing_normalized[:shared]:
                return True
        return False

    generic_surface = (
        "地点、行动、反馈、代价",
        "形成下一场压力",
        "下一场必须承接本场结果",
    )

    for index, scene in enumerate(scenes, start=1):
        title = _compact_prompt_text(_plain_writer_phrase(str(scene.get("title") or "")), 70)
        scene_goal = _compact_prompt_text(_plain_writer_phrase(str(scene.get("goal") or "")), 80)
        scene_goal = scene_goal.replace("；阻力是出现可见阻力。", "").replace("；阻力是出现可见阻力", "")
        required_surface = _compact_prompt_text(
            _plain_writer_phrase(str(scene.get("required_surface") or "")),
            180,
        )
        exit_state = _compact_prompt_text(_plain_writer_phrase(str(scene.get("exit_state") or "")), 100)
        parts: list[str] = []
        if title:
            parts.append(title)
        if (
            scene_goal
            and not any(marker in scene_goal for marker in generic_steps)
            and not repeats_existing(scene_goal)
        ):
            parts.append(f"目标与阻力：{scene_goal}")
            seen_steps.add(scene_goal)
        if required_surface and not any(marker in required_surface for marker in generic_surface):
            parts.append(f"写出：{required_surface}")
        if exit_state and not any(marker in exit_state for marker in generic_surface):
            parts.append(f"结束时：{exit_state}")
        if parts:
            lines.append(f"场景{index}：" + "；".join(parts))
    return "\n".join(lines)


def _writer_value_lines(values: dict[str, Any], *, max_items: int = 8) -> list[str]:
    lines: list[str] = []
    for label, value in list(values.items())[:max_items]:
        if value in (None, "", [], {}):
            continue
        if isinstance(value, list):
            rendered = "；".join(compact_text(str(item), 80) for item in value[:4] if str(item).strip())
        elif isinstance(value, dict):
            anchor_labels = {"chapter_title": "标题参考", "planned_payoff": "本章兑现"}
            rendered = "；".join(
                f"{anchor_labels.get(str(key), str(key))}：{compact_text(str(item), 100)}"
                for key, item in list(value.items())[:6]
                if item not in (None, "", [], {})
            )
        else:
            rendered = compact_text(str(value), 180)
        if rendered:
            lines.append(f"{label}：{rendered}")
    return lines


def _plan_target_chars(plan: dict[str, Any] | None) -> str:
    plan = plan if isinstance(plan, dict) else {}
    target = plan.get("target_chars") or plan.get("target_word_count") or plan.get("word_count")
    try:
        amount = int(target)
    except (TypeError, ValueError):
        amount = 0
    if amount < CHAPTER_TARGET_MIN_CHARS:
        return (
            f"{CHAPTER_TARGET_MIN_CHARS}到5000字，"
            f"绝对不要超过{CHAPTER_TARGET_MAX_CHARS}字"
        )
    if amount > 5200:
        return f"5000到5400字，绝对不要超过{CHAPTER_TARGET_MAX_CHARS}字"
    return (
        f"{max(CHAPTER_TARGET_MIN_CHARS, amount - 300)}到"
        f"{min(5400, amount + 300)}字，"
        f"绝对不要超过{CHAPTER_TARGET_MAX_CHARS}字"
    )


def _writer_output_section(chapter_number: int, plan: dict[str, Any]) -> list[str]:
    return [
        "## 输出要求",
        f"只输出第{chapter_number}章连续小说正文，不输出标题、提纲、规则、检查过程或说明。",
        f"目标篇幅：{_plan_target_chars(plan)}。写成一章顺着人物行动自然展开的连续正文。",
        "采用第三人称有限视角，一场戏只跟随一个观察人物。",
    ]


def _writer_direction_section(chapter_number: int, plan: dict[str, Any]) -> list[str]:
    taskbook = ensure_writing_taskbook(chapter_number, plan)
    lines = _compact_writer_taskbook_section(taskbook).splitlines()
    event_plan = plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}
    satisfaction = event_plan.get("chapter_satisfaction") if isinstance(event_plan.get("chapter_satisfaction"), dict) else {}
    for label, value in (
        ("主要阻力", satisfaction.get("obstacle") or event_plan.get("collision")),
        ("本章变化", satisfaction.get("state_change") or event_plan.get("turn") or event_plan.get("pivot")),
        ("结尾承接", satisfaction.get("next_hook") or event_plan.get("next_focus")),
    ):
        text = _compact_prompt_text(_plain_writer_phrase(str(value or "")), 100)
        if text:
            lines.append(f"{label}：{text}")
    return lines


def _world_relevance_score(value: str, relevance_text: str) -> int:
    candidate = str(value or "").lower()
    relevance = str(relevance_text or "").lower()
    if not candidate or not relevance:
        return 0
    score = 0
    for token in re.findall(r"[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}", candidate):
        max_size = min(8, len(token))
        for size in range(max_size, 1, -1):
            if any(token[start : start + size] in relevance for start in range(len(token) - size + 1)):
                score = max(score, size)
                break
    return score


def _stable_relevance_rank(values: list[str], relevance_text: str) -> list[str]:
    return [
        value
        for _, value in sorted(
            enumerate(values),
            key=lambda item: (-_world_relevance_score(item[1], relevance_text), item[0]),
        )
    ]


def _compact_world_context_for_prompt(world_context: Any, relevance_text: str, *, max_rules: int = 8) -> dict[str, Any]:
    if not isinstance(world_context, dict) or not world_context:
        return {}
    all_rules = [
        text
        for value in flatten_selected_rules(world_context)
        if (text := compact_text(_plain_world_rule_phrase(str(value or "")), 140))
    ]
    rules = _stable_relevance_rank(all_rules, relevance_text)[:max_rules]
    all_entities: list[str] = []
    for field in ("locations", "factions"):
        values = world_context.get(field)
        if not isinstance(values, list):
            continue
        for value in values:
            if not isinstance(value, dict):
                continue
            name = compact_text(str(value.get("name") or value.get("title") or ""), 50)
            if name:
                description = compact_text(_plain_world_rule_phrase(str(value.get("description") or "")), 120)
                all_entities.append(f"{name}：{description}" if description else name)
    entities = _stable_relevance_rank(all_entities, relevance_text)[:3]
    premise = compact_text(_plain_world_rule_phrase(str(world_context.get("premise") or "")), 180)
    return {key: value for key, value in {"premise": premise, "rules": rules, "entities": entities}.items() if value}


def _writer_trope_contract_lines(context: WriterContext, seed: dict[str, Any]) -> list[str]:
    # The trope contract shapes planning and review. Sending its labels to the
    # prose model makes planning terms leak into narration and duplicates the
    # concrete obstacle/payoff already present in the chapter direction.
    return []


def _writer_continuity_lines(story: Any) -> list[str]:
    source = story.outline_context if isinstance(story.outline_context, dict) else {}
    interface = source.get("continuity_interface") if isinstance(source.get("continuity_interface"), dict) else {}
    if not interface:
        return []
    lines = ["相邻章节接口（优先于静态人物设定）："]
    priority = interface.get("fact_priority") if isinstance(interface.get("fact_priority"), list) else []
    if priority:
        lines.append(f"事实优先级：{' > '.join(str(item) for item in priority if str(item).strip())}。")
    if interface.get("previous_tail"):
        lines.append(f"上一章真实结尾：{compact_text(str(interface['previous_tail']), 1000)}")
    previous_facts = compact_list(interface.get("previous_facts", []), max_items=10, item_chars=140)
    if previous_facts:
        lines.append(f"上一章已发生事实：{'；'.join(previous_facts)}")
    previous_threads = compact_list(interface.get("previous_threads", []), max_items=6, item_chars=120)
    if previous_threads:
        lines.append(f"尚未解决：{'；'.join(previous_threads)}")
    if interface.get("next_opening"):
        number = interface.get("next_chapter_number")
        label = f"第{number}章旧稿开头" if number else "下一章旧稿开头"
        lines.append(f"{label}（仅校验接口）：{compact_text(str(interface['next_opening']), 700)}")
        lines.append("后续旧稿不能覆盖已发生剧情；若二者冲突，服从上一章事实并标记后续章节需要同步重写。")
    return lines


def _compact_writer_governance_section(governance: dict[str, Any], *, omit_must_include: bool = False) -> str:
    governance = governance if isinstance(governance, dict) else {}
    intent = governance.get("chapter_intent") if isinstance(governance.get("chapter_intent"), dict) else {}
    rules = governance.get("rule_stack") if isinstance(governance.get("rule_stack"), dict) else {}
    lines = ["## 本章事实边界"]
    blocking = bool(governance_quality_gate(governance).get("blocking"))
    if blocking:
        lines.append("当前事实边界有冲突；只写能确认的事实，冲突项不进入正文。")
    include = [] if omit_must_include else compact_list(intent.get("must_include", []), max_items=4, item_chars=65)
    hard_facts = compact_list(rules.get("hard_facts", []), max_items=5, item_chars=70)
    avoid = compact_list(intent.get("must_avoid", []), max_items=4, item_chars=60)
    if include:
        lines.append(f"要出现：{'；'.join(include)}")
    if hard_facts and not blocking:
        lines.append(f"沿用：{'；'.join(hard_facts)}")
    if avoid:
        lines.append(f"不要提前写：{'；'.join(avoid)}")
    ending = _compact_prompt_text(_plain_writer_phrase(str(intent.get("ending_change") or "")), 100)
    if ending:
        lines.append(f"章尾变化：{ending}")
    if len(lines) == 1:
        lines.append("沿用项目账本和既有设定。")
    return "\n".join(lines)


def _writer_fact_section_from_context(context: WriterContext) -> list[str]:
    story, chapter_number, plan = context.story, context.chapter_number, context.plan
    lines = ["## 本章事实"]
    story_core = story.story_core if isinstance(story.story_core, dict) else {}
    if logline := compact_text(str(story_core.get("logline") or ""), 300):
        lines.append(f"全书方向：{logline}")
    if reader_promise := compact_text(str(story_core.get("reader_promise") or ""), 220):
        lines.append(f"持续兑现：{reader_promise}")
    continuity_lines = _writer_continuity_lines(story)
    lines.extend(continuity_lines)
    # The planner has already translated the book outline and author rules into
    # this chapter's event plan. Repeating long-range material here encourages
    # the prose model to explain the whole book inside the current scene.
    world_facts = context.world_facts_for_prompt
    if world_facts:
        lines.append(f"既有事实：{'；'.join(world_facts)}")
    world_context = _compact_world_context_for_prompt(
        story.world_context,
        json.dumps(context.writer_plan_for_prompt, ensure_ascii=False),
        max_rules=5,
    )
    world_rules = list(world_context.get("rules") or [])
    if not is_game_story(story):
        process_markers = ("流程", "程序", "证据", "鉴定", "记录", "材料", "票据", "合同")
        world_rules = [
            rule
            for rule in world_rules
            if not (
                any(marker in rule for marker in process_markers)
                and len(re.findall(r"、", rule)) >= 3
            )
        ]
    if world_rules:
        lines.append(f"本章相关世界规则：{'；'.join(world_rules)}")
    if world_context.get("entities"):
        lines.append(f"本章地点与阵营：{'；'.join(world_context['entities'])}")
    if story.chapter_summaries:
        latest = story.chapter_summaries[-1]
        if latest.summary and not continuity_lines:
            lines.append(f"上一章摘要回顾：{compact_text(latest.summary, 160)}")
        if latest.next_focus:
            lines.append(f"当前承接：{compact_text(latest.next_focus, 100)}")
    seed = context.chapter_seed
    if seed:
        material_seed = {key: value for key, value in seed.items() if key not in {"章节", "当前阶段套路", "套路写作提醒", "trope_contract"}}
        seed_lines = _writer_value_lines(material_seed, max_items=7)
        if seed_lines:
            lines.append("本章可用材料：")
            lines.extend(seed_lines)
        lines.extend(_writer_trope_contract_lines(context, seed))
    governance = plan.get("governance") if isinstance(plan.get("governance"), dict) else {}
    if governance:
        lines.append("本章事实边界：")
        lines.extend(_compact_writer_governance_section(governance, omit_must_include=bool(seed and chapter_number == 1)).splitlines()[1:])
    if len(lines) == 1:
        lines.append(f"第{chapter_number}章只沿用项目已经确定的事实，不补写未经大纲支持的背景。")
    return lines


def _writer_character_section(character_context: dict[str, Any], dialogue_context: dict[str, Any]) -> list[str]:
    lines = ["## 出场人物"]
    cards = character_context.get("cards") if isinstance(character_context, dict) else []
    for card in cards[:4] if isinstance(cards, list) else []:
        if not isinstance(card, dict):
            continue
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        name = str(identity.get("name") or "本章人物").strip()
        parts = [str(identity.get("display_role") or identity.get("role") or "").strip()]
        speech_style = normalize_speech_style_for_writing(
            card.get("speech_style") or card.get("speech_tendency")
        )
        # Long-term motivation belongs to planning. In prose context it often
        # makes characters explain their whole arc instead of handling the
        # immediate exchange.
        for value in (card.get("risk_posture"), speech_style):
            text = compact_text(str(value or ""), 90)
            if text:
                parts.append(text)
        rendered = "；".join(part for part in parts if part)
        lines.append(f"{name}：{rendered or '按既有角色卡行动和说话'}")
    conversation_reason = compact_text(str(dialogue_context.get("conversation_reason") or ""), 100)
    tone_boundary = compact_text(str(dialogue_context.get("tone_boundary") or ""), 100)
    if conversation_reason:
        lines.append(f"谈话缘由：{conversation_reason}")
    if tone_boundary:
        lines.append(f"关系尺度：{tone_boundary}")
    participants = dialogue_context.get("participants")
    for participant in participants[:4] if isinstance(participants, list) else []:
        if not isinstance(participant, dict):
            continue
        name = compact_text(str(participant.get("name") or "人物"), 40)
        want = compact_text(str(participant.get("want") or ""), 80)
        planner_meta = (
            want.startswith(f"让{name}")
            or "建立核心悬念" in want
            or "推进当前" in want
        )
        if want and not planner_meta:
            lines.append(f"{name}此刻想要：{want}")
        if emotion := compact_text(str(participant.get("emotion") or ""), 60):
            lines.append(f"{name}当前情绪：{emotion}")
    if unsaid_pressure := compact_text(str(dialogue_context.get("unsaid_pressure") or ""), 120):
        lines.append(f"没有说出口：{unsaid_pressure}")
    if expected_change := compact_text(str(dialogue_context.get("expected_change") or ""), 100):
        lines.append(f"谈完后的变化：{expected_change}")
    if len(lines) == 1:
        lines.append("只使用本章已经出现或明确计划出场的人物，按既有关系和身份说话。")
    return lines


def _iter_skill_modules(skill_context: dict[str, Any]):
    """Yield each selected module once, even when it serves two purposes."""

    seen: set[str] = set()
    for purpose, packs in skill_context.items():
        if purpose.startswith("_") or not isinstance(packs, list):
            continue
        for pack in packs:
            if not isinstance(pack, dict):
                continue
            skill_id = str(pack.get("skill_id") or pack.get("name") or "skill").strip()
            root_skill = str(pack.get("root_skill") or "").strip()
            if root_skill:
                key = f"{skill_id}::root"
                if key not in seen:
                    seen.add(key)
                    yield key, purpose, pack, {
                        "module_id": "root",
                        "instructions": root_skill,
                    }
            modules = pack.get("modules") if isinstance(pack.get("modules"), list) else []
            for module in modules:
                if not isinstance(module, dict):
                    continue
                module_id = str(module.get("module_id") or module.get("title") or "module").strip()
                key = f"{skill_id}::{module_id}"
                if key in seen:
                    continue
                seen.add(key)
                yield key, purpose, pack, module


def writer_skill_trace(skill_context: dict[str, Any]) -> list[dict[str, Any]]:
    """Return the exact selected modules that can reach the writer prompt."""

    trace: list[dict[str, Any]] = []
    for key, purpose, pack, module in _iter_skill_modules(skill_context):
        trace.append(
            {
                "key": key,
                "skill_id": str(pack.get("skill_id") or "").strip(),
                "module_id": str(module.get("module_id") or "").strip(),
                "purpose": purpose,
            }
        )
    return trace


def _writer_skill_lines(skill_context: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for _key, purpose, pack, module in _iter_skill_modules(skill_context):
        name = str(pack.get("name") or pack.get("skill_id") or "Skill").strip()
        instruction = str(
            module.get("instructions")
            or module.get("summary")
            or module.get("description")
            or module.get("content")
            or ""
        ).strip()
        if instruction:
            module_id = str(module.get("module_id") or "module").strip()
            lines.append(f"{name}（{purpose}/{module_id}）：{instruction}")

    if not lines:
        for purpose, packs in skill_context.items():
            if purpose.startswith("_") or not isinstance(packs, list):
                continue
            for pack in packs:
                if not isinstance(pack, dict):
                    continue
                fallback_value = pack.get("description") or pack.get("root_skill")
                if not fallback_value and isinstance(pack.get("skill_ids"), list):
                    fallback_value = "、".join(str(item) for item in pack["skill_ids"] if str(item).strip())
                if fallback := compact_text(str(fallback_value or ""), 260):
                    lines.append(f"{pack.get('name') or pack.get('skill_id') or 'Skill'}（{purpose}）：{fallback}")
    return lines


def _writer_craft_section(genre_context: dict[str, Any], skill_context: dict[str, Any], *, include_genre_method: bool, style_guidance: dict[str, Any] | None = None) -> list[str]:
    lines = [
        "## 正文写法",
        "人物按自己的经历、眼前利益和性格行动，选择要有当场可见的原因。",
        "配角有自己的目的、判断和反应，不只负责递信息或配合主角。",
        "关键冲突、转折和结果写成现场，让读者看到事情正在发生，不用概述代替过程。",
        "对话先回应对方刚说的内容，再说自己真正关心的事；关系和场合决定说话方式，允许解释、犹豫、回避和日常过渡；整场对话发生变化即可，不必让每句话都推进情节。",
        "普通谈话里，连续问答不能三句以上都只剩两到六个字；至少让一方把回应、原因或态度自然说完整。人物只说促成眼前决定所需的信息，不把完整流程、证据链或背景材料念给对方。",
        "情绪放进动作、停顿、语气、回避和选择里，不由旁白替人物下结论。",
        "环境跟着人物行动出现，只保留会影响判断、关系或结果的细节。",
        "使用完整的现代中文句子，把必要的原因、条件和结果说清楚，不把判断压成逗号清单。",
        "优先写具体动作、物件和后果，少写抽象评价和创作说明。",
        "每个场景结束时发生看得见的变化：人物得到、失去、决定、误解或发现了什么。篇幅不够时增加行动、阻力、关系反应或现场变化，不靠重复问答、材料清单或流程解释补足篇幅。",
    ]
    if include_genre_method:
        for method in genre_context.get("genre_method", [])[:3] if isinstance(genre_context.get("genre_method"), list) else []:
            if text := compact_text(str(method), 120):
                lines.append(text)
    if isinstance(style_guidance, dict):
        if voice := compact_text(str(style_guidance.get("voice") or ""), 120):
            lines.append(f"表达风格：{voice}")
        lines.extend(compact_list(style_guidance.get("avoid_rules", []), max_items=2, item_chars=90))
    skill_lines = _writer_skill_lines(skill_context)
    if skill_lines:
        lines.append("启用 Skill 模块摘要（可执行规则）：")
        lines.append("Skill 只提供写作方法，不新增世界设定；项目事实、作者约束和角色卡优先。Skill 中的示例和短句口号不能原样搬进正文；对白先让读者听懂对象、原因和决定，再按场景需要使用停顿、留白或短句。")
        lines.extend(skill_lines)
    return list(dict.fromkeys(lines))


def build_common_writer_sections(context: WriterContext) -> dict[str, list[str]]:
    genre_context = _genre_context_for_prompt(context.story, context.chapter_number, context.plan)
    return {
        "output_section": _writer_output_section(context.chapter_number, context.plan),
        "chapter_direction": _writer_direction_section(context.chapter_number, context.plan),
        "chapter_facts": _writer_fact_section_from_context(context),
        "character_context": _writer_character_section(context.character_context, context.dialogue_context),
        "prose_method": _writer_craft_section(
            genre_context,
            context.skill_context,
            include_genre_method=context.include_genre_method,
            style_guidance=context.style_guidance,
        ),
    }
