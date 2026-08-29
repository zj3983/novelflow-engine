from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
import re
from threading import RLock
from typing import Any
from uuid import uuid4


ALLOWED_CONTINUOUS_COUNTS = frozenset({2, 5, 10, 20})
ACTIVE_STATUSES = frozenset({"queued", "running", "stopping"})
TERMINAL_STATUSES = frozenset({"completed", "stopped", "failed"})
SAFE_RECOVERY_PHASES = frozenset({"queued", "between_chapters"})
_JOB_FILE_LOCK = RLock()
_MIN_CHAPTER_CHARS = 3800
_MAX_CHAPTER_CHARS = 5700
_MIN_AUTOMATIC_ACCEPT_RATIO = 0.90
_MAX_AUTOMATIC_ACCEPT_RATIO = 1.25
_MAX_CATASTROPHIC_RETRIES = 2


def _length_error_body_chars(error: str) -> int | None:
    for pattern in (
        r"body_chars\s+(\d+)",
        r"当前约\s*(\d+)\s*字",
        r"正文约\s*(\d+)\s*字",
    ):
        match = re.search(pattern, error)
        if match:
            return int(match.group(1))
    return None


def _is_catastrophic_length_error(error: str) -> bool:
    if not error.startswith("generate_length_failed:"):
        return False
    body_chars = _length_error_body_chars(error)
    if body_chars is None:
        return False
    return (
        body_chars < int(_MIN_CHAPTER_CHARS * _MIN_AUTOMATIC_ACCEPT_RATIO)
        or body_chars > int(_MAX_CHAPTER_CHARS * _MAX_AUTOMATIC_ACCEPT_RATIO)
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class ContinuousGenerationJobStore:
    def __init__(self, project_root: Path) -> None:
        self.project_root = Path(project_root)
        self.jobs_dir = (
            self.project_root / ".story-system" / "continuous-generation-jobs"
        )
        self._lock = _JOB_FILE_LOCK

    def create(
        self,
        *,
        project_id: str,
        story_id: str,
        count: int,
        start_chapter: int,
    ) -> dict[str, object]:
        if count not in ALLOWED_CONTINUOUS_COUNTS:
            raise ValueError("invalid_continuous_generation_count")
        now = _now_iso()
        job: dict[str, object] = {
            "schema_version": "continuous-generation-job/v1",
            "job_id": f"cgj-{uuid4().hex[:12]}",
            "project_id": project_id,
            "story_id": story_id,
            "status": "queued",
            "phase": "queued",
            "requested_count": count,
            "completed_count": 0,
            "start_chapter": start_chapter,
            "current_chapter": start_chapter,
            "completed_chapters": [],
            "review_warnings": [],
            "candidate_id": "",
            "stop_requested": False,
            "progress": "连续生成已排队",
            "stop_reason": "",
            "error": "",
            "created_at": now,
            "updated_at": now,
        }
        self.save(job)
        return job

    def load(self, job_id: str | None = None) -> dict[str, object] | None:
        path = self.jobs_dir / (f"{job_id}.json" if job_id else "latest.json")
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return None
        if not isinstance(payload, dict) or not str(payload.get("job_id") or ""):
            return None
        return payload

    def save(self, job: dict[str, object]) -> None:
        job_id = str(job.get("job_id") or "").strip()
        if not job_id:
            raise ValueError("continuous_generation_job_id_required")
        payload = dict(job)
        payload["updated_at"] = _now_iso()
        job["updated_at"] = payload["updated_at"]
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        with self._lock:
            self.jobs_dir.mkdir(parents=True, exist_ok=True)
            for target in (
                self.jobs_dir / f"{job_id}.json",
                self.jobs_dir / "latest.json",
            ):
                temporary = target.with_name(f".{target.name}.{uuid4().hex}.tmp")
                temporary.write_text(serialized, encoding="utf-8")
                temporary.replace(target)

    def request_stop(self, job_id: str) -> dict[str, object]:
        with self._lock:
            job = self.load(job_id)
            if job is None:
                raise FileNotFoundError("continuous_generation_job_not_found")
            if str(job.get("status")) in TERMINAL_STATUSES:
                return job
            job["stop_requested"] = True
            job["status"] = "stopping"
            job["progress"] = "当前章节完成后停止"
            self.save(job)
            return job

    def update(self, job_id: str, **updates: object) -> dict[str, object]:
        with self._lock:
            job = self.load(job_id)
            if job is None:
                raise FileNotFoundError("continuous_generation_job_not_found")
            job.update(updates)
            self.save(job)
            return job

    def reconcile(
        self,
        job: dict[str, object],
        *,
        official_chapter: int,
    ) -> dict[str, object]:
        reconciled = dict(job)
        status = str(reconciled.get("status") or "")
        if status not in ACTIVE_STATUSES:
            return reconciled

        start_chapter = int(reconciled.get("start_chapter") or 1)
        completed = sorted(
            {
                int(value)
                for value in list(reconciled.get("completed_chapters") or [])
                if isinstance(value, int) and value >= start_chapter
            }
        )
        expected_official = start_chapter - 1 + len(completed)
        phase = str(reconciled.get("phase") or "queued")

        if official_chapter == expected_official + 1 and phase in {
            "generating",
            "confirming",
        }:
            completed.append(official_chapter)
            reconciled["completed_chapters"] = completed
            reconciled["completed_count"] = len(completed)
            reconciled["current_chapter"] = official_chapter
            reconciled["candidate_id"] = ""
            reconciled["phase"] = "between_chapters"
            reconciled["progress"] = f"第 {official_chapter} 章已确认"
            if len(completed) >= int(reconciled.get("requested_count") or 0):
                reconciled["status"] = "completed"
                reconciled["progress"] = f"连续生成完成，共 {len(completed)} 章"
            self.save(reconciled)
            return reconciled

        if official_chapter != expected_official or phase not in SAFE_RECOVERY_PHASES:
            reconciled["status"] = "stopped"
            reconciled["stop_reason"] = "recovery_confirmation_required"
            reconciled["progress"] = "任务恢复状态不明确，请检查正文和候选稿"
            self.save(reconciled)
        return reconciled


class ContinuousGenerationRunner:
    def run(
        self,
        job_id: str,
        *,
        project_store: Any,
        job_store: ContinuousGenerationJobStore,
    ) -> dict[str, object]:
        job = job_store.load(job_id)
        if job is None:
            raise FileNotFoundError("continuous_generation_job_not_found")
        job = job_store.reconcile(
            job,
            official_chapter=int(project_store.summary().get("current_chapter") or 0),
        )
        if str(job.get("status")) in TERMINAL_STATUSES:
            return job

        job = job_store.update(
            job_id,
            status="running",
            progress="准备连续生成",
        )
        catastrophic_retries: dict[int, int] = {}

        while True:
            job = job_store.load(job_id) or job
            if bool(job.get("stop_requested")):
                return job_store.update(
                    job_id,
                    status="stopped",
                    stop_reason="user_stopped",
                    progress="连续生成已停止",
                )

            requested_count = int(job.get("requested_count") or 0)
            completed_count = int(job.get("completed_count") or 0)
            if completed_count >= requested_count:
                warning_count = len(list(job.get("review_warnings") or []))
                return job_store.update(
                    job_id,
                    status="completed",
                    phase="between_chapters",
                    progress=(
                        f"连续生成完成，共 {completed_count} 章"
                        + (f"，记录 {warning_count} 条审稿提醒" if warning_count else "")
                    ),
                )

            next_chapter = int(project_store.summary().get("current_chapter") or 0) + 1
            try:
                workflow = project_store.volume_workflow_status(next_chapter)
            except Exception as exc:
                return job_store.update(
                    job_id,
                    status="failed",
                    phase="checking_outline",
                    current_chapter=next_chapter,
                    error=f"outline_read_failed:{type(exc).__name__}:{exc}",
                    progress=f"第 {next_chapter} 章细纲状态读取失败",
                )
            # Pre-flight: the rolling outline is the cheapest gate and
            # the most user-actionable.  Run it after the workflow read
            # so a hard read failure still surfaces as ``failed`` rather
            # than being mis-classified as a missing outline.  Skip the
            # check entirely when the project doesn't expose a ``root``
            # directory (test fakes, pre-rolling-outline projects) so
            # the legacy volume gate stays the source of truth.
            root = getattr(project_store, "root", None)
            if root is not None:
                try:
                    from packages.story_core.outline_rolling_store import (
                        RollingOutlineStore,
                    )

                    rolling_payload = (
                        RollingOutlineStore(root).read_rolling_outline() or {}
                    )
                except Exception as exc:
                    return job_store.update(
                        job_id,
                        status="failed",
                        phase="checking_outline",
                        current_chapter=next_chapter,
                        error=f"outline_read_failed:{type(exc).__name__}:{exc}",
                        progress=f"第 {next_chapter} 章细纲状态读取失败",
                    )
                rolling_chapter_numbers = {
                    int(row["chapter_number"])
                    for row in rolling_payload.get("chapters", [])
                    if isinstance(row, dict)
                    and isinstance(row.get("chapter_number"), int)
                    and not isinstance(row.get("chapter_number"), bool)
                }
                if next_chapter not in rolling_chapter_numbers:
                    return job_store.update(
                        job_id,
                        status="stopped",
                        phase="checking_outline",
                        current_chapter=next_chapter,
                        stop_reason=f"chapter_outline_required:{next_chapter}",
                        progress=f"请先生成第 {next_chapter} 章细纲",
                    )

            workflow_status = str(workflow.get("status") or "")
            if workflow_status != "detail_complete":
                return job_store.update(
                    job_id,
                    status="stopped",
                    phase="checking_outline",
                    current_chapter=next_chapter,
                    stop_reason=(
                        "next_volume_required"
                        if workflow_status == "volume_missing"
                        else "volume_detail_required"
                    ),
                    progress=(
                        "请先设计下一卷"
                        if workflow_status == "volume_missing"
                        else "请先补完整卷章节细纲"
                    ),
                )

            job = job_store.update(
                job_id,
                status="running",
                phase="generating",
                current_chapter=next_chapter,
                progress=f"正在生成第 {next_chapter} 章",
                error="",
            )

            try:
                generated = project_store.generate_next_chapter(persist=False)
            except Exception as exc:
                return job_store.update(
                    job_id,
                    status="failed",
                    error=f"{type(exc).__name__}:{exc}",
                    progress=f"第 {next_chapter} 章生成失败",
                )

            candidate_payload = generated.get("candidate") if isinstance(generated, dict) else None
            candidate_id = (
                str(candidate_payload.get("candidate_id") or "")
                if isinstance(candidate_payload, dict)
                else ""
            )
            if not candidate_id:
                return job_store.update(
                    job_id,
                    status="failed",
                    error="candidate_id_missing",
                    progress=f"第 {next_chapter} 章候选稿保存失败",
                )

            job = job_store.update(
                job_id,
                phase="confirming",
                candidate_id=candidate_id,
                progress=f"正在确认第 {next_chapter} 章",
            )

            try:
                project_store.confirm_candidate(
                    candidate_id,
                    accept_quality_warnings=False,
                )
            except ValueError as exc:
                quality_error = str(exc)
                if _is_catastrophic_length_error(quality_error):
                    retries = catastrophic_retries.get(next_chapter, 0)
                    if retries >= _MAX_CATASTROPHIC_RETRIES:
                        return job_store.update(
                            job_id,
                            status="stopped",
                            stop_reason="candidate_confirmation_required",
                            error=quality_error,
                            progress=f"第 {next_chapter} 章连续生成异常，请人工检查",
                        )
                    try:
                        project_store.discard_candidate(candidate_id)
                    except Exception as discard_exc:
                        return job_store.update(
                            job_id,
                            status="failed",
                            error=f"{type(discard_exc).__name__}:{discard_exc}",
                            progress=f"第 {next_chapter} 章异常候选稿丢弃失败",
                        )
                    catastrophic_retries[next_chapter] = retries + 1
                    job_store.update(
                        job_id,
                        candidate_id="",
                        phase="between_chapters",
                        error="",
                        progress=(
                            f"第 {next_chapter} 章返回内容异常，"
                            f"正在重新生成（{retries + 1}/{_MAX_CATASTROPHIC_RETRIES}）"
                        ),
                    )
                    continue
                if quality_error.startswith(
                    ("generate_quality_failed:", "generate_length_failed:")
                ):
                    try:
                        project_store.confirm_candidate(
                            candidate_id,
                            accept_quality_warnings=True,
                        )
                    except Exception as force_exc:
                        return job_store.update(
                            job_id,
                            status="failed",
                            error=f"{type(force_exc).__name__}:{force_exc}",
                            progress=f"第 {next_chapter} 章保存失败",
                        )
                    job = job_store.load(job_id) or job
                    review_warnings = list(job.get("review_warnings") or [])
                    review_warnings.append(
                        {"chapter": next_chapter, "warning": quality_error}
                    )
                    job_store.update(
                        job_id,
                        review_warnings=review_warnings,
                        error="",
                        progress=f"第 {next_chapter} 章已保存，审稿警告已记录",
                    )
                else:
                    return job_store.update(
                        job_id,
                        status="stopped",
                        stop_reason="candidate_confirmation_required",
                        error=str(exc),
                        progress=f"第 {next_chapter} 章需要人工确认",
                    )
            except Exception as exc:
                return job_store.update(
                    job_id,
                    status="failed",
                    error=f"{type(exc).__name__}:{exc}",
                    progress=f"第 {next_chapter} 章保存失败",
                )

            job = job_store.load(job_id) or job
            completed = list(job.get("completed_chapters") or [])
            if next_chapter not in completed:
                completed.append(next_chapter)
            job = job_store.update(
                job_id,
                completed_chapters=completed,
                completed_count=len(completed),
                current_chapter=next_chapter,
                candidate_id="",
                phase="between_chapters",
                progress=f"第 {next_chapter} 章已确认",
            )
