"""Immutable-ish data returned by the context coordination step."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class ContextPackage:
    chapter_number: int | None
    sections: dict[str, Any]
    sources: dict[str, str] = field(default_factory=dict)
    excluded_sections: list[str] = field(default_factory=list)
    snapshot_id: str = ""
