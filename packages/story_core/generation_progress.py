from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar


ProgressReporter = Callable[[str], None]

_current_progress: ContextVar[ProgressReporter | None] = ContextVar(
    "current_generation_progress",
    default=None,
)


def report_generation_progress(message: str) -> None:
    cleaned = str(message or "").strip()
    if not cleaned:
        return
    reporter = _current_progress.get()
    if reporter is None:
        return
    try:
        reporter(cleaned)
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
