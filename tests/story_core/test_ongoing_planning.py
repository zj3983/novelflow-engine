"""Synthetic first-to-second volume planning and prose acceptance."""
from copy import deepcopy
from collections import Counter
import json
from time import monotonic, sleep
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from packages.story_core.models import NovelProject
from packages.story_core.opening_build import runtime, execution
from tests.story_core.test_opening_build import opening_store, opening_payloads
from tests.story_core.test_opening_prose import FakeEngine
from tests.story_core.test_candidate_confirmation_transaction import _long_body


def _nodes(template, start, end):
    return [{**deepcopy(template), "start_chapter": number, "end_chapter": min(number + 14, end)}
            for number in range(start, end + 1, 15)]


def two_volume_store(tmp_path):
    store, graph, service = opening_store(tmp_path)
    payloads = opening_payloads()
    payloads["book_outline"]["overall"].update(
        core_ending_chapter=60, extension_ceiling_chapter=60, planned_length=60)
    first = payloads["volume_plan"]["arcs"][0]
    first.update(end_chapter=50, is_final_arc=False)
    first["story_nodes"] = _nodes(first["story_nodes"][0], 1, 50)
    second = deepcopy(first)
    second.update(id="second", title="第二卷", start_chapter=51, end_chapter=60, is_final_arc=True)
    second["story_nodes"] = _nodes(first["story_nodes"][0], 51, 60)
    payloads["volume_plan"]["arcs"].append(second)
    payloads["event_chains"]["event_chains"] = [
        {"arc_id": arc["id"], "nodes": deepcopy(arc["story_nodes"])}
        for arc in (first, second)
    ]
    for task_id in graph.definition.ordered_task_ids:
        spec = graph.spec(task_id)
        candidate = (runtime.settings(store)["author_input"] if task_id == "opening_input" else
            runtime.deterministic_candidate(store, task_id, NovelProject.model_validate(store.project()), graph)
            if spec.kind == "deterministic" else payloads[task_id])
        result = service.commit_candidate(task_id, candidate, requested_writes=spec.task.owns)
        assert result.artifact, (task_id, result.validation.to_dict())
    runtime.publish(store, graph, service, runtime.source_revision(store))
    runtime.extend_first_volume(store, service.inspect_graph().graph_revision)
    project = NovelProject.model_validate(store.project())
    graph = runtime.graph_for(store, project)
    service = store.build_graph_service(graph.definition, validators=runtime.validators_for(store, project))
    for number in range(4, 51):
        candidate = deepcopy(opening_payloads()["chapter_outline_3"])
        candidate["chapter"].update(chapter_number=number, title=f"首卷第{number}章")
        task_id = f"chapter_outline_{number}"
        result = service.commit_candidate(task_id, candidate, requested_writes=graph.spec(task_id).task.owns)
        assert result.artifact, (task_id, result.validation.to_dict())
    final = runtime.deterministic_candidate(store, "outline_execution_contract", project, graph)
    result = service.commit_candidate("outline_execution_contract", final, expected_revision=1, source="deterministic")
    assert result.artifact, result.validation.to_dict()
    runtime.publish(store, graph, service, runtime.source_revision(store))
    state = store.state()
    for character in state["characters"]:
        character["lifecycle_state"] = "active"
    store.snapshot_store.replace_json_transaction({store.webnovel_dir / "state.json": state})
    return store


def _confirm_through(store, target):
    engine = FakeEngine()
    for number in range(int(store.state().get("current_chapter") or 0) + 1, target + 1):
        candidate = store.generate_next_chapter(engine=engine, persist=False)["candidate"]
        store.confirm_candidate(candidate["candidate_id"])
        assert store.state()["current_chapter"] == number
    return engine


