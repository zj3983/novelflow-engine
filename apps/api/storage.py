from __future__ import annotations

import json
import os
import sqlite3
import threading
from collections.abc import Mapping
from copy import deepcopy
from dataclasses import dataclass, field
from pathlib import Path

from packages.story_core.engine import ChapterBundle, StoryEngine
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.models import (
    CharacterPerformanceProfile,
    CharacterRelationship,
    CharacterState,
    GamePanel,
    NPCBehaviorProfile,
    NovelOutline,
    NovelProject,
    NovelStatus,
    PersonalityPortrait,
    StoryState,
    WorldBible,
)
from packages.story_core.dual_state import normalize_dual_state
from packages.story_core.book_style import normalize_book_style
from packages.story_core.genre_plugins import select_genre_plugins
from packages.story_core.novel_type_catalog import normalize_novel_type_ids
from packages.story_core.runtime_config import get_runtime_strategy_settings


def _project_world_facts(project: NovelProject) -> list[str]:
    world = project.world_blueprint or {}
    opening_arc = world.get("opening_arc") if isinstance(world.get("opening_arc"), dict) else {}
    golden_three = opening_arc.get("golden_three_chapters") if isinstance(opening_arc.get("golden_three_chapters"), dict) else {}
    systems = world.get("world_systems") if isinstance(world.get("world_systems"), dict) else {}
    living_world = world.get("living_world") if isinstance(world.get("living_world"), dict) else {}
    economy = living_world.get("economy") if isinstance(living_world.get("economy"), dict) else {}
    power = living_world.get("power_structure") if isinstance(living_world.get("power_structure"), dict) else {}
    info = living_world.get("information_network") if isinstance(living_world.get("information_network"), dict) else {}
    npc_system = world.get("npc_system") if isinstance(world.get("npc_system"), dict) else {}
    quest_network = world.get("quest_network") if isinstance(world.get("quest_network"), dict) else {}
    server_runtime = world.get("server_runtime") if isinstance(world.get("server_runtime"), dict) else {}
    map_ecology = world.get("map_ecology") if isinstance(world.get("map_ecology"), dict) else {}
    volume_plan = world.get("volume_plan") if isinstance(world.get("volume_plan"), dict) else {}
    longform = world.get("longform_framework") if isinstance(world.get("longform_framework"), dict) else {}
    progression_ledger = world.get("progression_ledger") if isinstance(world.get("progression_ledger"), dict) else {}

    facts: list[str] = []
    genre_ids = world.get("genre_plugin_ids") if isinstance(world.get("genre_plugin_ids"), list) else []
    if genre_ids:
        facts.append(f"小说类型：{genre_ids[0]}")
    if project.world_summary:
        facts.append(f"世界摘要：{project.world_summary}")
    if project.current_focus:
        facts.append(f"当前焦点：{project.current_focus}")
    if world.get("premise"):
        facts.append(f"世界前提：{world['premise']}")
    if volume_plan:
        title = str(volume_plan.get("volume_title", "")).strip()
        target = volume_plan.get("target_chapters")
        if title and target:
            facts.append(f"第一卷规划：{title}，目标约{target}章。")
        core_goal = str(volume_plan.get("core_goal", "")).strip()
        if core_goal:
            facts.append(f"第一卷核心目标：{core_goal}")
        for beat in volume_plan.get("phase_beats", []) if isinstance(volume_plan.get("phase_beats"), list) else []:
            if isinstance(beat, dict):
                range_text = str(beat.get("range", "")).strip()
                purpose = str(beat.get("purpose", "")).strip()
                if range_text and purpose:
                    facts.append(f"卷纲阶段：{range_text} - {purpose}")
        for thread in volume_plan.get("long_threads", []) if isinstance(volume_plan.get("long_threads"), list) else []:
            text = str(thread).strip()
            if text:
                facts.append(f"长期线索：{text}")
    if longform:
        target_words = longform.get("target_words")
        series_premise = str(longform.get("series_premise", "")).strip()
        if target_words:
            facts.append(f"百万字框架：目标约{target_words}字，章节推演必须服从长期解锁顺序与阶段上限。")
        if series_premise:
            facts.append(f"百万字总前提：{series_premise}")
        for entry in longform.get("volume_ladder", []) if isinstance(longform.get("volume_ladder"), list) else []:
            if isinstance(entry, dict):
                label = str(entry.get("chapters") or entry.get("range") or entry.get("name") or "").strip()
                name = str(entry.get("name", "")).strip()
                unlocks = entry.get("unlocks") if isinstance(entry.get("unlocks"), list) else []
                pressure_cap = str(entry.get("pressure_cap", "")).strip()
                detail_parts = [part for part in [name, "、".join(str(item) for item in unlocks[:5]), pressure_cap] if part]
                if label and detail_parts:
                    facts.append(f"长期卷阶梯：{label} - {'；'.join(detail_parts)}")
        for label, values in (
            ("长期成长阶梯", longform.get("progression_ladder")),
            ("长期势力阶梯", longform.get("faction_ladder")),
            ("长期经济阶梯", longform.get("economy_ladder")),
            ("现实线阶梯", longform.get("reality_ladder")),
            ("真相揭露阶梯", longform.get("mystery_ladder")),
            ("地图解锁阶梯", longform.get("map_ladder")),
            ("NPC演化阶梯", longform.get("npc_evolution_ladder")),
            ("长期推演规则", longform.get("simulation_rules")),
        ):
            if isinstance(values, list):
                for value in values[:6]:
                    text = str(value).strip()
                    if text:
                        facts.append(f"{label}：{text}")
    if progression_ledger:
        protagonist = progression_ledger.get("protagonist") if isinstance(progression_ledger.get("protagonist"), dict) else {}
        economy_state = progression_ledger.get("economy") if isinstance(progression_ledger.get("economy"), dict) else {}
        pressure_state = progression_ledger.get("pressure") if isinstance(progression_ledger.get("pressure"), dict) else {}
        quests_state = progression_ledger.get("quests") if isinstance(progression_ledger.get("quests"), dict) else {}
        if protagonist:
            facts.append(
                "成长账本："
                f"等级{protagonist.get('level', protagonist.get('stage', '未知'))}，"
                f"经验{protagonist.get('exp', '未知')}，"
                f"路线{protagonist.get('class_path', protagonist.get('path', '未定'))}。"
            )
        if economy_state:
            facts.append(
                "经济账本："
                f"{economy_state.get('currency', economy_state.get('resources', '未知'))}，"
                f"市场异常{economy_state.get('market_anomaly', economy_state.get('risk', 0))}。"
            )
        if pressure_state:
            facts.append(
                "压力账本："
                f"公会关注{pressure_state.get('guild_attention', pressure_state.get('external_attention', 0))}，"
                f"金手指暴露{pressure_state.get('goldfinger_exposure', 0)}，"
                f"系统风险{pressure_state.get('system_risk', 0)}。"
            )
        active_quests = quests_state.get("active") if isinstance(quests_state.get("active"), list) else []
        if active_quests:
            facts.append(f"任务账本：进行中 {', '.join(str(item) for item in active_quests[:5])}。")

    economy_rules = world.get("economy_rules") if isinstance(world.get("economy_rules"), list) else []
    for value in economy_rules:
        text = str(value).strip()
        if text and any(token in text for token in ("金币", "银币", "铜币", "汇率", "人民币", "兑换")):
            facts.append(f"经济规则：{text}")

    for label, values in (
        ("玩家生态", living_world.get("player_ecology")),
        ("信息可见规则", living_world.get("information_visibility_rules")),
        ("世界反应阶梯", living_world.get("world_reaction_ladder")),
    ):
        if isinstance(values, list):
            for value in values[:4]:
                text = str(value).strip()
                if text:
                    facts.append(f"{label}：{text}")

    for number, key in ((1, "chapter_1"), (2, "chapter_2"), (3, "chapter_3")):
        chapter_plan = golden_three.get(key) if isinstance(golden_three.get(key), dict) else {}
        purpose = str(chapter_plan.get("purpose", "")).strip()
        if purpose:
            facts.append(f"黄金三章第{number}章职责：{purpose}")
        for mode in chapter_plan.get("conflict_modes", []) if isinstance(chapter_plan.get("conflict_modes"), list) else []:
            text = str(mode).strip()
            if text:
                facts.append(f"第{number}章冲突模式：{text}")
        for forbidden in chapter_plan.get("forbidden_conflicts", []) if isinstance(chapter_plan.get("forbidden_conflicts"), list) else []:
            text = str(forbidden).strip()
            if text:
                facts.append(f"第{number}章禁止冲突：{text}")
        for beat in chapter_plan.get("exposition_beats", []) if isinstance(chapter_plan.get("exposition_beats"), list) else []:
            text = str(beat).strip()
            if text:
                facts.append(f"第{number}章背景节拍：{text}")
        background_budget = chapter_plan.get("background_budget") if isinstance(chapter_plan.get("background_budget"), dict) else {}
        for label, values in (
            ("必写层", background_budget.get("required_layers")),
            ("可写层", background_budget.get("allowed_layers")),
            ("禁写层", background_budget.get("forbidden_layers")),
        ):
            if isinstance(values, list):
                for value in values[:3]:
                    text = str(value).strip()
                    if text:
                        facts.append(f"第{number}章背景预算-{label}：{text}")
        hook = str(chapter_plan.get("ending_hook", "")).strip()
        if hook:
            facts.append(f"第{number}章章末钩子：{hook}")

    for value in economy_rules:
        text = str(value).strip()
        if text and any(token in text for token in ("金币", "银币", "铜币", "汇率", "人民币", "兑换")):
            facts.append(f"经济规则：{text}")

    for label, values in (
        ("经济规则", economy_rules),
        ("资源基础", systems.get("material_base")),
        ("社会秩序", systems.get("social_order")),
        ("冲突引擎", systems.get("conflict_engines")),
        ("日常运转", living_world.get("daily_routines")),
        ("资源流动", economy.get("resource_flow")),
        ("经济压力", economy.get("pressure_points")),
        ("支配群体", power.get("dominant_groups")),
        ("控制方式", power.get("control_methods")),
        ("消息渠道", info.get("channels")),
        ("流动传闻", info.get("rumors")),
        ("玩家生态", living_world.get("player_ecology")),
        ("信息可见规则", living_world.get("information_visibility_rules")),
        ("世界反应阶梯", living_world.get("world_reaction_ladder")),
        ("时间推进", living_world.get("timeline")),
        ("世界反应", living_world.get("reaction_rules")),
    ):
        if isinstance(values, list):
            for value in values[:4]:
                text = str(value).strip()
                if text:
                    facts.append(f"{label}：{text}")

    for entry in systems.get("institutions", []) if isinstance(systems.get("institutions"), list) else []:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            description = str(entry.get("description", "")).strip()
            if name:
                facts.append(f"制度机构：{name} - {description or name}")

    for entry in systems.get("causal_loops", []) if isinstance(systems.get("causal_loops"), list) else []:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            description = str(entry.get("description", "")).strip()
            if name:
                facts.append(f"因果链：{name} - {description or name}")

    for entry in living_world.get("location_functions", []) if isinstance(living_world.get("location_functions"), list) else []:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            description = str(entry.get("description", "")).strip()
            if name:
                facts.append(f"地点功能：{name} - {description or name}")

    for entry in npc_system.get("npcs", []) if isinstance(npc_system.get("npcs"), list) else []:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            role = str(entry.get("role", "")).strip()
            location = str(entry.get("location", "")).strip()
            services = entry.get("services") if isinstance(entry.get("services"), list) else []
            knowledge_limit = str(entry.get("knowledge_limit", "")).strip()
            quest_hooks = entry.get("quest_hooks") if isinstance(entry.get("quest_hooks"), list) else []
            if name:
                parts = [role or name]
                if location:
                    parts.append(f"位置：{location}")
                if services:
                    parts.append(f"服务：{'、'.join(str(v) for v in services[:3])}")
                if knowledge_limit:
                    parts.append(f"信息边界：{knowledge_limit}")
                if quest_hooks:
                    parts.append(f"任务钩子：{'、'.join(str(v) for v in quest_hooks[:3])}")
                facts.append(f"NPC：{name} - {'；'.join(parts)}")

    for value in npc_system.get("rules", []) if isinstance(npc_system.get("rules"), list) else []:
        text = str(value).strip()
        if text:
            facts.append(f"NPC规则：{text}")

    for value in quest_network.get("quest_types", []) if isinstance(quest_network.get("quest_types"), list) else []:
        text = str(value).strip()
        if text:
            facts.append(f"任务类型：{text}")

    for entry in quest_network.get("active_chains", []) if isinstance(quest_network.get("active_chains"), list) else []:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            description = str(entry.get("description", "")).strip()
            stages = entry.get("stages") if isinstance(entry.get("stages"), list) else []
            npc_links = entry.get("npc_links") if isinstance(entry.get("npc_links"), list) else []
            if name:
                suffix = description or name
                if stages:
                    suffix += f"；阶段：{' -> '.join(str(v) for v in stages[:4])}"
                if npc_links:
                    suffix += f"；关联NPC：{'、'.join(str(v) for v in npc_links[:4])}"
                facts.append(f"任务网络：{name} - {suffix}")

    for label, values in (
        ("任务奖励规则", quest_network.get("reward_rules")),
        ("任务失败代价", quest_network.get("failure_costs")),
        ("服务器公告规则", server_runtime.get("announcement_rules")),
        ("系统监管规则", server_runtime.get("gm_rules")),
        ("风控规则", server_runtime.get("anti_cheat_rules")),
        ("副本门槛", server_runtime.get("instance_rules")),
    ):
        if isinstance(values, list):
            for value in values[:3]:
                text = str(value).strip()
                if text:
                    facts.append(f"{label}：{text}")

    phase = str(server_runtime.get("phase", "")).strip()
    if phase:
        facts.append(f"服务器阶段：{phase}")
    channels = server_runtime.get("channels") if isinstance(server_runtime.get("channels"), list) else []
    if channels:
        facts.append(f"服务器频道：{'、'.join(str(v) for v in channels[:6])}")

    for entry in map_ecology.get("zones", []) if isinstance(map_ecology.get("zones"), list) else []:
        if isinstance(entry, dict):
            name = str(entry.get("name", "")).strip()
            description = str(entry.get("description", "")).strip()
            resources = entry.get("resources") if isinstance(entry.get("resources"), list) else []
            npcs = entry.get("npcs") if isinstance(entry.get("npcs"), list) else []
            risk = str(entry.get("risk", "")).strip()
            if name:
                parts = [description or name]
                if resources:
                    parts.append(f"资源：{'、'.join(str(v) for v in resources[:4])}")
                if npcs:
                    parts.append(f"NPC：{'、'.join(str(v) for v in npcs[:4])}")
                if risk:
                    parts.append(f"风险：{risk}")
                facts.append(f"地图生态：{name} - {'；'.join(parts)}")

    deduped: list[str] = []
    for fact in facts:
        if fact not in deduped:
            deduped.append(fact)
        if len(deduped) >= 120:
            break
    return deduped


