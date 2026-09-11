from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
from typing import Any, Iterable

from packages.story_core.dual_state import (
    project_character_for_scene,
    scene_kind_for_cards,
)
from packages.story_core.historical_state_replay import (
    get_character_state_for_writer,
)
from packages.story_core.knowledge_ledger import get_character_knowledge


_HISTORICAL_STABLE_FIELDS = (
    "name",
    "role",
    "character_tier",
    "first_appearance",
    "first_appearance_chapter",
    "introduced_by",
    "identity_profile",
    "background_profile",
    "performance_profile",
    "npc_profile",
    "personality_portrait",
    "character_type",
    "core_motivation",
    "behavior_logic",
    "interaction_mode",
    "poison_points",
    "social_profile",
    "psychological_profile",
    "moral_profile",
    "story_function",
    "traits",
)


def _plain_mapping(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError:
            dumped = model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def writer_historical_chapter(target_chapter: int) -> int:
    """Return the last completed chapter visible while writing a target chapter."""

    if isinstance(target_chapter, bool) or not isinstance(target_chapter, int) or target_chapter < 1:
        raise ValueError("target_chapter must be a positive integer")
    return target_chapter - 1


def _looks_like_game_story(story: Mapping[str, Any], characters: Sequence[Any]) -> bool:
    genre_text = " ".join(
        str(story.get(key) or "")
        for key in ("genre", "genre_plugin_id", "genre_plugin_ids", "style", "outline")
    ).casefold()
    if any(marker in genre_text for marker in ("game", "webnovel", "网游", "游戏")):
        return True
    return any(
        isinstance(item, Mapping) and ("game_state" in item or "game_panel" in item)
        for item in characters
    )


def _historical_writer_card(
    story: Mapping[str, Any],
    raw_character: Mapping[str, Any],
    *,
    as_of_chapter: int,
    scene_kind: str,
    is_game_story: bool,
) -> dict[str, Any]:
    name = str(raw_character.get("name") or "").strip()
    historical = get_character_state_for_writer(story, name, as_of_chapter)
    knowledge = get_character_knowledge(story, name, as_of_chapter)
    historical_current_state = deepcopy(historical.current_state)
    historical_real_state = deepcopy(historical.real_state)
    historical_game_state = deepcopy(historical.game_state)
    # Chapter zero is evidence-only.  get_character_state_for_writer() can
    # replay explicit baseline/initial/initial_state events at chapter 0, but
    # an undated ``current`` value is ambiguous and may be a latest-state
    # mirror from a much later chapter.
    safe: dict[str, Any] = {
        key: deepcopy(raw_character[key])
        for key in _HISTORICAL_STABLE_FIELDS
        if raw_character.get(key) not in (None, "", [], {})
    }
    safe["name"] = name
    safe["role"] = str(raw_character.get("role") or "")
    if raw_character.get("character_tier") not in (None, ""):
        safe["character_tier"] = deepcopy(raw_character["character_tier"])

    # Only the long-lived part of story_drive is stable enough for a rewrite.
    # immediate_goal is deliberately excluded; it is a latest-facing field.
    raw_drive = raw_character.get("story_drive")
    if isinstance(raw_drive, Mapping):
        drive = {
            key: deepcopy(raw_drive[key])
            for key in ("motivation", "long_term_goal")
            if raw_drive.get(key) not in (None, "", [], {})
        }
        if drive:
            safe["story_drive"] = drive

    safe["current_state"] = {"current": historical_current_state}
    safe["real_state"] = {"current": historical_real_state}
    safe["game_state"] = {"current": historical_game_state}
    safe["relationships"] = {
        str(item.get("target") or ""): {
            key: deepcopy(item[key])
            for key in ("target", "trust", "tension", "bond", "relation_type", "current_state", "status")
            if key in item and item.get(key) not in (None, "", [], {})
        }
        for item in historical.relationships
        if str(item.get("target") or "").strip()
    }
    safe["progression"] = deepcopy(historical.progression)
    safe["equipment"] = deepcopy(historical.equipment)
    safe["knowledge"] = deepcopy(knowledge)
    historical_payload = historical.to_dict()
    historical_payload["current_state"] = deepcopy(historical_current_state)
    historical_payload["real_state"] = deepcopy(historical_real_state)
    historical_payload["game_state"] = deepcopy(historical_game_state)
    safe["historical_state"] = historical_payload

    projected = project_character_for_scene(
        safe,
        scene_kind=scene_kind,
        is_game_story=is_game_story,
    )
    # Keep the explicit projections available to the typed WriterRequest. The
    # scene projection's state_context remains the compact prompt-facing view.
    projected["current_state"] = {"current": deepcopy(historical_current_state)}
    projected["real_state"] = {"current": deepcopy(historical_real_state)}
    projected["game_state"] = {"current": deepcopy(historical_game_state)}
    projected["progression"] = deepcopy(historical.progression)
    projected["equipment"] = deepcopy(historical.equipment)
    projected["relationships"] = deepcopy(historical.relationships)
    projected["knowledge"] = deepcopy(knowledge)
    projected["historical_state"] = historical_payload
    return projected


def historical_writer_character_cards(
    story_state: Mapping[str, Any] | Any,
    *,
    as_of_chapter: int,
    scene_kind: str = "transition",
    is_game_story: bool | None = None,
) -> list[dict[str, Any]]:
    """Build writer cards from stable profile plus chapter-bounded projections."""

    story = _plain_mapping(story_state)
    characters = story.get("characters")
    if not isinstance(characters, Sequence) or isinstance(characters, (str, bytes, bytearray)):
        return []
    raw_characters = [
        _plain_mapping(item)
        for item in characters
        if _plain_mapping(item).get("name")
    ]
    resolved_game_story = (
        _looks_like_game_story(story, raw_characters)
        if is_game_story is None
        else bool(is_game_story)
    )
    resolved_scene_kind = scene_kind if scene_kind in {"game", "reality", "transition"} else "transition"
    return [
        _historical_writer_card(
            story,
            raw_character,
            as_of_chapter=as_of_chapter,
            scene_kind=resolved_scene_kind,
            is_game_story=resolved_game_story,
        )
        for raw_character in raw_characters
    ]


def historical_writer_dynamic_fields(card: Mapping[str, Any]) -> dict[str, Any]:
    """Return the bounded dynamic fields for legacy prompt adapters."""

    if not isinstance(card, Mapping):
        return {}
    return {
        key: deepcopy(card.get(key))
        for key in (
            "historical_state",
            "current_state",
            "real_state",
            "game_state",
            "progression",
            "equipment",
            "knowledge",
        )
        if card.get(key) not in (None, "", [], {})
    }


class WriterCharacterContextMixin:
    """Select and project only the character cards needed by the writer."""

    @staticmethod
    def _writer_scene_kind(scene_cards: list[dict[str, Any]], *, is_game_story: bool) -> str:
        return scene_kind_for_cards(scene_cards, is_game_story=is_game_story)

    def _writer_character_cards(
        self,
        state: dict[str, Any],
        selected_outline: dict[str, Any],
        *,
        scene_kind: str = "reality",
        is_game_story: bool = True,
    ) -> list[dict[str, Any]]:
        characters = [
            dict(item)
            for item in state.get("characters", [])
            if isinstance(item, dict)
            and str(item.get("name") or "").strip()
            and self._is_character_card(item)
        ]
        chapter = selected_outline.get("chapter") if isinstance(selected_outline.get("chapter"), dict) else {}
        cast = [str(item).strip() for item in chapter.get("cast", []) if str(item).strip()]

        protagonist = next(
            (
                card
                for card in characters
                if str(card.get("character_tier") or "").strip() == "protagonist"
                or str(card.get("role") or "").strip().lower() in {"protagonist", "主角"}
            ),
            None,
        )
        wanted = list(cast) if cast else [str(card.get("name") or "").strip() for card in characters[:6]]
        if protagonist:
            protagonist_name = str(protagonist.get("name") or "").strip()
            if protagonist_name and protagonist_name not in wanted:
                wanted.insert(0, protagonist_name)

        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for identifier in wanted:
            card = next(
                (item for item in characters if self._character_matches(item, identifier)),
                None,
            )
            if card is None:
                continue
            name = str(card.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            projected = project_character_for_scene(
                card,
                scene_kind=scene_kind,
                is_game_story=is_game_story,
            )
            selected.append(projected)
        return selected

    @staticmethod
    def _without_replaced_baseline_protagonists(
        characters: Iterable[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        cards = [dict(item) for item in characters if isinstance(item, dict)]

        def is_protagonist(card: dict[str, Any]) -> bool:
            return (
                str(card.get("character_tier") or "").strip().lower() == "protagonist"
                or str(card.get("role") or "").strip().lower() in {"protagonist", "主角"}
            )

        has_project_protagonist = any(
            is_protagonist(card)
            and str(card.get("introduced_by") or "").strip() != "baseline:protagonist"
            for card in cards
        )
        if not has_project_protagonist:
            return cards
        return [
            card
            for card in cards
            if not (
                is_protagonist(card)
                and str(card.get("introduced_by") or "").strip() == "baseline:protagonist"
            )
        ]
