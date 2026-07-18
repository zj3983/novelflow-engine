from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any


_REAL_FIELDS = (
    "identity_profile",
    "background_profile",
    "current_life_profile",
    "story_drive",
)
_SCENE_KINDS = {"game", "reality", "transition"}
_LINES = {"game": "game_state", "reality": "real_state"}


def _current_from_state(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    current = value.get("current")
    if isinstance(current, Mapping):
        return deepcopy(dict(current))
    return deepcopy({key: item for key, item in value.items() if key != "recent_changes"})


def _recent_changes(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    changes: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            continue
        try:
            chapter = int(item.get("chapter", 0))
        except (TypeError, ValueError):
            chapter = 0
        changes.append({"chapter": chapter, "fact": str(item.get("fact", ""))})
    return changes


def _normalize_state(value: Any, *, fallback_current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    current = _current_from_state(value)
    if fallback_current:
        for key, item in fallback_current.items():
            current.setdefault(key, deepcopy(item))
    recent = value.get("recent_changes") if isinstance(value, Mapping) else None
    return {"current": current, "recent_changes": _recent_changes(recent)}


def normalize_dual_state(card: Mapping[str, Any], *, is_game_story: bool) -> dict[str, Any]:
    """Normalize legacy character fields into isolated reality and game lines."""

    normalized = deepcopy(dict(card))
    real_fallback = {
        field_name: normalized[field_name]
        for field_name in _REAL_FIELDS
        if field_name in normalized
    }
    normalized["real_state"] = _normalize_state(
        normalized.get("real_state"),
        fallback_current=real_fallback,
    )

    # An existing game namespace is data to preserve; legacy game_panel alone
    # is materialized only for an explicitly game-story normalization.
    if is_game_story or "game_state" in normalized:
        normalized["game_state"] = _normalize_state(
            normalized.get("game_state"),
            fallback_current=(
                normalized.get("game_panel")
                if is_game_story and isinstance(normalized.get("game_panel"), Mapping)
                else None
            ),
        )
    return normalized


def _project_state(card: Mapping[str, Any], normalized: Mapping[str, Any], name: str) -> dict[str, Any]:
    state = deepcopy(normalized[name])
    original = card.get(name)
    # Existing envelopes historically allowed omitted optional members. Keep
    # that compact representation in scene projections while new envelopes
    # still use the complete shape.
    if isinstance(original, Mapping) and "recent_changes" not in original:
        state.pop("recent_changes", None)
    return state


def project_dual_state(card: Mapping[str, Any], *, scene_kind: str) -> dict[str, Any]:
    """Return only the state namespace visible to a scene."""

    if scene_kind not in _SCENE_KINDS:
        raise ValueError(f"scene_kind must be one of: {', '.join(sorted(_SCENE_KINDS))}")

    normalized = normalize_dual_state(
        card,
        is_game_story=scene_kind in {"game", "transition"},
    )
    names = ("game_state",) if scene_kind == "game" else ("real_state",)
    if scene_kind == "transition":
        names = ("real_state", "game_state")
    return {name: _project_state(card, normalized, name) for name in names}


def merge_state_change(
    card: Mapping[str, Any],
    *,
    line: str,
    change: Mapping[str, Any],
    chapter: int,
) -> dict[str, Any]:
    """Apply one explicit change to one state line and record its fact."""

    if line not in _LINES:
        raise ValueError("line must be 'game' or 'reality'")

    namespace = _LINES[line]
    normalized = normalize_dual_state(
        card,
        is_game_story=line == "game" or "game_state" in card,
    )
    untouched_namespace = "real_state" if line == "game" else "game_state"
    if untouched_namespace in card:
        normalized[untouched_namespace] = deepcopy(card[untouched_namespace])
    state = normalized[namespace]
    payload = change.get("current")
    if not isinstance(payload, Mapping):
        payload = {
            key: value
            for key, value in change.items()
            if key not in {"fact", "recent_changes"}
        }
    state["current"].update(deepcopy(dict(payload)))
    state["recent_changes"].append(
        {"chapter": int(chapter), "fact": str(change.get("fact", ""))}
    )
    normalized[namespace] = state
    return normalized
