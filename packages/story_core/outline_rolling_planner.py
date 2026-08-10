"""Rolling-outline planner — the orchestrator-facing entry point.

The plan rule (Round 8, 滚动细纲补全): when a new
chapter is about to be written, the system must guarantee
a usable outline exists for the target chapter AND for the
next ``window`` chapters ahead. A missing outline triggers
a *rolling fill* of the next ``window`` chapters.

The planner composes the pure :func:`plan_rolling_window`
planner and the side-effectful
:class:`RollingOutlineStore` so the orchestrator only has
to call :meth:`RollingOutlinePlanner.ensure_rolling_outline`
and get back a single :class:`RollingOutlineStatus`
envelope. The planner does not call any model directly;
it delegates the actual chapter generation to a
``chapter_generator`` callable that the test or
production caller injects. Production wires a real LLM
call; tests inject a deterministic stub.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable

from .outline_rolling import (
    RollingPlanError,
    RollingValidationError,
    plan_rolling_window,
)
from .outline_rolling_store import (
    RollingOutlineStore,
    RollingOutlineStoreError,
)


class RollingOutlineFailed(RuntimeError):
    """Raised when the rolling fill cannot write a valid
    batch to disk.

    The exception message names the failing reason
    (validation error, generator exception, store I/O
    failure) so the operator can fix the right thing on
    the next attempt.
    """


@dataclass
class RollingOutlineStatus:
    """The envelope the planner returns.

    ``kind`` is one of:

    * ``"present"`` — the target chapter already has an
      outline; ``chapter_numbers`` is empty.
    * ``"filled"`` — the rolling fill wrote ``chapter_numbers``
      to disk.
    * ``"no_op"`` — the planner determined the rolling
      window is already full (alias of ``present`` for
      backwards compatibility).

    ``volume_range`` and ``target_chapter`` are echoed
    back so the caller can render a precise UI without
    re-reading the project's config.
    """

    kind: str
    target_chapter: int
    volume_range: tuple[int, int]
    chapter_numbers: list[int] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "target_chapter": self.target_chapter,
            "volume_range": list(self.volume_range),
            "chapter_numbers": list(self.chapter_numbers),
        }


def _read_existing_outline_chapters(
    project_root: Path,
) -> list[dict[str, Any]]:
    """Return the existing chapter rows from BOTH the
    legacy ``.webnovel/outline.json`` and the rolling
    ``.story-system/outline-generation/rolling_outline.json``.

    The planner only needs the chapter numbers + source
    markers to compute the gap; the store handles the
    actual read-back at write time. Reading both files
    means a project whose outline was split across the
    legacy migration path and the rolling-fill path
    still reports a single coherent filled set.
    """
    chapters: list[dict[str, Any]] = []
    for relative in (
        ".webnovel/outline.json",
        ".story-system/outline-generation/rolling_outline.json",
    ):
        target = project_root / relative
        if not target.is_file():
            continue
        try:
            payload = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        rows = payload.get("chapters")
        if not isinstance(rows, list):
            continue
        for row in rows:
            if isinstance(row, dict):
                chapters.append(row)
    return chapters


def _build_payloads_from_generator(
    *,
    chapter_numbers: list[int],
    generator: Callable[[int], dict[str, Any]],
) -> list[dict[str, Any]]:
    """Invoke ``generator`` once per chapter number and
    return the payloads in order.

    The generator is responsible for producing a payload
    whose ``chapter_number`` matches the requested
    number; the planner validates the claim through
    :func:`validate_rolling_batch`. A generator
    exception is re-raised as
    :class:`RollingOutlineFailed` so the caller sees a
    single error class for all generation failures.
    """
    payloads: list[dict[str, Any]] = []
    for number in chapter_numbers:
        try:
            payload = generator(number)
        except Exception as exc:  # noqa: BLE001
            raise RollingOutlineFailed(
                f"rolling_outline_generator_failed: "
                f"chapter={number} {type(exc).__name__}: {exc}"
            ) from exc
        if not isinstance(payload, dict):
            raise RollingOutlineFailed(
                f"rolling_outline_generator_returned_non_dict: "
                f"chapter={number}"
            )
        payloads.append(payload)
    return payloads


@dataclass
class RollingOutlinePlanner:
    """The high-level rolling-fill entry point.

    The planner is intentionally thin: the plan logic
    lives in :mod:`packages.story_core.outline_rolling`,
    the storage protocol in
    :mod:`packages.story_core.outline_rolling_store`,
    and the model call lives in the injected
    ``chapter_generator``. Keeping these layers separate
    means the planner is easy to test (a stub generator
    is enough) and easy to evolve (a future real-model
    version swaps the generator without touching the
    rest).
    """

    generator: Callable[[int], dict[str, Any]]

    def ensure_rolling_outline(
        self,
        *,
        project_root: Path | str,
        target_chapter: int,
        volume_range: tuple[int, int],
        window: int = 5,
    ) -> RollingOutlineStatus:
        """Ensure the rolling window starting at
        ``target_chapter`` is fully outlined. Returns a
        :class:`RollingOutlineStatus` describing what the
        planner did.

        Raises
        ------
        RollingPlanError
            When the inputs (target, volume range, window)
            are invalid.
        RollingOutlineFailed
            When the generator returns an invalid payload
            or the on-disk write fails. The on-disk
            outline is not modified on failure.
        """
        root = Path(project_root)
        existing_chapters = _read_existing_outline_chapters(root)

        gap = plan_rolling_window(
            target_chapter=target_chapter,
            existing_chapters=existing_chapters,
            volume_range=volume_range,
            window=window,
        )
        if not gap:
            return RollingOutlineStatus(
                kind="present",
                target_chapter=target_chapter,
                volume_range=volume_range,
                chapter_numbers=[],
            )

        # Build the batch from the generator. The
        # ``RollingOutlineStore`` validates the batch
        # before writing so a single bad chapter aborts
        # the whole write.
        payloads = _build_payloads_from_generator(
            chapter_numbers=gap,
            generator=self.generator,
        )

        store = RollingOutlineStore(root)
        try:
            written = store.apply_rolling_batch(
                chapters=payloads,
                expected_chapter_numbers=gap,
                volume_range=volume_range,
            )
        except RollingValidationError as exc:
            raise RollingOutlineFailed(
                f"rolling_outline_validation_failed: {exc}"
            ) from exc
        except RollingOutlineStoreError as exc:
            raise RollingOutlineFailed(
                f"rolling_outline_write_failed: {exc}"
            ) from exc
        return RollingOutlineStatus(
            kind="filled",
            target_chapter=target_chapter,
            volume_range=volume_range,
            chapter_numbers=written,
        )


__all__ = [
    "RollingOutlineFailed",
    "RollingOutlinePlanner",
    "RollingOutlineStatus",
]
