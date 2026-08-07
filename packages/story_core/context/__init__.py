"""Project context primitives for the modular agent migration.

This package owns the read-trace and artifact-reference types that
every role-specific context builder records against. Director and
writer contexts (built elsewhere) reuse the same ``ContextTrace``
and ``ArtifactRead`` models so the workbench can show exactly
what each stage consumed.
"""

from .contracts import ArtifactRead, ContextTrace

__all__ = ["ArtifactRead", "ContextTrace"]