def _project_genre_selection(project: NovelProject) -> tuple[list[str], bool]:
    world = project.world_blueprint if isinstance(project.world_blueprint, dict) else {}
    raw = world.get("genre_plugin_ids")
    if isinstance(raw, str):
        has_explicit_value = bool(raw.strip())
    elif isinstance(raw, list):
        has_explicit_value = any(str(item).strip() for item in raw)
    else:
        has_explicit_value = False
    return normalize_novel_type_ids(raw), has_explicit_value


def _merge_prefer_existing(existing: object, incoming: object) -> object:
    if isinstance(existing, Mapping) and isinstance(incoming, Mapping):
        merged = deepcopy(dict(existing))
        for key, value in incoming.items():
            if key in merged:
                merged[key] = _merge_prefer_existing(merged[key], value)
            else:
                merged[key] = deepcopy(value)
        return merged
    if existing not in (None, "", [], {}):
        return deepcopy(existing)
    return deepcopy(incoming)


def _merge_character_state(existing: object, incoming: object) -> dict[str, object]:
    existing_state = existing if isinstance(existing, Mapping) else {}
    incoming_state = incoming if isinstance(incoming, Mapping) else {}
    current = _merge_prefer_existing(
        existing_state.get("current", {}), incoming_state.get("current", {})
    )
    existing_recent = existing_state.get("recent_changes")
    incoming_recent = incoming_state.get("recent_changes")
    recent: list[object] = []
    for item in [
        *(existing_recent if isinstance(existing_recent, list) else []),
        *(incoming_recent if isinstance(incoming_recent, list) else []),
    ]:
        if item not in recent:
            recent.append(deepcopy(item))
    return {"current": current if isinstance(current, dict) else {}, "recent_changes": recent}


