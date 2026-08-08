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
from .pipeline import (
    ModularChapterBundle,
    plan_director_artifact,
    run_fact_extractor,
    run_modular_pipeline,
    run_writer,
)

__all__ = [
    "DirectorArtifact",
    "EntityRequirement",
    "ModularChapterBundle",
    "SceneBeat",
    "WriterRequest",
    "WriterResult",
    "plan_director_artifact",
    "run_fact_extractor",
    "run_modular_pipeline",
    "run_writer",
]
