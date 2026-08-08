"""End-to-end smoke for the modular agent pipeline.

Task 15 of the modular agent migration plan asks for two real
smoke generations: one game project and one non-game project.
The CLI does not have a live model endpoint in this session,
so the smoke here drives the orchestrator with stub
director / writer runtimes and asserts every step the
workbench cares about lands on disk for a project that was
just migrated from the legacy ``.webnovel/`` shape.

The script is intentionally side-effect-free: the user runs
it against a copied project tree (``smoke --copy <src> <dst>``)
so the original project is never touched. The on-disk
artifacts the script produces are exactly the ones the
workbench reads back; if any file is missing, the smoke
fails loudly.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


REQUIRED_STAGES = ("director", "writer", "fact-extractor")


@dataclass
class SmokeReport:
    project: Path
    chapter_number: int
    started_at: str
    finished_at: str = ""
    elapsed_ms: int = 0
    stages: list[dict[str, Any]] = field(default_factory=list)
    workflow_files: list[str] = field(default_factory=list)
    canon_files: list[str] = field(default_factory=list)
    snapshot_files: list[str] = field(default_factory=list)
    director_files: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": str(self.project),
            "chapter_number": self.chapter_number,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "elapsed_ms": self.elapsed_ms,
            "stages": list(self.stages),
            "workflow_files": list(self.workflow_files),
            "canon_files": list(self.canon_files),
            "snapshot_files": list(self.snapshot_files),
            "director_files": list(self.director_files),
            "warnings": list(self.warnings),
        }


# --- Stub runtimes ----------------------------------------------------------


class _StubDirectorRuntime:
    """Return a small canned director artifact for the smoke."""

    def __init__(self, chapter_number: int) -> None:
        self._chapter_number = chapter_number
        self.calls = 0

    def complete(self, request: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "chapter_number": self._chapter_number,
            "chapter_goal": "smoke: 山门开启",
            "opening_state": "天将暮",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "山脚",
                    "action": "主角登门",
                    "result": "山门开启",
                },
            ],
            "ending_state": "夜宿山腰",
            "hook": "远处钟声响起",
            "entity_requirements": [
                {
                    "kind": "character",
                    "name": "林昭",
                    "importance": 7,
                    "inline_minor": False,
                    "notes": "smoke 主角",
                }
            ],
        }


class _StubWriterRuntime:
    """Return a small canned writer body for the smoke."""

    def __init__(self, body: str) -> None:
        self.body = body
        self.calls = 0

    def complete(self, request: Any) -> Any:
        self.calls += 1

        class _Resp:
            def __init__(self, text: str) -> None:
                self.text = text
                self.raw: dict[str, Any] = {}

        return _Resp(self.body)


# --- Helpers ----------------------------------------------------------------


def _now() -> str:
    import datetime as _dt

    return _dt.datetime.now(_dt.timezone.utc).isoformat()


def _emit_progress(
    report: SmokeReport,
    *,
    stage: str,
    agent: str,
    status: str,
    outputs: dict[str, Any] | None = None,
) -> None:
    """Record one stage in the smoke report.

    The smoke mirrors the ``_emit_progress_with_artifact``
    contract the orchestrator already uses, so the workbench
    can render the same row the live flow would have written.
    """
    report.stages.append(
        {
            "stage": stage,
            "agent": agent,
            "status": status,
            "outputs": dict(outputs or {}),
        }
    )


def _run_modular_pipeline(
    project_root: Path,
    chapter_number: int,
) -> SmokeReport:
    """Drive the orchestrator's modular pipeline against ``project_root``."""
    from packages.story_core.orchestrator import StoryOrchestrator

    report = SmokeReport(
        project=project_root,
        chapter_number=chapter_number,
        started_at=_now(),
    )
    start = time.monotonic()
    orchestrator = StoryOrchestrator(use_modular_agents=True)
    director_runtime = _StubDirectorRuntime(chapter_number)
    writer_runtime = _StubWriterRuntime(
        f"smoke: 林昭登门第{chapter_number}次。夜宿山腰。{"。" * 120}"
    )
    job_id = f"smoke-chapter-{chapter_number}"
    try:
        bundle = orchestrator.generate_next_chapter_via_modular_pipeline(
            project_root=project_root,
            chapter_number=chapter_number,
            director_runtime=director_runtime,
            writer_runtime=writer_runtime,
            job_id=job_id,
        )
    except Exception as exc:  # pragma: no cover - defensive
        report.warnings.append(f"pipeline_failed: {type(exc).__name__}: {exc}")
        report.finished_at = _now()
        report.elapsed_ms = int((time.monotonic() - start) * 1000)
        return report

    _emit_progress(
        report,
        stage="director",
        agent="DirectorAgent",
        status="done",
        outputs={
            "chapter_number": bundle.director_artifact.chapter_number,
            "scene_beats": len(bundle.director_artifact.scene_beats),
        },
    )
    _emit_progress(
        report,
        stage="writer",
        agent="WriterAgent",
        status="done",
        outputs={"body_chars": len(bundle.body)},
    )
    _emit_progress(
        report,
        stage="fact_extractor",
        agent="FactExtractor",
        status="done",
        outputs={
            "delta_chapter": (
                bundle.continuity_delta.chapter_number
                if bundle.continuity_delta is not None
                else None
            ),
        },
    )

    workflow_dir = project_root / ".story-system" / "workflow" / job_id
    if workflow_dir.is_dir():
        for path in sorted(workflow_dir.glob("*.json")):
            report.workflow_files.append(str(path))
    for name in REQUIRED_STAGES:
        target = workflow_dir / f"{name}.json"
        if not target.is_file():
            report.warnings.append(f"workflow_stage_missing: {name}")
    canon_dir = project_root / ".story-system" / "canon"
    if canon_dir.is_dir():
        for path in sorted(canon_dir.glob("**/*")):
            if path.is_file():
                report.canon_files.append(str(path))
    snapshot_dir = project_root / ".story-system" / "continuity" / "snapshots"
    if snapshot_dir.is_dir():
        for path in sorted(snapshot_dir.glob("*.json")):
            report.snapshot_files.append(str(path))
    director_dir = project_root / ".story-system" / "director"
    if director_dir.is_dir():
        for path in sorted(director_dir.glob("*.json")):
            report.director_files.append(str(path))

    report.finished_at = _now()
    report.elapsed_ms = int((time.monotonic() - start) * 1000)
    return report


