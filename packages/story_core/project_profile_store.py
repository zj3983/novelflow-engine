from __future__ import annotations

import json
import logging
from copy import deepcopy
from hashlib import sha256
from typing import Any

from packages.story_core.book_style import normalize_book_style
from packages.story_core.character_persistence import (
    normalize_character_persistence_card,
)
from packages.story_core.character_portraits import (
    complete_character_portrait as complete_portrait,
)
from packages.story_core.character_profiles import (
    filter_character_cards,
    merge_character_alias_cards,
    remove_cross_character_aliases,
)
from packages.story_core.equipment_cards import normalize_equipment_cards
from packages.story_core.foreshadowing import (
    canonicalize_foreshadowing_ledger,
    normalize_foreshadowing_text,
)
from packages.story_core.models import CharacterState, ForeshadowingState
from packages.story_core.novel_type_catalog import (
    is_game_story_type,
    normalize_novel_type_ids,
    novel_type_id_from_metadata_fact,
    resolve_novel_type_id,
    runtime_novel_type,
)
from packages.story_core.persistence.project_locking import with_project_update_lock
from packages.story_core.relationship_graph import (
    graph_from_character_cards,
    normalize_relationship_graph,
)
from packages.story_core.world_blueprint_context import (
    merge_world_blueprint,
    sync_world_markdown,
)