def _confirm_second_volume_modular(store, monkeypatch):
    from packages.story_core.orchestrator import StoryOrchestrator
    from packages.story_core.character_agent import RuleBasedCharacterProposalProvider
    from packages.story_core.agents.fact_extractor import FactExtractor
    from packages.story_core.agents import pipeline
    from tests.story_core.test_modular_main_flow import _StubDirectorRuntime, _StubWriterRuntime

    calls = []
    class Review:
        def complete(self, request):
            calls.append("canon-review")
            return {"issues": []}
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda _: Review())
    build_request = pipeline._build_writer_request
    def checked_request(**kwargs):
        request = build_request(**kwargs)
        number = request.director_artifact.chapter_number
        expected = store.build_artifact("outline_execution_contract")["payload"]["outline_execution_contract"][number - 1]
        assert request.director_artifact.outline_contract.model_dump(mode="json") == expected
        assert request.director_artifact.hook == expected["planned_hook"]
        calls.append("writer-contract")
        return request
    monkeypatch.setattr(pipeline, "_build_writer_request", checked_request)
    for number in (51, 52, 53):
        expected = store.build_artifact("outline_execution_contract")["payload"]["outline_execution_contract"][number - 1]
        class CharacterAgent(RuleBasedCharacterProposalProvider):
            def propose_all(self, story):
                assert story.outline_context["chapter"]["execution_contract"] == expected
                calls.append("character")
                return super().propose_all(story)
        writer = _StubWriterRuntime(_long_body("林照") + "\n" + expected["planned_hook"])
        orchestrator = StoryOrchestrator(use_modular_agents=True, project_root=store.root)
        class Engine:
            def generate_next_chapter(self, story):
                return orchestrator.generate_next_chapter(story,
                    director_runtime=_StubDirectorRuntime(), writer_runtime=writer,
                    character_agent=CharacterAgent(), fact_extractor=FactExtractor())
        candidate = store.generate_next_chapter(engine=Engine(), persist=False)["candidate"]
        assert writer.calls == 1
        official_title = store.build_artifact(f"chapter_outline_{number}")["payload"]["chapter"]["title"]
        assert candidate["chapter_title"] == official_title
        assert store.state()["current_chapter"] == number - 1
        store.confirm_candidate(candidate["candidate_id"])
        assert store.state()["current_chapter"] == number
        persisted = store.snapshot_store.read_json(store.story_system_dir / "chapters" / f"{number:04d}.json", {})
        assert persisted["chapter_title"] == official_title
        assert persisted["chapter_summary"]["chapter_title"] == official_title
        assert store.snapshot_store.read_json(store.story_system_dir / "director" / f"{number:04d}.json", {})["output"]["outline_contract"] == expected
    assert calls.count("character") == 3
    assert calls.count("writer-contract") == 3
    assert calls.count("canon-review") == 3


