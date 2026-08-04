from __future__ import annotations

from collections.abc import Iterable, Mapping
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
_GAME_SCENE_MARKERS = ("游戏", "副本", "任务", "背包", "等级")
_REALITY_SCENE_MARKERS = ("现实", "出租屋", "工作", "房租", "银行")
_PRIVATE_KEY_MARKERS = ("secret", "private", "hidden_matters", "continuity_locks")
_SCENE_PRIVATE_KEYS = {
    "game_panel",
    "continuity_locks",
    "current_state",
    "real_state",
    "game_state",
}


def infer_scene_kind(scene_card: Mapping[str, Any], *, is_game_story: bool) -> str:
    """Infer the visible story line for one scene card."""

    card = scene_card if isinstance(scene_card, Mapping) else {}
    for key in ("line", "scene_line"):
        explicit = str(card.get(key) or "").strip().lower()
        if explicit in {"game", "游戏", "game_state"}:
            return "game" if is_game_story else "reality"
        if explicit in {"reality", "real", "现实", "real_state"}:
            return "reality"
        if explicit in {"transition", "mixed", "过渡", "切换"}:
            return "transition" if is_game_story else "reality"

    if not is_game_story:
        return "reality"

    def collect_text(value: Any) -> list[str]:
        if isinstance(value, Mapping):
            return [piece for item in value.values() for piece in collect_text(item)]
        if isinstance(value, (list, tuple, set)):
            return [piece for item in value for piece in collect_text(item)]
        if value in (None, ""):
            return []
        return [str(value)]

    text = " ".join(
        piece
        for key, value in card.items()
        if key not in {"line", "scene_line", "real_state", "game_state", "game_panel"}
        for piece in collect_text(value)
    )
    has_game = any(marker in text for marker in _GAME_SCENE_MARKERS)
    has_reality = any(marker in text for marker in _REALITY_SCENE_MARKERS)
    if has_game and has_reality:
        return "transition"
    if has_game:
        return "game"
    if has_reality:
        return "reality"
    return "transition" if is_game_story else "reality"


def scene_kind_for_cards(scene_cards: Any, *, is_game_story: bool) -> str:
    """Choose one writer-visible line for a chapter's scene cards."""

    kinds = {
        infer_scene_kind(card, is_game_story=is_game_story)
        for card in scene_cards
        if isinstance(card, Mapping)
    }
    if "transition" in kinds or {"game", "reality"}.issubset(kinds):
        return "transition"
    if "game" in kinds:
        return "game"
    if "reality" in kinds:
        return "reality"
    return "transition" if is_game_story else "reality"


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


def _scrub_private(value: Any) -> Any:
    if isinstance(value, Mapping):
        cleaned: dict[Any, Any] = {}
        for key, item in value.items():
            normalized_key = str(key).strip().lower()
            if any(marker in normalized_key for marker in _PRIVATE_KEY_MARKERS):
                continue
            cleaned[key] = _scrub_private(item)
        return cleaned
    if isinstance(value, list):
        return [_scrub_private(item) for item in value]
    return deepcopy(value)


def _normalize_state(value: Any, *, fallback_current: Mapping[str, Any] | None = None) -> dict[str, Any]:
    current = _current_from_state(value)
    if fallback_current:
        for key, item in fallback_current.items():
            current.setdefault(key, deepcopy(item))
    recent = value.get("recent_changes") if isinstance(value, Mapping) else None
    return {"current": current, "recent_changes": _recent_changes(recent)}


def _generic_state(value: Any) -> dict[str, Any]:
    if isinstance(value, str):
        summary = value.strip()
        return {
            "current": {"summary": summary} if summary else {},
            "recent_changes": [],
        }
    return _normalize_state(value)


def _merge_recent_changes(*groups: Any) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[tuple[int, str]] = set()
    for group in groups:
        for item in _recent_changes(group):
            key = (item["chapter"], item["fact"])
            if key in seen:
                continue
            seen.add(key)
            merged.append(item)
    return merged


def normalize_character_state(
    card: Mapping[str, Any],
    *,
    is_game_story: bool,
) -> dict[str, Any]:
    """Normalize mutable character state according to the project's genre."""

    if is_game_story:
        return normalize_dual_state(card, is_game_story=True)

    normalized = deepcopy(dict(card))
    explicit = _generic_state(normalized.get("current_state"))
    legacy = _generic_state(normalized.get("real_state"))

    # Earlier code copied static profile blocks into real_state. They describe
    # who the character is, not what changed in the current story moment.
    legacy_current = {
        key: value
        for key, value in legacy["current"].items()
        if key not in _REAL_FIELDS
    }
    current = deepcopy(legacy_current)
    current.update(deepcopy(explicit["current"]))
    recent_changes = _merge_recent_changes(
        explicit.get("recent_changes"),
        legacy.get("recent_changes"),
    )

    normalized.pop("real_state", None)
    normalized.pop("game_state", None)
    normalized.pop("game_panel", None)
    normalized["current_state"] = {
        "current": current,
        "recent_changes": recent_changes,
    }
    return normalized


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
    state = _scrub_private(normalized[name])
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


def _strip_scene_private_fields(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            key: _strip_scene_private_fields(item)
            for key, item in value.items()
            if str(key).strip().lower() not in _SCENE_PRIVATE_KEYS
        }
    if isinstance(value, list):
        return [_strip_scene_private_fields(item) for item in value]
    return deepcopy(value)


def project_character_for_scene(
    card: Mapping[str, Any],
    *,
    scene_kind: str,
    is_game_story: bool = True,
    allowed_reveals: Iterable[str] = (),
) -> dict[str, Any]:
    """Build one scene-safe writer card with a single projected state context."""

    from packages.story_core.character_profiles import project_character_for_writer

    projected = project_character_for_writer(dict(card), allowed_reveals=allowed_reveals)
    projected = _strip_scene_private_fields(projected)
    if is_game_story:
        projected["state_context"] = project_dual_state(card, scene_kind=scene_kind)
    else:
        normalized = normalize_character_state(card, is_game_story=False)
        projected["state_context"] = {
            "current_state": _scrub_private(normalized["current_state"]),
        }
    return projected


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
