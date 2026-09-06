from __future__ import annotations

from typing import Any, Iterable

from packages.story_core.dual_state import (
    project_character_for_scene,
    scene_kind_for_cards,
)


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
