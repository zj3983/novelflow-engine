from __future__ import annotations

import inspect
import json
import logging
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from packages.story_core.character_profiles import (
    is_non_character_card,
    merge_character_profile,
    normalize_character_profile,
)
from packages.story_core.elastic_outline import outline_window_status, validate_outline_for_project
from packages.story_core.novel_type_catalog import (
    normalize_novel_type_ids,
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.outline_generation_checkpoints import OutlineCheckpointStore
from packages.story_core.outline_planning import (
    GeneratedOutlinePlan,
    INITIAL_OUTLINE_CHAPTER_COUNT,
    _volume_validation_input,
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
    validate_generated_trope_selection,
)
from packages.story_core.outline_planning_generation import OutlinePlanningBrief
from packages.story_core.persistence.project_locking import with_project_update_lock
from packages.story_core.project_outline import (
    normalize_outline_for_story_type,
    normalize_project_outline,
    outline_from_legacy_project,
)
from packages.story_core.relationship_graph import (
    graph_from_character_cards,
    merge_relationship_graph,
)
from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
)
from packages.story_core.story_core_card import (
    StoryCoreCard,
    merge_story_core_into_overall,
)
from packages.story_core.volume_outline import validate_volume_structure


class OutlinePlanStoreMixin:
    """Project outline persistence, planning context, and generated plan merging."""

    @with_project_update_lock
    def project_outline(self) -> dict[str, Any]:
        # 先尝试 Markdown 大纲双向同步（last-writer-wins）；同步失败静默降级，
        # 绝不能因为 md 解析/导出问题搞挂读接口。
        try:
            from packages.story_core.outline_markdown_sync import sync_outline_if_stale

            sync_outline_if_stale(self.root)
        except Exception:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "outline markdown sync failed", exc_info=True
            )
        path = self.webnovel_dir / "outline.json"
        if path.exists():
            project = self.project()
            state = self._read_json(self.webnovel_dir / "state.json", {})
            normalized = normalize_outline_for_story_type(
                self._read_json(path, {}),
                is_game_story=self._is_game_story_payload(project, state),
            )
            legacy_path = self.webnovel_dir / "story_core.json"
            if legacy_path.exists():
                try:
                    legacy = StoryCoreCard.model_validate(self._read_json(legacy_path, {}))
                    normalized["overall"] = merge_story_core_into_overall(
                        normalized.get("overall"), legacy, overwrite=False
                    )
                    saved = self.update_project_outline(normalized)
                    normalized = {key: value for key, value in saved.items() if key != "source"}
                    archive_path = self.webnovel_dir / "story_core.legacy.json"
                    suffix = 2
                    while archive_path.exists():
                        archive_path = self.webnovel_dir / f"story_core.legacy-{suffix}.json"
                        suffix += 1
                    legacy_path.rename(archive_path)
                except Exception:  # noqa: BLE001
                    logging.getLogger(__name__).warning(
                        "legacy story core migration failed", exc_info=True
                    )
            return {**normalized, "source": "saved"}
        return {**outline_from_legacy_project(self.project()), "source": "legacy"}

    @with_project_update_lock
    def update_project_outline(self, payload: dict[str, Any]) -> dict[str, Any]:
        outline_payload = dict(payload)
        outline_payload.pop("source", None)
        state = self._read_json(self.webnovel_dir / "state.json", {})
        outline_payload = normalize_outline_for_story_type(
            outline_payload,
            is_game_story=self._is_game_story_payload(self.project(), state),
        )
        current_chapter = int(state.get("current_chapter") or 0)
        normalized = validate_outline_for_project(
            outline_payload, current_chapter=current_chapter
        )
        self._write_json_atomic(self.webnovel_dir / "outline.json", normalized)
        # 保存后立即把 json 字段级合并渲染回 大纲/*.md；导出失败不影响保存结果，
        # 导出状态只写日志，避免把运行状态混进可再次提交的大纲数据。
        try:
            from packages.story_core.outline_markdown_sync import export_outline_to_markdown

            export_outline_to_markdown(self.root, normalized)
        except Exception as exc:  # noqa: BLE001
            logging.getLogger(__name__).warning(
                "outline markdown export failed: %s", exc, exc_info=True
            )
        return {**normalized, "source": "saved"}

    def _planning_opening_direction(
        self,
        project: dict[str, Any],
        outline: dict[str, Any],
    ) -> dict[str, Any]:
        # Priority 1: canonical story_core from `overall` (only when the user has
        # actually populated it via `select_opening_direction` or
        # `update_story_core`). We detect that by checking fields that those
        # code paths exclusively write (positioning.*, core_selling_point, etc.).
        # `overall.story` alone is NOT a reliable signal because
        # `outline_from_legacy_project` also fills it from `seed_outline`.
        overall = outline.get("overall") if isinstance(outline.get("overall"), dict) else {}
        positioning = (
            overall.get("positioning")
            if isinstance(overall.get("positioning"), dict)
            else {}
        )
        story_core_populated = bool(
            positioning.get("reader_promise")
            or positioning.get("target_audience")
            or positioning.get("protagonist_profile")
            or positioning.get("inciting_incident")
            or positioning.get("failure_stakes")
            or positioning.get("excitement_point")
            or overall.get("core_selling_point")
            or overall.get("ending_contract")
            or overall.get("ending_image")
        )
        if story_core_populated:
            story = str(overall.get("story") or "").strip()
            primary_trope_id = overall.get("primary_trope_id")
            if isinstance(primary_trope_id, str):
                primary_trope_id = primary_trope_id.strip() or None
            else:
                primary_trope_id = None
            return {
                "title": str(project.get("title") or ""),
                "hook": story,
                "opening_promise": str(
                    positioning.get("reader_promise")
                    or overall.get("ending_direction")
                    or "开篇建立的核心冲突会得到阶段性兑现。"
                ),
                "primary_trope_id": primary_trope_id,
            }
        # Priority 2: user-selected opening direction from opening_directions.json
        # (the only signal available when no story_core has been written).
        directions = self.opening_directions()
        selected_id = str((directions or {}).get("selected_id") or "")
        selected = next(
            (
                dict(item)
                for item in (directions or {}).get("directions", [])
                if isinstance(item, dict) and str(item.get("id") or "") == selected_id
            ),
            None,
        )
        if selected:
            return {
                "title": str(selected.get("title") or ""),
                "hook": str(selected.get("hook") or ""),
                "opening_promise": str(selected.get("opening_promise") or ""),
                "primary_trope_id": selected.get("primary_trope_id"),
            }
        # Priority 3: project-level fallback (seed / world_summary / title).
        seed = str(project.get("seed_outline") or project.get("world_summary") or overall.get("story") or project.get("title") or "")
        primary_trope_id = overall.get("primary_trope_id")
        if isinstance(primary_trope_id, str):
            primary_trope_id = primary_trope_id.strip() or None
        else:
            primary_trope_id = None
        return {
            "title": str(project.get("title") or ""),
            "hook": str(overall.get("story") or seed),
            "opening_promise": str(overall.get("ending_direction") or "开篇建立的核心冲突会得到阶段性兑现。"),
            "primary_trope_id": primary_trope_id,
        }

    def _current_project_trope_candidates(
        self,
        project: dict[str, Any],
        state: dict[str, Any],
    ) -> list[dict[str, Any]]:
        blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        genre_ids = normalize_novel_type_ids(blueprint.get("genre_plugin_ids"))
        if not genre_ids:
            genre_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
        if not genre_ids:
            genre_ids = ["generic_webnovel"]
        genre = runtime_novel_type(genre_ids[0])
        if genre is None:
            raise ValueError("invalid_novel_type")
        prompt_context = novel_type_prompt_context(genre)
        return [
            dict(item)
            for item in prompt_context.get("genre_trope_templates", [])
            if isinstance(item, dict)
        ]

    @staticmethod
    def _outline_primary_trope_id(outline: dict[str, Any]) -> str | None:
        overall = outline.get("overall") if isinstance(outline.get("overall"), dict) else {}
        primary_trope_id = overall.get("primary_trope_id")
        if isinstance(primary_trope_id, str):
            return primary_trope_id.strip() or None
        return None

    @staticmethod
    def _validate_generated_locked_tropes_match(
        current: dict[str, Any],
        generated: dict[str, Any],
        *,
        current_chapter: int,
        locked_through_chapter: int | None = None,
    ) -> None:
        current_arcs = {
            str(arc.get("id")): arc
            for arc in current.get("arcs", [])
            if isinstance(arc, dict) and str(arc.get("id") or "").strip()
        }
        locked_current_arcs = [
            arc
            for arc in current_arcs.values()
            if arc.get("trope_id") is not None
            and (
                locked_through_chapter is None
                or int(arc.get("end_chapter") or 0) <= locked_through_chapter
            )
        ]
        for arc in generated.get("arcs", []):
            if not isinstance(arc, dict):
                continue
            arc_id = str(arc.get("id") or "")
            current_arc = current_arcs.get(arc_id)
            if not current_arc:
                for locked_arc in locked_current_arcs:
                    exact_range = (
                        int(arc["start_chapter"]) == int(locked_arc["start_chapter"])
                        and int(arc["end_chapter"]) == int(locked_arc["end_chapter"])
                    )
                    committed_overlap = max(
                        int(arc["start_chapter"]),
                        int(locked_arc["start_chapter"]),
                    ) <= min(
                        int(arc["end_chapter"]),
                        int(locked_arc["end_chapter"]),
                        current_chapter,
                    )
                    if exact_range or committed_overlap:
                        raise ValueError(f"locked_arc_overlap:{arc_id}")
                continue
            current_trope_id = current_arc.get("trope_id")
            generated_trope_id = arc.get("trope_id")
            current_arc_locked = (
                locked_through_chapter is None
                or int(current_arc.get("end_chapter") or 0) <= locked_through_chapter
            )
            if current_arc_locked and current_trope_id is not None and generated_trope_id != current_trope_id:
                raise ValueError(f"locked_arc_trope_drift:{arc_id}")

    def _planning_brief(self) -> OutlinePlanningBrief:
        project = self.project()
        outline = dict(self.project_outline())
        outline.pop("source", None)
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        plugin_ids = blueprint.get("genre_plugin_ids") if isinstance(blueprint.get("genre_plugin_ids"), list) else []
        novel_type_id = str(plugin_ids[0] if plugin_ids else "generic_webnovel")
        existing_cards: list[dict[str, Any]] = []
        existing_character_names: list[str] = []
        seen_character_names: set[str] = set()
        for item in [
            *(project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []),
            *(state.get("characters") if isinstance(state.get("characters"), list) else []),
        ]:
            if not isinstance(item, dict) or is_non_character_card(item):
                continue
            name = str(item.get("name") or "").strip()
            if not name or name in seen_character_names:
                continue
            seen_character_names.add(name)
            existing_character_names.append(name)
            if len(existing_cards) >= 6:
                continue
            card = normalize_character_profile(item)
            existing_cards.append(
                {
                    key: card.get(key)
                    for key in (
                        "name",
                        "role",
                        "character_tier",
                        "importance",
                        "narrative_function",
                        "profile_status",
                        "profile_completeness",
                        "first_appearance",
                        "identity_profile",
                        "background_profile",
                        "current_life_profile",
                        "story_drive",
                        "performance_profile",
                        "dialogue_examples",
                        "relationship_notes",
                    )
                }
            )
        summaries = state.get("chapter_summaries") if isinstance(state.get("chapter_summaries"), list) else []
        continuation = project.get("continuation") if isinstance(project.get("continuation"), dict) else {}
        raw_continuation_start = continuation.get("start_after_chapter")
        continuation_start = (
            int(raw_continuation_start)
            if isinstance(raw_continuation_start, int)
            and not isinstance(raw_continuation_start, bool)
            and raw_continuation_start >= 1
            else None
        )
        historical_summaries: list[dict[str, Any]] = []
        if continuation_start is not None:
            for path in sorted((self.story_system_dir / "chapters").glob("*.json")):
                payload = self._read_json(path, {})
                if not isinstance(payload, dict):
                    continue
                number = payload.get("chapter_number")
                if (
                    not isinstance(number, int)
                    or isinstance(number, bool)
                    or number < 1
                    or number > continuation_start
                ):
                    continue
                chapter_summary = payload.get("chapter_summary")
                summary = (
                    str(chapter_summary.get("summary") or "").strip()
                    if isinstance(chapter_summary, dict)
                    else ""
                )
                historical_summaries.append(
                    {
                        "chapter_number": number,
                        "title": str(payload.get("chapter_title") or "").strip(),
                        "summary": summary[:500],
                    }
                )
        return OutlinePlanningBrief(
            novel_type_id=novel_type_id,
            title=str(project.get("title") or ""),
            overall_context=dict(outline.get("overall") or {}),
            opening_direction=self._planning_opening_direction(project, outline),
            author_constraints=[str(item) for item in project.get("author_constraints", []) if str(item).strip()],
            existing_outline=outline,
            existing_characters=existing_cards,
            existing_character_names=existing_character_names,
            current_chapter=int(state.get("current_chapter") or 0),
            recent_chapter_summaries=[dict(item) for item in summaries[-3:] if isinstance(item, dict)],
            continuation_start_chapter=continuation_start,
            historical_chapter_summaries=historical_summaries,
            power_system_spec=(
                dict(blueprint.get("power_system_spec"))
                if isinstance(blueprint.get("power_system_spec"), dict)
                else {}
            ),
            world_facts=deepcopy(
                state.get("world_facts") if isinstance(state.get("world_facts"), list) else []
            ),
            continuity_facts=deepcopy(
                state.get("continuity_facts")
                if isinstance(state.get("continuity_facts"), list)
                else []
            ),
            committed_facts=deepcopy(
                state.get("committed_facts")
                if isinstance(state.get("committed_facts"), list)
                else (
                    blueprint.get("continuity_state", {}).get("chapter_facts", [])
                    if isinstance(blueprint.get("continuity_state"), dict)
                    else []
                )
            ),
            unresolved_foreshadowing=deepcopy(
                [
                    item
                    for item in (
                        state.get("foreshadowing")
                        if isinstance(state.get("foreshadowing"), list)
                        else []
                    )
                    if isinstance(item, dict)
                    and str(item.get("status") or "open")
                    in {"open", "reinforced"}
                ]
            ),
            character_current_states=deepcopy(
                [
                    {
                        key: item.get(key)
                        for key in (
                            "name",
                            "role",
                            "current_life_profile",
                            "story_drive",
                            "real_state",
                            "game_state",
                            "status",
                        )
                        if item.get(key) not in (None, "", [], {})
                    }
                    for item in (
                        state.get("characters")
                        if isinstance(state.get("characters"), list)
                        else []
                    )
                    if isinstance(item, dict) and str(item.get("name") or "").strip()
                ]
            ),
            enabled_skill_ids=resolve_enabled_skill_ids(project, state),
            enabled_skill_module_ids=resolve_enabled_skill_module_ids(project, state),
        )

    def _merge_generated_character_cards(
        self,
        generated: list[dict[str, Any]],
        *,
        preserve_unmentioned: bool = True,
    ) -> list[dict[str, Any]]:
        project = self.project()
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        existing: dict[str, dict[str, Any]] = {}
        existing_order: list[str] = []
        for item in [
            *(project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []),
            *(state.get("characters") if isinstance(state.get("characters"), list) else []),
        ]:
            if not isinstance(item, dict) or is_non_character_card(item):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if name not in existing:
                existing[name] = dict(item)
                existing_order.append(name)
            else:
                existing[name] = merge_character_profile(existing[name], item)

        generated_names: list[str] = []
        for card in generated:
            if is_non_character_card(card):
                continue
            name = str(card.get("name") or "").strip()
            if not name:
                continue
            generated_names.append(name)
            current = existing.get(name, {"name": name})
            merged = merge_character_profile(current, card)
            generated_role = str(card.get("role") or "").strip().casefold()
            generated_tier = str(card.get("character_tier") or "").strip().casefold()
            current_role = str(current.get("role") or "").strip().casefold()
            current_tier = str(current.get("character_tier") or "").strip().casefold()
            if generated_role == "protagonist" and current_role in {"", "supporting"}:
                merged["role"] = card["role"]
            if generated_tier == "protagonist" and current_tier in {"", "supporting"}:
                merged["character_tier"] = card["character_tier"]
            if not preserve_unmentioned:
                for field_name in (
                    "current_state",
                    "current_location",
                    "recent_changes",
                ):
                    if field_name in card:
                        merged[field_name] = deepcopy(card[field_name])
                    else:
                        merged.pop(field_name, None)
            existing[name] = merged
        order = list(generated_names)
        if preserve_unmentioned:
            order.extend(name for name in existing_order if name not in generated_names)
        cards = [
            normalize_character_profile(existing[name])
            for name in order
            if not is_non_character_card(existing[name])
        ]
        for card in cards:
            if not isinstance(card.get("relationships"), dict):
                card["relationships"] = {}
        return cards

    def _persist_volume_character_cards(
        self,
        generated: list[Any],
        *,
        roster_path: Path,
        volume_id: str,
        volume_fingerprint: str,
    ) -> list[dict[str, Any]]:
        serialized = [
            item.model_dump(mode="json") if hasattr(item, "model_dump") else dict(item)
            for item in generated
            if hasattr(item, "model_dump") or isinstance(item, dict)
        ]
        cards = self._merge_generated_character_cards(serialized)
        project = self.project()
        state = self.state()
        project["character_profiles"] = deepcopy(cards)
        project["relationship_graph"] = merge_relationship_graph(
            project.get("relationship_graph"),
            graph_from_character_cards(cards),
        )
        state["characters"] = deepcopy(cards)
        roster_payload = {
            "schema_version": "volume-character-roster/v1",
            "volume_id": volume_id,
            "volume_fingerprint": volume_fingerprint,
            "characters": serialized,
        }
        self._replace_json_transaction(
            {
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "state.json": state,
                roster_path: roster_payload,
            }
        )
        return cards

    @staticmethod
    def _validate_volume_detail_cast(
        chapters: list[Any],
        *,
        known_character_names: set[str],
        first_appearance_by_name: dict[str, int] | None = None,
    ) -> None:
        first_appearance_by_name = first_appearance_by_name or {}
        for chapter in chapters:
            chapter_number = (
                int(chapter.get("chapter_number") or 0)
                if isinstance(chapter, dict)
                else int(getattr(chapter, "chapter_number", 0) or 0)
            )
            cast = (
                getattr(chapter, "cast", None)
                if not isinstance(chapter, dict)
                else chapter.get("cast")
            )
            for raw_name in cast or []:
                name = (
                    str(raw_name.get("name") or "").strip()
                    if isinstance(raw_name, dict)
                    else str(raw_name or "").strip()
                )
                if name and name not in known_character_names:
                    raise ValueError(f"missing_character_card:{name}")
                planned_first = int(first_appearance_by_name.get(name) or 0)
                if planned_first > 0 and chapter_number < planned_first:
                    raise ValueError(
                        f"character_appears_before_card:{name}:"
                        f"{chapter_number}:{planned_first}"
                    )

    def _extend_outline(
        self,
        current: dict[str, Any],
        addition: dict[str, Any],
        *,
        current_chapter: int,
    ) -> dict[str, Any]:
        current = normalize_project_outline(current)
        addition = normalize_project_outline(addition)
        added_numbers = [int(item["chapter_number"]) for item in addition["chapters"]]
        window_status = outline_window_status(
            current,
            current_chapter=current_chapter,
        )
        detail_batches = window_status.get("detail_batches") or []
        expected = list(detail_batches[0]) if detail_batches else []
        if not expected:
            legacy_expected = list(
                range(
                    current_chapter + 1,
                    current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT + 1,
                )
            )
            if added_numbers == legacy_expected:
                expected = legacy_expected
            elif added_numbers:
                raise ValueError("outline_window_already_full")
        legacy_prefix = expected[:INITIAL_OUTLINE_CHAPTER_COUNT]
        if added_numbers not in (expected, legacy_prefix):
            raise ValueError("generated_chapters_do_not_match_target_window")
        arcs = {str(item["id"]): dict(item) for item in current["arcs"]}
        for arc in addition["arcs"]:
            arc_id = str(arc["id"])
            existing_arc = arcs.get(arc_id)
            if existing_arc is None:
                arcs[arc_id] = dict(arc)
                continue
            merged_arc = merge_character_profile(existing_arc, arc)
            merged_arc["end_chapter"] = max(int(existing_arc["end_chapter"]), int(arc["end_chapter"]))
            if existing_arc.get("trope_id") is not None:
                merged_arc["trope_id"] = existing_arc["trope_id"]
            merged_arc["long_term_antagonist_traces"] = list(
                dict.fromkeys(
                    [
                        *existing_arc.get("long_term_antagonist_traces", []),
                        *arc.get("long_term_antagonist_traces", []),
                    ]
                )
            )
            arcs[arc_id] = merged_arc
        return normalize_project_outline(
            {
                "overall": merge_character_profile(current["overall"], addition["overall"]),
                "arcs": list(arcs.values()),
                "chapters": [*current["chapters"], *addition["chapters"]],
            }
        )

    @staticmethod
    def _split_outline_arcs_at_boundary(
        outline: dict[str, Any],
        boundary: int,
    ) -> dict[str, Any]:
        normalized = normalize_project_outline(outline)
        source_arcs = [dict(arc) for arc in normalized["arcs"]]
        historical_ends = [
            int(arc["end_chapter"])
            for arc in source_arcs
            if int(arc["end_chapter"]) <= boundary
        ]
        latest_historical_end = max(historical_ends, default=0)
        boundary_is_historical = any(
            int(arc["start_chapter"]) <= boundary <= int(arc["end_chapter"])
            and int(arc["end_chapter"]) <= boundary
            for arc in source_arcs
        )
        arcs: list[dict[str, Any]] = []
        for arc in source_arcs:
            start = int(arc["start_chapter"])
            end = int(arc["end_chapter"])
            if not (start <= boundary < end):
                arcs.append(arc)
                continue
            if not boundary_is_historical:
                history_start = max(start, latest_historical_end + 1)
                if history_start <= boundary:
                    history_arc = {
                        **arc,
                        "id": f"{arc['id']}-history",
                        "title": f"{arc['title']}（已发生）",
                        "start_chapter": history_start,
                        "end_chapter": boundary,
                    }
                    arcs.append(history_arc)
                    latest_historical_end = boundary
                    boundary_is_historical = True
            arcs.append({**arc, "start_chapter": boundary + 1})
        return normalize_project_outline(
            {
                **normalized,
                "arcs": sorted(
                    arcs,
                    key=lambda item: (
                        int(item["start_chapter"]),
                        int(item["end_chapter"]),
                    ),
                ),
            }
        )

    def _preserve_committed_outline(
        self,
        current: dict[str, Any],
        generated: dict[str, Any],
        *,
        current_chapter: int,
        immutable_arc_through: int | None = None,
    ) -> dict[str, Any]:
        current = normalize_project_outline(current)
        generated = normalize_project_outline(generated)
        overall = dict(generated["overall"])
        current_primary_trope_id = self._outline_primary_trope_id(current)
        if current_primary_trope_id is not None:
            overall["primary_trope_id"] = current_primary_trope_id
        current_arcs = {str(item["id"]): dict(item) for item in current["arcs"]}
        arcs = {str(item["id"]): dict(item) for item in generated["arcs"]}
        for arc_id, current_arc in current_arcs.items():
            arc_start = int(current_arc["start_chapter"])
            arc_end = int(current_arc["end_chapter"])
            if immutable_arc_through is not None and arc_end <= immutable_arc_through:
                arcs[arc_id] = current_arc
                continue
            if arc_id not in arcs:
                crosses_immutable_boundary = (
                    immutable_arc_through is not None
                    and arc_start <= immutable_arc_through < arc_end
                )
                if arc_start <= current_chapter and not crosses_immutable_boundary:
                    arcs[arc_id] = current_arc
                continue
            if current_arc.get("trope_id") is not None:
                arcs[arc_id]["trope_id"] = current_arc["trope_id"]
        committed = {
            item["chapter_number"]: item
            for item in current["chapters"]
            if item["chapter_number"] <= current_chapter
        }
        future = {
            item["chapter_number"]: item
            for item in generated["chapters"]
            if item["chapter_number"] > current_chapter
        }
        merged = normalize_project_outline(
            {
                "overall": overall,
                "arcs": list(arcs.values()),
                "chapters": [*committed.values(), *future.values()],
            }
        )
        if immutable_arc_through is not None:
            return self._split_outline_arcs_at_boundary(
                merged,
                immutable_arc_through,
            )
        return merged

    @with_project_update_lock
    def save_generated_outline_plan(
        self,
        plan: Any,
        *,
        mode: str,
        persist_chapter_window: bool = True,
    ) -> dict[str, Any]:
        validated = GeneratedOutlinePlan.model_validate(plan)
        if mode not in {"initial", "regenerate", "extend"}:
            raise ValueError("invalid_outline_planning_mode")

        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        project = dict(self.project())
        continuation = project.get("continuation") if isinstance(project.get("continuation"), dict) else {}
        raw_continuation_start = continuation.get("start_after_chapter")
        continuation_start = (
            int(raw_continuation_start)
            if isinstance(raw_continuation_start, int)
            and not isinstance(raw_continuation_start, bool)
            and raw_continuation_start >= 1
            else None
        )
        current_chapter = int(state.get("current_chapter") or 0)
        current_outline = dict(self.project_outline())
        current_outline.pop("source", None)
        validation_fallback_outline = current_outline
        if mode == "regenerate":
            validation_fallback_outline = deepcopy(current_outline)
            validation_fallback_outline["arcs"] = [
                arc
                for arc in validation_fallback_outline.get("arcs", [])
                if int(arc["start_chapter"]) <= current_chapter
            ]
            validation_fallback_outline["chapters"] = [
                chapter
                for chapter in validation_fallback_outline.get("chapters", [])
                if int(chapter["chapter_number"]) <= current_chapter
            ]
        trope_candidates = self._current_project_trope_candidates(project, state)
        expected_primary_trope_id = self._outline_primary_trope_id(current_outline)
        if (
            mode in {"extend", "regenerate"}
            and current_chapter > 0
            and expected_primary_trope_id is None
        ):
            # Legacy projects may predate trope locking. Continuing or rebuilding
            # their future outline must not force a newly available genre template
            # into the established book.
            trope_candidates = []
        if mode == "initial":
            if current_chapter != 0:
                raise ValueError("initial_outline_requires_unstarted_project")
            expected_chapter_numbers = list(range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1))
        elif mode == "regenerate":
            if current_chapter == 0:
                expected_chapter_numbers = list(
                    range(1, INITIAL_OUTLINE_CHAPTER_COUNT + 1)
                )
            else:
                ceiling = (
                    current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT
                    if continuation_start is not None
                    else normalize_project_outline(current_outline)["overall"][
                        "extension_ceiling_chapter"
                    ]
                )
                expected_chapter_numbers = list(
                    range(
                        current_chapter + 1,
                        min(current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT, ceiling) + 1,
                    )
                )
            if not expected_chapter_numbers:
                raise ValueError("outline_window_already_full")
        else:
            window_status = outline_window_status(
                current_outline,
                current_chapter=current_chapter,
            )
            detail_batches = window_status.get("detail_batches") or []
            expected_chapter_numbers = (
                list(detail_batches[0]) if detail_batches else []
            )
            if not expected_chapter_numbers:
                direct_numbers = [
                    chapter.chapter_number for chapter in validated.outline.chapters
                ]
                legacy_expected = list(
                    range(
                        current_chapter + 1,
                        current_chapter + INITIAL_OUTLINE_CHAPTER_COUNT + 1,
                    )
                )
                if direct_numbers == legacy_expected:
                    expected_chapter_numbers = legacy_expected
                elif direct_numbers:
                    raise ValueError("outline_window_already_full")
            direct_numbers = [
                chapter.chapter_number for chapter in validated.outline.chapters
            ]
            legacy_prefix = expected_chapter_numbers[
                :INITIAL_OUTLINE_CHAPTER_COUNT
            ]
            if direct_numbers == legacy_prefix:
                expected_chapter_numbers = legacy_prefix
        if mode in {"initial", "regenerate"}:
            validated = validate_generated_opening_plan(
                validated.model_dump(mode="json"),
                expected_chapter_numbers=expected_chapter_numbers,
                trope_templates=trope_candidates,
                expected_primary_trope_id=expected_primary_trope_id,
                fallback_outline=validation_fallback_outline if mode == "regenerate" else None,
                committed_through_chapter=(
                    current_chapter if mode == "regenerate" else None
                ),
                enforce_full_opening_roster=(
                    mode == "initial" and current_chapter == 0
                ),
                allow_established_roster=(mode == "regenerate"),
                # The generator applies the character quality gate.  Keep
                # migrated legacy models compatible at this persistence edge.
                enforce_character_quality=False,
            )
        else:
            existing_character_names: set[str] = set()
            for item in [
                *(
                    project.get("character_profiles")
                    if isinstance(project.get("character_profiles"), list)
                    else []
                ),
                *(
                    state.get("characters")
                    if isinstance(state.get("characters"), list)
                    else []
                ),
            ]:
                if not isinstance(item, dict):
                    continue
                raw_name = str(item.get("name") or "").strip()
                canonical_name = self._canonical_character_name(raw_name)
                if raw_name:
                    existing_character_names.add(raw_name)
                if canonical_name:
                    existing_character_names.add(canonical_name)
            validated = validate_generated_continuation_plan(
                validated.model_dump(mode="json"),
                expected_chapter_numbers=expected_chapter_numbers,
                existing_character_names=existing_character_names,
                trope_templates=trope_candidates,
                expected_primary_trope_id=expected_primary_trope_id,
                fallback_outline=current_outline,
                committed_through_chapter=current_chapter,
                enforce_character_quality=False,
            )

        generated_outline = validated.outline.model_dump(mode="json")
        if mode in {"extend", "regenerate"}:
            self._validate_generated_locked_tropes_match(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
                locked_through_chapter=(
                    continuation_start if mode == "regenerate" else None
                ),
            )
        if mode == "extend":
            generated_outline = self._extend_outline(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
            )
        elif mode == "regenerate":
            generated_outline = self._preserve_committed_outline(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
                immutable_arc_through=continuation_start,
            )
        volume_arcs, volume_ending = _volume_validation_input(
            generated_outline["arcs"],
            core_ending_chapter=generated_outline["overall"][
                "core_ending_chapter"
            ],
            fallback_outline=(
                current_outline if mode in {"extend", "regenerate"} else None
            ),
            committed_through_chapter=(
                current_chapter if mode in {"extend", "regenerate"} else None
            ),
            require_future_coverage=mode == "regenerate",
        )
        validate_volume_structure(volume_arcs, core_ending_chapter=volume_ending)
        final_validation_payload = validated.model_dump(mode="json")
        final_validation_payload["outline"] = generated_outline
        validate_generated_trope_selection(
            final_validation_payload,
            trope_candidates,
            expected_primary_trope_id=expected_primary_trope_id,
            fallback_outline=(
                validation_fallback_outline
                if mode == "regenerate"
                else current_outline if mode == "extend" else None
            ),
            committed_through_chapter=(
                current_chapter if mode in {"extend", "regenerate"} else None
            ),
        )
        replace_unstarted_roster = (
            current_chapter == 0 and mode in {"initial", "regenerate"}
        )
        cards = self._merge_generated_character_cards(
            [card.model_dump(mode="json") for card in validated.characters],
            preserve_unmentioned=not replace_unstarted_roster,
        )
        project["character_profiles"] = cards
        generated_relationships = graph_from_character_cards(cards)
        project["relationship_graph"] = (
            generated_relationships
            if replace_unstarted_roster
            else merge_relationship_graph(
                project.get("relationship_graph"),
                generated_relationships,
            )
        )
        project["pipeline_stage"] = "world_ready"
        first_arc = generated_outline["arcs"][0] if generated_outline["arcs"] else {}
        project["current_focus"] = str(first_arc.get("goal") or project.get("current_focus") or "")
        state["characters"] = cards
        state["outline"] = str(generated_outline["overall"].get("story") or state.get("outline") or "")
        # Plan rule: the bootstrapper is responsible for the
        # rolling window. With ``persist_chapter_window=False``,
        # the legacy outline keeps only the overall/arcs layer
        # plus the committed historical chapter rows; the
        # planner-stage chapter detail stays in the bootstrap
        # checkpoint so the rolling-only generator can re-emit
        # it without rewriting the three-level outline.
        if not persist_chapter_window:
            committed_numbers = {
                number
                for number, _ in self._read_chapter_records(ignore_errors=True)
            }
            generated_outline["chapters"] = [
                chapter
                for chapter in generated_outline.get("chapters", [])
                if int(chapter.get("chapter_number") or 0) in committed_numbers
            ]
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = self.story_system_dir / "plans" / f"{stamp}-{mode}.json"
        snapshot = {
            "schema_version": "generated-outline-plan/v1",
            "mode": mode,
            "outline": generated_outline,
            "characters": cards,
        }
        self._replace_json_transaction(
            {
                self.webnovel_dir / "outline.json": generated_outline,
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "state.json": state,
                snapshot_path: snapshot,
            }
        )
        return {**snapshot, "source": "generated"}

    @with_project_update_lock
    def _save_generated_outline_foundation(
        self,
        plan: Any,
        *,
        mode: str,
    ) -> dict[str, Any]:
        """Persist only overall/arcs while preserving committed history.

        Continuation bootstrap already owns character cards and the rolling
        chapter window.  Saving the foundation separately prevents an outline
        repair from making two unrelated model calls and from replacing those
        approved layers.
        """

        if mode != "regenerate":
            raise ValueError("outline_foundation_requires_regenerate")
        validated = GeneratedOutlinePlan.model_validate(plan)
        project = dict(self.project())
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        current_chapter = int(state.get("current_chapter") or 0)
        continuation = (
            project.get("continuation")
            if isinstance(project.get("continuation"), dict)
            else {}
        )
        continuation_start = continuation.get("start_after_chapter")
        immutable_arc_through = (
            int(continuation_start)
            if isinstance(continuation_start, int)
            and not isinstance(continuation_start, bool)
            and continuation_start >= 1
            else None
        )
        current_outline = dict(self.project_outline())
        current_outline.pop("source", None)
        generated_outline = validated.outline.model_dump(mode="json")
        generated_outline["chapters"] = []
        generated_outline = self._preserve_committed_outline(
            current_outline,
            generated_outline,
            current_chapter=current_chapter,
            immutable_arc_through=immutable_arc_through,
        )
        volume_arcs, volume_ending = _volume_validation_input(
            generated_outline["arcs"],
            core_ending_chapter=generated_outline["overall"][
                "core_ending_chapter"
            ],
            fallback_outline=current_outline,
            committed_through_chapter=current_chapter,
            require_future_coverage=True,
        )
        validate_volume_structure(volume_arcs, core_ending_chapter=volume_ending)
        cards = [
            dict(card)
            for card in project.get("character_profiles", [])
            if isinstance(card, dict)
        ]
        project["pipeline_stage"] = "world_ready"
        next_arc = next(
            (
                arc
                for arc in generated_outline.get("arcs", [])
                if int(arc.get("start_chapter") or 0)
                <= current_chapter + 1
                <= int(arc.get("end_chapter") or 0)
            ),
            {},
        )
        project["current_focus"] = str(
            next_arc.get("goal") or project.get("current_focus") or ""
        )
        state["outline"] = str(
            generated_outline.get("overall", {}).get("story")
            or state.get("outline")
            or ""
        )
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = self.story_system_dir / "plans" / f"{stamp}-{mode}-foundation.json"
        snapshot = {
            "schema_version": "generated-outline-foundation/v1",
            "mode": mode,
            "outline": generated_outline,
            "characters": cards,
        }
        self._replace_json_transaction(
            {
                self.webnovel_dir / "outline.json": generated_outline,
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "state.json": state,
                snapshot_path: snapshot,
            }
        )
        return {
            **snapshot,
            "outline_foundation": {
                "overall": generated_outline["overall"],
                "arcs": generated_outline["arcs"],
            },
            "character_roster": cards,
            "source": "generated",
        }

    def generate_outline_plan(
        self,
        generator: Any,
        *,
        mode: str,
        guidance: str = "",
        restart_from: str | None = None,
        persist_chapter_window: bool = True,
        foundation_only: bool = False,
    ) -> dict[str, Any]:
        if mode == "extend":
            readiness = self.outline_extension_readiness()
            if not readiness["ready"]:
                codes = ",".join(item["code"] for item in readiness["blockers"])
                raise ValueError(f"outline_extension_not_ready:{codes}")
        brief = self._planning_brief()
        normalized_guidance = guidance.strip()
        generate_parameters = inspect.signature(generator.generate).parameters
        supports_checkpoints = {
            "phase_payloads",
            "phase_callback",
        }.issubset(generate_parameters)
        if supports_checkpoints:
            fingerprint_source = {
                "mode": mode,
                "guidance": normalized_guidance,
                "brief": brief.model_dump(mode="json"),
            }
            fingerprint = sha256(
                json.dumps(
                    fingerprint_source,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode("utf-8")
            ).hexdigest()
            checkpoints = OutlineCheckpointStore(
                self.story_system_dir / "outline-generation"
            )
            if restart_from:
                checkpoints.prepare_restart(fingerprint, restart_from)
            else:
                checkpoints.prepare(fingerprint)

            def record_phase(
                phase: str,
                status: str,
                payload: dict[str, Any] | None,
                error: str,
            ) -> None:
                if status == "running":
                    checkpoints.mark_running(phase)
                elif status == "completed" and payload is not None:
                    checkpoints.complete(phase, payload)
                elif status == "failed":
                    checkpoints.fail(phase, error)

            generation_kwargs = {
                "mode": mode,
                "guidance": normalized_guidance,
                "phase_payloads": checkpoints.completed_payloads(),
                "phase_callback": record_phase,
            }
            if foundation_only and "stop_after_phase" in generate_parameters:
                generation_kwargs["stop_after_phase"] = "outline_foundation"
            plan = generator.generate(brief, **generation_kwargs)
        else:
            plan = generator.generate(
                brief,
                mode=mode,
                guidance=normalized_guidance,
            )
        if foundation_only:
            return self._save_generated_outline_foundation(plan, mode=mode)
        return self.save_generated_outline_plan(
            plan,
            mode=mode,
            persist_chapter_window=persist_chapter_window,
        )