def test_next_volume_requires_confirmed_boundary_and_preserves_old_release(tmp_path, monkeypatch):
    store = two_volume_store(tmp_path)
    _confirm_through(store, 4)
    with pytest.raises(ValueError, match="build_graph_changed"):
        runtime.extend_next_volume(store, store.build_graph_store().read_state().graph_revision - 1)
    with pytest.raises(ValueError, match="opening_volume_boundary_required"):
        runtime.extend_next_volume(store, store.build_graph_store().read_state().graph_revision)
    _confirm_through(store, 50)
    original_marker = (store.webnovel_dir / "build_graph_materialization.json").read_bytes()
    original_outline = (store.webnovel_dir / "outline.json").read_bytes()
    original_state_bytes = (store.webnovel_dir / "state.json").read_bytes()
    original_receipt = (store.webnovel_dir / "opening_execution_receipts" / "50.json").read_bytes()
    original_artifact = store.build_graph_store().read_artifact("chapter_outline_50")
    artifact_history = {path.relative_to(store.build_graph_store().artifacts_dir): path.read_bytes()
        for path in store.build_graph_store().artifacts_dir.rglob("*.json")}
    old_receipts = {path.name: path.read_bytes()
        for path in (store.webnovel_dir / "opening_execution_receipts").glob("*.json")}
    old = store.build_graph_store().read_state()
    with pytest.raises(ValueError, match="opening_prose_chapter_not_planned"):
        execution.capture(store)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    client = TestClient(app)
    base = "/file-projects/generic_webnovel/build-graph"
    visible = client.get(base)
    assert visible.status_code == 200 and visible.json()["opening_next_volume_available"]
    assert not visible.json()["opening_planning_pending"]
    response = client.post(base + "/opening/next-volume", json={"expected_graph_revision": old.graph_revision})
    assert response.status_code == 200, response.text
    assert response.json()["opening_planning_pending"]
    assert response.json()["materialization_status"] == "outdated"
    assert store.project()["pipeline_stage"] == "world_ready"
    state = store.build_graph_store().read_state()
    assert state.tasks["chapter_outline_51"].status == "ready"
    assert state.tasks["outline_execution_contract"].status == "stale"
    assert state.tasks["chapter_outline_50"] == old.tasks["chapter_outline_50"]
    assert (store.webnovel_dir / "build_graph_materialization.json").read_bytes() == original_marker
    assert (store.webnovel_dir / "outline.json").read_bytes() == original_outline
    assert (store.webnovel_dir / "state.json").read_bytes() == original_state_bytes
    assert (store.webnovel_dir / "opening_execution_receipts" / "50.json").read_bytes() == original_receipt
    assert store.build_graph_store().read_artifact("chapter_outline_50") == original_artifact
    assert all((store.build_graph_store().artifacts_dir / path).read_bytes() == data for path, data in artifact_history.items())
    assert all((store.webnovel_dir / "opening_execution_receipts" / name).read_bytes() == data for name, data in old_receipts.items())
    response = client.post(base + "/opening/next-volume", json={"expected_graph_revision": state.graph_revision})
    assert response.status_code == 200, response.text  # retry is idempotent
    assert store.build_graph_store().read_state() == state
    with pytest.raises(ValueError, match="opening_prose_not_ready"):
        execution.capture(store)
    gated_engine = FakeEngine()
    with pytest.raises(ValueError, match="opening_prose_not_ready|volume_detail_required"):
        store.generate_next_chapter(engine=gated_engine, persist=False)
    assert gated_engine.calls == 0

    calls = []
    fail_once = True
    drift_once = True
    original_project = deepcopy(store.project())
    original_state = deepcopy(store.state())
    def complete(_stage, request):
        nonlocal fail_once, drift_once
        task_id = request.metadata["world_build_task"]
        calls.append(task_id)
        assert "confirmed_state" in request.prompt
        assert "confirmed_canon" in request.prompt
        assert "confirmed_through" in request.prompt
        assert "read_paths" in request.prompt and "output_schema" in request.prompt
        assert "existing_candidate" not in request.prompt
        if fail_once:
            fail_once = False
            return SimpleNamespace(ok=False, text="", provider="test", model="test", resolved_model="test")
        if drift_once:
            drift_once = False
            store.update_project({"author_constraints": ["并发修改卷末源输入"]})
        number = int(task_id.rsplit("_", 1)[1])
        candidate = deepcopy(opening_payloads()["chapter_outline_3"])
        candidate["chapter"].update(chapter_number=number, title=f"第二卷第{number}章")
        return SimpleNamespace(ok=True, text=json.dumps(candidate, ensure_ascii=False),
            provider="test", model="test", resolved_model="test")
    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", SimpleNamespace(complete_stage=complete))
    def run(mode):
        start = client.post(base + "/orchestrations", json={"mode": mode})
        assert start.status_code == 200, start.text
        deadline = monotonic() + 900
        while monotonic() < deadline:
            job = client.get(base + "/orchestrations/" + start.json()["job_id"]).json()
            if job["status"] in {"completed", "failed", "conflicted", "interrupted"}:
                return job
            sleep(.1)
        raise AssertionError("synthetic orchestration timed out")
    failed = run("next")
    assert failed["status"] == "failed" and failed["failure_task_id"] == "chapter_outline_51"
    assert store.build_graph_store().read_artifact("chapter_outline_51") is None
    assert store.build_graph_store().read_state().tasks["chapter_outline_51"].status == "ready"
    assert (store.webnovel_dir / "build_graph_materialization.json").read_bytes() == original_marker
    conflicted = run("next")
    assert conflicted["status"] == "conflicted" and conflicted["failure_task_id"] == "chapter_outline_51"
    assert store.build_graph_store().read_artifact("chapter_outline_51") is None
    assert store.build_graph_store().read_state().tasks["chapter_outline_51"].status == "ready"
    store.snapshot_store.replace_json_transaction({
        store.webnovel_dir / "project.json": original_project,
        store.webnovel_dir / "state.json": original_state,
    })
    runtime.assert_planning_sources_current(store)
    original_publish = runtime.publish_next_volume
    publish_calls = 0
    def interrupted_publish(*args):
        nonlocal publish_calls
        publish_calls += 1
        if publish_calls == 1:
            raise RuntimeError("synthetic interruption before release transaction")
        return original_publish(*args)
    monkeypatch.setattr(runtime, "publish_next_volume", interrupted_publish)
    interrupted = run("continue")
    assert interrupted["status"] == "failed"
    assert runtime.settings(store).get("pending_extension")
    assert (store.webnovel_dir / "build_graph_materialization.json").read_bytes() == original_marker
    assert (store.webnovel_dir / "outline.json").read_bytes() == original_outline
    completed = run("continue")
    assert completed["status"] == "completed", completed
    assert completed["materialized"]
    assert publish_calls == 2
    assert client.get(base).json()["materialization_status"] == "in_use"
    assert Counter(calls) == Counter({"chapter_outline_51": 3, **{f"chapter_outline_{n}": 1 for n in range(52, 61)}})
    first_future = store.build_graph_store().read_artifact("chapter_outline_51")
    assert first_future.revision == 1 and first_future.source == "llm"
    assert first_future.provider == "test" and first_future.prompt_call_id
    runs = [run.status for run in store.build_graph_store().read_state().runs.values()
        if run.task_id == "chapter_outline_51"]
    assert {"failed", "conflict", "committed"}.issubset(runs)
    assert store.project()["pipeline_stage"] == "environment_ready"
    assert (store.webnovel_dir / "state.json").read_bytes() == original_state_bytes
    assert "pending_extension" not in runtime.settings(store)
    assert runtime.settings(store)["plan_versions"][-1]["start_chapter"] == 51
    assert (store.webnovel_dir / "opening_plan_versions" / "v1" / "build_graph_materialization.json").exists()
    assert (store.webnovel_dir / "opening_plan_versions" / "v1" / "build_graph_materialization.json").read_bytes() == original_marker
    assert (store.webnovel_dir / "opening_plan_versions" / "v2" / "build_graph_materialization.json").exists()
    assert (store.webnovel_dir / "opening_execution_receipts" / "50.json").read_bytes() == original_receipt
    assert store.build_graph_store().read_artifact("chapter_outline_50") == original_artifact
    assert all((store.build_graph_store().artifacts_dir / path).read_bytes() == data for path, data in artifact_history.items())
    assert all((store.webnovel_dir / "opening_execution_receipts" / name).read_bytes() == data for name, data in old_receipts.items())
    assert execution.capture(store)["chapter_number"] == 51
    pending = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    assert store.state()["current_chapter"] == 50
    assert execution.capture(store)["chapter_number"] == 51
    store.discard_candidate(pending["candidate_id"])
    assert store.state()["current_chapter"] == 50
    from packages.story_core.file_project_store import ChapterQualityError
    blocked = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    blocked_record = store.candidate_store.get(blocked["candidate_id"])
    blocked_record.quality_report = {"ok": False, "writing_review": {"pass": False,
        "blocking": [{"code": "fact.contradiction", "source": "canon.entity:synthetic"}]}}
    store.candidate_store.save(blocked_record)
    with pytest.raises(ChapterQualityError):
        store.confirm_candidate(blocked["candidate_id"], accept_quality_warnings=True)
    assert store.state()["current_chapter"] == 50
    store.discard_candidate(blocked["candidate_id"])
    outline_path = store.webnovel_dir / "outline.json"
    official_outline = store.snapshot_store.read_json(outline_path, {})
    def drift():
        changed = deepcopy(official_outline)
        changed["overall"]["story"] = "并发旧规划改动"
        store.snapshot_store.replace_json_transaction({outline_path: changed})
    with pytest.raises(ValueError, match="opening_.*(conflict|changed)"):
        store.generate_next_chapter(engine=FakeEngine(drift), persist=False)
    store.snapshot_store.replace_json_transaction({outline_path: official_outline})
    assert execution.capture(store)["chapter_number"] == 51
    unconfirmed = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    drift()
    with pytest.raises(ValueError, match="opening_.*(conflict|changed)"):
        store.confirm_candidate(unconfirmed["candidate_id"])
    assert store.state()["current_chapter"] == 50
    store.snapshot_store.replace_json_transaction({outline_path: official_outline})
    store.discard_candidate(unconfirmed["candidate_id"])
    _confirm_second_volume_modular(store, monkeypatch)
    assert store.state()["current_chapter"] == 53
    for number in (51, 52, 53):
        receipt = store.snapshot_store.read_json(store.webnovel_dir / "opening_execution_receipts" / f"{number}.json", {})
        assert receipt["plan_version"] == 2


def test_extension_rejects_source_drift_without_migration(tmp_path):
    store = two_volume_store(tmp_path)
    _confirm_through(store, 1)
    before = store.build_graph_store().read_state()
    store.update_project({"seed_outline": "作者在卷末改动源输入"})
    with pytest.raises(ValueError, match="opening_planning_source_conflict"):
        runtime.extend_next_volume(store, before.graph_revision)
    assert store.build_graph_store().read_state() == before
