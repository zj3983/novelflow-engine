from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

from packages.story_core.models import ForeshadowingState


UNRESOLVED_STATUSES = frozenset({"open", "reinforced"})


def normalize_foreshadowing_text(text: str) -> str:
    """Return the deterministic key used for exact ledger matching."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def reconcile_foreshadowing(
    ledger: Sequence[ForeshadowingState],
    *,
    chapter_number: int,
    unresolved_threads: Iterable[str],
    resolved_threads: Iterable[str] = (),
) -> list[ForeshadowingState]:
    """Merge explicit chapter thread evidence into the canonical ledger."""

    reconciled = [entry.model_copy(deep=True) for entry in ledger]
    by_key = {
        normalize_foreshadowing_text(entry.text): entry
        for entry in reconciled
        if normalize_foreshadowing_text(entry.text)
    }

    seen_unresolved: set[str] = set()
    for raw_text in unresolved_threads:
        text = " ".join(raw_text.split())
        key = normalize_foreshadowing_text(text)
        if not key or key in seen_unresolved:
            continue
        seen_unresolved.add(key)

        existing = by_key.get(key)
        if existing is None:
            existing = ForeshadowingState(
                text=text,
                first_chapter=chapter_number,
                last_touched_chapter=chapter_number,
                status="open",
            )
            reconciled.append(existing)
            by_key[key] = existing
        elif existing.status in UNRESOLVED_STATUSES:
            existing.last_touched_chapter = chapter_number
            if existing.status == "open":
                existing.status = "reinforced"

    seen_resolved: set[str] = set()
    for raw_text in resolved_threads:
        key = normalize_foreshadowing_text(raw_text)
        if not key or key in seen_resolved:
            continue
        seen_resolved.add(key)

        existing = by_key.get(key)
        if existing is not None:
            existing.status = "resolved"
            existing.last_touched_chapter = chapter_number
            existing.resolved_chapter = chapter_number

    return reconciled


def select_unresolved_foreshadowing(
    ledger: Sequence[ForeshadowingState],
    *,
    limit: int = 8,
) -> list[ForeshadowingState]:
    """Select a bounded unresolved view without exposing the full ledger."""

    if limit <= 0:
        return []
    unresolved = (entry for entry in ledger if entry.status in UNRESOLVED_STATUSES)
    ranked = sorted(
        unresolved,
        key=lambda entry: (
            -entry.last_touched_chapter,
            -entry.first_chapter,
            normalize_foreshadowing_text(entry.text),
        ),
    )
    return ranked[:limit]


select_open_foreshadowing = select_unresolved_foreshadowing