_GAME_PANEL_STATE_FIELDS = (
    "game_id",
    "level",
    "class_path",
    "exp",
    "hp",
    "mp",
    "attributes",
    "skills",
    "equipment",
    "inventory",
    "currency",
    "quests",
    "risk",
)


def _sync_game_panel_mirror(character: CharacterState) -> None:
    current = character.game_state.get("current") if isinstance(character.game_state, dict) else None
    if not isinstance(current, Mapping):
        return
    panel = character.game_panel.model_dump(mode="json")
    for field in _GAME_PANEL_STATE_FIELDS:
        value = current.get(field)
        if value not in (None, "", [], {}):
            panel[field] = deepcopy(value)
    character.game_panel = GamePanel.model_validate(panel)


def _sync_project_character_profiles(story: StoryState, project: NovelProject) -> None:
    """Keep runtime characters as rich as the imported/project character bible."""
    profiles = [profile for profile in project.character_profiles if isinstance(profile, dict)]
    if not profiles:
        return
    genre_ids, has_explicit_genre_value = _project_genre_selection(project)
    selected_plugins = select_genre_plugins(project)
    plugin_ids = {plugin.plugin_id for plugin in selected_plugins}
    story_genre_ids = normalize_novel_type_ids(story.genre) if not has_explicit_genre_value else []
    effective_genre_ids = genre_ids or story_genre_ids
    is_game_story = "game_webnovel" in plugin_ids or "game_webnovel" in effective_genre_ids
    should_clear_game_state = bool(effective_genre_ids) and not is_game_story

    characters_by_name = {character.name: character for character in story.characters}
    for profile in profiles:
        name = str(profile.get("name", "")).strip()
        if not name:
            continue
        if name not in characters_by_name:
            character = CharacterState(name=name, role=str(profile.get("role", "")).strip() or "supporting")
            story.characters.append(character)
            characters_by_name[name] = character
        else:
            character = characters_by_name[name]

        raw_character = character.model_dump(mode="json", exclude_defaults=True, exclude_none=True)
        normalized_character = normalize_dual_state(raw_character, is_game_story=is_game_story)
        normalized_profile = normalize_dual_state(profile, is_game_story=is_game_story)
        for state_name in ("real_state", "game_state"):
            if state_name not in normalized_profile:
                continue
            existing_state = normalized_character.get(state_name, {})
            if state_name == "game_state" and "game_state" not in raw_character:
                existing_state = {}
                legacy_panel = raw_character.get("game_panel")
                if is_game_story and isinstance(legacy_panel, Mapping):
                    existing_state = {"current": {}, "recent_changes": []}
            merged_state = _merge_character_state(existing_state, normalized_profile[state_name])
            if state_name == "game_state" and "game_state" not in raw_character:
                legacy_panel = raw_character.get("game_panel")
                if is_game_story and isinstance(legacy_panel, Mapping):
                    merged_state["current"] = _merge_prefer_existing(
                        merged_state["current"], legacy_panel
                    )
            setattr(character, state_name, merged_state)

        role = str(profile.get("role", "")).strip()
        if role:
            character.role = role

        game_id = str(profile.get("game_id", "")).strip()
        if should_clear_game_state:
            character.game_id = ""
            character.game_panel = GamePanel()
        else:
            if is_game_story and isinstance(profile.get("game_panel"), Mapping):
                existing_panel = character.game_panel.model_dump(mode="json")
                merged_panel = _merge_prefer_existing(existing_panel, profile["game_panel"])
                character.game_panel = GamePanel.model_validate(merged_panel)
            if game_id:
                character.game_id = game_id
        if is_game_story:
            _sync_game_panel_mirror(character)

        motivation = str(profile.get("motivation", "")).strip()
        personality = str(profile.get("personality", "")).strip()
        speech_style = str(profile.get("speech_style", "")).strip()
        if motivation:
            character.core_motivation = motivation
        if personality:
            character.behavior_logic = personality
        if speech_style:
            character.interaction_mode = speech_style

        if should_clear_game_state:
            existing_text = json.dumps(character.model_dump(), ensure_ascii=False)
            legacy_terms = ("游戏", "网游", "玩家", "爆率", "余额", "法师", "铜币", "掉落")
            if any(term in existing_text for term in legacy_terms):
                character.performance_profile = CharacterPerformanceProfile()
                character.npc_profile = NPCBehaviorProfile()
                character.personality_portrait = PersonalityPortrait()
                character.social_profile = {}
                character.psychological_profile = {}
                character.moral_profile = {}
                character.poison_points = []
                character.story_function = ""
                character.chapter_role = ""
                if motivation:
                    character.core_motivation = motivation
                if personality:
                    character.behavior_logic = personality
                if speech_style:
                    character.interaction_mode = speech_style

        profile_goals = [str(goal).strip() for goal in profile.get("goals", []) if str(goal).strip()]
        if profile_goals:
            existing = [
                goal
                for goal in character.goals
                if goal
                and "正面撞上" not in goal
                and "侧面压力" not in goal
                and "核心资源的控制权" not in goal
            ]
            character.goals = [*profile_goals, *[goal for goal in existing if goal not in profile_goals]][:8]

        secrets = [str(secret).strip() for secret in profile.get("secrets", []) if str(secret).strip()]
        if secrets:
            character.secrets = [*secrets, *[secret for secret in character.secrets if secret not in secrets]][:8]

        profile_memory = []
        for label, key in (
            ("动机", "motivation"),
            ("性格", "personality"),
            ("说话方式", "speech_style"),
            ("当前状态", "current_state"),
        ):
            value = str(profile.get(key, "")).strip()
            if value:
                profile_memory.append(f"角色档案-{label}：{value}")
        if game_id:
            profile_memory.append(f"角色档案-游戏ID：{game_id}")
        hooks = [str(hook).strip() for hook in profile.get("conflict_hooks", []) if str(hook).strip()]
        if hooks:
            profile_memory.append(f"角色档案-冲突钩子：{' / '.join(hooks[:4])}")
        if profile_memory:
            cleaned_memory = [
                memory
                for memory in character.memory
                if "正面撞上" not in memory
                and "侧面压力" not in memory
                and "核心资源的控制权" not in memory
                and not memory.startswith("角色档案-")
            ]
            character.memory = [*profile_memory, *cleaned_memory][-12:]

        current_state = str(profile.get("current_state", "")).strip()
        if current_state:
            character.location = current_state[:40]

    for edge in project.relationship_graph:
        if not isinstance(edge, dict):
            continue
        source = str(edge.get("source", "")).strip()
        target = str(edge.get("target", "")).strip()
        if not source or not target or source not in characters_by_name:
            continue
        characters_by_name[source].relationships[target] = CharacterRelationship(
            target=target,
            trust=float(edge.get("trust", 0.0) or 0.0),
            tension=float(edge.get("tension", 0.0) or 0.0),
            bond=str(edge.get("bond", "")).strip(),
        )


