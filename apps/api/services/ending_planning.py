"""Persistent progress for the one-click ending planner (no prose generation)."""
from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any, Callable
from uuid import uuid4

from packages.story_core.ending_planning import plan_ending, _context_version
from packages.story_core.persistence.project_locking import project_update_lock
from packages.story_core.persistence.snapshot_store import SnapshotStore


class EndingPlanningJobs:
    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="ending-plan")
        self._runs: dict[str, Future] = {}
        self._writer = SnapshotStore()

    @staticmethod
    def _path(store: Any):
        return store.story_system_dir / "ending-plans" / "latest-job.json"

    def current(self, store: Any) -> dict | None:
        with project_update_lock(store.root):
            job = self._writer.read_json(self._path(store))
            if job and job["status"] in {"queued", "running"} and job["job_id"] not in self._runs:
                job.update(status="failed", error="ending_planning_interrupted",
                           progress="规划被服务重启中断，原大纲保留，可以重新规划。")
                self._writer.write_json_atomic(self._path(store), job)
            return job

    def start(self, store: Any, generator: Any, *, draft: dict | None, guidance: str,
              assert_mutation_allowed: Callable[[], None]) -> dict:
        with project_update_lock(store.root):
            existing = self.current(store)
            if existing and existing["status"] in {"queued", "running"}:
                return existing
            assert_mutation_allowed()
            version = _context_version(store)
            job = {"job_id": uuid4().hex, "status": "queued", "progress": "准备读取作品并规划结尾。",
                   "error": "", "result": None, "created_at": datetime.now(timezone.utc).isoformat()}
            self._writer.write_json_atomic(self._path(store), job)
            try:
                self._runs[job["job_id"]] = self._executor.submit(
                    self._run, store, generator, dict(job), draft, guidance, assert_mutation_allowed, version)
            except Exception:
                job.update(status="failed", error="ending_planning_start_failed")
                self._writer.write_json_atomic(self._path(store), job)
                raise
            return job

    def _run(self, store, generator, job, draft, guidance, assert_mutation_allowed, version):
        def progress(message: str):
            with project_update_lock(store.root):
                job.update(status="running", progress=message)
                self._writer.write_json_atomic(self._path(store), job)

        try:
            result = plan_ending(store, generator, draft=draft, guidance=guidance,
                                 progress=progress, assert_mutation_allowed=assert_mutation_allowed,
                                 expected_version=version)
            job.update(status="completed", progress="结尾规划已保存，可以查看和编辑逐章细纲。",
                       result={key: result[key] for key in ("base_chapter", "chapter_range", "chapter_count")})
        except Exception as exc:
            error = str(getattr(exc, "detail", None) or exc)[:800]
            if not error.startswith(("ending_planning_", "invalid_ending_", "project_generation_in_progress", "runtime_")):
                error = "ending_planning_generation_failed:" + error
            job.update(status="failed", error=error,
                       progress="结尾规划未完成，原大纲保留。")
        with project_update_lock(store.root):
            self._writer.write_json_atomic(self._path(store), job)


ending_planning_jobs = EndingPlanningJobs()
