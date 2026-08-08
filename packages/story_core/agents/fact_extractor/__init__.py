"""Public surface of the FactExtractor agent.

The extractor is the only producer of ``ContinuityDelta`` records:
deterministic regex passes for explicit numeric state and named
ownership, and a model-backed path for ambiguous relationships,
knowledge changes, and foreshadowing. The model runtime is a
swappable boundary so a CLI / HTTP swap stays invisible to the
extractor itself.
"""

from .agent import (
    FactExtractor,
    FactExtractorContext,
    FactExtractorRuntime,
    build_default_extractor,
)

__all__ = [
    "FactExtractor",
    "FactExtractorContext",
    "FactExtractorRuntime",
    "build_default_extractor",
]