def _sync_project_generation_context(story: StoryState, project: NovelProject, *, has_history: bool) -> None:
    story.author_constraints = list(project.author_constraints)
    story.world_facts = _project_world_facts(project)
    story.enabled_skill_ids = list(project.enabled_skill_ids)

    genre_ids, _ = _project_genre_selection(project)
    primary_genre = genre_ids[0] if genre_ids else ""
    if primary_genre and primary_genre != "game_webnovel":
        game_only_terms = ("交易行", "公会", "玩家", "NPC", "背包", "法杖", "铜币", "掉落", "网游", "游戏面板")
        game_memory_terms = (*game_only_terms, "角色面板", "见习冒险者")
        story.writing_lessons = [
            lesson for lesson in story.writing_lessons if not any(term in lesson for term in game_only_terms)
        ]
        for character in story.characters:
            character.game_id = ""
            character.game_panel = GamePanel()
            character.goals = [
                goal for goal in character.goals if not any(term in goal for term in game_only_terms)
            ]
            character.memory = [
                memory for memory in character.memory if not any(term in memory for term in game_memory_terms)
            ]
    # A freshly created story can already carry a placeholder chapter number
    # from the simulation flow. History, not that number, decides whether the
    # project is still initializing the story context.
    first_generation = not has_history
    outline_compact = "".join(story.outline.split())
    placeholder_outline = not outline_compact or set(outline_compact) <= {"?", "？"}
    if project.seed_outline and (first_generation or placeholder_outline):
        story.outline = project.seed_outline
    if primary_genre:
        story.genre = primary_genre
    world_blueprint = project.world_blueprint if isinstance(project.world_blueprint, dict) else {}
    story.style = normalize_book_style(world_blueprint.get("writing_style"))

    ledger = project.world_blueprint.get("progression_ledger") if isinstance(project.world_blueprint, dict) else None
    ledger_keys = set(ledger) if isinstance(ledger, dict) else set()
    story_ledger_keys = set(story.progression_ledger) if isinstance(story.progression_ledger, dict) else set()
    incompatible_ledger = bool(ledger_keys) and not ledger_keys.intersection(story_ledger_keys)
    if isinstance(ledger, dict) and (first_generation or not story.progression_ledger or incompatible_ledger):
        story.progression_ledger = dict(ledger)


