from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

import apps.api.services.continuous_generation as continuous_generation
from apps.api.services.continuous_generation import (
    ContinuousGenerationJobStore,
    ContinuousGenerationRunner,
)
from packages.story_core.character_inspection import ConsistencyWarning
from packages.story_core.consistency_replanning import ConsistencyReplanResult
from packages.story_core.generation_consistency_gate import (
    ConsistencyGateRequired,
    GenerationConsistencyGate,
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
        self.consistency_gate: GenerationConsistencyGate | None = None
        self.consistency_calls: list[bool] = []
        self.consistency_gates: dict[int, GenerationConsistencyGate] = {}
        self.blocking_plans: dict[int, dict[str, object]] = {}
        self.writer_plan_inputs: list[dict[str, object] | None] = []
        self.generation_sources: dict[int, object] = {}
        self.replan_requests: list[object] = []

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

    def generate_next_chapter(self, *, persist: bool, **kwargs: object) -> dict[str, object]:
        target = self.current_chapter + 1
        self.generated.append({"chapter": target, "persist": persist})
        consistency_override = bool(kwargs.get("consistency_override"))
        self.consistency_calls.append(consistency_override)
        plan_override = kwargs.get("director_plan_override")
        self.writer_plan_inputs.append(
            deepcopy(plan_override) if isinstance(plan_override, dict) else None
        )
        gate = self.consistency_gates.pop(target, None)
        if gate is None:
            gate = self.consistency_gate
            self.consistency_gate = None
        if gate is not None and not consistency_override and plan_override is None:
            raise ConsistencyGateRequired(gate, plan=self.blocking_plans.get(target))
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

    def generation_story_for_target(self, target_chapter: int) -> object:
        return self.generation_sources.setdefault(target_chapter, {"chapter": target_chapter})

    def replan_consistency_plan(self, request: object) -> dict[str, object]:
        self.replan_requests.append(request)
        return {}


def _create_job(tmp_path: Path, *, count: int = 2, current_chapter: int = 10):
    jobs = ContinuousGenerationJobStore(tmp_path)
    job = jobs.create(
        project_id="file:p-test",
        story_id="file:p-test",
        count=count,
        start_chapter=current_chapter + 1,
    )
    return jobs, job


def _blocking_gate(target_chapter: int = 11) -> GenerationConsistencyGate:
    return GenerationConsistencyGate(
        target_chapter=target_chapter,
        status="blocking",
        warnings=[
            ConsistencyWarning(
                code="SKILL_NOT_YET_ACQUIRED",
                severity="error",
                character_name="林照",
                target_chapter=target_chapter,
                message="技能尚未获得",
                expected="FUTURE_SKILL_999",
                observed={"acquired_chapter": 25},
            )
        ],
        checked_characters=["林照"],
        checked_at_boundary=target_chapter - 1,
    )


def _replan_result(
    *,
    original_gate: GenerationConsistencyGate,
    revised_plan: dict[str, object],
    status: str,
    revised_gate: GenerationConsistencyGate | None = None,
    error: str = "",
) -> ConsistencyReplanResult:
    return ConsistencyReplanResult(
        target_chapter=original_gate.target_chapter,
        historical_boundary=original_gate.checked_at_boundary,
        attempt_number=1,
        original_plan_summary={"chapter_number": original_gate.target_chapter},
        revised_plan=revised_plan,
        addressed_warning_codes=[],
        original_gate=original_gate,
        remaining_gate=revised_gate or original_gate,
        status=status,
        error=error,
    )


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


def test_runner_persists_consistency_pause_and_override_is_scoped_to_one_chapter(
    tmp_path: Path,
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    project.consistency_gate = GenerationConsistencyGate(
        target_chapter=11,
        status="blocking",
        warnings=[
            ConsistencyWarning(
                code="SKILL_NOT_YET_ACQUIRED",
                severity="error",
                character_name="林照",
                target_chapter=11,
                message="技能尚未获得",
                expected="FUTURE_SKILL_999",
                observed={"acquired_chapter": 25},
            )
        ],
        checked_characters=["林照"],
        checked_at_boundary=10,
    )

    paused = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert paused["status"] == "awaiting_consistency_override"
    assert paused["phase"] == "awaiting_consistency_override"
    assert paused["consistency_gate"]["target_chapter"] == 11
    assert paused["completed_chapters"] == []
    assert project.generated == [{"chapter": 11, "persist": False}]
    assert project.confirmed == []
    assert project.consistency_calls == [False]
    assert jobs.load(str(job["job_id"]))["status"] == "awaiting_consistency_override"

    jobs.update(
        str(job["job_id"]),
        status="queued",
        phase="between_chapters",
        consistency_override=True,
    )
    resumed = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert resumed["status"] == "completed"
    assert resumed["completed_chapters"] == [11, 12]
    assert resumed["consistency_override_chapters"] == [11]
    assert project.consistency_calls == [False, True, False]


def test_runner_auto_replans_once_and_sends_only_revised_plan_to_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    gate = _blocking_gate(11)
    original_plan = {
        "chapter_number": 11,
        "character_moves": [{"name": "林照", "skills_used": ["FUTURE_SKILL_999"]}],
    }
    revised_plan = {
        "chapter_number": 11,
        "character_moves": [{"name": "林照", "location": "北岸"}],
    }
    source = {"current_chapter": 10, "ledger": {"immutable": True}}
    project.consistency_gates[11] = gate
    project.blocking_plans[11] = original_plan
    project.generation_sources[11] = source
    calls: list[dict[str, object]] = []

    def fake_replan(**kwargs: object) -> ConsistencyReplanResult:
        calls.append(kwargs)
        assert kwargs["source"] is source
        assert kwargs["target_chapter"] == 11
        assert kwargs["original_plan"] == original_plan
        return _replan_result(
            original_gate=gate,
            revised_plan=revised_plan,
            revised_gate=GenerationConsistencyGate(
                target_chapter=11,
                status="clear",
                checked_characters=["林照"],
                checked_at_boundary=10,
            ),
            status="replanned_clear",
        )

    monkeypatch.setattr(continuous_generation, "run_consistency_replan", fake_replan)
    before_source = deepcopy(source)

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert result["completed_chapters"] == [11, 12]
    assert len(calls) == 1
    assert project.writer_plan_inputs == [None, revised_plan, None]
    assert result["auto_consistency_replan_attempted"] is False
    recovery = result["consistency_recovery_history"][0]
    assert recovery["chapter_number"] == 11
    assert recovery["replan_status"] == "replanned_clear"
    assert recovery["original_plan"] == original_plan
    assert recovery["revised_plan"] == revised_plan
    assert recovery["revised_consistency_gate"]["status"] == "clear"
    assert source == before_source


def test_runner_pauses_after_replan_still_blocks_without_second_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    gate = _blocking_gate(11)
    original_plan = {"chapter_number": 11, "skill": "FUTURE_SKILL_999"}
    revised_plan = {"chapter_number": 11, "skill": "FUTURE_SKILL_999"}
    project.consistency_gates[11] = gate
    project.blocking_plans[11] = original_plan
    calls = 0

    def fake_replan(**_kwargs: object) -> ConsistencyReplanResult:
        nonlocal calls
        calls += 1
        return _replan_result(
            original_gate=gate,
            revised_plan=revised_plan,
            revised_gate=gate,
            status="replanned_clear",
        )

    monkeypatch.setattr(continuous_generation, "run_consistency_replan", fake_replan)

    paused = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )
    duplicate = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert paused["status"] == "awaiting_replanned_confirmation"
    assert paused["replan_status"] == "still_blocking"
    assert paused["revised_plan"] == revised_plan
    assert paused["revised_consistency_gate"]["status"] == "blocking"
    assert paused["auto_consistency_replan_attempts"] == 1
    assert paused["progress"] == "自动重新规划后仍有一致性问题，已暂停，等待处理"
    assert paused["consistency_recovery_history"][0]["replan_status"] == "still_blocking"
    assert duplicate == paused
    assert calls == 1
    assert project.writer_plan_inputs == [None]


def test_runner_pauses_replan_failure_without_persisting_a_chapter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    gate = _blocking_gate(11)
    original_plan = {"chapter_number": 11, "skill": "FUTURE_SKILL_999"}
    project.consistency_gates[11] = gate
    project.blocking_plans[11] = original_plan

    def failed_replan(**_kwargs: object) -> ConsistencyReplanResult:
        raise TimeoutError("planner timeout")

    monkeypatch.setattr(continuous_generation, "run_consistency_replan", failed_replan)

    paused = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert paused["status"] == "awaiting_consistency_override"
    assert paused["replan_status"] == "failed"
    assert paused["auto_consistency_replan_attempted"] is True
    assert paused["auto_consistency_replan_attempts"] == 1
    assert "consistency_replan_failed" in str(paused["error"])
    assert paused["original_plan"] == original_plan
    assert paused["original_consistency_gate"]["target_chapter"] == 11
    assert paused["revised_plan"] is None
    assert paused["completed_chapters"] == []
    assert project.writer_plan_inputs == [None]


def test_runner_pauses_on_warning_only_replan_instead_of_silent_acceptance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    gate = _blocking_gate(11)
    project.consistency_gates[11] = gate
    project.blocking_plans[11] = {"chapter_number": 11, "skill": "FUTURE_SKILL_999"}
    warning_gate = GenerationConsistencyGate(
        target_chapter=11,
        status="warnings",
        warnings=[
            ConsistencyWarning(
                code="LOCATION_MISMATCH",
                severity="warning",
                character_name="林照",
                target_chapter=11,
                message="地点需要作者确认",
                expected="北岸",
                observed={"location": "未知"},
            )
        ],
        checked_characters=["林照"],
        checked_at_boundary=10,
    )

    monkeypatch.setattr(
        continuous_generation,
        "run_consistency_replan",
        lambda **_kwargs: _replan_result(
            original_gate=gate,
            revised_plan={"chapter_number": 11, "location": "未知"},
            revised_gate=warning_gate,
            status="replanned_with_warnings",
        ),
    )

    paused = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert paused["status"] == "awaiting_replanned_confirmation"
    assert paused["replan_status"] == "replanned_with_warnings"
    assert paused["revised_consistency_gate"]["status"] == "warnings"
    assert paused["progress"] == "自动重新规划后仍有一致性提示，已暂停，请确认"
    assert project.writer_plan_inputs == [None]


def test_runner_gives_each_chapter_a_fresh_automatic_replan_attempt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs, job = _create_job(tmp_path)
    project = FakeProjectStore()
    gates = {11: _blocking_gate(11), 12: _blocking_gate(12)}
    project.consistency_gates.update(gates)
    project.blocking_plans.update(
        {
            chapter: {"chapter_number": chapter, "skill": f"FUTURE_SKILL_{chapter}"}
            for chapter in gates
        }
    )
    calls: list[int] = []

    def fake_replan(**kwargs: object) -> ConsistencyReplanResult:
        target = int(kwargs["target_chapter"])
        calls.append(target)
        return _replan_result(
            original_gate=gates[target],
            revised_plan={"chapter_number": target, "location": "北岸"},
            revised_gate=GenerationConsistencyGate(
                target_chapter=target,
                status="clear",
                checked_characters=["林照"],
                checked_at_boundary=target - 1,
            ),
            status="replanned_clear",
        )

    monkeypatch.setattr(continuous_generation, "run_consistency_replan", fake_replan)

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert calls == [11, 12]
    assert result["completed_chapters"] == [11, 12]
    assert [item["chapter_number"] for item in result["consistency_recovery_history"]] == [11, 12]
    assert result["auto_consistency_replan_chapter"] == 12
    assert result["auto_consistency_replan_attempts"] == 1


def test_runner_uses_boundary_zero_for_continuous_chapter_one_replan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs, job = _create_job(tmp_path, current_chapter=0)
    project = FakeProjectStore(current_chapter=0)
    gate = _blocking_gate(1)
    project.consistency_gates[1] = gate
    project.blocking_plans[1] = {"chapter_number": 1, "skill": "FUTURE_SKILL_999"}
    requests: list[dict[str, object]] = []

    def fake_replan(**kwargs: object) -> ConsistencyReplanResult:
        requests.append(kwargs)
        assert kwargs["target_chapter"] == 1
        assert kwargs["source"] == project.generation_sources[1]
        return _replan_result(
            original_gate=gate,
            revised_plan={"chapter_number": 1, "location": "北岸"},
            revised_gate=GenerationConsistencyGate(
                target_chapter=1,
                status="clear",
                checked_characters=["林照"],
                checked_at_boundary=0,
            ),
            status="replanned_clear",
        )

    monkeypatch.setattr(continuous_generation, "run_consistency_replan", fake_replan)

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result["status"] == "completed"
    assert requests[0]["original_gate"].checked_at_boundary == 0
    assert requests[0]["target_chapter"] == 1


def test_runner_does_not_restart_a_persisted_consistency_pause(tmp_path: Path) -> None:
    jobs, job = _create_job(tmp_path)
    paused = jobs.update(
        str(job["job_id"]),
        status="awaiting_consistency_override",
        phase="awaiting_consistency_override",
    )
    project = FakeProjectStore()

    result = ContinuousGenerationRunner().run(
        str(job["job_id"]), project_store=project, job_store=jobs
    )

    assert result == paused
    assert project.generated == []


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
