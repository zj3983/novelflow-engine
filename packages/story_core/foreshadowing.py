from __future__ import annotations

import unicodedata
from collections.abc import Iterable, Sequence

from packages.story_core.models import ForeshadowingState


UNRESOLVED_STATUSES = frozenset({"open", "reinforced"})
TERMINAL_STATUSES = frozenset({"resolved", "expired"})
_STATUS_PRIORITY = {"open": 0, "reinforced": 1, "resolved": 2, "expired": 3}


def normalize_foreshadowing_text(text: str) -> str:
    """Return the deterministic key used for exact ledger matching."""

    normalized = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(normalized.split())


def _canonicalize_ledger(
    ledger: Sequence[ForeshadowingState],
) -> tuple[list[ForeshadowingState], dict[str, ForeshadowingState]]:
    grouped: dict[str, list[ForeshadowingState]] = {}
    for entry in ledger:
        key = normalize_foreshadowing_text(entry.text)
        grouped.setdefault(key, []).append(entry)

    canonical: list[ForeshadowingState] = []
    for key, entries in grouped.items():
        text_source = min(
            entries,
            key=lambda entry: (
                entry.first_chapter,
                " ".join(entry.text.split()).casefold(),
                entry.text,
            ),
        )
        payoff_candidates = [entry for entry in entries if entry.payoff_plan.strip()]
        payoff_plan = ""
        if payoff_candidates:
            payoff_plan = max(
                payoff_candidates,
                key=lambda entry: (
                    entry.last_touched_chapter,
                    -entry.first_chapter,
                    entry.payoff_plan,
                ),
            ).payoff_plan
        resolved_chapters = [
            entry.resolved_chapter
            for entry in entries
            if entry.resolved_chapter is not None
        ]
        canonical.append(
            ForeshadowingState(
                text=" ".join(text_source.text.split()),
                first_chapter=min(entry.first_chapter for entry in entries),
                last_touched_chapter=max(entry.last_touched_chapter for entry in entries),
                status=max(entries, key=lambda entry: _STATUS_PRIORITY[entry.status]).status,
                payoff_plan=payoff_plan,
                resolved_chapter=max(resolved_chapters, default=None),
            )
        )

    canonical.sort(
        key=lambda entry: (
            entry.first_chapter,
            normalize_foreshadowing_text(entry.text),
        )
    )
    return canonical, {
        normalize_foreshadowing_text(entry.text): entry for entry in canonical
    }


def reconcile_foreshadowing(
    ledger: Sequence[ForeshadowingState],
    *,
    chapter_number: int,
    unresolved_threads: Iterable[str],
    resolved_threads: Iterable[str] = (),
) -> list[ForeshadowingState]:
    """Merge explicit chapter thread evidence into the canonical ledger."""

    reconciled, by_key = _canonicalize_ledger(ledger)

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
        elif (
            existing.status in UNRESOLVED_STATUSES
            and chapter_number > existing.last_touched_chapter
        ):
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
        if (
            existing is not None
            and existing.status not in TERMINAL_STATUSES
            and chapter_number >= existing.last_touched_chapter
        ):
            existing.status = "resolved"
            existing.last_touched_chapter = chapter_number
            existing.resolved_chapter = max(
                chapter_number,
                existing.resolved_chapter or chapter_number,
            )

    reconciled.sort(
        key=lambda entry: (
            entry.first_chapter,
            normalize_foreshadowing_text(entry.text),
        )
    )
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
