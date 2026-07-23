from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any


ProgressReporter = Callable[[str | dict[str, Any]], None]

_current_progress: ContextVar[ProgressReporter | None] = ContextVar(
    "current_generation_progress",
    default=None,
)


def _should_report_progress(message: str | dict[str, Any]) -> bool:
    if isinstance(message, dict):
        cleaned_message = str(message.get("message", "")).strip()
    else:
        cleaned_message = str(message).strip()
    return bool(cleaned_message)


def report_generation_progress(message: str | dict[str, Any]) -> None:
    if not _should_report_progress(message):
        return
    reporter = _current_progress.get()
    if reporter is None:
        return
    try:
        reporter(message)
    except Exception:
        # Progress reporting is best-effort and must not break chapter generation.
        return


@contextmanager
def generation_progress(reporter: ProgressReporter) -> Iterator[None]:
    token = _current_progress.set(reporter)
    try:
        yield
    finally:
        _current_progress.reset(token)
