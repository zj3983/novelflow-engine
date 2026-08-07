"""Pydantic contracts for project context reads and traces.

The director, writer, consistency, and fact-extractor agents all
record the artifacts they consumed into a ``ContextTrace`` so the
workbench and the migration script can later prove exactly which
files each chapter's pipeline touched. ``ArtifactRead`` is the
typed read event; ``ContextTrace`` is the per-agent accumulator.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class ArtifactRead(BaseModel):
    """One concrete read against a project artifact.

    ``sha256`` is the hash of the exact bytes that were read; the
    same value must reappear in the candidate's continuity trace so
    a stale-context rewrite can be detected. ``chars`` is the
    post-decode character count after the reader's UTF-8 (with BOM
    tolerance) normalization.
    """

    kind: str
    path: str
    sha256: str
    chars: int = 0


AgentKind = Literal[
    "director",
    "entity_designer",
    "writer",
    "consistency",
    "fact_extractor",
]


class ContextTrace(BaseModel):
    """Per-agent accumulator of artifact reads and selections.

    The trace is built up during context assembly; once the agent
    runs, the trace is attached to the candidate draft so later
    stages (and the workbench) can inspect it without re-deriving
    anything.
    """

    schema_version: str = "context-trace/v1"
    agent: AgentKind
    chapter_number: int
    reads: list[ArtifactRead] = Field(default_factory=list)
    selected_entity_ids: list[str] = Field(default_factory=list)
    selected_module_ids: list[str] = Field(default_factory=list)

    def add(self, read: ArtifactRead) -> None:
        self.reads.append(read)


__all__ = ["ArtifactRead", "ContextTrace", "AgentKind"]
