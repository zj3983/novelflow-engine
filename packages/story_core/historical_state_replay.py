from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from packages.story_core.attribute_allocation import (
    normalize_attribute_allocation_rule,
    rebuild_attribute_progression,
)
from packages.story_core.foreshadowing import (
    canonicalize_foreshadowing_ledger,
    normalize_foreshadowing_text,
    reconcile_foreshadowing,
)
from packages.story_core.models import ForeshadowingState, StoryState


class HistoricalStateReplayMixin:
    @staticmethod
    def _protagonist_ledger(state: dict[str, Any], *, chapter_number: int) -> dict[str, Any]:
        ledger = state.get("progression_ledger")
        protagonist = ledger.get("protagonist") if isinstance(ledger, dict) else None
        if not isinstance(protagonist, dict):
            raise ValueError(f"attribute_rebase_missing_protagonist:{chapter_number}")
        return protagonist

    @staticmethod
    def _replace_attribute_slice(state: dict[str, Any], attribute_slice: dict[str, Any]) -> None:
        fields = (
            "attributes",
            "unallocated_attribute_points",
            "attribute_point_awards",
            "attribute_allocations",
        )
        ledger = dict(state.get("progression_ledger") or {})
        protagonist = dict(ledger.get("protagonist") or {})
        for field in fields:
            protagonist[field] = deepcopy(attribute_slice[field])
        ledger["protagonist"] = protagonist
        state["progression_ledger"] = ledger

        for raw_character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(raw_character, dict):
                continue
            role = str(raw_character.get("role") or "").strip().casefold()
            tier = str(raw_character.get("character_tier") or "").strip().casefold()
            if role not in {"protagonist", "主角"} and tier != "protagonist":
                continue
            game_state = dict(raw_character.get("game_state") or {})
            current = dict(game_state.get("current") or {})
            panel = dict(raw_character.get("game_panel") or {})
            for field in fields:
                current[field] = deepcopy(attribute_slice[field])
                panel[field] = deepcopy(attribute_slice[field])
            game_state["current"] = current
            game_state.setdefault("recent_changes", [])
            raw_character["game_state"] = game_state
            raw_character["game_panel"] = panel

    @staticmethod
    def _parse_foreshadowing_ledger(raw_ledger: Any) -> list[ForeshadowingState]:
        if not isinstance(raw_ledger, (list, tuple)):
            return []
        parsed: list[ForeshadowingState] = []
        for item in raw_ledger:
            try:
                parsed.append(ForeshadowingState.model_validate(item))
            except ValidationError:
                continue
        return parsed

    @staticmethod
    def _foreshadowing_chapter_number(value: Any) -> int | None:
        if isinstance(value, bool):
            return None
        try:
            chapter_number = int(value)
        except (TypeError, ValueError):
            return None
        return chapter_number if chapter_number > 0 else None

    def _project_foreshadowing_history(
        self,
        existing_ledger: Any,
        chapters: list[dict[str, Any]],
        *,
        evidence_complete: bool,
        manual_ledger: Any = None,
    ) -> tuple[
        list[dict[str, Any]],
        dict[int, list[dict[str, Any]]],
        list[dict[str, Any]],
    ]:
        existing = self._parse_foreshadowing_ledger(existing_ledger)
        manual = self._parse_foreshadowing_ledger(manual_ledger)
        if not manual and manual_ledger is None:
            manual = [entry for entry in existing if entry.payoff_plan.strip()]
        manual_keys = {
            normalize_foreshadowing_text(entry.text) for entry in manual
        }
        if evidence_complete:
            pending_terminal = [
                entry
                for entry in canonicalize_foreshadowing_ledger([*existing, *manual])
                if entry.status == "resolved" and entry.resolved_chapter is not None
            ]
            ledger = canonicalize_foreshadowing_ledger(
                [
                    *[
                        entry
                        for entry in manual
                        if entry.status != "resolved" or entry.resolved_chapter is None
                    ],
                    *[
                        entry
                        for entry in existing
                        if (
                            entry.status == "expired"
                            or (entry.status == "resolved" and entry.resolved_chapter is None)
                        )
                        and normalize_foreshadowing_text(entry.text) not in manual_keys
                    ],
                ]
            )
        else:
            pending_terminal = []
            ledger = canonicalize_foreshadowing_ledger([*existing, *manual])

        by_chapter: dict[int, list[dict[str, Any]]] = {}
        for chapter in sorted(
            chapters,
            key=lambda item: self._foreshadowing_chapter_number(
                item.get("chapter_number")
            ) or 0,
        ):
            chapter_number = self._foreshadowing_chapter_number(
                chapter.get("chapter_number")
            )
            if chapter_number is None:
                continue
            summary = self._chapter_summary_payload(chapter)
            due_terminal = [
                entry
                for entry in pending_terminal
                if int(entry.resolved_chapter or 0) <= chapter_number
            ]
            if due_terminal:
                pending_terminal = [
                    entry for entry in pending_terminal if entry not in due_terminal
                ]
            ledger = reconcile_foreshadowing(
                [*ledger, *due_terminal],
                chapter_number=chapter_number,
                unresolved_threads=summary["unresolved_threads"],
                resolved_threads=summary["resolved_threads"],
            )
            by_chapter[chapter_number] = [entry.model_dump() for entry in ledger]

        if pending_terminal:
            ledger = reconcile_foreshadowing(
                [*ledger, *pending_terminal],
                chapter_number=max(by_chapter, default=0),
                unresolved_threads=[],
            )
        final = [entry.model_dump() for entry in ledger]
        manual_final = [
            entry.model_dump()
            for entry in ledger
            if normalize_foreshadowing_text(entry.text) in manual_keys
        ]
        return final, by_chapter, manual_final

    def _historical_foreshadowing_for_rewrite(
        self,
        replacement_chapter: dict[str, Any],
    ) -> dict[str, Any] | None:
        raw_global = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        if not isinstance(raw_global, dict):
            return None
        target_chapter = self._foreshadowing_chapter_number(
            replacement_chapter.get("chapter_number")
        )
        current_chapter = self._foreshadowing_chapter_number(
            raw_global.get("current_chapter")
        )
        if (
            target_chapter is None
            or current_chapter is None
            or target_chapter >= current_chapter
        ):
            return None

        chapters_by_number = {target_chapter: replacement_chapter}
        available_numbers = {
            number for number in self.chapter_numbers() if number <= current_chapter
        }
        for chapter_number in sorted(available_numbers):
            if chapter_number > current_chapter or chapter_number == target_chapter:
                continue
            try:
                saved_chapter = self._read_json(
                    self.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
                    {},
                )
            except (OSError, ValueError):
                continue
            saved_chapter_number = (
                self._foreshadowing_chapter_number(saved_chapter.get("chapter_number"))
                if isinstance(saved_chapter, dict)
                else None
            )
            if saved_chapter_number == chapter_number:
                chapters_by_number[chapter_number] = saved_chapter

        expected_numbers = set(range(1, current_chapter + 1))
        summaries_complete = all(
            isinstance(chapter.get("chapter_summary"), dict)
            and isinstance(chapter["chapter_summary"].get("unresolved_threads"), list)
            for chapter in chapters_by_number.values()
        )
        evidence_complete = (
            expected_numbers == set(chapters_by_number)
            and summaries_complete
        )
        final_ledger, by_chapter, manual_ledger = self._project_foreshadowing_history(
            raw_global.get("foreshadowing"),
            list(chapters_by_number.values()),
            evidence_complete=evidence_complete,
            manual_ledger=raw_global.get("manual_foreshadowing"),
        )
        return {
            "final": final_ledger,
            "manual": manual_ledger,
            "by_chapter": by_chapter,
            "chapters": chapters_by_number,
            "evidence_complete": evidence_complete,
        }

    def _prepare_historical_attribute_rebase(
        self,
        chapter: dict[str, Any],
        updated_story: Any,
    ) -> tuple[dict[str, Any], dict[Path, Any]] | None:
        target_chapter = int(chapter.get("chapter_number") or 0)
        raw_global = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        if not isinstance(raw_global, dict):
            return None
        current_chapter = int(raw_global.get("current_chapter") or 0)
        if target_chapter >= current_chapter:
            return None

        project = self.project()
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        power_system = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), dict) else {}
        rule = normalize_attribute_allocation_rule(power_system.get("attribute_allocation"))
        if not rule:
            return None

        target_state = self._validated_runtime_state(updated_story, raw_global)
        if target_state is None or int(target_state.get("current_chapter") or 0) != target_chapter:
            raise ValueError(f"attribute_rebase_invalid_target_snapshot:{target_chapter}")
        prepared_chapter = self._hydrate_chapter_display_fields(deepcopy(chapter), target_state)
        target_state = self._sync_state_after_chapter(deepcopy(target_state), prepared_chapter)
        target_state = self._sync_ledger_from_chapter_body(target_state, prepared_chapter)
        target_state["current_chapter"] = target_chapter
        target_protagonist = self._protagonist_ledger(target_state, chapter_number=target_chapter)

        future_chapters: list[tuple[int, Path, dict[str, Any]]] = []
        future_protagonists: list[tuple[int, dict[str, Any]]] = []
        for chapter_number in range(target_chapter + 1, current_chapter + 1):
            path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            raw_chapter = self._read_json(path)
            if not isinstance(raw_chapter, dict):
                raise ValueError(f"attribute_rebase_missing_future_chapter:{chapter_number}")
            snapshot = raw_chapter.get("updated_story")
            snapshot_chapter = snapshot.get("current_chapter") if isinstance(snapshot, dict) else None
            if (
                not isinstance(snapshot, dict)
                or isinstance(snapshot_chapter, bool)
                or not isinstance(snapshot_chapter, int)
                or snapshot_chapter != chapter_number
            ):
                raise ValueError(f"attribute_rebase_invalid_future_snapshot:{chapter_number}")
            protagonist = self._protagonist_ledger(snapshot, chapter_number=chapter_number)
            future_chapters.append((chapter_number, path, deepcopy(raw_chapter)))
            future_protagonists.append((chapter_number, protagonist))

        rebuilt = rebuild_attribute_progression(
            rule,
            target_chapter,
            target_protagonist,
            future_protagonists,
        )
        self._replace_attribute_slice(target_state, rebuilt[target_chapter])
        prepared_chapter["updated_story"] = target_state
        prepared_chapter["chapter_summary"] = self._chapter_summary_payload(prepared_chapter)

        payloads: dict[Path, Any] = {}
        for chapter_number, path, future_chapter in future_chapters:
            snapshot = deepcopy(future_chapter["updated_story"])
            self._replace_attribute_slice(snapshot, rebuilt[chapter_number])
            StoryState.model_validate(snapshot)
            future_chapter["updated_story"] = snapshot
            payloads[path] = future_chapter

        rebuilt_global = deepcopy(raw_global)
        self._replace_attribute_slice(rebuilt_global, rebuilt[current_chapter])
        StoryState.model_validate(target_state)
        StoryState.model_validate(rebuilt_global)
        payloads[self.webnovel_dir / "state.json"] = rebuilt_global
        return prepared_chapter, payloads

    def _chapter_summary_payload(self, chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        summary = dict(chapter.get("chapter_summary") or {})
        title = str(chapter.get("chapter_title") or summary.get("chapter_title") or f"Chapter {chapter_number}")
        summary_text = self._compact_text(summary.get("summary"), 320)
        if self._is_placeholder_text(summary_text):
            chapter_intent = chapter.get("chapter_intent") or {}
            summary_text = self._first_mapping_text(
                chapter_intent.get("primary_conflict")
                if isinstance(chapter_intent, dict)
                else {},
                ("summary", "collision", "goal", "conflict"),
            )
        if self._is_placeholder_text(summary_text):
            summary_text = self._compact_text(
                (chapter.get("event_plan") or {}).get("summary"),
                320,
            )
        if self._is_placeholder_text(summary_text):
            summary_text = self._compact_text(chapter.get("body"), 320)
        raw_facts = summary.get("facts") if isinstance(summary.get("facts"), list) else []
        facts = [
            self._compact_text(item, 220)
            for item in raw_facts
            if str(item).strip() and not self._is_placeholder_text(item)
        ]
        if summary_text and not facts:
            facts = [summary_text]
        event_beat = self._coerce_summary_mapping(
            summary.get("event_beat") or chapter.get("event_beat"),
            label="event_beat",
        )
        next_focus = ""
        for candidate in (
            summary.get("next_focus"),
            chapter.get("next_outline"),
            (chapter.get("event_plan") or {}).get("next_focus"),
            self._first_mapping_text(
                event_beat,
                ("turn", "pivot", "hook", "result", "change", "next"),
            ),
            (chapter.get("chapter_intent") or {}).get("next_focus"),
        ):
            compact = self._compact_text(candidate, 220)
            if compact and not self._is_placeholder_text(compact):
                next_focus = compact
                break
        cadence = str(
            summary.get("cadence") or chapter.get("cadence") or "measured"
        ).strip()
        if cadence not in {"urgent", "measured", "breathing"}:
            cadence = "measured"
        return {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "cadence": cadence,
            "summary": summary_text or f"Chapter {chapter_number}.",
            "facts": facts[:8],
            "unresolved_threads": [
                self._compact_text(item, 220)
                for item in (summary.get("unresolved_threads") if isinstance(summary.get("unresolved_threads"), list) else [])
                if str(item).strip()
            ][:8],
            "resolved_threads": [
                self._compact_text(item, 220)
                for item in (summary.get("resolved_threads") if isinstance(summary.get("resolved_threads"), list) else [])
                if str(item).strip()
            ][:8],
            "next_focus": next_focus,
            "primary_conflict": self._coerce_summary_mapping(
                summary.get("primary_conflict") or chapter.get("conflict_summary", {}).get("primary_conflict"),
                label="primary_conflict",
            ),
            "secondary_conflict": self._coerce_summary_mapping(
                summary.get("secondary_conflict") or chapter.get("conflict_summary", {}).get("secondary_conflict"),
                label="secondary_conflict",
            ),
            "event_beat": event_beat,
        }
