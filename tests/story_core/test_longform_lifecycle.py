from packages.story_core import longform_lifecycle as lifecycle
from packages.story_core.candidate_editing import candidate_authority
from packages.story_core.opening_build.execution import source_fingerprint
from packages.story_core.persistence.project_locking import project_update_lock
from tests.story_core.test_opening_prose import FakeEngine, prepared_store


def test_confirmed_chapter_survives_launch_failure_and_explicit_retry_is_once(tmp_path):
    store = prepared_store(tmp_path)
    lifecycle.accept_plan(store, lifecycle.plan_state(store)["fingerprint"])
    generated = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    candidate = store.candidate_store.get(generated["candidate_id"])
    launches = []

    def fail(job_id):
        assert not project_update_lock(store.root)._is_owned()
        launches.append(job_id)
        raise RuntimeError("synthetic failure")

    args = dict(expected_candidate=candidate_authority(candidate), accept_quality_warnings=True,
                start_next=fail, read_job=lambda _: None)
    result = lifecycle.confirm_and_continue(store, candidate.candidate_id, **args)
    assert len(launches) == 1
    assert store.chapter_numbers() == [1]
    original_body = store.chapter(1)["body"]
    assert "本章已保存" in result["next"]["message"]
    lifecycle.confirm_and_continue(store, candidate.candidate_id, **args)
    assert len(launches) == 1

    def succeed(job_id):
        assert not project_update_lock(store.root)._is_owned()
        launches.append(job_id)
        return {"job_id": job_id, "status": "queued"}

    args.update(start_next=succeed, retry=True)
    lifecycle.confirm_and_continue(store, candidate.candidate_id, **args)
    assert launches == [launches[0], launches[0]]
    args["read_job"] = lambda job_id: {"job_id": job_id, "status": "queued", "worker_active": True}
    lifecycle.confirm_and_continue(store, candidate.candidate_id, **args)
    assert len(launches) == 2
    assert store.chapter_numbers() == [1]
    assert store.chapter(1)["body"] == original_body


def test_author_requirements_invalidate_adoption_without_changing_confirmed_body(tmp_path):
    store = prepared_store(tmp_path)
    lifecycle.accept_plan(store, lifecycle.plan_state(store)["fingerprint"])
    generated = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    store.confirm_candidate(generated["candidate_id"], accept_quality_warnings=True)
    original_body = store.chapter(1)["body"]
    lifecycle.save_author_requirements(store, ["保留核对记录。"], expected_source=source_fingerprint(store))
    assert not lifecycle.plan_state(store)["accepted"]
    assert store.chapter(1)["body"] == original_body
    assert store.chapter_numbers() == [1]
