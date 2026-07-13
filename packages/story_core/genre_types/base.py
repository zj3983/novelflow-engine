from __future__ import annotations

from dataclasses import dataclass


RULEBOOK_FIELDS = (
    "progression_rules",
    "economy_rules",
    "quest_rules",
    "faction_rules",
    "panel_rules",
    "chapter_formula",
    "forbidden_breaks",
)


@dataclass(frozen=True)
class GenrePlugin:
    plugin_id: str
    name: str
    keywords: tuple[str, ...]
    core_promises: tuple[str, ...]
    ledger_fields: tuple[str, ...]
    rulebook: dict[str, tuple[str, ...]]
    quality_checks: tuple[str, ...]