class ProjectProfileStoreMixin:
    """Project metadata, character profiles, and foreshadowing persistence."""

    def exists(self) -> bool:
        return (
            (self.story_system_dir / "MASTER_SETTING.json").exists()
            and (self.webnovel_dir / "state.json").exists()
        )

    def master_setting(self) -> dict[str, Any]:
        return self._read_json(
            self.story_system_dir / "MASTER_SETTING.json",
            {},
        ) or {}

    @staticmethod
    def _is_game_story_payload(
        project: dict[str, Any],
        state: dict[str, Any] | None = None,
    ) -> bool:
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        state = state if isinstance(state, dict) else {}
        state_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
        genre_plugin_ids = state_ids or normalize_novel_type_ids(
            world_blueprint.get("genre_plugin_ids")
        )
        return is_game_story_type(
            {
                "genre_plugin_ids": genre_plugin_ids,
                "genre": state.get("genre") or project.get("genre"),
            }
        )

    def project(self) -> dict[str, Any]:
        project = (
            self._read_json(self.webnovel_dir / "project.json", {})
            or self.master_setting().get("project", {})
            or {}
        )
        project = dict(project)
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        is_game_story = self._is_game_story_payload(project, state)
        project["character_profiles"] = remove_cross_character_aliases(
            filter_character_cards(
                merge_character_alias_cards(
                    [
                        normalize_character_persistence_card(
                            item,
                            is_game_story=is_game_story,
                        )
                        for item in project.get("character_profiles", [])
                        if isinstance(item, dict)
                    ]
                )
            )
        )
        if "relationship_graph" in project:
            project["relationship_graph"] = normalize_relationship_graph(
                project.get("relationship_graph")
            )
        else:
            project["relationship_graph"] = graph_from_character_cards(
                project.get("character_profiles")
            )
        return project

    def _review_genre_context(self) -> dict[str, Any]:
        project = self.project()
        state = self.state()
        blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        genre_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
        if not genre_ids:
            genre_ids = normalize_novel_type_ids(
                blueprint.get("genre_plugin_ids")
            )
        return {
            "genre": str(state.get("genre") or project.get("genre") or ""),
            "genre_plugin_ids": genre_ids,
        }

    @with_project_update_lock
    def update_project(
        self,
        patch: dict[str, Any],
        *,
        replace_world_blueprint: bool = False,
    ) -> dict[str, Any]:
        world_blueprint_updated = patch.get("world_blueprint") is not None
        normalized_patch_genre_ids: list[str] | None = None
        patch_world_blueprint = patch.get("world_blueprint")
        if (
            isinstance(patch_world_blueprint, dict)
            and "equipment_cards" in patch_world_blueprint
        ):
            raw_equipment_cards = patch_world_blueprint.get("equipment_cards")
            if not isinstance(raw_equipment_cards, list):
                raise ValueError("invalid_equipment_cards")
            normalized_equipment_cards = normalize_equipment_cards(
                raw_equipment_cards
            )
            if len(normalized_equipment_cards) != len(raw_equipment_cards):
                raise ValueError("invalid_equipment_cards")
            patch_world_blueprint = dict(patch_world_blueprint)
            patch_world_blueprint["equipment_cards"] = normalized_equipment_cards
            patch = {**patch, "world_blueprint": patch_world_blueprint}
        if (
            isinstance(patch_world_blueprint, dict)
            and "writing_style" in patch_world_blueprint
        ):
            raw_writing_style = str(
                patch_world_blueprint.get("writing_style") or ""
            ).strip()
            normalized_writing_style = normalize_book_style(raw_writing_style)
            if raw_writing_style and not normalized_writing_style:
                raise ValueError("invalid_writing_style")
            patch_world_blueprint = dict(patch_world_blueprint)
            patch_world_blueprint["writing_style"] = normalized_writing_style
            patch = {**patch, "world_blueprint": patch_world_blueprint}
        if (
            isinstance(patch_world_blueprint, dict)
            and "genre_plugin_ids" in patch_world_blueprint
        ):
            raw_genre_ids = patch_world_blueprint.get("genre_plugin_ids")
            if raw_genre_ids is None:
                genre_values: list[Any] = []
            elif isinstance(raw_genre_ids, str):
                genre_values = [raw_genre_ids]
            elif isinstance(raw_genre_ids, list):
                genre_values = raw_genre_ids
            else:
                raise ValueError("invalid_novel_type")

            normalized_patch_genre_ids = []
            for value in genre_values:
                if not str(value or "").strip():
                    continue
                resolved_id = resolve_novel_type_id(value)
                if not resolved_id:
                    raise ValueError("invalid_novel_type")
                if resolved_id not in normalized_patch_genre_ids:
                    normalized_patch_genre_ids.append(resolved_id)

        project = dict(self.project())
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        for key in (
            "title",
            "game_title",
            "world_summary",
            "author_constraints",
            "character_profiles",
            "relationship_graph",
            "enabled_skill_ids",
            "enabled_skill_module_ids",
            "status",
            "pipeline_stage",
            "project_lifecycle",
            "archived_at",
            "trashed_at",
            "pre_trash_lifecycle",
        ):
            if key in patch and patch[key] is not None:
                project[key] = patch[key]
        if isinstance(project.get("character_profiles"), list):
            project["character_profiles"] = filter_character_cards(
                project["character_profiles"]
            )
            if (
                "character_profiles" in patch
                and patch["character_profiles"] is not None
            ):
                state["characters"] = deepcopy(project["character_profiles"])
        if isinstance(state.get("characters"), list):
            state["characters"] = filter_character_cards(state["characters"])
        for key in ("enabled_skill_ids", "enabled_skill_module_ids"):
            if key in patch and patch[key] is not None:
                state[key] = deepcopy(project[key])
        if (
            "relationship_graph" in patch
            and patch.get("relationship_graph") is not None
        ):
            project["relationship_graph"] = normalize_relationship_graph(
                patch["relationship_graph"]
            )
        if patch.get("seed_outline") is not None:
            project["seed_outline"] = patch["seed_outline"]
            state["outline"] = patch["seed_outline"]
        if world_blueprint_updated:
            world_blueprint_patch = patch["world_blueprint"]
            world_blueprint = (
                deepcopy(world_blueprint_patch)
                if replace_world_blueprint
                else merge_world_blueprint(
                    project.get("world_blueprint"),
                    world_blueprint_patch,
                )
            )
            if normalized_patch_genre_ids is not None:
                world_blueprint = dict(world_blueprint)
                world_blueprint["genre_plugin_ids"] = normalized_patch_genre_ids
            project["world_blueprint"] = world_blueprint
            if (
                isinstance(world_blueprint_patch, dict)
                and "equipment_cards" in world_blueprint_patch
            ):
                state["equipment_cards"] = deepcopy(
                    world_blueprint.get("equipment_cards") or []
                )
            if (
                isinstance(world_blueprint_patch, dict)
                and "writing_style" in world_blueprint_patch
            ):
                state["style"] = normalize_book_style(
                    world_blueprint_patch.get("writing_style")
                )
            if (
                isinstance(world_blueprint_patch, dict)
                and "genre_plugin_ids" in world_blueprint_patch
            ):
                raw_genre_ids = world_blueprint.get("genre_plugin_ids")
                genre_plugin_ids = normalize_novel_type_ids(raw_genre_ids)
                explicitly_empty = raw_genre_ids in (None, "", []) or (
                    isinstance(raw_genre_ids, list)
                    and not any(str(item or "").strip() for item in raw_genre_ids)
                )
                synchronized_genre_ids: list[str] | None = None
                if genre_plugin_ids:
                    state["genre_plugin_ids"] = genre_plugin_ids
                    synchronized_genre_ids = genre_plugin_ids
                    primary_type = runtime_novel_type(genre_plugin_ids[0])
                    if primary_type is not None:
                        state["genre"] = primary_type.name
                elif explicitly_empty:
                    state["genre_plugin_ids"] = []
                    state["genre"] = ""
                    synchronized_genre_ids = []
                if synchronized_genre_ids is not None:
                    world_facts = (
                        state.get("world_facts")
                        if isinstance(state.get("world_facts"), list)
                        else []
                    )
                    state["world_facts"] = [
                        fact
                        for fact in world_facts
                        if not (
                            isinstance(fact, str)
                            and novel_type_id_from_metadata_fact(fact)
                        )
                    ]
                    if synchronized_genre_ids:
                        state["world_facts"].append(
                            f"小说类型：{synchronized_genre_ids[0]}"
                        )
        if patch.get("current_focus") is not None:
            project["current_focus"] = patch["current_focus"]
            state["current_focus"] = patch["current_focus"]
        elif (
            isinstance(project.get("world_blueprint"), dict)
            and project["world_blueprint"].get("current_arc")
        ):
            project["current_focus"] = (
                project.get("current_focus")
                or project["world_blueprint"]["current_arc"]
            )

        payloads = {
            self.webnovel_dir / "project.json": project,
            self.webnovel_dir / "state.json": state,
        }
        if world_blueprint_updated:
            master_path = self.story_system_dir / "MASTER_SETTING.json"
            master = dict(self._read_json(master_path, {}) or {})
            canonical_blueprint = deepcopy(project["world_blueprint"])
            master["world_blueprint"] = canonical_blueprint
            master_project = master.get("project")
            synchronized_master_project = (
                dict(master_project) if isinstance(master_project, dict) else {}
            )
            synchronized_master_project["world_blueprint"] = deepcopy(
                canonical_blueprint
            )
            for key in ("project_id", "active_story_id", "title", "game_title"):
                if key in project:
                    synchronized_master_project[key] = deepcopy(project[key])
            master["project"] = synchronized_master_project
            payloads[master_path] = master

        self._replace_json_transaction(payloads)
        if world_blueprint_updated:
            title = (
                project.get("game_title")
                or project.get("title")
                or "未命名作品"
            )
            try:
                sync_world_markdown(
                    self.root,
                    title,
                    project["world_blueprint"],
                )
            except Exception:  # noqa: BLE001
                logging.getLogger(__name__).warning(
                    "world blueprint markdown sync failed",
                    exc_info=True,
                )
        return project

    @staticmethod
    def _merge_character_patch(current: Any, patch: Any) -> Any:
        if isinstance(current, dict) and isinstance(patch, dict):
            merged = dict(current)
            for key, value in patch.items():
                merged[key] = ProjectProfileStoreMixin._merge_character_patch(
                    merged.get(key),
                    value,
                )
            return merged
        return patch

    @staticmethod
    def _character_matches(card: dict[str, Any], identifier: str) -> bool:
        target = str(identifier or "").strip()
        if not target:
            return False
        panel = (
            card.get("game_panel")
            if isinstance(card.get("game_panel"), dict)
            else {}
        )
        return target in {
            str(card.get("name") or "").strip(),
            str(card.get("game_id") or "").strip(),
            str(panel.get("game_id") or "").strip(),
        }

    def _completed_character_card(
        self,
        card: dict[str, Any],
        *,
        genre: str = "",
    ) -> dict[str, Any]:
        def drop_none(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: drop_none(item)
                    for key, item in value.items()
                    if item is not None
                }
            if isinstance(value, list):
                return [drop_none(item) for item in value]
            return value

        card = drop_none(card)
        raw_state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        normalized_card = normalize_character_persistence_card(
            card,
            is_game_story=self._is_game_story_payload(self.project(), raw_state),
        )
        validated = CharacterState.model_validate(normalized_card)
        completed = complete_portrait(
            validated,
            genre=genre,
            story_function=str(normalized_card.get("story_function") or ""),
        )
        completed_card = self._merge_character_patch(
            normalized_card,
            completed.model_dump(exclude_defaults=True, exclude_none=True),
        )
        return normalize_character_persistence_card(
            completed_card,
            is_game_story=self._is_game_story_payload(self.project(), raw_state),
        )

    def update_character(
        self,
        name: str,
        patch: dict[str, Any],
    ) -> dict[str, Any]:
        identifier = str(name or "").strip()
        if not identifier:
            raise KeyError("character_not_found:")
        patch = dict(patch or {})

        visible_state = self.state()
        visible_cards = (
            visible_state.get("characters")
            if isinstance(visible_state.get("characters"), list)
            else []
        )
        current = next(
            (
                dict(item)
                for item in visible_cards
                if isinstance(item, dict)
                and self._character_matches(item, identifier)
            ),
            None,
        )
        if current is None:
            raise KeyError(f"character_not_found:{identifier}")
        canonical_name = str(current.get("name") or "").strip()
        if patch.get("name") and str(patch["name"]).strip() != canonical_name:
            raise ValueError("character_name_immutable")

        merged = self._merge_character_patch(current, patch)
        merged["name"] = canonical_name
        completed = self._completed_character_card(
            merged,
            genre=str(visible_state.get("genre") or ""),
        )

        raw_state = dict(
            self._read_json(self.webnovel_dir / "state.json", {}) or {}
        )
        raw_cards = [
            dict(item)
            for item in raw_state.get("characters", [])
            if isinstance(item, dict)
        ]
        raw_index = next(
            (
                index
                for index, item in enumerate(raw_cards)
                if self._character_matches(item, canonical_name)
            ),
            None,
        )
        if raw_index is None:
            raw_cards.append(completed)
        else:
            raw_cards[raw_index] = self._merge_character_patch(
                raw_cards[raw_index],
                completed,
            )
        is_game_story = self._is_game_story_payload(self.project(), raw_state)
        raw_cards = [
            normalize_character_persistence_card(
                card,
                is_game_story=is_game_story,
            )
            for card in raw_cards
        ]
        raw_state["characters"] = raw_cards

        project = dict(self.project())
        project_cards = [
            dict(item)
            for item in project.get("character_profiles", [])
            if isinstance(item, dict)
        ]
        project_index = next(
            (
                index
                for index, item in enumerate(project_cards)
                if self._character_matches(item, canonical_name)
            ),
            None,
        )
        if project_index is None:
            project_cards.append(dict(completed))
        else:
            project_cards[project_index] = self._merge_character_patch(
                project_cards[project_index],
                completed,
            )
        project["character_profiles"] = [
            normalize_character_persistence_card(
                card,
                is_game_story=is_game_story,
            )
            for card in project_cards
        ]
        self._replace_json_transaction(
            {
                self.webnovel_dir / "state.json": raw_state,
                self.webnovel_dir / "project.json": project,
            }
        )

        return raw_cards[raw_index if raw_index is not None else -1]

    def complete_character_portrait(self, name: str) -> dict[str, Any]:
        identifier = str(name or "").strip()
        visible_state = self.state()
        cards = (
            visible_state.get("characters")
            if isinstance(visible_state.get("characters"), list)
            else []
        )
        current = next(
            (
                dict(item)
                for item in cards
                if isinstance(item, dict)
                and self._character_matches(item, identifier)
            ),
            None,
        )
        if current is None:
            raise KeyError(f"character_not_found:{identifier}")
        completed = self._completed_character_card(
            current,
            genre=str(visible_state.get("genre") or ""),
        )
        return self.update_character(
            str(completed.get("name") or identifier),
            completed,
        )

    def _valid_foreshadowing_ledger(
        self,
        raw_ledger: Any,
    ) -> list[ForeshadowingState]:
        parsed = self._parse_foreshadowing_ledger(raw_ledger)
        valid = [
            item
            for item in parsed
            if item.text.strip()
            and item.first_chapter >= 0
            and item.last_touched_chapter >= item.first_chapter
            and (
                item.resolved_chapter is None
                or item.resolved_chapter >= item.last_touched_chapter
            )
            and (item.status != "resolved" or item.resolved_chapter is not None)
            and (
                item.status not in {"open", "reinforced"}
                or item.resolved_chapter is None
            )
        ]
        return canonicalize_foreshadowing_ledger(valid)

    def foreshadowing_ledger(self) -> list[ForeshadowingState]:
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        raw_ledger = state.get("foreshadowing") if isinstance(state, dict) else None
        return self._valid_foreshadowing_ledger(raw_ledger)

    @staticmethod
    def foreshadowing_version(ledger: list[ForeshadowingState]) -> str:
        payload = json.dumps(
            [item.model_dump(mode="json") for item in ledger],
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        return sha256(payload.encode("utf-8")).hexdigest()

    @with_project_update_lock
    def update_foreshadowing_ledger(
        self,
        ledger: list[ForeshadowingState],
        *,
        expected_version: str | None = None,
    ) -> list[ForeshadowingState]:
        canonical = canonicalize_foreshadowing_ledger(ledger)
        state_path = self.webnovel_dir / "state.json"
        state = self._read_json(state_path, {}) or {}
        if not isinstance(state, dict):
            raise ValueError("invalid_story_state")
        current = self._valid_foreshadowing_ledger(state.get("foreshadowing"))
        if (
            expected_version is not None
            and expected_version != self.foreshadowing_version(current)
        ):
            raise ValueError("foreshadowing_version_conflict")
        if expected_version is None:
            current_keys = {
                normalize_foreshadowing_text(item.text) for item in current
            }
            canonical = canonicalize_foreshadowing_ledger(
                [
                    *current,
                    *[
                        item
                        for item in canonical
                        if normalize_foreshadowing_text(item.text)
                        not in current_keys
                    ],
                ]
            )
        updated = dict(state)
        updated["foreshadowing"] = [item.model_dump() for item in canonical]
        existing = {
            normalize_foreshadowing_text(item.text): item
            for item in self._parse_foreshadowing_ledger(
                state.get("foreshadowing")
            )
        }
        previously_manual = {
            normalize_foreshadowing_text(item.text): item
            for item in self._parse_foreshadowing_ledger(
                state.get("manual_foreshadowing")
            )
        }
        manual: list[ForeshadowingState] = []
        for item in canonical:
            key = normalize_foreshadowing_text(item.text)
            prior = existing.get(key)
            if key in previously_manual or prior is None or item != prior:
                manual.append(item)
        updated["manual_foreshadowing"] = [
            item.model_dump()
            for item in canonicalize_foreshadowing_ledger(manual)
        ]
        self._write_json_atomic(state_path, updated)
        return canonical


__all__ = ["ProjectProfileStoreMixin"]
