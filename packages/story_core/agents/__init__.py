"""Modular agent contracts and runtimes.

The agents in this package replace the legacy single-string
director prompt and ad-hoc writer module assembly. Each agent has
exactly one typed input contract and one typed output contract;
the orchestrator never reaches into the agent's internals.
"""

from .contracts import (
    DirectorArtifact,
    EntityRequirement,
    SceneBeat,
    WriterRequest,
    WriterResult,
)

__all__ = [
    "DirectorArtifact",
    "EntityRequirement",
    "SceneBeat",
    "WriterRequest",
    "WriterResult",
]
