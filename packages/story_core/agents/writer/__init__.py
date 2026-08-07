"""Modular writer agent.

The writer agent is the only path that turns a director-approved
chapter plan into prose. It talks to a ``WriterRuntime`` so the
backing transport (Codex CLI, Gemini CLI, HTTP API) stays a
configuration concern, not an implementation detail.
"""

from .agent import WriterAgent
from .prompt import build_writer_prompt
from .runtime import GatewayWriterRuntime, WriterRuntime

__all__ = [
    "WriterAgent",
    "WriterRuntime",
    "GatewayWriterRuntime",
    "build_writer_prompt",
]