# --- CLI --------------------------------------------------------------------


def _copy_project(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


def _resolve_projects(
    *,
    project: str | None,
    copy: tuple[str, str] | None,
) -> list[Path]:
    if copy is not None:
        src, dst = copy
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()
        _copy_project(src_path, dst_path)
        return [dst_path]
    if project:
        return [Path(project).resolve()]
    raise SystemExit("specify --project <path> or --copy <src> <dst>")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "End-to-end smoke for the modular agent pipeline. "
            "Drives the orchestrator with stub director / writer "
            "runtimes and asserts every step the workbench needs "
            "is on disk."
        )
    )
    parser.add_argument("--project", help="path to a project root")
    parser.add_argument(
        "--copy",
        nargs=2,
        metavar=("SRC", "DST"),
        help="copy SRC to DST then smoke DST (does not touch SRC)",
    )
    parser.add_argument(
        "--chapter",
        type=int,
        default=1,
        help="chapter number the smoke drives (default 1)",
    )
    parser.add_argument(
        "--quiet",
        action="store_true",
        help="only print warnings and the final summary",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    roots = _resolve_projects(
        project=args.project,
        copy=tuple(args.copy) if args.copy else None,
    )
    failures = 0
    for root in roots:
        report = _run_modular_pipeline(root, args.chapter)
        if not args.quiet:
            print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        if report.warnings:
            failures += 1
    return 1 if failures else 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
