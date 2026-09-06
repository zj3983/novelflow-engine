from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from packages.story_core.chapter_continuity import build_continuity_interface
from packages.story_core.chapter_length_policy import (
    CHAPTER_HARD_MAX_CHARS,
    CHAPTER_HARD_MIN_CHARS,
    CHAPTER_TARGET_MAX_CHARS,
    CHAPTER_TARGET_MIN_CHARS,
)
from packages.story_core.character_profiles import is_non_character_card, merge_character_profile
from packages.story_core.equipment_cards import equipment_cards_for_context, merge_equipment_cards
from packages.story_core.foreshadowing import select_unresolved_foreshadowing
from packages.story_core.novel_type_catalog import normalize_novel_type_ids
from packages.story_core.outline_rolling import rolling_chapter_to_outline_entry
from packages.story_core.outline_rolling_store import RollingOutlineStore
from packages.story_core.project_outline import select_outline_context
from packages.story_core.relationship_graph import select_relationship_subgraph
from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
    writer_skill_pack_prompt_context,
)
from packages.story_core.web_game_economy import normalize_legacy_economy_prompt_value
from packages.story_core.world_blueprint_context import select_world_context
from packages.story_core.world_state import (
    normalize_world_context,
    relevant_continuity_facts,
)
from packages.story_core.writing_packet import power_system_context_for_state, prose_renderer_contract


_PROGRESSION_GOVERNANCE_CHINESE_MARKERS = (
    "必须", "不得", "不能", "每章", "至少", "前十章", "只", "只能", "仅", "一律", "禁止", "严禁", "务必",
)
_PROGRESSION_GOVERNANCE_ENGLISH_MARKERS = (
    "must", "shall", "never", "cannot", "only", "every chapter", "at least", "required",
)


def _is_progression_governance_rule(rule: str) -> bool:
    if any(marker in rule for marker in _PROGRESSION_GOVERNANCE_CHINESE_MARKERS):
        return True
    folded = rule.casefold()
    return any(
        re.search(rf"\b{re.escape(marker)}\b", folded)
        for marker in _PROGRESSION_GOVERNANCE_ENGLISH_MARKERS
    )


def _progression_governance_hard_locks(
    progression_rules: Any,
    scoped_progression_rules: Any,
) -> list[str]:
    if not isinstance(progression_rules, list):
        return []
    scoped = {
        str(rule).strip()
        for rule in (scoped_progression_rules if isinstance(scoped_progression_rules, list) else [])
        if isinstance(rule, str) and rule.strip()
    }
    selected: list[str] = []
    for value in progression_rules:
        if not isinstance(value, str):
            continue
        rule = value.strip()
        if not rule or rule in scoped or rule in selected or not _is_progression_governance_rule(rule):
            continue
        selected.append(rule)
    return selected


def _select_relevant_monster_profiles(
    monster_profiles: Any,
    relevance_text: str,
    *,
    max_profiles: int = 6,
) -> list[dict[str, Any]]:
    if not isinstance(monster_profiles, list):
        return []
    relevance = str(relevance_text or "").casefold()
    selected: list[dict[str, Any]] = []
    for profile in monster_profiles:
        if not isinstance(profile, dict):
            continue
        identifiers = (
            str(profile.get(field) or "").strip().casefold()
            for field in ("name", "title")
        )
        if any(identifier and identifier in relevance for identifier in identifiers):
            selected.append(deepcopy(profile))
        if len(selected) >= max_profiles:
            break
    return selected


FILE_CHAPTER_MIN_CHARS = CHAPTER_HARD_MIN_CHARS
FILE_CHAPTER_TARGET_MIN_CHARS = CHAPTER_TARGET_MIN_CHARS
FILE_CHAPTER_MAX_CHARS = CHAPTER_TARGET_MAX_CHARS
FILE_CHAPTER_HARD_MAX_CHARS = CHAPTER_HARD_MAX_CHARS


