"""Build a compact, deterministic context package without model calls."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any, Iterable, Mapping

from .context_package import ContextPackage


_SOURCE_NAMES = {
    "outline": "project.outline",
    "adjacent_chapters": "chapters.adjacent",
    "characters": "project.characters",
    "relationships": "project.relationships",
    "foreshadowings": "project.foreshadowings",
    "world": "project.world",
    "genre": "project.genre",
    "long_term_memory": "memory.long_term",
    "author_request": "task.author_request",
}


def build_context_package(
    source: Mapping[str, Any],
    *,
    requested_sections: Iterable[str] | None = None,
    chapter_number: int | None = None,
) -> ContextPackage:
    requested = list(requested_sections or source.keys())
    sections: dict[str, Any] = {}
    sources: dict[str, str] = {}
    for key in requested:
        if key not in source:
            continue
        sections[key] = deepcopy(source[key])
        sources[key] = _SOURCE_NAMES.get(key, f"project.{key}")

    excluded = [key for key in source.keys() if key not in sections]
    fingerprint = json.dumps(
        {"chapter_number": chapter_number, "sections": sections},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    snapshot_id = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
    return ContextPackage(
        chapter_number=chapter_number,
        sections=sections,
        sources=sources,
        excluded_sections=excluded,
        snapshot_id=snapshot_id,
    )
