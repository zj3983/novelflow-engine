from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from packages.story_core.chapter_history import replace_chapter_record
from packages.story_core.chapter_state_helpers import (
    GAME_STATE_FIELDS,
    sync_game_panel_from_state,
    without_monster_stat_surfaces,
)
from packages.story_core.character_profiles import (
    merge_character_alias_cards,
    reconcile_character_appearance_history,
    record_character_appearances,
)
from packages.story_core.dual_state import merge_state_change
from packages.story_core.equipment_cards import merge_equipment_cards
from packages.story_core.foreshadowing import (
    normalize_foreshadowing_text,
    reconcile_foreshadowing,
)
from packages.story_core.inventory_normalization import normalize_inventory_item_name
from packages.story_core.relationship_graph import apply_relationship_updates
from packages.story_core.world_state import append_continuity_facts, normalize_world_context
from packages.story_core.writing_learning import (
    learning_snapshot,
    lessons_from_quality_report,
    merge_writing_lessons,
)


_GAME_STATE_FIELDS = GAME_STATE_FIELDS
_sync_game_panel_from_state = sync_game_panel_from_state
_without_monster_stat_surfaces = without_monster_stat_surfaces


class ChapterStateSyncMixin:
    def _sync_time_state_after_chapter(self, state: dict[str, Any], project: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return {}
        existing = dict(state.get("time_state") or ((project.get("world_blueprint") or {}).get("time_state") or {}))
        launch_offset = int(existing.get("launch_clock_offset_minutes") or 17 * 60)
        previous_elapsed = int(existing.get("elapsed_minutes_since_launch") or 0)
        spans = [
            dict(item)
            for item in existing.get("chapter_time_spans", [])
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) != chapter_number
        ]
        # Replaying earlier chapters should rebuild elapsed time from the remaining spans.
        previous_elapsed = sum(int(item.get("duration_minutes") or 0) for item in spans)
        duration = self._infer_chapter_duration_minutes(chapter)
        start_label = self._clock_label(launch_offset + previous_elapsed)
        end_minutes = previous_elapsed + duration
        end_label = self._clock_label(launch_offset + end_minutes)
        span = {
            "chapter_number": chapter_number,
            "chapter_title": chapter.get("chapter_title") or f"Chapter {chapter_number}",
            "start": start_label,
            "end": end_label,
            "duration_minutes": duration,
            "scene_time": f"第{chapter_number}章章末",
        }
        spans.append(span)
        spans.sort(key=lambda item: int(item.get("chapter_number") or 0))
        total_elapsed = sum(int(item.get("duration_minutes") or 0) for item in spans)
        day = total_elapsed // (24 * 60) + 1
        time_state = {
            "server_day": day,
            "server_phase": f"开服第{day}天",
            "game_clock": self._clock_label(launch_offset + total_elapsed).replace(f"开服第{day}天", "") or "开服初期",
            "real_clock": existing.get("real_clock") or "晚上",
            "launch_clock_offset_minutes": launch_offset,
            "current_scene_time": f"第{chapter_number}章章末",
            "elapsed_minutes_since_launch": total_elapsed,
            "elapsed_since_launch": f"约{max(1, round(total_elapsed / 60, 1))}小时",
            "chapter_time_spans": spans[-120:],
            "cooldowns": existing.get("cooldowns") or [],
            "scheduled_events": existing.get("scheduled_events") or [],
            "time_rules": self._merge_unique(
                list(existing.get("time_rules") or []),
                [
                    "下一章必须承接 current_scene_time，除非正文明确下线、过夜或长途赶路。",
                    "前期开服节奏按小时推进，不要无说明跳到第二天或跨越大量任务。",
                    "寄售、任务、怪物刷新和NPC服务需要写出等待、路程或冷却代价。",
                ],
                limit=20,
            ),
        }
        state["time_state"] = time_state
        return time_state

    def _sync_state_after_chapter(self, state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return state
        synced = dict(state)
        summary = self._chapter_summary_payload(chapter)
        current_project = self.project()
        normalized_world = normalize_world_context(
            blueprint=current_project.get("world_blueprint"),
            state=synced,
            current_focus=current_project.get("current_focus"),
        )
        synced["world_snapshot"] = normalized_world.world_snapshot
        synced["continuity_facts"] = append_continuity_facts(
            normalized_world.continuity_facts,
            chapter_number=chapter_number,
            facts=summary["facts"],
        )
        foreshadowing = self._parse_foreshadowing_ledger(synced.get("foreshadowing"))
        reconciled_foreshadowing = reconcile_foreshadowing(
            foreshadowing,
            chapter_number=chapter_number,
            unresolved_threads=summary["unresolved_threads"],
            resolved_threads=summary["resolved_threads"],
        )
        synced["foreshadowing"] = [
            item.model_dump() for item in reconciled_foreshadowing
        ]
        if "manual_foreshadowing" in synced:
            manual_keys = {
                normalize_foreshadowing_text(item.text)
                for item in self._parse_foreshadowing_ledger(
                    synced.get("manual_foreshadowing")
                )
            }
            synced["manual_foreshadowing"] = [
                item.model_dump()
                for item in reconciled_foreshadowing
                if normalize_foreshadowing_text(item.text) in manual_keys
            ]
        synced["current_chapter"] = max(int(synced.get("current_chapter") or 0), chapter_number)
        synced["chapter_summaries"] = replace_chapter_record(
            list(synced.get("chapter_summaries") or []),
            summary,
            limit=240,
        )
        timeline_entry = {
            "chapter_number": chapter_number,
            "summary": summary["summary"],
            "impact": summary["next_focus"],
        }
        synced["timeline"] = replace_chapter_record(
            list(synced.get("timeline") or []),
            timeline_entry,
            limit=240,
        )
        memory_entry = {
            "chapter_number": chapter_number,
            "chapter_title": summary["chapter_title"],
            "summary": summary["summary"],
            "tags": [],
            "characters": self._character_names_in_chapter(synced, chapter),
            "locations": [],
            "factions": [],
            "quests": [],
            "items": [],
            "facts": summary["facts"],
            "unresolved_threads": summary["unresolved_threads"],
            "resolved_threads": summary["resolved_threads"],
        }
        is_game_story = self._is_game_story_payload(current_project, synced)
        protagonist_card = (
            self._protagonist_character_card(synced, current_project)
            if is_game_story
            else None
        )
        protagonist_cards = [protagonist_card] if protagonist_card else []
        entity_cards = self._chapter_entity_cards(chapter) if is_game_story else []
        synced["characters"] = self._merge_character_cards(
            list(synced.get("characters") or []),
            [*protagonist_cards, *entity_cards],
        )
        visible_character_names = self._character_names_in_chapter(synced, chapter)
        synced["characters"] = record_character_appearances(
            merge_character_alias_cards(synced["characters"]),
            chapter_number=chapter_number,
            visible_names=visible_character_names,
        )
        character_entity_names = [
            self._canonical_character_name(str(card.get("name") or ""))
            for card in entity_cards
            if self._is_character_card(card)
        ]
        memory_entry["characters"] = self._merge_unique(
            list(memory_entry["characters"]),
            [*([str(protagonist_card["name"])] if protagonist_card else []), *character_entity_names],
            limit=24,
        )
        synced["memory_index"] = replace_chapter_record(
            list(synced.get("memory_index") or []),
            memory_entry,
            limit=240,
        )
        if is_game_story:
            self._sync_time_state_after_chapter(synced, current_project, chapter)
            synced["world_snapshot"]["time_state"] = deepcopy(synced.get("time_state") or {})
        else:
            synced.pop("time_state", None)
            synced["world_snapshot"].pop("time_state", None)
        if summary["next_focus"] and summary["next_focus"] != "continue":
            synced["world_snapshot"]["current_focus"] = summary["next_focus"]
        return synced

    def _sync_project_after_chapter(self, project: dict[str, Any], state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return project
        summary = self._chapter_summary_payload(chapter)
        synced = dict(project)
        synced["current_chapter"] = chapter_number
        is_game_story = self._is_game_story_payload(synced, state)
        blueprint = dict(synced.get("world_blueprint") or {})
        equipment_merge = merge_equipment_cards(
            blueprint.get("equipment_cards"),
            state.get("equipment_cards"),
        )
        if equipment_merge.cards:
            blueprint["equipment_cards"] = equipment_merge.cards
        blueprint.pop("continuity_state", None)
        blueprint.pop("time_state", None)
        blueprint.pop("current_arc", None)
        synced["world_blueprint"] = blueprint
        if summary["next_focus"] and summary["next_focus"] != "continue":
            synced["current_focus"] = summary["next_focus"]

        existing_profiles: list[dict[str, Any]] = []
        for item in synced.get("character_profiles", []) if isinstance(synced.get("character_profiles"), list) else []:
            if not isinstance(item, dict):
                continue
            profile = dict(item)
            name = self._canonical_character_name(str(profile.get("name") or ""))
            if not name:
                continue
            profile["name"] = name
            if not self._is_character_card(profile):
                continue
            existing_profiles.append(profile)
        by_name = {str(item.get("name")): item for item in existing_profiles}
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            character = dict(character)
            name = self._canonical_character_name(str(character.get("name") or ""))
            if not name:
                continue
            character["name"] = name
            if not self._is_character_card(character):
                continue
            profile = dict(by_name.get(name) or {"name": name})
            for key in ("role", "game_id", "goals", "secrets", "relationships", "lifecycle_state"):
                if character.get(key) not in (None, "", [], {}):
                    profile[key] = character.get(key)
            if isinstance(character.get("real_state"), dict) and character["real_state"]:
                profile["real_state"] = deepcopy(character["real_state"])
            elif not is_game_story:
                profile.pop("game_state", None)
            if is_game_story and isinstance(character.get("game_state"), dict) and character["game_state"]:
                profile["game_state"] = deepcopy(character["game_state"])
            profile["current_emotion"] = character.get("current_emotion") or profile.get("current_emotion") or "neutral"
            profile["current_location"] = character.get("location") or profile.get("current_location") or ""
            profile["latest_chapter"] = chapter_number
            memories = character.get("memory") if isinstance(character.get("memory"), list) else []
            if memories:
                profile["memory"] = self._merge_unique(
                    list(profile.get("memory") or []),
                    [self._compact_text(item, 180) for item in memories[-6:]],
                    limit=40,
                )
            game_panel = character.get("game_panel")
            if isinstance(game_panel, dict) and game_panel:
                panel = dict(game_panel)
                if is_game_story and isinstance(character.get("game_state"), dict):
                    current = character["game_state"].get("current")
                    if isinstance(current, dict):
                        for field in _GAME_STATE_FIELDS:
                            value = current.get(field)
                            if value not in (None, "", [], {}):
                                panel[field] = deepcopy(value)
                profile["game_panel"] = panel | {"updated_chapter": chapter_number}
            if not is_game_story:
                profile.pop("game_state", None)
            by_name[name] = profile
        visible_character_names = self._character_names_in_chapter(state, chapter)
        synced["character_profiles"] = record_character_appearances(
            merge_character_alias_cards(list(by_name.values())),
            chapter_number=chapter_number,
            visible_names=visible_character_names,
        )
        relationship_updates: list[dict[str, Any]] = []
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            source = self._canonical_character_name(str(character.get("name") or ""))
            relationships = character.get("relationships")
            if isinstance(relationships, dict):
                items = relationships.items()
            elif isinstance(relationships, list):
                items = (("", item) for item in relationships)
            else:
                items = ()
            for fallback_target, relation in items:
                if not isinstance(relation, dict):
                    continue
                target = self._canonical_character_name(
                    str(relation.get("target") or relation.get("name") or fallback_target or "")
                )
                if not source or not target or source == target:
                    continue
                relation_summary = self._compact_text(
                    relation.get("current_state")
                    or relation.get("bond")
                    or summary.get("summary")
                    or "关系状态更新",
                    180,
                )
                relationship_updates.append(
                    {
                        "source": source,
                        "target": target,
                        "relation_type": relation.get("relation_type"),
                        "bond": relation.get("bond"),
                        "current_state": relation.get("current_state"),
                        "trust": relation.get("trust"),
                        "tension": relation.get("tension"),
                        "last_changed_chapter": chapter_number,
                        "changes": [
                            {
                                "chapter_number": chapter_number,
                                "summary": relation_summary,
                                "trust": relation.get("trust"),
                                "tension": relation.get("tension"),
                            }
                        ],
                    }
                )
        synced["relationship_graph"] = apply_relationship_updates(
            synced.get("relationship_graph"), relationship_updates
        )
        return synced

    def _prepare_sync_after_chapter(
        self,
        chapter: dict[str, Any],
        state: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        base_state = dict(state or self.state())
        synced_state = self._sync_state_after_chapter(base_state, chapter)
        synced_state = self._sync_ledger_from_chapter_body(synced_state, chapter)
        chapter["updated_story"] = synced_state
        chapter["chapter_summary"] = self._chapter_summary_payload(chapter)
        new_lessons = lessons_from_quality_report(chapter.get("quality_report") if isinstance(chapter.get("quality_report"), dict) else {})
        synced_state["writing_lessons"] = merge_writing_lessons(synced_state.get("writing_lessons"), new_lessons)
        chapter["updated_story"] = synced_state
        synced_project = self._sync_project_after_chapter(self.project(), synced_state, chapter)
        blueprint = dict(synced_project.get("world_blueprint") or {})
        blueprint["writing_learning"] = learning_snapshot(synced_state.get("writing_lessons"))
        synced_project["world_blueprint"] = blueprint
        return synced_state, synced_project

    def _sync_after_chapter(self, chapter: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
        synced_state, synced_project = self._prepare_sync_after_chapter(chapter, state)
        self._write_json(self.webnovel_dir / "state.json", synced_state)
        self._write_json(self.webnovel_dir / "project.json", synced_project)
        return synced_state

    def _state_before_chapter(self, chapter_number: int) -> dict[str, Any]:
        current_state = dict(self.state())
        current_chapter = int(current_state.get("current_chapter") or 0)
        if chapter_number > current_chapter:
            return current_state
        return self._generation_state_for_target(current_state, chapter_number)

    def _chapter_body_ledger_summary(self, chapter: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("chapter_title") or f"第{chapter_number}章")
        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        real = ledger.get("real") if isinstance(ledger.get("real"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}

        exp = str(protagonist.get("exp") or "").strip()
        hp = str(protagonist.get("hp") or "").strip()
        mp = str(protagonist.get("mp") or "").strip()
        durability = str(equipment.get("durability") or "").strip()
        currency = str(economy.get("game_currency") or "").strip()
        backpack = str(economy.get("backpack") or "").strip()
        real_balance = str(real.get("end_balance") or economy.get("real_balance") or "").strip()
        start_balance = str(real.get("start_balance") or "").strip()
        balance_unchanged = bool(real_balance and start_balance and real_balance == start_balance)

        inv_text = "、".join(f"{name}×{count}" for name, count in inventory.items()) if inventory else "空"
        real_name = str(protagonist.get("real_name") or "主角").strip()
        game_id = str(protagonist.get("game_id") or real_name).strip()
        identity = str(protagonist.get("class_path") or protagonist.get("identity") or "").strip()
        weapon = str(equipment.get("weapon") or "").strip()
        facts: list[str] = [
            f"{real_name}现实余额{real_balance}" if real_balance else "",
            "，".join(
                item
                for item in (
                    f"{game_id}当前等级{protagonist.get('level')}" if protagonist.get("level") else "",
                    f"身份为{identity}" if identity else "",
                )
                if item
            ),
            f"经验{exp}" if exp else "",
            f"生命{hp}" if hp else "",
            f"法力{mp}" if mp else "",
            f"{weapon}耐久{durability}" if weapon and durability else "",
            f"钱袋{currency}" if currency else "",
            f"背包为{inv_text}" + (f"，占用{backpack}" if backpack else ""),
        ]
        for name, value in quests.items():
            text = str(value).strip()
            if text:
                facts.append(f"{name}：{text}")
        facts = [item for item in facts if item]

        quest_focus = next(
            (f"{name}{value}" for name, value in quests.items() if str(value).strip()),
            "",
        )
        ledger_parts = [
            part
            for part in (
                f"经验{exp}" if exp else "",
                f"生命{hp}" if hp else "",
                f"法力{mp}" if mp else "",
                f"游戏货币{currency}" if currency else "",
                f"背包{inv_text}" if inventory else "",
            )
            if part
        ]
        summary = f"{game_id}本章推进{quest_focus or '当前目标'}"
        if ledger_parts:
            summary += "，章末状态为" + "、".join(ledger_parts)
        summary += "。"
        existing_summary = chapter.get("chapter_summary") if isinstance(chapter.get("chapter_summary"), dict) else {}
        confirmed_focus = str(existing_summary.get("next_focus") or "").strip()
        if not confirmed_focus:
            candidate = str(chapter.get("next_outline") or "").strip()
            confirmed_focus = "" if candidate.lower() in {"", "continue"} else candidate
        next_focus = confirmed_focus or "承接当前任务状态，推进一个具体目标并更新账本。"
        if not confirmed_focus and "后坡巡查" in quests and "2/3" in str(quests["后坡巡查"]):
            next_focus = "先解决血蓝和补给，再完成后坡巡查最后一段。"
        return {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "cadence": "measured",
            "summary": summary,
            "facts": facts[:12],
            "unresolved_threads": [
                item
                for item in (
                    "现实余额仍未改变" if balance_unchanged else "",
                )
                if item
            ],
            "next_focus": next_focus,
            "primary_conflict": {"collision": next_focus},
            "secondary_conflict": {"detail": "外部人物只能依据本章公开发生的事实作出判断。"},
            "event_beat": {"turn": "任务推进", "pivot": next_focus},
        }

    def _sync_game_character_from_ledger(
        self,
        character: dict[str, Any],
        ledger: dict[str, Any],
        *,
        chapter_number: int | None = None,
    ) -> dict[str, Any]:
        """Write game ledger leaves to game_state and its legacy panel only."""

        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests")
        pressure = ledger.get("pressure") if isinstance(ledger.get("pressure"), dict) else {}
        panel = dict(character.get("game_panel") or {})
        game_state = dict(character.get("game_state") or {})
        current = dict(game_state.get("current") or {}) if isinstance(game_state.get("current"), dict) else {}
        previous_current = deepcopy(current)

        game_id = protagonist.get("game_id") or current.get("game_id") or panel.get("game_id") or character.get("game_id")
        if not game_id and character.get("name") == "苏叶":
            game_id = "夜烬"
        values = {
            "game_id": game_id,
            "level": protagonist.get("level"),
            "class_path": protagonist.get("class_path") or protagonist.get("identity"),
            "exp": protagonist.get("exp"),
            "hp": protagonist.get("hp"),
            "mp": protagonist.get("mp"),
            "attributes": protagonist.get("attributes"),
            "unallocated_attribute_points": protagonist.get("unallocated_attribute_points"),
            "attribute_point_awards": protagonist.get("attribute_point_awards"),
            "attribute_allocations": protagonist.get("attribute_allocations"),
            "equipment": equipment,
            "inventory": economy.get("inventory"),
            "backpack": economy.get("backpack"),
            "currency": economy.get("game_currency") or economy.get("currency") or ledger.get("currency"),
            "quests": quests,
            "risk": pressure,
        }
        skills = ledger.get("skills") or protagonist.get("skills")
        if isinstance(skills, list):
            values["skills"] = [str(item) for item in skills if str(item).strip()]
        elif isinstance(skills, dict):
            values["skills"] = [
                str(item)
                for value in skills.values()
                for item in (value if isinstance(value, list) else [value])
                if str(item).strip()
            ]

        attribute_fields = {
            "attributes",
            "unallocated_attribute_points",
            "attribute_point_awards",
            "attribute_allocations",
        }

        def valid_attribute_value(field: str, value: Any) -> bool:
            if field == "attributes":
                return isinstance(value, dict)
            if field == "unallocated_attribute_points":
                return isinstance(value, int) and not isinstance(value, bool) and value >= 0
            return isinstance(value, list) and all(isinstance(item, dict) for item in value)

        for field, value in values.items():
            if field in attribute_fields:
                if field not in protagonist or not valid_attribute_value(field, value):
                    continue
            elif value in (None, "", [], {}):
                continue
            current[field] = deepcopy(value)
            panel[field] = deepcopy(value)
        if current.get("game_id"):
            character["game_id"] = current["game_id"]
        if chapter_number is not None:
            panel["updated_chapter"] = chapter_number
        game_state["current"] = current
        game_state.setdefault("recent_changes", [])
        changed_fields = [
            field
            for field in values
            if previous_current.get(field) != current.get(field)
        ]
        if chapter_number is not None and changed_fields:
            fact = f"游戏账本更新：{', '.join(changed_fields[:5])}"
            recent_changes = game_state["recent_changes"]
            if not any(
                isinstance(item, dict)
                and item.get("chapter") == int(chapter_number)
                and item.get("fact") == fact
                for item in recent_changes
            ):
                recent_changes.append({"chapter": int(chapter_number), "fact": fact})
        character["game_state"] = game_state
        character["game_panel"] = panel
        return character

    @staticmethod
    def _chapter_state_events(chapter: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for key in ("state_changes", "events", "ledger_events"):
            raw = chapter.get(key)
            if isinstance(raw, dict):
                raw = raw.get("events") or raw.get("changes") or []
            if isinstance(raw, list):
                events.extend(item for item in raw if isinstance(item, dict))
        summary = chapter.get("chapter_summary")
        if isinstance(summary, dict) and isinstance(summary.get("state_changes"), list):
            events.extend(item for item in summary["state_changes"] if isinstance(item, dict))
        return events

    @staticmethod
    def _event_change_payload(
        event: dict[str, Any],
        *,
        line: str,
        strict_namespace: bool = False,
    ) -> dict[str, Any]:
        change = event.get("change") or event.get("state_change") or event.get("state_delta")
        if not isinstance(change, dict):
            change = {}
        namespace_keys = {"real_change", "real_state", "game_change", "game_state"}
        has_namespace = any(key in event or key in change for key in namespace_keys)
        if line == "reality":
            candidates = (
                event.get("real_change"),
                event.get("real_state"),
                change.get("real_change"),
                change.get("real_state"),
            )
        else:
            candidates = (
                event.get("game_change"),
                event.get("game_state"),
                change.get("game_change"),
                change.get("game_state"),
            )
        selected = next((item for item in candidates if isinstance(item, dict)), None) if has_namespace else None
        if selected is None and not has_namespace and not strict_namespace:
            selected = change
        if not isinstance(selected, dict):
            return {}
        if isinstance(selected.get("current"), dict):
            current = selected["current"]
        else:
            current = {
                key: value
                for key, value in selected.items()
                if key not in {"line", "scene_line", "fact", "recent_changes", "real_change", "game_change"}
            }
        return {
            "current": deepcopy(current),
            "fact": str(event.get("fact") or selected.get("fact") or change.get("fact") or "").strip(),
        } if current else {}

    def _apply_chapter_state_events(
        self,
        state: dict[str, Any],
        chapter: dict[str, Any],
        *,
        is_game_story: bool,
    ) -> None:
        chapter_number = int(chapter.get("chapter_number") or 0)
        characters = state.get("characters") if isinstance(state.get("characters"), list) else []
        for event in self._chapter_state_events(chapter):
            raw_line = str(event.get("line") or event.get("scene_line") or "").strip().lower()
            if raw_line in {"游戏", "game_state"}:
                raw_line = "game"
            elif raw_line in {"现实", "real", "real_state"}:
                raw_line = "reality"
            elif raw_line in {"混合", "mixed", "过渡", "切换"}:
                raw_line = "transition"
            if raw_line not in {"game", "reality", "transition"}:
                continue
            lines = ("reality", "game") if raw_line == "transition" else (raw_line,)
            for line in lines:
                if line == "game" and not is_game_story:
                    continue
                change = self._event_change_payload(
                    event,
                    line=line,
                    strict_namespace=raw_line == "transition",
                )
                if not isinstance(change.get("current"), dict) or not change["current"]:
                    continue
                target = str(event.get("character") or event.get("character_name") or event.get("target") or "").strip()
                if target:
                    selected = [
                        item
                        for item in characters
                        if isinstance(item, dict) and item.get("name") == target
                    ]
                    if not selected:
                        continue
                else:
                    selected = [
                        item
                        for item in characters
                        if isinstance(item, dict) and item.get("role") in {"protagonist", "主角"}
                    ]
                    if not selected:
                        selected = [item for item in characters if isinstance(item, dict)][:1]
                for character in selected:
                    state_key = "game_state" if line == "game" else "real_state"
                    existing = character.get(state_key) if isinstance(character.get(state_key), dict) else {}
                    existing_current = existing.get("current") if isinstance(existing.get("current"), dict) else {}
                    if not any(existing_current.get(key) != value for key, value in change["current"].items()):
                        continue
                    merged = merge_state_change(
                        character,
                        line=line,
                        change=change,
                        chapter=chapter_number,
                    )
                    character.clear()
                    character.update(merged)
                    if line == "game":
                        _sync_game_panel_from_state(character)

    def _sync_ledger_from_chapter_body(self, state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        body = str(chapter.get("body") or "")
        protagonist_body = _without_monster_stat_surfaces(body)
        is_game_story = self._is_game_story_payload(self.project(), state)
        if not body or not is_game_story:
            self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
            return state
        chinese_markers = (
            "经验",
            "生命",
            "法力",
            "钱袋：",
            "钱袋:",
            "背包",
            "背包：",
            "背包:",
            "新手法杖",
            "后坡巡查",
            "清道夫委托",
            "铜币",
            "等级：",
            "等级:",
            "任务：",
            "任务:",
            "现实余额",
            "可用余额",
            "银行卡可用余额",
        )
        english_field = re.search(
            r"\b(?:experience|exp|hp|health|mp|mana|inventory|backpack|level|durability|equipment)\s*(?:[:=]|\s+\d)",
            body,
            flags=re.IGNORECASE,
        )
        currency_field = re.search(
            r"\b(?:currency|coins?)\s*[:=]",
            body,
            flags=re.IGNORECASE,
        )
        amount_context = re.search(
            r"\b\d+(?:\.\d+)?\s*(?:coins?|copper|gold|silver)\b",
            body,
            flags=re.IGNORECASE,
        )
        if not any(marker in body for marker in chinese_markers) and not (english_field or currency_field or amount_context):
            self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
            return state
        ledger = dict(state.get("progression_ledger") or {})
        protagonist = dict(ledger.get("protagonist") or {})
        panel = dict(ledger.get("panel") or {})
        economy = dict(ledger.get("economy") or {})
        real = dict(ledger.get("real") or {})
        equipment = dict(ledger.get("equipment") or {})
        quests = dict(ledger.get("quests") or {})
        protagonist_card = next(
            (
                item
                for item in (state.get("characters") or [])
                if isinstance(item, dict)
                and str(item.get("role") or "").strip().lower() in {"protagonist", "主角"}
            ),
            {},
        )
        if protagonist_card:
            protagonist.setdefault("real_name", str(protagonist_card.get("name") or "").strip())
            protagonist.setdefault("game_id", str(protagonist_card.get("game_id") or "").strip())

        def last(pattern: str, source: str | None = None) -> str:
            matches = re.findall(pattern, body if source is None else source, flags=re.IGNORECASE)
            return str(matches[-1]).strip() if matches else ""

        level = last(
            r"【[^】]{1,24}；\s*lv\.?\s*(\d+)(?=[^】]{0,24}(?:经验|生命|法力|可用属性点))",
            protagonist_body,
        )
        if not level:
            level = last(
            r"(?:等级提升至|升级到|升级至|升到|当前等级\s*[：:]?|等级\s*[：:]?|level\s*[:=]?)\s*(?:lv\.?\s*)?(\d+)",
            protagonist_body,
            )
        exp = last(r"(?:经验|experience|exp)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)", protagonist_body)
        hp = last(r"(?:生命|hp|health)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)", protagonist_body)
        mp = last(r"(?:法力|mp|mana)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)", protagonist_body)
        durability = last(
            r"(?:新手法杖[^。！？\n]{0,60}?耐久\s*(?:回到|恢复到|变为|为)?|法杖[^。！？\n]{0,60}?耐久\s*(?:回到|恢复到|变为|为)?|耐久(?:回到|恢复到|变为)|durability\s*[:=]?)\s*(\d+\s*/\s*\d+|\d{1,3}%)",
            protagonist_body,
        )
        money = last(r"(?:钱袋\s*[：:]|currency\s*[:=]|coins?\s*[:=])\s*([^\n。；,，】]+)")
        if not money:
            amount_matches = re.findall(
                r"\b\d+(?:\.\d+)?\s*(?:coins?|copper|gold|silver)\b",
                body,
                flags=re.IGNORECASE,
            )
            money = str(amount_matches[-1]).strip() if amount_matches else ""
        patrol = last(r"后坡巡查[：:]\s*(\d+\s*/\s*\d+)")
        quest_line = last(r"(?<!完成)(?:任务\s*[：:]|quest(?:\s+status)?\s*[:=])\s*([^\n。】]+)")
        real_balance = last(
            r"(?:银行卡可用余额|现实账户余额|现实余额|可用余额)"
            r"\s*(?:(?:停在|变为|变成|还有|只剩|为)\s*)?[：:]?\s*"
            r"(\d+(?:\.\d+)?\s*元)"
        )

        if level:
            protagonist["level"] = f"Lv.{level}"
            panel["level"] = protagonist["level"]
        if exp:
            protagonist["exp"] = exp.replace(" ", "")
            panel["exp"] = protagonist["exp"]
        if hp:
            protagonist["hp"] = hp.replace(" ", "")
        if mp:
            protagonist["mp"] = mp.replace(" ", "")
        if durability:
            protagonist["weapon_durability"] = f"新手法杖：{durability.replace(' ', '')}"
            equipment["weapon"] = "新手法杖"
            equipment["durability"] = durability.replace(" ", "")
        if money:
            economy["game_currency"] = money.rstrip("】】 ]")
        if real_balance:
            normalized_balance = real_balance.replace(" ", "")
            real["end_balance"] = normalized_balance
            economy["real_balance"] = normalized_balance
        if "急账代付已通过" in body or re.search(r"房租[^。\n]{0,80}信用卡最低还款[^。\n]{0,40}已付清", body):
            real["paid"] = "正文明确写出的现实急账已付清"

        inventory_lines = re.findall(
            r"(?:背包|inventory|backpack)\s*(?:[：:]\s*)?([^\n。]+)",
            body,
            flags=re.IGNORECASE,
        )
        quantified_inventory_lines = [
            str(item).strip()
            for item in inventory_lines
            if re.search(r"[×xX*＊]\s*\d+", str(item))
        ]
        inventory_line = quantified_inventory_lines[-1] if quantified_inventory_lines else ""
        if inventory_line:
            inventory: dict[str, int] = {}
            for raw_item, count in re.findall(
                r"([^×xX*＊,，;；]+?)\s*[×xX*＊]\s*(\d+)",
                inventory_line,
            ):
                item = normalize_inventory_item_name(
                    re.sub(r"\s+", " ", raw_item)
                )
                if item:
                    inventory[item] = int(count)
            if inventory:
                economy["inventory"] = inventory
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}
        removed_inventory_items = [
            item
            for item in list(inventory)
            if f"{item}从背包消失" in body or f"{item}已从背包消失" in body
        ]
        for item in removed_inventory_items:
            inventory.pop(item, None)
        if removed_inventory_items:
            economy["inventory"] = inventory
        occupied = last(r"占用[：:]\s*(\d+\s*/\s*20)")
        if not occupied and inventory_line:
            occupied_match = re.search(r"(?:占用)?\s*(\d+\s*/\s*20)", inventory_line)
            occupied = occupied_match.group(1) if occupied_match else ""
        if removed_inventory_items and inventory:
            economy["backpack"] = f"{len(inventory)}/20"
        elif occupied:
            economy["backpack"] = occupied.replace(" ", "")
        completed_quests: list[str] = []
        for match in re.finditer(r"完成任务\s*[：:]?\s*([^\n。；;，,】\]]+)", body):
            prefix = body[max(0, match.start() - 12) : match.start()]
            if re.search(
                r"(?:还没有|没有|尚未|并未|未能|无法|不能|如果|若|要是|只要|一旦|等到?|是否|能否)\s*$",
                prefix,
            ):
                continue
            completed_name = match.group(1).strip(" \t：:，,")
            if completed_name:
                completed_quests.append(completed_name)

        active_quest = str(quests.get("active") or "").strip()
        active_name = re.split(r"[：:(（]", active_quest, maxsplit=1)[0].strip()
        for completed_name in completed_quests:
            quests[completed_name] = "已完成"
            if active_name == completed_name:
                quests.pop("active", None)
        if quest_line and quest_line not in completed_quests:
            quests["active"] = quest_line
        progress_matches = re.findall(
            r"([^。！？\n【】]{1,30}?)(?:任务)?仍(?:停在|为|是)\s*(\d+\s*/\s*\d+)[，,；;]?\s*(?:尚未提交|未提交)",
            body,
        )
        if progress_matches:
            raw_name, raw_progress = progress_matches[-1]
            quest_name = re.sub(r"(?:普通)?任务[：:]?", "", raw_name).strip(" ，,；;：:")
            if quest_name:
                quests["active"] = f"{quest_name}：{raw_progress.replace(' ', '')}；未提交"
        if protagonist:
            ledger["protagonist"] = protagonist
        protagonist.pop("cost_delta", None)
        if panel:
            ledger["panel"] = panel
        if economy:
            ledger["economy"] = economy
        if real:
            ledger["real"] = real
        if equipment:
            ledger["equipment"] = equipment
        equipment.pop("durability_delta", None)
        if quests:
            ledger["quests"] = quests
        state["progression_ledger"] = ledger

        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict) or character.get("role") not in {"protagonist", "主角"}:
                continue
            character.setdefault("game_panel", {})
            if identity := str(protagonist.get("identity") or protagonist.get("class_path") or "").strip():
                character["game_panel"]["identity"] = identity
            self._sync_game_character_from_ledger(
                character,
                ledger,
                chapter_number=int(chapter.get("chapter_number") or 0),
            )
            if real_balance:
                real_state = dict(character.get("real_state") or {})
                current_real = dict(real_state.get("current") or {})
                current_real["balance"] = real["end_balance"]
                real_state["current"] = current_real
                real_state.setdefault("recent_changes", [])
                character["real_state"] = real_state
        if level or exp or hp or mp or durability or money or real_balance or inventory_line or quest_line:
            summary = self._chapter_body_ledger_summary(chapter, ledger)
            chapter["chapter_summary"] = summary
            state["chapter_summaries"] = replace_chapter_record(
                list(state.get("chapter_summaries") or []),
                summary,
                limit=240,
            )
            chapter_number = int(chapter.get("chapter_number") or 0)
            normalized_world = normalize_world_context(
                blueprint=self.project().get("world_blueprint"),
                state=state,
                current_focus=self.project().get("current_focus"),
            )
            state["world_snapshot"] = normalized_world.world_snapshot
            state["continuity_facts"] = append_continuity_facts(
                normalized_world.continuity_facts,
                chapter_number=chapter_number,
                facts=summary["facts"],
            )
            timeline_entry = {
                "chapter_number": chapter_number,
                "summary": summary["summary"],
                "impact": summary["next_focus"],
            }
            state["timeline"] = replace_chapter_record(
                list(state.get("timeline") or []),
                timeline_entry,
                limit=240,
            )
            memory_entry = {
                "chapter_number": chapter_number,
                "chapter_title": summary["chapter_title"],
                "summary": summary["summary"],
                "tags": [],
                "characters": self._character_names_in_chapter(state, chapter),
                "locations": [],
                "factions": [],
                "quests": [],
                "items": [],
                "facts": summary["facts"],
                "unresolved_threads": summary["unresolved_threads"],
            }
            state["memory_index"] = replace_chapter_record(
                list(state.get("memory_index") or []),
                memory_entry,
                limit=240,
            )
        self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
        return state