class WritingContextStoreMixin:
    def summary(self) -> dict[str, Any]:
        project = self.project()
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        chapters = [
            {
                "chapter_number": entry["chapter_number"],
                "chapter_title": entry["chapter_title"],
            }
            for entry in self.chapter_index()
        ]
        return {
            "schema_version": "file-project-summary/v1",
            "root": str(self.root),
            "project_id": project.get("project_id"),
            "title": project.get("title") or state.get("outline"),
            "active_story_id": project.get("active_story_id") or state.get("story_id"),
            "current_chapter": state.get("current_chapter") or (chapters[-1]["chapter_number"] if chapters else 0),
            "chapter_count": len(chapters),
            "chapters": chapters,
        }

    def query(self, keyword: str, *, max_results: int = 20) -> dict[str, Any]:
        needle = keyword.strip()
        if not needle:
            raise ValueError("keyword_required")
        results: list[dict[str, Any]] = []
        search_paths = [
            self.story_system_dir / "MASTER_SETTING.json",
            self.webnovel_dir / "project.json",
            self.webnovel_dir / "state.json",
            *sorted((self.story_system_dir / "chapters").glob("*.json")),
            *sorted(self.chapters_dir.glob("*.md")),
        ]
        for path in search_paths:
            if not path.exists() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            index = text.find(needle)
            if index < 0:
                continue
            start = max(0, index - 80)
            end = min(len(text), index + len(needle) + 120)
            results.append(
                {
                    "file": str(path.relative_to(self.root)),
                    "match": needle,
                    "snippet": text[start:end].replace("\r\n", "\n"),
                }
            )
            if len(results) >= max_results:
                break
        return {
            "schema_version": "file-project-query/v1",
            "root": str(self.root),
            "keyword": needle,
            "result_count": len(results),
            "results": results,
        }

    def _world_relevance_text(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        target_chapter: int,
        outline_context: dict[str, Any],
        scene_cards: Any = None,
        *,
        current_chapter: int,
    ) -> str:
        chapter = (
            outline_context.get("chapter")
            if isinstance(outline_context.get("chapter"), dict)
            else {}
        )
        parts: list[str] = []
        if target_chapter > current_chapter:
            parts.append(str(state.get("current_focus") or project.get("current_focus") or ""))

        chapter_fields = (
            "title",
            "goal",
            "action",
            "payoff",
            "turn",
            "ending_hook",
            "line",
            "scene_line",
        )
        parts.extend(str(chapter.get(field) or "") for field in chapter_fields)

        scene_fields = ("title", "purpose", *chapter_fields[1:])
        parts.extend(
            str(card.get(field) or "")
            for card in (scene_cards if isinstance(scene_cards, list) else [])
            if isinstance(card, dict)
            for field in scene_fields
        )
        return "\n".join(part for part in parts if part.strip())

    def _continuity_interface_for_target(
        self,
        target_chapter: int,
        chapter_numbers: list[int] | None = None,
    ) -> dict[str, Any]:
        numbers = set(chapter_numbers if chapter_numbers is not None else self.chapter_numbers())

        def adjacent(number: int) -> dict[str, Any] | None:
            if number < 1 or number not in numbers:
                return None
            try:
                chapter = self.chapter(number)
            except FileNotFoundError:
                return None
            return chapter if isinstance(chapter, dict) else None

        return build_continuity_interface(
            target_chapter,
            previous=adjacent(target_chapter - 1),
            next_chapter=adjacent(target_chapter + 1),
        )

    def _story_state_payload_for_direction(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        target_chapter: int,
    ) -> dict[str, Any]:
        raw_project_outline = self.project_outline()
        outline_source = str(raw_project_outline.get("source") or "")
        project_outline = dict(raw_project_outline)
        project_outline.pop("source", None)
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        outline_context = dict(select_outline_context(project_outline, target_chapter))
        rolling_chapter = RollingOutlineStore(self.root).read_chapter(target_chapter)
        adapted_rolling_chapter = rolling_chapter_to_outline_entry(rolling_chapter)
        if adapted_rolling_chapter:
            outline_context["chapter"] = adapted_rolling_chapter
        known_chapter_numbers = self.chapter_numbers()
        continuity_interface = self._continuity_interface_for_target(target_chapter, known_chapter_numbers)
        if continuity_interface:
            outline_context["continuity_interface"] = continuity_interface
        latest_number = max(known_chapter_numbers or [0])
        current_chapter = max(latest_number, int(state.get("current_chapter") or 0))
        profile_latest_chapter = max(
            [
                int(card.get("latest_chapter") or 0)
                for card in project.get("character_profiles", [])
                if isinstance(card, dict)
                and str(card.get("latest_chapter") or "").strip().isdigit()
            ]
            or [0]
        )
        historical_target = target_chapter <= max(latest_number, profile_latest_chapter)
        relevance_text = self._world_relevance_text(
            state,
            project,
            target_chapter,
            outline_context,
            current_chapter=current_chapter,
        )
        normalized_world = normalize_world_context(
            blueprint=world_blueprint,
            state=state,
            current_focus=project.get("current_focus"),
        )
        world_snapshot = deepcopy(normalized_world.world_snapshot)
        if target_chapter <= current_chapter:
            world_snapshot.pop("current_focus", None)
        scoped_world = select_world_context(
            normalized_world.static_blueprint,
            relevance_text,
            max_rules=8,
        )
        equipment_cards = merge_equipment_cards(
            world_blueprint.get("equipment_cards"),
            state.get("equipment_cards"),
        ).cards
        if isinstance(world_blueprint.get("power_system_spec"), dict):
            scoped_world["power_system_spec"] = deepcopy(world_blueprint["power_system_spec"])
        state_genre_ids = state.get("genre_plugin_ids")
        project_genre_ids = world_blueprint.get("genre_plugin_ids")
        genre_plugin_ids = normalize_novel_type_ids(state_genre_ids)
        if not genre_plugin_ids:
            genre_plugin_ids = normalize_novel_type_ids(project_genre_ids)
        project_profiles = {
            str(card.get("name") or "").strip(): (
                self._historical_character_profile(card, target_chapter=target_chapter)
                if historical_target
                else card
            )
            for card in project.get("character_profiles", [])
            if isinstance(card, dict) and str(card.get("name") or "").strip()
        }
        characters: list[dict[str, Any]] = []
        for item in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(item, dict) or is_non_character_card(item):
                continue
            panel = item.get("game_panel") if isinstance(item.get("game_panel"), dict) else {}
            character = deepcopy(item)
            character["name"] = str(item.get("name") or panel.get("game_id") or "主角")
            character["role"] = str(item.get("role") or "protagonist")
            character["game_id"] = str(item.get("game_id") or panel.get("game_id") or "")
            if historical_target:
                # Strip future-dated fields from the state card only when the
                # matching project profile proves the data postdates the target;
                # a state already time-travelled by the regeneration base keeps
                # its era-correct runtime fields.
                project_card = next(
                    (
                        card
                        for card in project.get("character_profiles", [])
                        if isinstance(card, dict)
                        and str(card.get("name") or "").strip() == character["name"]
                    ),
                    None,
                )
                latest = 0
                if isinstance(project_card, dict):
                    try:
                        latest = int(project_card.get("latest_chapter") or 0)
                    except (TypeError, ValueError):
                        latest = 0
                if latest > target_chapter:
                    character = self._historical_character_profile(
                        character,
                        target_chapter=target_chapter,
                    )
            profile = project_profiles.get(character["name"])
            if isinstance(profile, dict):
                for field in (
                    "role",
                    "character_tier",
                    "first_appearance",
                    "identity_profile",
                    "background_profile",
                    "current_life_profile",
                    "story_drive",
                    "performance_profile",
                    "dialogue_examples",
                    "relationship_notes",
                    "personality_portrait",
                    "character_type",
                    "core_motivation",
                    "behavior_logic",
                    "interaction_mode",
                    "poison_points",
                ):
                    value = profile.get(field)
                    if value not in (None, "", [], {}):
                        if historical_target and isinstance(value, dict) and isinstance(character.get(field), dict):
                            character[field] = merge_character_profile(character[field], value)
                        else:
                            character[field] = deepcopy(value)
                drive = profile.get("story_drive") if isinstance(profile.get("story_drive"), dict) else {}
                if not character.get("goals"):
                    character["goals"] = [
                        value
                        for key in ("immediate_goal", "long_term_goal")
                        if (value := str(drive.get(key) or "").strip())
                    ]
                if str(profile.get("character_tier") or "").strip().casefold() == "protagonist":
                    character["role"] = "protagonist"
                    character["character_tier"] = "protagonist"
            characters.append(character)
        relevant_characters = [
            character
            for character in characters
            if str(character.get("character_tier") or "").strip().casefold()
            == "protagonist"
            or str(character.get("role") or "").strip().casefold()
            in {"protagonist", "主角"}
            or str(character.get("name") or "").strip() in relevance_text
        ]
        # The downstream director and writer perform their own chapter-scoped
        # filtering. Keep every explicitly relevant actor here so file order
        # cannot drop the protagonist before those filters run.
        characters = relevant_characters[:8] if relevant_characters else characters[:4]
        opening_arc = (
            world_blueprint.get("opening_arc")
            if isinstance(world_blueprint.get("opening_arc"), dict)
            else {}
        )
        golden_chapters = (
            opening_arc.get("golden_three_chapters")
            if isinstance(opening_arc.get("golden_three_chapters"), dict)
            else {}
        )
        opening_chapter = golden_chapters.get(str(target_chapter))
        if not isinstance(opening_chapter, dict):
            opening_chapter = golden_chapters.get(target_chapter)
        stable_chapter_facts = []
        if outline_source != "saved":
            stable_chapter_facts = (
                opening_chapter.get("must_include")
                if isinstance(opening_chapter, dict) and isinstance(opening_chapter.get("must_include"), list)
                else []
            )
        continuity_facts = relevant_continuity_facts(
            normalized_world.continuity_facts,
            query_terms=re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,16}", relevance_text),
            limit=12,
        )
        merged_world_facts = list(
            dict.fromkeys(
                str(item).strip()
                for item in [*stable_chapter_facts, *(item["text"] for item in continuity_facts)]
                if str(item).strip()
            )
        )
        return {
            "story_id": str(state.get("story_id") or project.get("active_story_id") or project.get("project_id") or "file-project"),
            "outline": str(state.get("outline") or project.get("seed_outline") or project.get("title") or ""),
            "genre": str(state.get("genre") or project.get("genre") or ""),
            "genre_plugin_ids": genre_plugin_ids,
            "style": str(state.get("style") or project.get("style") or ""),
            "current_chapter": int(state.get("current_chapter") or 0),
            "enabled_skill_ids": resolve_enabled_skill_ids(project, state),
            "enabled_skill_module_ids": resolve_enabled_skill_module_ids(project, state),
            "author_constraints": self._global_author_constraints(
                project.get("author_constraints") or state.get("author_constraints") or []
            ),
            "world_facts": merged_world_facts,
            "world_snapshot": world_snapshot,
            "continuity_facts": continuity_facts,
            "progression_ledger": dict(state.get("progression_ledger") or {}),
            "world_context": scoped_world,
            "characters": characters,
            "timeline": [
                deepcopy(item)
                for item in (state.get("timeline") or [])
                if isinstance(item, dict)
                and 0 < int(item.get("chapter_number") or 0) < target_chapter
            ][-8:],
            "chapter_summaries": [
                {
                    **deepcopy(item),
                    "cadence": (
                        item.get("cadence")
                        if item.get("cadence") in {"urgent", "measured", "breathing"}
                        else "measured"
                    ),
                }
                for item in (state.get("chapter_summaries") or [])
                if isinstance(item, dict)
                and 0 < int(item.get("chapter_number") or 0) < target_chapter
                and str(item.get("summary") or "").strip()
            ][-3:],
            "monster_profiles": [
                deepcopy(item)
                for item in world_blueprint.get("monster_profiles", [])[:20]
                if isinstance(item, dict) and str(item.get("name") or "").strip()
            ],
            "equipment_cards": equipment_cards,
            "outline_context": outline_context,
        }

    def _chapter_direction_options(self, state: dict[str, Any], project: dict[str, Any], chapter_number: int) -> dict[str, Any]:
        """Deprecated: the three-card "next chapter direction" picker was
        replaced by the rolling outline (Round 8). This method is kept so
        legacy callers (and the ``chapter_direction_options`` field on the
        writing packet) still resolve; it now returns an empty
        ``{options: []}`` payload so the frontend can detect "no direction
        options" without crashing.
        """
        return {"schema_version": "chapter-direction-options/v1", "chapter_number": int(chapter_number or 0), "options": [], "recommended_id": ""}

    def _read_rolling_fill_log(self) -> dict[str, Any] | None:
        """Read ``.story-system/outline-generation/rolling_fill_log.json``.

        Returns the parsed payload, or None when the file is missing or
        corrupt. The writing_packet uses this to surface the most recent
        fill status (so a failed batch is visible in the UI without an
        extra round-trip).
        """
        path = self.root / ".story-system" / "outline-generation" / "rolling_fill_log.json"
        if not path.is_file():
            return None
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict):
            return None
        return payload

    def _resolve_chapter_direction(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        chapter_number: int,
        chapter_direction_id: str | None,
    ) -> dict[str, Any]:
        """Resolve a ``chapter_direction_id`` against the legacy three-card
        picker. Round 8 Task 5 removed the picker; the parameter is
        preserved for API compatibility but is silently ignored when no
        options are available. The rolling outline is the new source of
        truth for the chapter's structure.
        """
        direction_id = str(chapter_direction_id or "").strip()
        if not direction_id:
            return {}
        options = self._chapter_direction_options(state, project, chapter_number)
        for option in options.get("options", []):
            if isinstance(option, dict) and str(option.get("id") or "") == direction_id:
                return option
        # Legacy ``chapter_direction_id`` from the v1 UI: silently ignore
        # rather than raise. The rolling outline (or its absence) drives
        # the body generation now.
        return {}

    def writing_packet(
        self,
        chapter_number: int | None = None,
    ) -> dict[str, Any]:
        packet, game_context, target = self._build_writing_packet(chapter_number)
        return normalize_legacy_economy_prompt_value(
            packet,
            game_context=game_context,
            chapter_number=target,
        )

    def rolling_fill_status(self, target_chapter: int) -> dict[str, Any]:
        """Pure-read rolling-fill status for ``target_chapter``.

        Returns a dict matching the ``rolling_fill`` field on the
        writing packet. No side effects: this method does not call the
        generator or write any chapter. The API uses this for the
        ``GET /outline/rolling-fill-status`` endpoint so the frontend
        can poll without triggering accidental fills.

        The status enum:

        * ``"present"`` — a rolling chapter exists on disk.
        * ``"missing"`` — neither rolling nor legacy outline has the
          chapter; a fill is needed before body generation.
        * ``"legacy"`` — the legacy outline has the chapter; no rolling
          fill needed but the rolling file is empty for this chapter.
        * ``"failed"`` — the most recent fill log row failed; the
          operator (or the user) needs to retry.
        """
        target = int(target_chapter)
        if target < 1:
            raise ValueError("rolling_fill_invalid_target_chapter")
        next_chapter_outline_source: str | None = None
        rolling_fill_status_name = "missing"
        filled_chapter_numbers: list[int] = []
        error_message: str = ""
        rolling_store = RollingOutlineStore(self.root)
        if rolling_store.read_chapter(target):
            next_chapter_outline_source = "rolling"
            rolling_fill_status_name = "present"
        else:
            outline = self.project_outline()
            chapters = outline.get("chapters") if isinstance(outline, dict) else None
            if isinstance(chapters, list):
                for chapter in chapters:
                    if (
                        isinstance(chapter, dict)
                        and chapter.get("chapter_number") == target
                    ):
                        next_chapter_outline_source = "legacy"
                        rolling_fill_status_name = "legacy"
                        break
        fill_log = self._read_rolling_fill_log()
        if isinstance(fill_log, dict) and fill_log.get("last_status") == "failed":
            rolling_fill_status_name = "failed"
            error_message = str(fill_log.get("last_error") or "")
            last_numbers = fill_log.get("last_chapter_numbers")
            if isinstance(last_numbers, list):
                filled_chapter_numbers = [
                    int(n) for n in last_numbers
                    if isinstance(n, int) and not isinstance(n, bool)
                ]
        return {
            "status": rolling_fill_status_name,
            "chapter_number": target,
            "source": next_chapter_outline_source,
            "filled_chapter_numbers": filled_chapter_numbers,
            "error": error_message,
        }

    def _build_writing_packet(
        self,
        chapter_number: int | None = None,
    ) -> tuple[dict[str, Any], bool, int]:
        current_state = dict(self.state())
        project = self.project()
        world_blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        forbidden_breaks = world_blueprint.get("forbidden_breaks") if isinstance(world_blueprint.get("forbidden_breaks"), list) else []
        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        saved_current_chapter = max(latest_number, int(current_state.get("current_chapter") or 0))
        if chapter_number is None:
            state = self._generation_state(current_state)
            target = int(state.get("current_chapter") or latest_number or 0) + 1
        else:
            target = int(chapter_number)
            state = self._generation_state_for_target(current_state, target)
        prior_numbers = [number for number in numbers if number < int(target or 0)]
        latest_context_number = prior_numbers[-1] if prior_numbers else 0
        latest_chapter = self.chapter(latest_context_number) if latest_context_number else {}
        project_outline = dict(self.project_outline())
        project_outline.pop("source", None)
        selected_outline = select_outline_context(project_outline, int(target or 0))
        outline_context = {
            key: selected_outline[key]
            for key in ("overall", "active_arc", "chapter")
        }
        chapter_outline = outline_context["chapter"] if isinstance(outline_context.get("chapter"), dict) else {}
        # Round 8 Task 5: surface the rolling-fill state and the next-chapter
        # outline. The packet is the canonical place for the frontend to
        # discover whether a rolling outline exists, what its source is, and
        # whether the body-generation path is allowed to start. The
        # computation is delegated to ``rolling_fill_status`` so the API
        # GET endpoint and the writing packet emit the same shape.
        next_chapter_outline: dict[str, Any] | None = None
        next_chapter_outline_source: str | None = None
        try:
            rolling_fill_info = self.rolling_fill_status(int(target or 0))
        except ValueError:
            rolling_fill_info = {
                "status": "missing",
                "chapter_number": int(target or 0),
                "source": None,
                "filled_chapter_numbers": [],
                "error": "",
            }
        rolling_fill_status = str(rolling_fill_info.get("status") or "missing")
        filled_chapter_numbers = list(rolling_fill_info.get("filled_chapter_numbers") or [])
        rolling_fill_error = str(rolling_fill_info.get("error") or "")
        next_chapter_outline_source = rolling_fill_info.get("source")
        # Fetch the actual rolling chapter (or legacy outline row) for the
        # packet body. The status object above only carries the source
        # label — it does not include the chapter body.
        if next_chapter_outline_source == "rolling":
            rolling_chapter = RollingOutlineStore(self.root).read_chapter(int(target or 0))
            if rolling_chapter:
                next_chapter_outline = rolling_chapter
                adapted_rolling_chapter = rolling_chapter_to_outline_entry(rolling_chapter)
                if adapted_rolling_chapter:
                    chapter_outline = adapted_rolling_chapter
                    outline_context["chapter"] = adapted_rolling_chapter
        elif next_chapter_outline_source == "legacy" and chapter_outline:
            next_chapter_outline = dict(chapter_outline)
        # ``filled_chapter_numbers`` is a renamed local to keep the
        # packet construction untouched below.
        rolling_fill_chapter_numbers = filled_chapter_numbers
        recent = []
        for number in prior_numbers[-3:]:
            item = self.chapter(number)
            recent.append(
                {
                    "chapter_number": item.get("chapter_number"),
                    "chapter_title": item.get("chapter_title"),
                    "summary": (item.get("chapter_summary") or {}).get("summary"),
                    "next_focus": item.get("next_outline") or (item.get("event_plan") or {}).get("next_focus"),
                }
            )
        scene_cards: list[dict[str, Any]] = []
        if chapter_outline:
            chapter = int(chapter_outline.get("chapter_number") or target or 0)
            title = self._compact_text(chapter_outline.get("title"), 80) or f"第{chapter}章剧情点"
            goal = self._compact_text(chapter_outline.get("goal"), 220)
            action = self._compact_text(chapter_outline.get("action"), 220)
            payoff = self._compact_text(chapter_outline.get("payoff"), 220)
            turn = self._compact_text(chapter_outline.get("turn"), 220)
            hook = self._compact_text(chapter_outline.get("ending_hook"), 180)
            scene_cards.append(
                {
                    "id": f"outline-beat-{chapter}",
                    "title": title,
                    "purpose": payoff or goal or action or turn or "按大纲推进本章明确结果。",
                    "goal": goal,
                    "action": action,
                    "payoff": payoff,
                    "turn": turn,
                    "ending_hook": hook,
                    "chapter": chapter,
                    "source": (
                        "rolling_outline.chapter"
                        if next_chapter_outline_source == "rolling"
                        else "outline_context.chapter"
                    ),
                    "line": chapter_outline.get("line"),
                    "scene_line": chapter_outline.get("scene_line"),
                }
            )
        is_game_story = self._is_game_story_payload(project, state)
        scene_kind = self._writer_scene_kind(scene_cards, is_game_story=is_game_story)
        current_chapter = saved_current_chapter
        relevance_text = self._world_relevance_text(
            state,
            project,
            int(target or 0),
            outline_context,
            scene_cards,
            current_chapter=current_chapter,
        )
        normalized_world = normalize_world_context(
            blueprint=world_blueprint,
            state=state,
            current_focus=project.get("current_focus"),
        )
        world_snapshot = deepcopy(normalized_world.world_snapshot)
        if int(target or 0) <= current_chapter:
            world_snapshot.pop("current_focus", None)
        scoped_world = select_world_context(
            normalized_world.static_blueprint,
            relevance_text,
            max_rules=8,
        )
        continuity_facts = relevant_continuity_facts(
            normalized_world.continuity_facts,
            query_terms=re.findall(r"[\u4e00-\u9fffA-Za-z0-9_]{2,16}", relevance_text),
            limit=12,
        )
        relevant_monster_profiles = _select_relevant_monster_profiles(
            world_blueprint.get("monster_profiles"),
            relevance_text,
            max_profiles=6,
        )
        target_min_chars = FILE_CHAPTER_TARGET_MIN_CHARS
        target_max_chars = FILE_CHAPTER_MAX_CHARS
        acceptance_min_chars = FILE_CHAPTER_MIN_CHARS
        acceptance_max_chars = FILE_CHAPTER_HARD_MAX_CHARS
        hard_locks = [
            (
                f"正文目标为{target_min_chars}至{target_max_chars}字；"
                f"低于{acceptance_min_chars}字或超过{acceptance_max_chars}字不能通过章节检查，"
                f"超过{target_max_chars}字应压缩。"
            ),
            "新人物出场前必须先有角色卡；没有角色卡只能作为待出场对象提出，不能直接写成已出场角色。",
        ]
        if is_game_story:
            hard_locks[1:1] = [
                "前十章每章必须给出可见成长或可见收益，不能连续只给线索。",
                "装备、任务条件和游戏术语只按本项目设定；题材模板不得补写特定武器、职业或前置任务。",
            ]
        current_focus = state.get("current_focus") or project.get("current_focus")
        if current_focus and int(target or 0) > current_chapter:
            hard_locks.append(f"当前主线焦点：{self._compact_text(current_focus, 220)}")
        if chapter_outline:
            goal = self._compact_text(chapter_outline.get("goal"), 220)
            payoff = self._compact_text(chapter_outline.get("payoff"), 220)
            hook = self._compact_text(chapter_outline.get("ending_hook"), 180)
            if goal:
                hard_locks.append(f"第{target}章目标：{goal}")
            if payoff:
                hard_locks.append(f"第{target}章必须兑现：{payoff}")
            if hook:
                hard_locks.append(f"第{target}章结尾钩子：{hook}")
        hard_locks.extend(
            _progression_governance_hard_locks(
                world_blueprint.get("progression_rules"),
                scoped_world.get("progression_rules"),
            )
        )
        hard_locks.extend(str(item) for item in forbidden_breaks[:4] if str(item).strip())
        characters = self._writer_character_cards(
            state,
            selected_outline,
            scene_kind=scene_kind,
            is_game_story=is_game_story,
        )
        equipment_cards: list[dict[str, Any]] = []
        if is_game_story:
            all_equipment = (
                world_blueprint.get("equipment_cards")
                if isinstance(world_blueprint.get("equipment_cards"), list)
                else []
            )
            relevance_folded = relevance_text.casefold()
            character_names = {
                str(card.get("name") or "").strip().casefold()
                for card in characters
                if str(card.get("name") or "").strip()
            }
            relevant_equipment = [
                card
                for card in all_equipment if isinstance(card, dict)
                if (
                    str(card.get("name") or "").strip().casefold() in relevance_folded
                    or str(card.get("current_owner") or "").strip().casefold() in character_names
                )
            ]
            equipment_cards = equipment_cards_for_context(
                relevant_equipment or all_equipment,
                names=[
                    str(card.get("name") or "")
                    for card in relevant_equipment
                    if isinstance(card, dict)
                ],
                owners=[str(card.get("name") or "") for card in characters],
                limit=12,
            )
            if equipment_cards:
                scoped_world["equipment_cards"] = deepcopy(equipment_cards)
        relationship_context = select_relationship_subgraph(
            project.get("relationship_graph"),
            [str(card.get("name") or "") for card in characters],
        )
        # Round 8 Task 5: the three-card "next chapter direction" picker
        # was replaced by the rolling outline. We still emit
        # ``chapter_direction_options`` for backward compatibility (legacy
        # clients that read the field), but the payload is always empty.
        chapter_direction_options: dict[str, Any] = (
            self._chapter_direction_options(state, project, int(target or 0))
            if int(target or 0) > current_chapter and not next_chapter_outline
            else {}
        )
        enabled_skill_ids = resolve_enabled_skill_ids(project, state)
        enabled_skill_module_ids = resolve_enabled_skill_module_ids(project, state)
        genre_context = self._review_genre_context()
        genre_ids = genre_context.get("genre_plugin_ids") or []
        genre_id = str(
            genre_ids[0]
            if genre_ids
            else genre_context.get("genre") or ""
        )
        writer_skill_context = writer_skill_pack_prompt_context(
            enabled_skill_ids,
            enabled_module_ids=enabled_skill_module_ids,
            genre_id=genre_id,
            max_chars_per_pack=2600,
        )
        skill_context = (
            {"writer": writer_skill_context}
            if writer_skill_context
            else {}
        )
        packet_project = dict(project)
        packet_project["character_profiles"] = characters
        scoped_author_constraints = self._global_author_constraints(
            project.get("author_constraints") or state.get("author_constraints") or []
        )
        packet_project["author_constraints"] = scoped_author_constraints
        packet_project.pop("relationship_graph", None)
        if int(target or 0) <= current_chapter:
            packet_project.pop("current_focus", None)
        packet_project["world_blueprint"] = scoped_world
        power_system = power_system_context_for_state(
            world_blueprint.get("power_system_spec"),
            progression_ledger=state.get("progression_ledger"),
            characters=state.get("characters"),
        )
        foreshadowing_context = select_unresolved_foreshadowing(
            self._parse_foreshadowing_ledger(state.get("foreshadowing")),
            chapter_number=int(target or 0),
            limit=8,
        )
        title_contract = (
            {
                "style": "tomato_concrete_short_title",
                "rules": [
                    "4到10字左右，像真实章节目录，不像广告文案",
                    "优先使用具体事件、地点、道具、职业、NPC服务点或委托名",
                    "可以有悬念，但不要用“他/别人/没人知道”这类营销句式",
                    "避免材料数量、铜币账目、成本核算、后台规则和说明句",
                ],
                "examples": ["登录建号", "职业学徒", "任务委托", "低级野怪区", "回村补给"],
            }
            if is_game_story
            else {
                "style": "concrete_short_title",
                "rules": [
                    "4到10字左右，像真实章节目录，不像广告文案",
                    "优先使用具体事件、地点、物件或人物关系",
                    "可以有悬念，但不要用“他/别人/没人知道”这类营销句式",
                    "避免数量清单、成本核算、后台规则和说明句",
                ],
                "examples": ["雪山来客", "断剑回响", "旧信开封", "夜访祖祠"],
            }
        )
        style_rules = (
            [
                "句子要完整，人物行动、理由和结果要接得上；对话不能省略必要的连接词、原因、条件和态度。",
                "网游信息通过动作、数值、道具消耗、位置变化和直接后果表现，不用旁白解释后台处理过程。",
                "每个场景都要有目标、阻力、结果或危机，结尾必须留下下一步问题。",
                "前10章节奏要快，连续两章不能只拿线索不给成长；下一章至少兑现一个可见成长：等级、经验大幅推进、技能、装备、货币补给或任务权限。",
                "武器、职业、技能和任务术语必须来自本项目资料；不要把其他网游项目的专名或示例写进正文。",
                "人物先行：本章要出场的新NPC必须先在角色卡里有候选卡；模型只能提出建议，不能直接改写既有角色主档。",
            ]
            if is_game_story
            else [
                "句子要完整，人物行动、理由和结果要接得上；对话不能省略必要的连接词、原因、条件和态度。",
                "设定通过行动、器物变化、身体反应、环境后果和人物关系表现，不用旁白解释后台过程。",
                "每个场景都要有目标、阻力、结果或危机，结尾必须留下下一步问题。",
                "连续两章不能只增加线索而没有可见推进；推进内容必须服从本书大纲和当前阶段。",
                "人物先行：本章要出场的新人物必须先有角色卡；模型只能提出建议，不能直接改写既有角色主档。",
            ]
        )
        volume_plan = world_blueprint.get("volume_plan") or {}
        active_arc = (
            outline_context.get("active_arc")
            if isinstance(outline_context.get("active_arc"), dict)
            else {}
        )
        outline_arcs = [
            item
            for item in project_outline.get("arcs", [])
            if isinstance(item, dict)
        ]
        first_arc = min(
            outline_arcs,
            key=lambda item: int(item.get("start_chapter") or 1),
            default={},
        )
        if (
            len(outline_arcs) > 1
            and active_arc
            and str(active_arc.get("id") or "") != str(first_arc.get("id") or "")
        ):
            start_chapter = int(active_arc.get("start_chapter") or target or 1)
            end_chapter = int(active_arc.get("end_chapter") or start_chapter)
            volume_plan = {
                "volume_title": str(active_arc.get("title") or ""),
                "target_chapters": max(end_chapter - start_chapter + 1, 1),
                "core_goal": str(active_arc.get("goal") or ""),
                "phase_beats": [
                    {
                        "range": f"{start_chapter}-{end_chapter}",
                        "goal": str(active_arc.get("payoff") or active_arc.get("goal") or ""),
                    }
                ],
                "long_threads": list(
                    (world_blueprint.get("volume_plan") or {}).get("long_threads")
                    or []
                ),
            }
        packet = {
            "schema_version": "file-writing-packet/v1",
            "root": str(self.root),
            "target_chapter": target,
            "chapter_number": target,
            "scene_kind": scene_kind,
            "latest_chapter_number": latest_context_number,
            "prose_renderer": prose_renderer_contract(),
            "target_chars": {"min": target_min_chars, "max": target_max_chars},
            "acceptance_chars": {"min": acceptance_min_chars, "max": acceptance_max_chars},
            "hard_locks": hard_locks,
            "monster_profiles": relevant_monster_profiles,
            "equipment_cards": equipment_cards,
            "scene_cards": scene_cards,
            "outline_context": outline_context,
            "character_cards": characters,
            "relationship_context": relationship_context,
            "foreshadowing_context": [item.model_dump() for item in foreshadowing_context],
            "title_contract": title_contract,
            "style_rules": style_rules,
            "outline_constraints": {
                "volume_plan": volume_plan,
                "longform_framework": world_blueprint.get("longform_framework") or {},
                "chapter_formula": world_blueprint.get("chapter_formula") or [],
                "forbidden_breaks": forbidden_breaks,
            },
            "project": packet_project,
            "state": {
                "story_id": state.get("story_id"),
                "genre": state.get("genre"),
                "style": state.get("style"),
                "current_chapter": state.get("current_chapter"),
                "current_focus": (
                    state.get("current_focus") or project.get("current_focus")
                    if int(target or 0) > current_chapter
                    else ""
                ),
                "world_snapshot": world_snapshot,
                "continuity_facts": continuity_facts,
                "author_constraints": scoped_author_constraints,
                "characters": characters,
            },
            "recent_chapters": recent,
            "latest_review": self.review(latest_context_number) if latest_context_number else {},
            "latest_event_plan": latest_chapter.get("event_plan", {}) if isinstance(latest_chapter, dict) else {},
            "chapter_direction_options": chapter_direction_options,
            "next_chapter_outline": next_chapter_outline,
            "next_chapter_outline_source": next_chapter_outline_source,
            "rolling_fill": {
                "status": rolling_fill_status,
                "chapter_number": int(target or 0),
                "source": next_chapter_outline_source,
                "filled_chapter_numbers": rolling_fill_chapter_numbers,
                "error": rolling_fill_error,
            },
            "skill_context": skill_context,
        }
        if power_system:
            packet["power_system"] = power_system
        return packet, is_game_story, int(target or 0)
