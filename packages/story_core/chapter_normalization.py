from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from packages.story_core.chapter_read_model import _chapter_payload_title
from packages.story_core.models import StoryState


class ChapterNormalizationMixin:
    def _compact_text(self, value: Any, limit: int = 180) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _merge_unique(self, current: list[Any], additions: list[Any], *, limit: int = 80) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for item in [*current, *additions]:
            if item in (None, ""):
                continue
            key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result[-limit:]

    def _coerce_summary_mapping(self, value: Any, *, label: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        return {"note": self._compact_text(value, 220), "source": label}

    def _clean_state_fact_list(self, values: Any) -> list[Any]:
        if not isinstance(values, list):
            return []
        blocked_fragments = (
            "manual draft",
            "第2章事实：夜烬仍为Lv.1",
            "夜烬仍为Lv.1见习冒险者",
            "第2章事实：新手法杖9/10",
            "第2章事实：背包为粗糙狼皮×7",
        )
        cleaned: list[Any] = []
        for item in values:
            if not isinstance(item, str):
                cleaned.append(item)
                continue
            compact = self._compact_text(item, 260)
            if any(fragment in compact for fragment in blocked_fragments):
                continue
            if self._is_placeholder_text(compact) or re.search(
                r"(?:事实|摘要|fact|summary)\s*[:：]\s*continue\s*$",
                compact,
                re.IGNORECASE,
            ):
                continue
            cleaned.append(item)
        return cleaned

    def _clean_summary_mapping(self, value: Any, *, label: str) -> dict[str, Any]:
        mapping = self._coerce_summary_mapping(value, label=label)
        if not mapping:
            return {}
        meaningful_values = [item for key, item in mapping.items() if key != "source"]
        if not meaningful_values or all(self._is_placeholder_text(item) for item in meaningful_values):
            return {}
        return mapping

    def _is_placeholder_text(self, value: Any) -> bool:
        text = self._compact_text(value, 260).lower()
        if not text:
            return True
        return text in {
            "continue",
            "manual draft",
            "manual rewrite",
            "manual chapter",
            "chapter-progress",
        } or text.startswith("codex hand-written")

    def _first_mapping_text(self, value: Any, keys: tuple[str, ...], fallback: str = "") -> str:
        if isinstance(value, dict):
            for key in keys:
                text = self._compact_text(value.get(key), 260)
                if text and not self._is_placeholder_text(text):
                    return text
            note = self._compact_text(value.get("note"), 260)
            if note and not self._is_placeholder_text(note):
                return note
            return fallback
        text = self._compact_text(value, 260)
        if text and not self._is_placeholder_text(text):
            return text
        return fallback

    def _hydrate_chapter_display_fields(self, chapter: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Backfill workbench insight cards for legacy/manual file chapters.

        Generated bundles already carry these fields. Older restored chapters and
        hand-written rewrites may only have a chapter summary, which made the UI
        show empty "not organized yet" cards even though enough chapter state
        existed to present a useful reading report.
        """

        hydrated = dict(chapter)
        try:
            chapter_number = int(hydrated.get("chapter_number") or 0)
        except (TypeError, ValueError):
            chapter_number = 0
        if chapter_number > 0:
            display_title = _chapter_payload_title(hydrated, chapter_number)
            if not display_title:
                try:
                    display_title = self._authoritative_chapter_title(
                        chapter_number,
                        operation="generate",
                    )
                except ValueError:
                    display_title = f"Chapter {chapter_number}"
            hydrated["chapter_title"] = display_title
            if isinstance(hydrated.get("chapter_summary"), dict):
                hydrated["chapter_summary"] = dict(hydrated["chapter_summary"])
                hydrated["chapter_summary"]["chapter_title"] = display_title
        source_state = state if isinstance(state, dict) else self.state()
        hydrated = self._sanitize_legacy_chapter_artifacts(hydrated, source_state)
        summary = self._chapter_summary_payload(hydrated)
        summary_text = self._compact_text(summary.get("summary"), 260)
        next_focus = self._compact_text(summary.get("next_focus"), 220) or hydrated.get("next_outline") or "continue"

        if not isinstance(hydrated.get("chapter_intent"), dict) or not hydrated.get("chapter_intent"):
            primary = self._coerce_summary_mapping(summary.get("primary_conflict"), label="primary_conflict")
            secondary = self._coerce_summary_mapping(summary.get("secondary_conflict"), label="secondary_conflict")
            collision = self._first_mapping_text(primary, ("collision", "summary", "detail"), summary_text)
            hydrated["chapter_intent"] = {
                "chapter_title": summary.get("chapter_title"),
                "cadence": summary.get("cadence") or hydrated.get("cadence") or "measured",
                "next_focus": next_focus,
                "primary_conflict": primary | {"collision": collision},
                "secondary_conflict": secondary,
            }

        if not isinstance(hydrated.get("event_beat"), dict) or not hydrated.get("event_beat"):
            event_beat = self._coerce_summary_mapping(summary.get("event_beat"), label="event_beat")
            pivot = self._first_mapping_text(event_beat, ("pivot", "summary", "detail"), summary_text)
            hydrated["event_beat"] = {
                "turn": self._first_mapping_text(event_beat, ("turn",), "chapter-progress"),
                "pivot": pivot,
            }

        if not isinstance(hydrated.get("memory_constraints"), dict) or not hydrated.get("memory_constraints"):
            facts = [
                self._compact_text(item, 220)
                for item in (summary.get("facts") if isinstance(summary.get("facts"), list) else [])
                if str(item).strip() and not self._is_placeholder_text(item)
            ]
            hydrated["memory_constraints"] = {
                "must_keep_facts": facts[:8] or ([summary_text] if summary_text else []),
                "unresolved_threads": [
                    self._compact_text(item, 220)
                    for item in (
                        summary.get("unresolved_threads")
                        if isinstance(summary.get("unresolved_threads"), list)
                        else []
                    )
                    if str(item).strip()
                ][:8],
                "current_focus": next_focus,
            }

        if not isinstance(hydrated.get("character_moves"), list) or not hydrated.get("character_moves"):
            names = self._character_names_in_chapter(source_state, hydrated)
            if not names:
                for character in source_state.get("characters", []) if isinstance(source_state.get("characters"), list) else []:
                    if isinstance(character, dict) and str(character.get("name") or "").strip():
                        names = [str(character["name"]).strip()]
                        break
            hydrated["character_moves"] = [
                {
                    "name": name,
                    "goal": next_focus,
                    "action": summary_text,
                    "priority": index + 1,
                }
                for index, name in enumerate(names[:4])
            ]

        if not isinstance(hydrated.get("character_cards"), list) or not hydrated.get("character_cards"):
            visible_names = set(self._character_names_in_chapter(source_state, hydrated))
            hydrated["character_cards"] = [
                deepcopy(character)
                for character in (
                    source_state.get("characters", [])
                    if isinstance(source_state.get("characters"), list)
                    else []
                )
                if isinstance(character, dict)
                and str(character.get("name") or "").strip() in visible_names
            ][:8]

        if not hydrated.get("next_outline") and next_focus:
            hydrated["next_outline"] = next_focus

        return hydrated

    def _sanitize_legacy_chapter_artifacts(
        self,
        chapter: dict[str, Any],
        state: dict[str, Any],
    ) -> dict[str, Any]:
        """Hide stale cross-genre artifacts without rewriting accepted prose."""

        cleaned = deepcopy(chapter)
        project = self.project()
        game_story = self._is_game_story_payload(project, state)

        if not game_story:
            simulation_plan = cleaned.get("simulation_plan")
            if isinstance(simulation_plan, dict):
                world_context = simulation_plan.get("world_context")
                world_text = json.dumps(world_context, ensure_ascii=False).lower()
                game_markers = (
                    "world-pulse/v1",
                    "market_order_book",
                    "price_copper",
                    "white_robe_guild",
                    "service_npc",
                )
                if any(marker in world_text for marker in game_markers):
                    simulation_plan = dict(simulation_plan)
                    simulation_plan.pop("world_context", None)
                    cleaned["simulation_plan"] = simulation_plan

        summary = cleaned.get("chapter_summary")
        if isinstance(summary, dict):
            summary = dict(summary)
            primary = summary.get("primary_conflict")
            if isinstance(primary, dict):
                lead = str(primary.get("lead") or "").strip()
                opposition = str(primary.get("opposition") or "").strip()
                if lead and lead == opposition:
                    collision = str(primary.get("collision") or "").strip()
                    summary["primary_conflict"] = {}
                    event_beat = summary.get("event_beat")
                    if isinstance(event_beat, dict) and collision:
                        event_beat = dict(event_beat)
                        pivot = str(event_beat.get("pivot") or "")
                        if collision in pivot:
                            event_beat["pivot"] = pivot.replace(collision, "").strip(" ，。")
                        summary["event_beat"] = event_beat
                    cleaned["chapter_summary"] = summary

        return cleaned

    def _sanitize_story_state(self, state: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(state)
        ledger = sanitized.get("progression_ledger")
        if isinstance(ledger, dict):
            ledger = dict(ledger)
            economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
            if isinstance(economy.get("inventory"), dict):
                ledger.pop("inventory", None)
            if economy.get("game_currency") not in (None, "", [], {}):
                ledger.pop("currency", None)
            if isinstance(ledger.get("skills"), list):
                ledger["skills"] = [item for item in ledger["skills"] if "熟练度" not in str(item)]
                if not ledger["skills"]:
                    ledger.pop("skills", None)
            pressure = ledger.get("pressure") if isinstance(ledger.get("pressure"), dict) else {}
            next_pressure = pressure.get("next") if isinstance(pressure, dict) else None
            if isinstance(next_pressure, list):
                pressure = dict(pressure)
                pressure["next"] = [
                    "后坡探路前置已满足，但等级和补给仍压着风险"
                    if "熟练度" in str(item)
                    else item
                    for item in next_pressure
                ]
                ledger["pressure"] = pressure
            sanitized["progression_ledger"] = ledger
        sanitized["world_facts"] = self._clean_state_fact_list(sanitized.get("world_facts"))
        summaries: list[Any] = []
        changed = False
        for item in sanitized.get("chapter_summaries", []) if isinstance(sanitized.get("chapter_summaries"), list) else []:
            if not isinstance(item, dict):
                summaries.append(item)
                continue
            summary = dict(item)
            cleaned_facts = self._clean_state_fact_list(summary.get("facts"))
            if cleaned_facts != summary.get("facts"):
                summary["facts"] = cleaned_facts
                changed = True
            for field in ("primary_conflict", "secondary_conflict", "event_beat"):
                coerced = self._clean_summary_mapping(summary.get(field), label=field)
                if coerced != summary.get(field):
                    summary[field] = coerced
                    changed = True
            summaries.append(summary)
        deduped_summaries = self._dedupe_numbered_records(summaries)
        if changed or deduped_summaries != sanitized.get("chapter_summaries"):
            sanitized["chapter_summaries"] = deduped_summaries
        if isinstance(sanitized.get("timeline"), list):
            sanitized["timeline"] = self._dedupe_numbered_records(list(sanitized.get("timeline") or []))
        if isinstance(sanitized.get("memory_index"), list):
            memory_records = []
            for item in sanitized.get("memory_index") or []:
                if isinstance(item, dict):
                    record = dict(item)
                    record["facts"] = self._clean_state_fact_list(record.get("facts"))
                    memory_records.append(record)
                else:
                    memory_records.append(item)
            sanitized["memory_index"] = self._dedupe_numbered_records(memory_records)
        return sanitized

    def _strip_temporary_generation_fields(self, state: dict[str, Any]) -> dict[str, Any]:
        stripped = dict(state)
        ledger = stripped.get("progression_ledger")
        if not isinstance(ledger, dict):
            return stripped
        ledger = dict(ledger)
        variant = ledger.get("simulation_variant")
        if isinstance(variant, dict) and "rewrite_guidance" in variant:
            variant = dict(variant)
            variant.pop("rewrite_guidance", None)
            ledger["simulation_variant"] = variant
            stripped["progression_ledger"] = ledger
        return stripped

    def _validated_runtime_state(
        self,
        updated_story: Any,
        current_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        if not isinstance(updated_story, dict) or not updated_story:
            return None
        if updated_story.get("story_id") != current_state.get("story_id"):
            return None
        if not all(
            isinstance(updated_story.get(field), str)
            for field in ("story_id", "outline", "genre", "style")
        ):
            return None
        chapter_number = updated_story.get("current_chapter")
        if not isinstance(chapter_number, int) or isinstance(chapter_number, bool) or chapter_number < 0:
            return None
        try:
            validated = StoryState.model_validate(updated_story)
        except (TypeError, ValueError):
            return None

        usable = validated.model_dump(mode="json")
        extra_contracts = {
            "time_state": lambda value: isinstance(value, dict),
            "novel_type": lambda value: isinstance(value, str),
            "novel_type_id": lambda value: isinstance(value, str),
            "novel_type_ids": lambda value: isinstance(value, list)
            and all(isinstance(item, str) for item in value),
        }
        for field, is_valid in extra_contracts.items():
            source = updated_story if field in updated_story else current_state
            value = source.get(field)
            if is_valid(value):
                usable[field] = deepcopy(value)
        return self._strip_temporary_generation_fields(usable)

    def _usable_bundle_state(
        self,
        updated_story: Any,
        current_state: dict[str, Any],
        *,
        target_chapter: int,
    ) -> dict[str, Any]:
        usable = self._validated_runtime_state(updated_story, current_state)
        if usable is None:
            return current_state
        try:
            bundle_chapter = int(usable.get("current_chapter") or 0)
            current_chapter = int(current_state.get("current_chapter") or 0)
        except (TypeError, ValueError):
            return current_state
        if bundle_chapter != target_chapter or bundle_chapter not in {
            current_chapter,
            current_chapter + 1,
        }:
            return current_state
        for field in ("timeline", "chapter_summaries", "memory_index"):
            current_records = current_state.get(field)
            usable_records = usable.get(field)
            if not isinstance(current_records, list):
                continue
            usable[field] = self._dedupe_numbered_records(
                [*current_records, *(usable_records if isinstance(usable_records, list) else [])]
            )
        return usable
