from __future__ import annotations

import json
from pathlib import Path

import pytest

from apps.api.services.continuous_generation import (
    ContinuousGenerationJobStore,
    ContinuousGenerationRunner,
)


class FakeProjectStore:
    def __init__(self, *, current_chapter: int = 10) -> None:
        self.current_chapter = current_chapter
        self.workflow_status = "detail_complete"
        self.generated: list[dict[str, object]] = []
        self.confirmed: list[dict[str, object]] = []
        self.fail_generation_at: int | None = None
        self.fail_confirmation_at: int | None = None
        self.confirmation_error = "generate_quality_failed:body"
        self.fail_workflow = False
        self.after_generate = None
        self.discarded: list[str] = []
        self.recover_after_discard = False

    def summary(self) -> dict[str, int]:
        return {"current_chapter": self.current_chapter}

    def volume_workflow_status(self, target_chapter: int) -> dict[str, object]:
        if self.fail_workflow:
            raise OSError("outline_read_failed")
        return {
            "status": self.workflow_status,
            "target_chapter": target_chapter,
            "volume_id": "volume-1",
            "volume_range": [1, 60],
        }

    def generate_next_chapter(self, *, persist: bool) -> dict[str, object]:
        target = self.current_chapter + 1
        self.generated.append({"chapter": target, "persist": persist})
        if self.fail_generation_at == target:
            raise RuntimeError("model_unavailable")
        if self.after_generate is not None:
            self.after_generate(target)
        return {
            "chapter_number": target,
            "candidate": {
                "candidate_id": f"candidate-{target}",
                "chapter_number": target,
            },
        }

    def confirm_candidate(
        self,
        candidate_id: str,
        *,
        accept_quality_warnings: bool,
    ) -> dict[str, object]:
        target = int(candidate_id.rsplit("-", 1)[1])
        self.confirmed.append(
            {
                "chapter": target,
                "accept_quality_warnings": accept_quality_warnings,
            }
        )
        if self.fail_confirmation_at == target and not accept_quality_warnings:
            raise ValueError(self.confirmation_error)
        self.current_chapter = target
        return {"candidate": {"candidate_id": candidate_id, "status": "confirmed"}}

    def discard_candidate(self, candidate_id: str) -> dict[str, object]:
        self.discarded.append(candidate_id)
        if self.recover_after_discard:
            self.fail_confirmation_at = None
        return {"candidate": {"candidate_id": candidate_id, "status": "discarded"}}


def _create_job(tmp_path: Path, *, count: int = 2, current_chapter: int = 10):
    jobs = ContinuousGenerationJobStore(tmp_path)
    job = jobs.create(
        project_id="file:p-test",
        story_id="file:p-test",
        count=count,
        start_chapter=current_chapter + 1,
    )
    return jobs, job


@pytest.mark.parametrize("count", [2, 5, 10, 20])
def test_job_store_accepts_supported_counts_and_persists_latest(tmp_path: Path, count: int) -> None:
    jobs, job = _create_job(tmp_path, count=count)

    assert job["status"] == "queued"
    assert job["phase"] == "queued"
    assert job["requested_count"] == count
    assert job["completed_chapters"] == []
    assert jobs.load(job["job_id"]) == job
    assert jobs.load() == job
    persisted = json.loads(
        (
            tmp_path
            / ".story-system"
            / "continuous-generation-jobs"
            / f"{job['job_id']}.json"
        ).read_text(encoding="utf-8")
    )
    assert persisted == job
    assert not list((tmp_path / ".story-system" / "continuous-generation-jobs").glob("*.tmp"))


def test_job_store_rejects_unsupported_count(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="invalid_continuous_generation_count"):
        _create_job(tmp_path, count=3)