# SQLite database path: next to this file, or override via env var
_DB_PATH = os.environ.get(
    "NOVEL_AUTOGROWTH_DB_PATH",
    os.environ.get(
        "STORY_DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "stories.db"),
    ),
)


def _get_db_path() -> str:
    return _DB_PATH


def _ensure_db_dir(db_path: str) -> None:
    parent = os.path.dirname(db_path)
    if parent:
        os.makedirs(parent, exist_ok=True)


def _init_db(db_path: str) -> sqlite3.Connection:
    _ensure_db_dir(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS stories (
            story_id TEXT PRIMARY KEY,
            story_state TEXT NOT NULL,
            initial_state TEXT NOT NULL,
            parent_story_id TEXT,
            branched_from_chapter INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS chapter_bundles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            story_id TEXT NOT NULL,
            chapter_number INTEGER NOT NULL,
            bundle_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_chapter_bundles_story
            ON chapter_bundles(story_id, chapter_number);
        CREATE INDEX IF NOT EXISTS idx_stories_parent
            ON stories(parent_story_id);
        CREATE TABLE IF NOT EXISTS novel_outlines (
            story_id TEXT PRIMARY KEY,
            outline_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS world_bibles (
            story_id TEXT PRIMARY KEY,
            world_bible_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS novel_statuses (
            story_id TEXT PRIMARY KEY,
            status_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS novel_projects (
            project_id TEXT PRIMARY KEY,
            project_json TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS project_stories (
            project_id TEXT NOT NULL,
            story_id TEXT NOT NULL PRIMARY KEY,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (project_id) REFERENCES novel_projects(project_id) ON DELETE CASCADE,
            FOREIGN KEY (story_id) REFERENCES stories(story_id) ON DELETE CASCADE
        );
        CREATE INDEX IF NOT EXISTS idx_project_stories_project
            ON project_stories(project_id, created_at);
    """)
    conn.commit()
    return conn


# Thread-local storage for DB connections
_local = threading.local()


def _get_conn(db_path: str | None = None) -> sqlite3.Connection:
    path = db_path or _get_db_path()
    if not hasattr(_local, "connections"):
        _local.connections = {}
    if path not in _local.connections:
        conn = _init_db(path)
        _local.connections[path] = conn
    return _local.connections[path]


@dataclass
class StoryRecord:
    story: StoryState
    initial_story: StoryState
    history: list[ChapterBundle] = field(default_factory=list)
    parent_story_id: str | None = None
    branched_from_chapter: int | None = None


class SimulationFailedError(RuntimeError):
    def __init__(self, bundle: ChapterBundle) -> None:
        self.bundle = bundle
        super().__init__("simulation_failed")


class SQLiteStoryStore:
    """SQLite-backed persistent story store.

    Replaces InMemoryStoryStore. Keeps the same public API so
    API routes and tests require no changes.
    """

    def __init__(self, db_path: str | None = None) -> None:
        self._db_path = db_path or _get_db_path()

    def _conn(self) -> sqlite3.Connection:
        return _get_conn(self._db_path)

    # ── helpers ──────────────────────────────────────────────

    def _serialize_story(self, story: StoryState) -> str:
        return story.model_dump_json()

    def _deserialize_story(self, json_str: str) -> StoryState:
        story = StoryState.model_validate_json(json_str)
        self._apply_runtime_strategy_defaults(story)
        return story

    def _apply_runtime_strategy_defaults(self, story: StoryState) -> None:
        current = story.agent_settings
        if not (
            current.global_model == "gpt-5.4"
            and current.character_model == "gpt-5.4-mini"
            and current.director_model == "gpt-5.4"
            and current.writer_model == "gpt-5.4"
            and current.memory_model == "gpt-5.4"
            and float(current.temperature) == 0.7
        ):
            return

        runtime_strategy = get_runtime_strategy_settings()
        if runtime_strategy == current:
            return
        story.agent_settings = runtime_strategy.model_copy(deep=True)

    def _serialize_bundle(self, bundle: ChapterBundle) -> str:
        return bundle.model_dump_json()

    def _deserialize_bundle(self, json_str: str) -> ChapterBundle:
        return ChapterBundle.model_validate_json(json_str)

    def _serialize_project(self, project: NovelProject) -> str:
        return project.model_dump_json()

    def _deserialize_project(self, json_str: str) -> NovelProject:
        return NovelProject.model_validate_json(json_str)

    def _load_history(self, conn: sqlite3.Connection, story_id: str) -> list[ChapterBundle]:
        cursor = conn.execute(
            "SELECT id, chapter_number, bundle_json FROM chapter_bundles WHERE story_id = ? ORDER BY id",
            (story_id,),
        )
        latest_by_chapter: dict[int, tuple[int, ChapterBundle]] = {}
        for row_id, chapter_number, bundle_json in cursor.fetchall():
            latest_by_chapter[int(chapter_number)] = (int(row_id), self._deserialize_bundle(bundle_json))
        return [
            bundle
            for _, bundle in sorted(
                latest_by_chapter.values(),
                key=lambda item: (item[1].chapter_number, item[0]),
            )
        ]

    def _save_record(self, conn: sqlite3.Connection, record: StoryRecord) -> None:
        # Use UPDATE to avoid ON DELETE CASCADE wiping chapter_bundles.
        # INSERT only if the row doesn't exist yet (e.g. after create).
        cursor = conn.execute(
            """
            UPDATE stories
            SET story_state = ?, initial_state = ?, parent_story_id = ?,
                branched_from_chapter = ?, updated_at = CURRENT_TIMESTAMP
            WHERE story_id = ?
            """,
            (
                self._serialize_story(record.story),
                self._serialize_story(record.initial_story),
                record.parent_story_id,
                record.branched_from_chapter,
                record.story.story_id,
            ),
        )
        if cursor.rowcount == 0:
            # Row didn't exist yet — insert it
            conn.execute(
                """
                INSERT INTO stories
                    (story_id, story_state, initial_state, parent_story_id,
                     branched_from_chapter, updated_at)
                VALUES (?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                """,
                (
                    record.story.story_id,
                    self._serialize_story(record.story),
                    self._serialize_story(record.initial_story),
                    record.parent_story_id,
                    record.branched_from_chapter,
                ),
            )
        conn.commit()

    def _save_bundle(self, conn: sqlite3.Connection, story_id: str, bundle: ChapterBundle) -> None:
        conn.execute(
            "DELETE FROM chapter_bundles WHERE story_id = ? AND chapter_number = ?",
            (story_id, bundle.chapter_number),
        )
        conn.execute(
            """
            INSERT INTO chapter_bundles (story_id, chapter_number, bundle_json)
            VALUES (?, ?, ?)
            """,
            (story_id, bundle.chapter_number, self._serialize_bundle(bundle)),
        )
        conn.commit()

    def _save_project(self, conn: sqlite3.Connection, project: NovelProject) -> None:
        conn.execute(
            """
            INSERT INTO novel_projects (project_id, project_json, created_at, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            ON CONFLICT(project_id) DO UPDATE SET
                project_json = excluded.project_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (project.project_id, self._serialize_project(project)),
        )
        conn.commit()

    # ── public API ───────────────────────────────────────────

    def create(self, story: StoryState) -> StoryRecord:
        conn = self._conn()
        record = StoryRecord(
            story=story,
            initial_story=story.model_copy(deep=True),
        )
        self._save_record(conn, record)
        return record

    def get(self, story_id: str) -> StoryRecord | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT story_state, initial_state, parent_story_id, branched_from_chapter FROM stories WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return StoryRecord(
            story=self._deserialize_story(row[0]),
            initial_story=self._deserialize_story(row[1]),
            history=self._load_history(conn, story_id),
            parent_story_id=row[2],
            branched_from_chapter=row[3],
        )

    def list(self) -> list[StoryRecord]:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT story_id FROM stories ORDER BY created_at"
        )
        records: list[StoryRecord] = []
        for (story_id,) in cursor.fetchall():
            record = self.get(story_id)
            if record is not None:
                records.append(record)
        return records

    def rename(self, story_id: str, new_story_id: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        # Check new ID doesn't exist
        cursor = conn.execute("SELECT 1 FROM stories WHERE story_id = ?", (new_story_id,))
        if cursor.fetchone():
            raise ValueError("story_exists")

        # Update parent references in children
        conn.execute(
            "UPDATE stories SET parent_story_id = ? WHERE parent_story_id = ?",
            (new_story_id, story_id),
        )

        # Update story_id in all fields
        record.story.story_id = new_story_id
        record.initial_story.story_id = new_story_id
        for bundle in record.history:
            bundle.updated_story.story_id = new_story_id
        record.parent_story_id = new_story_id if record.parent_story_id == story_id else record.parent_story_id

        # Insert with new ID
        self._save_record(conn, record)
        for bundle in record.history:
            self._save_bundle(conn, new_story_id, bundle)

        # Re-key per-story side tables before removing the old row,
        # otherwise ON DELETE CASCADE wipes them with it.
        for table in ("novel_outlines", "world_bibles", "novel_statuses", "project_stories"):
            conn.execute(
                f"UPDATE {table} SET story_id = ? WHERE story_id = ?",
                (new_story_id, story_id),
            )

        # Delete old
        conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
        conn.execute("DELETE FROM chapter_bundles WHERE story_id = ?", (story_id,))
        conn.commit()

        return record

    def delete(self, story_id: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)
        if record.parent_story_id is None:
            raise ValueError("cannot_delete_root")

        # Check for children
        cursor = conn.execute(
            "SELECT 1 FROM stories WHERE parent_story_id = ? LIMIT 1",
            (story_id,),
        )
        if cursor.fetchone():
            raise ValueError("story_has_children")

        conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
        conn.execute("DELETE FROM chapter_bundles WHERE story_id = ?", (story_id,))
        conn.commit()
        return record

    def generate_next(self, story_id: str, engine: StoryEngine) -> ChapterBundle:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        project_id = self.find_project_id_by_story(story_id)
        if project_id:
            project = self.get_project(project_id)
            if project is not None:
                _sync_project_generation_context(record.story, project, has_history=bool(record.history))
                _sync_project_character_profiles(record.story, project)

        bundle = engine.generate_next_chapter(record.story)

        if not bundle.simulation_status.get("ok", False):
            raise SimulationFailedError(bundle)

        # Update story state
        record.story = bundle.updated_story
        record.history.append(bundle)

        report_generation_progress(
            {
                "message": "写入故事中",
                "stage": "orchestrator",
                "source": "story-store",
                "artifact": {
                    "chapter_number": bundle.chapter_number,
                    "message": "持久化章节与剧情记忆更新",
                    "used_modules": ["story_store", "history_append"],
                },
            }
        )
        self._save_record(conn, record)
        self._save_bundle(conn, story_id, bundle)

        return bundle

    def append_chapter_bundle(self, story_id: str, bundle: ChapterBundle) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        latest_chapter = record.history[-1].chapter_number if record.history else 0
        if bundle.chapter_number != latest_chapter + 1:
            raise IndexError(bundle.chapter_number)

        record.story = bundle.updated_story.model_copy(deep=True)
        record.history.append(bundle)
        self._save_record(conn, record)
        self._save_bundle(conn, story_id, bundle)
        return record

    def rollback_last(self, story_id: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        if record.history:
            # Delete last bundle from DB
            last_chapter = record.history[-1].chapter_number
            conn.execute(
                "DELETE FROM chapter_bundles WHERE story_id = ? AND chapter_number = ?",
                (story_id, last_chapter),
            )

            record.history.pop()
            if record.history:
                record.story = record.history[-1].updated_story.model_copy(deep=True)
            else:
                record.story = record.initial_story.model_copy(deep=True)

            self._save_record(conn, record)
            conn.commit()

        return record

    def replace_chapter_bundle(self, story_id: str, bundle: ChapterBundle) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        replace_index = next(
            (index for index, existing in enumerate(record.history) if existing.chapter_number == bundle.chapter_number),
            None,
        )
        if replace_index is None:
            raise IndexError(bundle.chapter_number)

        record.history = [
            existing
            for index, existing in enumerate(record.history)
            if existing.chapter_number != bundle.chapter_number or index == replace_index
        ]
        replace_index = next(
            index for index, existing in enumerate(record.history) if existing.chapter_number == bundle.chapter_number
        )
        record.history[replace_index] = bundle
        if replace_index == len(record.history) - 1:
            record.story = bundle.updated_story.model_copy(deep=True)

        conn.execute(
            "DELETE FROM chapter_bundles WHERE story_id = ? AND chapter_number = ?",
            (story_id, bundle.chapter_number),
        )
        self._save_record(conn, record)
        self._save_bundle(conn, story_id, bundle)
        conn.commit()
        return record

    def branch_from(self, story_id: str, new_story_id: str, from_chapter: int) -> StoryRecord:
        conn = self._conn()

        # Check new ID doesn't exist
        cursor = conn.execute("SELECT 1 FROM stories WHERE story_id = ?", (new_story_id,))
        if cursor.fetchone():
            raise ValueError("story_exists")

        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        if from_chapter < 0 or from_chapter > len(record.history):
            raise IndexError(from_chapter)

        if from_chapter == 0:
            branch_story = record.initial_story.model_copy(deep=True)
            branch_history: list[ChapterBundle] = []
        else:
            branch_history = [bundle.model_copy(deep=True) for bundle in record.history[:from_chapter]]
            branch_story = branch_history[-1].updated_story.model_copy(deep=True)

        branch_story.story_id = new_story_id
        for bundle in branch_history:
            bundle.updated_story.story_id = new_story_id

        branch_record = StoryRecord(
            story=branch_story,
            initial_story=record.initial_story.model_copy(deep=True),
            history=branch_history,
            parent_story_id=story_id,
            branched_from_chapter=from_chapter,
        )
        branch_record.initial_story.story_id = new_story_id

        # Persist branch
        self._save_record(conn, branch_record)
        for bundle in branch_history:
            self._save_bundle(conn, new_story_id, bundle)

        return branch_record

    def freeze_character(self, story_id: str, character_name: str) -> StoryRecord:
        conn = self._conn()
        record = self.get(story_id)
        if record is None:
            raise KeyError(story_id)

        for character in record.story.characters:
            if character.name == character_name:
                character.frozen = True
                character.lifecycle_state = "frozen"
                self._save_record(conn, record)
                return record

        raise KeyError(character_name)


    # ── outline persistence ──────────────────────────────────

    def create_project(self, project: NovelProject) -> NovelProject:
        conn = self._conn()
        self._save_project(conn, project)
        return project

    def get_project(self, project_id: str) -> NovelProject | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT project_json FROM novel_projects WHERE project_id = ?",
            (project_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._deserialize_project(row[0])

    def sync_project_context(self, project_id: str) -> StoryRecord | None:
        """Synchronize project settings into its active story before inspection."""
        project = self.get_project(project_id)
        if project is None or not project.active_story_id:
            return None
        record = self.get(project.active_story_id)
        if record is None:
            return None
        _sync_project_generation_context(record.story, project, has_history=bool(record.history))
        _sync_project_character_profiles(record.story, project)
        self._save_record(self._conn(), record)
        return record

    def list_projects(self) -> list[NovelProject]:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT project_json FROM novel_projects ORDER BY updated_at DESC, created_at DESC"
        )
        return [self._deserialize_project(row[0]) for row in cursor.fetchall()]

    def delete_project(self, project_id: str, *, delete_stories: bool = True) -> NovelProject:
        """Delete a project and, by default, all story branches owned by it."""
        conn = self._conn()
        project = self.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        story_ids = [
            str(row[0])
            for row in conn.execute(
                "SELECT story_id FROM project_stories WHERE project_id = ?",
                (project_id,),
            ).fetchall()
        ]
        conn.execute("DELETE FROM novel_projects WHERE project_id = ?", (project_id,))
        if delete_stories:
            for story_id in story_ids:
                conn.execute("DELETE FROM stories WHERE story_id = ?", (story_id,))
        conn.commit()
        return project

    def attach_story_to_project(self, project_id: str, story_id: str) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO project_stories (project_id, story_id)
            VALUES (?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                project_id = excluded.project_id
            """,
            (project_id, story_id),
        )
        conn.commit()

    def list_project_stories(self, project_id: str) -> list[StoryRecord]:
        conn = self._conn()
        cursor = conn.execute(
            """
            SELECT story_id
            FROM project_stories
            WHERE project_id = ?
            ORDER BY created_at
            """,
            (project_id,),
        )
        records: list[StoryRecord] = []
        for (story_id,) in cursor.fetchall():
            record = self.get(story_id)
            if record is not None:
                records.append(record)
        return records

    def find_project_id_by_story(self, story_id: str) -> str | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT project_id FROM project_stories WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        return row[0] if row else None

    def set_project_active_story(self, project_id: str, story_id: str) -> NovelProject:
        conn = self._conn()
        project = self.get_project(project_id)
        if project is None:
            raise KeyError(project_id)
        project.active_story_id = story_id
        project.status = "simulating"
        project.pipeline_stage = "environment_ready"
        self._save_project(conn, project)
        return project

    def update_project(self, project: NovelProject) -> NovelProject:
        conn = self._conn()
        self._save_project(conn, project)
        return project

    def save_outline(self, story_id: str, outline: NovelOutline) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO novel_outlines (story_id, outline_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(story_id) DO UPDATE SET
                outline_json = excluded.outline_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (story_id, outline.model_dump_json()),
        )
        conn.commit()

    def get_outline(self, story_id: str) -> NovelOutline | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT outline_json FROM novel_outlines WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return NovelOutline.model_validate_json(row[0])

    def delete_outline(self, story_id: str) -> bool:
        conn = self._conn()
        cursor = conn.execute("DELETE FROM novel_outlines WHERE story_id = ?", (story_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ── world bible persistence ──────────────────────────────

    def save_world_bible(self, story_id: str, world_bible: WorldBible) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO world_bibles (story_id, world_bible_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(story_id) DO UPDATE SET
                world_bible_json = excluded.world_bible_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (story_id, world_bible.model_dump_json()),
        )
        conn.commit()

    def get_world_bible(self, story_id: str) -> WorldBible | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT world_bible_json FROM world_bibles WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return WorldBible.model_validate_json(row[0])

    def delete_world_bible(self, story_id: str) -> bool:
        conn = self._conn()
        cursor = conn.execute("DELETE FROM world_bibles WHERE story_id = ?", (story_id,))
        conn.commit()
        return cursor.rowcount > 0

    # ── novel status persistence ─────────────────────────────

    def save_novel_status(self, story_id: str, novel_status: NovelStatus) -> None:
        conn = self._conn()
        conn.execute(
            """
            INSERT INTO novel_statuses (story_id, status_json, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT(story_id) DO UPDATE SET
                status_json = excluded.status_json,
                updated_at = CURRENT_TIMESTAMP
            """,
            (story_id, novel_status.model_dump_json()),
        )
        conn.commit()

    def get_novel_status(self, story_id: str) -> NovelStatus | None:
        conn = self._conn()
        cursor = conn.execute(
            "SELECT status_json FROM novel_statuses WHERE story_id = ?",
            (story_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return NovelStatus.model_validate_json(row[0])

    def update_novel_status_after_chapter(self, story_id: str, chapter_number: int, word_count: int) -> NovelStatus | None:
        """Auto-update novel status after a chapter is generated."""
        conn = self._conn()
        status = self.get_novel_status(story_id)
        if status is None:
            return None
        status.total_chapters_written = chapter_number
        status.last_written_chapter = chapter_number
        status.total_word_count += word_count
        status.updated_at = ""
        self.save_novel_status(story_id, status)
        return status


# Backward-compatible alias: existing code imports InMemoryStoryStore
# and expects the same interface. SQLiteStoryStore is a drop-in replacement.
InMemoryStoryStore = SQLiteStoryStore
