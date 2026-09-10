"""Adapters for legacy project layout.

The modular agent migration introduced a new canonical project
layout under ``.story-system/`` (outline, volume, characters/*.json,
entities/*.json, world-rules.json, craft-modules/*.json). Real
projects on disk still use the long-standing ``.webnovel/`` shape
(outline.json, state.json, project.json) — the shape that
``FileProjectStore`` has been writing since day one.

The agents must work on real projects, so the context readers fall
back to the legacy paths when the canonical artifact is missing.
This module owns the translation: it reads the legacy shape and
emits the shape the new agents expect. The work is intentionally
read-only — no canonical files are written by the adapter so the
two layouts can co-exist during the migration window.

The translation rules:

* ``.webnovel/outline.json`` → canonical ``outline.json`` view
  (chapters normalized to ``{number, summary, ...}``).
* ``.webnovel/state.json`` → canonical ``state.json`` view and
  volume / chapter-summaries proxies (the director context reads
  the volume range; the writer context reads previous-chapter
  summaries).
* ``.webnovel/project.json`` → canonical ``project.json`` view
  (character_profiles become the active character list).
* ``.story-system/chapters/NNNN.json`` and
  ``.story-system/continuity/snapshots/NNNN.json`` are the only
  new artifacts the agents rely on. They are written by the
  store during the candidate flow, so real projects will
  accumulate them over time.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from packages.story_core.inventory_normalization import (
    normalize_inventory_item_name as _normalize_inventory_item_name,
    normalize_inventory_mapping,
)


_LEGACY_OUTLINE_PATH = ("..", ".webnovel", "outline.json")
_LEGACY_STATE_PATH = ("..", ".webnovel", "state.json")
_LEGACY_PROJECT_PATH = ("..", ".webnovel", "project.json")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return None


def _normalize_character_inventory(card: dict[str, Any]) -> dict[str, Any]:
    """Normalize inventory keys in both legacy state namespaces."""
    for namespace in ("game_state", "game_panel"):
        container = card.get(namespace)
        if not isinstance(container, dict):
            continue
        target = (
            container.get("current")
            if namespace == "game_state"
            else container
        )
        if not isinstance(target, dict) or not isinstance(target.get("inventory"), dict):
            continue
        target["inventory"] = normalize_inventory_mapping(target["inventory"])
    return card


def _system_path(system_root: Path, *parts: str) -> Path:
    # ``system_root / ".."`` is not safe when ``system_root`` has not
    # been created yet: POSIX path lookup must traverse the missing
    # directory before it can resolve ``..``.  Resolve the parent
    # directly so the legacy fallback works on both POSIX and Windows.
    if parts and parts[0] == "..":
        return system_root.parent.joinpath(*parts[1:])
    return system_root.joinpath(*parts)


def legacy_outline_view(system_root: Path) -> dict[str, Any] | None:
    """Return a canonical outline view synthesised from ``.webnovel/outline.json``.

    Real projects have ``chapters: [{chapter_number, title, goal, ...}]``.
    The director context expects ``chapters: [{number, summary, ...}]``.
    We translate the key and compose ``summary`` from the available
    fields so the director sees a usable entry for every chapter.
    """
    legacy_path = _system_path(system_root, *_LEGACY_OUTLINE_PATH)
    if not legacy_path.is_file():
        return None
    raw = _read_json(legacy_path)
    if not isinstance(raw, dict):
        return None
    chapters: list[dict[str, Any]] = []
    for entry in raw.get("chapters") or []:
        if not isinstance(entry, dict):
            continue
        number = entry.get("chapter_number")
        if not isinstance(number, int):
            continue
        title = str(entry.get("title") or "").strip()
        goal = str(entry.get("goal") or "").strip()
        obstacle = str(entry.get("obstacle") or "").strip()
        action = str(entry.get("action") or "").strip()
        # ``summary`` is what the director context keys on. The
        # legacy project does not carry an explicit summary, so
        # compose one from the available fields.
        summary = " · ".join(part for part in (title, goal, obstacle, action) if part)
        chapters.append(
            {
                "number": number,
                "summary": summary,
                "title": title,
                "goal": goal,
                "obstacle": obstacle,
                "action": action,
            }
        )
    return {
        "schema_version": raw.get("schema_version") or "project-outline/v1",
        "chapters": chapters,
        "arcs": raw.get("arcs") or [],
        "overall": raw.get("overall") or {},
    }


def legacy_state_view(system_root: Path) -> dict[str, Any] | None:
    """Return a canonical state view synthesised from ``.webnovel/state.json``.

    The agents need ``current_chapter`` and a chapter_summaries list.
    The legacy state file is the single source of truth for both.
    """
    legacy_path = _system_path(system_root, *_LEGACY_STATE_PATH)
    if not legacy_path.is_file():
        return None
    raw = _read_json(legacy_path)
    if not isinstance(raw, dict):
        return None
    return dict(raw)


def legacy_project_view(system_root: Path) -> dict[str, Any] | None:
    """Return a canonical project view synthesised from ``.webnovel/project.json``.

    The agents read ``character_profiles`` to find the active roster
    and ``enabled_skill_ids`` to pick craft modules.
    """
    legacy_path = _system_path(system_root, *_LEGACY_PROJECT_PATH)
    if not legacy_path.is_file():
        return None
    raw = _read_json(legacy_path)
    if not isinstance(raw, dict):
        return None
    return dict(raw)


def legacy_volume_view(
    system_root: Path,
    chapter_number: int,
) -> dict[str, Any] | None:
    """Derive a minimal volume envelope from the legacy outline arcs.

    The director context expects a ``volume.json`` with a
    ``chapter_range`` so it can show nearby chapters. The legacy
    outline carries arcs with ``start_chapter`` and ``end_chapter``;
    we pick the arc that contains the target chapter.
    """
    outline = legacy_outline_view(system_root)
    if not outline:
        return None
    for arc in outline.get("arcs") or []:
        if not isinstance(arc, dict):
            continue
        start = arc.get("start_chapter")
        end = arc.get("end_chapter")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start <= chapter_number <= end:
            return {
                "schema_version": "volume/v1",
                "id": str(arc.get("id") or ""),
                "title": str(arc.get("title") or ""),
                "chapter_range": [start, end],
            }
    return None


def legacy_active_characters(system_root: Path) -> list[dict[str, Any]]:
    """Return the active character list, preferring the new
    ``characters/`` directory but falling back to legacy paths.

    The director / writer contexts need a list of character dicts
    shaped like ``{name, role, lifecycle, ...}``. The legacy
    ``state.json#characters`` is the same data; we annotate it
    with ``lifecycle='active'`` so the contexts' filter passes
    every legacy character through.
    """
    canonical = _system_path(system_root, "characters")
    if canonical.is_dir():
        items: list[dict[str, Any]] = []
        for path in sorted(canonical.glob("*.json")):
            try:
                card = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(card, dict):
                items.append(_normalize_character_inventory(card))
        if items:
            return items
    state = legacy_state_view(system_root)
    if state:
        chars = list(state.get("characters") or [])
        for card in chars:
            if isinstance(card, dict):
                _normalize_character_inventory(card)
                card.setdefault("lifecycle", "active")
        return chars
    project = legacy_project_view(system_root)
    if project:
        chars = list(project.get("character_profiles") or [])
        for card in chars:
            if isinstance(card, dict):
                _normalize_character_inventory(card)
                card.setdefault("lifecycle", "active")
        return chars
    return []


def legacy_previous_chapter(
    system_root: Path,
    chapter_number: int,
) -> dict[str, Any] | None:
    """Return the previous-chapter summary in the shape the writer
    context expects (``{tail, summary, continuity_ledger}``).

    Reads the new ``chapters/NNNN.json`` first; falls back to the
    legacy ``state.json#chapter_summaries`` list.
    """
    if chapter_number <= 1:
        return None
    canonical = _system_path(system_root, "chapters", f"{chapter_number - 1:04d}.json")
    if canonical.is_file():
        raw = _read_json(canonical)
        if isinstance(raw, dict):
            return raw
    state = legacy_state_view(system_root)
    if not state:
        return None
    summaries = list(state.get("chapter_summaries") or [])
    target = None
    for entry in summaries:
        if not isinstance(entry, dict):
            continue
        if entry.get("chapter_number") == chapter_number - 1:
            target = entry
            break
    if target is None and summaries:
        # Fall back to the most recent summary.
        target = summaries[-1]
    if not isinstance(target, dict):
        return None
    return {
        "chapter_number": target.get("chapter_number"),
        "chapter_title": target.get("chapter_title"),
        "summary": str(target.get("summary") or ""),
        "tail": str(target.get("next_focus") or target.get("summary") or ""),
        "facts": list(target.get("facts") or []),
        "continuity_ledger": [],
    }


def legacy_enabled_skill_ids(system_root: Path) -> list[str]:
    """Return the project's enabled skill ids from the legacy
    ``project.json``.
    """
    project = legacy_project_view(system_root)
    if not project:
        return []
    return [str(item) for item in (project.get("enabled_skill_ids") or [])]


__all__ = [
    "legacy_active_characters",
    "legacy_enabled_skill_ids",
    "legacy_outline_view",
    "legacy_previous_chapter",
    "legacy_project_view",
    "legacy_state_view",
    "legacy_volume_view",
]