def test_stop_request_is_durable_and_keeps_progress(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    job.update(
        {
            "status": "running",
            "completed_count": 1,
            "completed_chapters": [11],
        }
    )
    jobs.save(job)

    stopped = jobs.request_stop(str(job["job_id"]))

    assert stopped["status"] == "stopping"
    assert stopped["stop_requested"] is True
    assert stopped["completed_chapters"] == [11]
    assert jobs.load(str(job["job_id"])) == stopped


def test_progress_update_does_not_overwrite_existing_stop_request(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    jobs.request_stop(str(job["job_id"]))

    updated = jobs.update(
        str(job["job_id"]),
        phase="confirming",
        candidate_id="candidate-11",
        progress="正在确认第 11 章",
    )

    assert updated["status"] == "stopping"
    assert updated["stop_requested"] is True
    assert updated["phase"] == "confirming"


def test_runner_generates_candidates_then_uses_ordinary_confirmation(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert result["completed_chapters"] == [11, 12]
    assert project.generated == [
        {"chapter": 11, "persist": False},
        {"chapter": 12, "persist": False},
    ]
    assert project.confirmed == [
        {"chapter": 11, "accept_quality_warnings": False},
        {"chapter": 12, "accept_quality_warnings": False},
    ]


def test_runner_stops_after_current_chapter_when_user_requests_stop(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path, count=5)
    project = FakeProjectStore()
    project.after_generate = lambda _chapter: jobs.request_stop(str(job["job_id"]))

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "stopped"
    assert result["stop_reason"] == "user_stopped"
    assert result["completed_chapters"] == [11]
    assert project.generated == [{"chapter": 11, "persist": False}]


@pytest.mark.parametrize(
    ("workflow_status", "stop_reason"),
    [
        ("volume_missing", "next_volume_required"),
        ("volume_plan_ready", "volume_detail_required"),
        ("detail_partial", "volume_detail_required"),
    ],
)
def test_runner_stops_at_volume_boundaries(
    tmp_path: Path, workflow_status: str, stop_reason: str
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.workflow_status = workflow_status

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "stopped"
    assert result["stop_reason"] == stop_reason
    assert project.generated == []


def test_quality_warning_saves_new_chapter_and_continues(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.fail_confirmation_at = 11

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert result["stop_reason"] == ""
    assert result["candidate_id"] == ""
    assert result["completed_chapters"] == [11, 12]
    assert result["review_warnings"] == [
        {"chapter": 11, "warning": "generate_quality_failed:body"}
    ]
    assert project.current_chapter == 12
    assert project.confirmed == [
        {"chapter": 11, "accept_quality_warnings": False},
        {"chapter": 11, "accept_quality_warnings": True},
        {"chapter": 12, "accept_quality_warnings": False},
    ]


def test_length_warning_saves_new_chapter_and_continues(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.fail_confirmation_at = 11
    project.confirmation_error = "generate_length_failed:body_chars 5900 > 5700"

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert result["stop_reason"] == ""
    assert result["candidate_id"] == ""
    assert result["completed_chapters"] == [11, 12]
    assert result["review_warnings"] == [
        {
            "chapter": 11,
            "warning": "generate_length_failed:body_chars 5900 > 5700",
        }
    ]
    assert project.current_chapter == 12
    assert project.confirmed == [
        {"chapter": 11, "accept_quality_warnings": False},
        {"chapter": 11, "accept_quality_warnings": True},
        {"chapter": 12, "accept_quality_warnings": False},
    ]


def test_catastrophically_short_candidate_is_discarded_and_regenerated(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.fail_confirmation_at = 11
    project.confirmation_error = "generate_length_failed:章节字数偏少：当前约85字，最低要求3800字。"
    project.recover_after_discard = True

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert result["completed_chapters"] == [11, 12]
    assert project.discarded == ["candidate-11"]
    assert project.generated == [
        {"chapter": 11, "persist": False},
        {"chapter": 11, "persist": False},
        {"chapter": 12, "persist": False},
    ]
    assert project.confirmed == [
        {"chapter": 11, "accept_quality_warnings": False},
        {"chapter": 11, "accept_quality_warnings": False},
        {"chapter": 12, "accept_quality_warnings": False},
    ]


def test_severely_overlong_candidate_is_discarded_and_regenerated(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.fail_confirmation_at = 11
    project.confirmation_error = "generate_length_failed:body_chars 7313 > 5700"
    project.recover_after_discard = True

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert project.discarded == ["candidate-11"]
    assert project.confirmed[0:2] == [
        {"chapter": 11, "accept_quality_warnings": False},
        {"chapter": 11, "accept_quality_warnings": False},
    ]


def test_non_quality_confirmation_error_keeps_candidate_pending(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.fail_confirmation_at = 11
    project.confirmation_error = "candidate_not_pending"

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "stopped"
    assert result["stop_reason"] == "candidate_confirmation_required"
    assert result["candidate_id"] == "candidate-11"
    assert result["completed_chapters"] == []
    assert project.confirmed == [
        {"chapter": 11, "accept_quality_warnings": False},
    ]


def test_generation_failure_keeps_previously_confirmed_chapters(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path, count=5)
    project = FakeProjectStore()
    project.fail_generation_at = 13

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "failed"
    assert result["completed_chapters"] == [11, 12]
    assert "model_unavailable" in str(result["error"])


def test_outline_status_failure_marks_job_failed_instead_of_leaving_it_running(
    tmp_path: Path,
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.fail_workflow = True

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "failed"
    assert "outline_read_failed" in str(result["error"])


def test_reconcile_records_one_confirmed_chapter_once(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    job.update({"status": "running", "phase": "confirming", "current_chapter": 11})
    jobs.save(job)

    reconciled = jobs.reconcile(job, official_chapter=11)
    reconciled_again = jobs.reconcile(reconciled, official_chapter=11)

    assert reconciled_again["completed_chapters"] == [11]
    assert reconciled_again["completed_count"] == 1
    assert reconciled_again["phase"] == "between_chapters"


@pytest.mark.parametrize("phase", ["generating", "confirming"])
def test_recovery_stops_when_inflight_state_is_ambiguous(tmp_path: Path, phase: str) -> None:
    jobs, job = _create_job(tmp_path)
    job.update({"status": "running", "phase": phase, "current_chapter": 11})
    jobs.save(job)

    recovered = jobs.reconcile(job, official_chapter=10)

    assert recovered["status"] == "stopped"
    assert recovered["stop_reason"] == "recovery_confirmation_required"
