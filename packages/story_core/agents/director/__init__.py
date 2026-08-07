"""Modular director agent.

The director agent is the only path that turns a director
context into a ``DirectorArtifact``. The writer never sees
the raw prompt that produced the artifact; the orchestrator
never reaches into the agent's internals.
"""

from .agent import DirectorAgent
from .prompt import build_director_prompt, parse_director_response
from .runtime import DirectorRuntime, GatewayDirectorRuntime

__all__ = [
    "DirectorAgent",
    "DirectorRuntime",
    "GatewayDirectorRuntime",
    "build_director_prompt",
    "parse_director_response",
]
