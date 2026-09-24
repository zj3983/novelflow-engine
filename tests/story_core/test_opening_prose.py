from copy import deepcopy
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from threading import Event

import pytest

from packages.story_core.models import NovelProject
from packages.story_core.opening_build import runtime, execution
from tests.story_core.test_opening_build import opening_store, complete_opening, opening_payloads
from tests.story_core.test_candidate_confirmation_transaction import _long_body


def prepared_store(tmp_path, *, complete_volume=True):
    store, graph, service = opening_store(tmp_path)
    payloads = opening_payloads()
    payloads["book_outline"]["overall"].update(core_ending_chapter=50, extension_ceiling_chapter=50, planned_length=50)
    arc = payloads["volume_plan"]["arcs"][0]
    arc["end_chapter"] = 50
    node = deepcopy(arc["story_nodes"][0])
    arc["story_nodes"] = [{**node, "start_chapter": start, "end_chapter": min(start + 14, 50)} for start in (1, 16, 31, 46)]
    payloads["event_chains"]["event_chains"][0]["nodes"] = deepcopy(arc["story_nodes"])
    for task_id in graph.definition.ordered_task_ids:
        spec = graph.spec(task_id)
        payload = runtime.settings(store)["author_input"] if task_id == "opening_input" else (
            runtime.deterministic_candidate(store, task_id, NovelProject.model_validate(store.project()), graph)
            if spec.kind == "deterministic" else payloads[task_id])
        result = service.commit_candidate(task_id, payload, requested_writes=spec.task.owns)
        assert result.artifact, result.validation
    runtime.publish(store, graph, service, runtime.source_revision(store))
    if not complete_volume:
        return store
    runtime.extend_first_volume(store, service.inspect_graph().graph_revision)
    project = NovelProject.model_validate(store.project())
    graph = runtime.graph_for(store, project)
    service = store.build_graph_service(graph.definition, validators=runtime.validators_for(store, project))
    for number in range(4, runtime.settings(store)["chapter_count"] + 1):
        payload = deepcopy(opening_payloads()["chapter_outline_3"])
        payload["chapter"]["chapter_number"] = number
        payload["chapter"]["title"] = f"线索的第{number}次推进"
        task = f"chapter_outline_{number}"
        result = service.commit_candidate(task, payload, requested_writes=graph.spec(task).task.owns)
        assert result.artifact, result.validation
    payload = runtime.deterministic_candidate(store, "outline_execution_contract", project, graph)
    result = service.commit_candidate("outline_execution_contract", payload, expected_revision=1, source="deterministic")
    assert result.artifact, result.validation
    runtime.publish(store, graph, service, runtime.source_revision(store))
    return store


class FakeEngine:
    def __init__(self, callback=None):
        self.calls = 0
        self.callback = callback

    def generate_next_chapter(self, story):
        self.calls += 1
        if self.callback:
            self.callback()
        n = story.current_chapter + 1
        return SimpleNamespace(chapter_number=n, chapter_title=f"候选{n}", body=_long_body(f"第{n}章"),
            quality_report={"ok": True}, context_snapshot_id=f"synthetic-context-{n}")


def test_volume_extension_retains_accepted_artifacts_and_prose_gate(tmp_path):
    store = prepared_store(tmp_path, complete_volume=False)
    engine = FakeEngine()
    with pytest.raises(ValueError, match="volume_detail_incomplete"):
        store.generate_next_chapter(engine=engine, persist=False)
    assert engine.calls == 0
    old = store.build_graph_store().read_state()
    first = store.build_graph_store().read_artifact("chapter_outline_1")
    marker = store.build_graph_materialization()
    runtime.extend_first_volume(store, old.graph_revision)
    new = store.build_graph_store().read_state()
    assert runtime.settings(store)["chapter_count"] == 50
    assert store.build_graph_store().read_artifact("chapter_outline_1") == first
    assert new.tasks["chapter_outline_4"].status == "ready"
    assert new.tasks["outline_execution_contract"].status == "stale"
    assert new.tasks["story_core"] == old.tasks["story_core"]
    assert store.build_graph_materialization() == marker
    assert store.project()["pipeline_stage"] == "world_ready"


def test_first_three_candidates_confirm_through_existing_transaction(tmp_path):
    store = prepared_store(tmp_path)
    engine = FakeEngine()
    marker = store.build_graph_materialization()
    revisions = marker["artifact_revisions"]
    for number in range(1, 4):
        result = store.generate_next_chapter(engine=engine, persist=False)
        candidate = store.candidate_store.get(result["candidate"]["candidate_id"])
        assert candidate.submission_payload["opening_authority"]["artifact_revisions"] == revisions
        assert int(store.state().get("current_chapter") or 0) == number - 1
        store.confirm_candidate(candidate.candidate_id)
        assert store.state()["current_chapter"] == number
        receipt = store.snapshot_store.read_json(store.webnovel_dir / "opening_execution_receipts" / f"{number}.json", {})
        assert receipt["authority"]["artifact_revisions"] == revisions
        assert receipt["candidate_id"] == candidate.candidate_id
        assert runtime.settings(store)["execution"]["confirmed_through"] == number
    assert engine.calls == 3
    assert store.build_graph_materialization() == marker
    with pytest.raises(ValueError, match="opening_requires_unwritten_project"):
        runtime.sync_input(store, store.build_graph_store().read_state().graph_revision)


def test_source_edit_during_provider_does_not_save_candidate(tmp_path):
    store = prepared_store(tmp_path)
    engine = FakeEngine(lambda: store.update_project({"seed_outline": "并发作者修改"}))
    with pytest.raises(ValueError, match="opening_.*(source|revision).*conflict|opening_source_changed"):
        store.generate_next_chapter(engine=engine, persist=False)
    assert store.chapter_numbers() == []
    assert not list((store.story_system_dir / "candidates").glob("cd-*.json"))


def test_graph_edit_after_candidate_blocks_confirmation(tmp_path):
    store = prepared_store(tmp_path)
    candidate = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    graph = runtime.graph_for(store, NovelProject.model_validate(store.project()))
    service = store.build_graph_service(graph.definition, validators=runtime.validators_for(store, NovelProject.model_validate(store.project())))
    payload = deepcopy(service.inspect_artifact("story_core").payload)
    payload["story_core"]["main_conflict"] = "作者调整冲突"
    service.edit_artifact("story_core", payload, expected_revision=1)
    with pytest.raises(ValueError, match="opening_prose_graph_not_clean"):
        store.confirm_candidate(candidate["candidate_id"])
    assert store.chapter_numbers() == []
    assert store.candidate_store.get(candidate["candidate_id"]).status == "pending"


def test_confirmation_receipt_failure_rolls_back_prose_and_execution(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    candidate = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    baseline = runtime.settings(store)
    def fail(*args):
        raise OSError("synthetic receipt failure")
    monkeypatch.setattr(execution, "record_confirmation", fail)
    with pytest.raises(OSError, match="synthetic receipt"):
        store.confirm_candidate(candidate["candidate_id"])
    assert store.chapter_numbers() == []
    assert runtime.settings(store) == baseline
    assert store.candidate_store.get(candidate["candidate_id"]).status == "pending"


def test_opening_never_generates_directly_into_confirmed_prose(tmp_path):
    store = prepared_store(tmp_path, complete_volume=False)
    engine = FakeEngine()
    with pytest.raises(ValueError, match="opening_candidate_confirmation_required"):
        store.generate_next_chapter(engine=engine)
    assert engine.calls == 0
    with pytest.raises(ValueError, match="opening_prose_operation_unsupported"):
        store.regenerate_chapter(1, engine=engine, persist=False)
    with pytest.raises(ValueError, match="opening_prose_operation_unsupported"):
        store.polish_chapter(1, orchestrator=engine)
    assert engine.calls == 0


def test_prose_provider_does_not_hold_project_lock(tmp_path):
    store = prepared_store(tmp_path)
    entered, release = Event(), Event()
    def block():
        entered.set()
        assert release.wait(10)
    with ThreadPoolExecutor(max_workers=2) as pool:
        generation = pool.submit(store.generate_next_chapter, engine=FakeEngine(block), persist=False)
        try:
            assert entered.wait(5)
            edit = pool.submit(store.update_project, {"seed_outline": "独立线程修改作者输入"})
            edit.result(timeout=5)
        finally:
            release.set()
        with pytest.raises(ValueError, match="opening_source_changed|opening_prose_.*conflict"):
            generation.result(timeout=5)
    assert store.chapter_numbers() == []
    assert not list((store.story_system_dir / "candidates").glob("cd-*.json"))


@pytest.mark.parametrize("accept_quality_warnings", [False, True])
def test_opening_canon_blocking_cannot_be_confirmed(tmp_path, accept_quality_warnings):
    from packages.story_core.file_project_store import ChapterQualityError
    store = prepared_store(tmp_path)
    result = store.generate_next_chapter(engine=FakeEngine(), persist=False)
    candidate = store.candidate_store.get(result["candidate"]["candidate_id"])
    candidate.quality_report = {"ok": False, "writing_review": {"pass": False,
        "blocking": [{"code": "fact.contradiction", "source": "canon.entity:test"}]}}
    store.candidate_store.save(candidate)
    settings = runtime.settings(store)
    with pytest.raises(ChapterQualityError):
        store.confirm_candidate(candidate.candidate_id, accept_quality_warnings=accept_quality_warnings)
    assert store.chapter_numbers() == []
    assert runtime.settings(store) == settings
    assert store.candidate_store.get(candidate.candidate_id).status == "pending"


def test_materialized_handoff_reaches_actual_modular_pipeline(tmp_path, monkeypatch):
    from packages.story_core.orchestrator import StoryOrchestrator
    from packages.story_core.character_agent import RuleBasedCharacterProposalProvider
    from packages.story_core.agents.fact_extractor import FactExtractor
    from packages.story_core.agents import pipeline
    from tests.story_core.test_modular_main_flow import _StubDirectorRuntime, _StubWriterRuntime
    store = prepared_store(tmp_path)
    calls = []
    class CharacterAgent(RuleBasedCharacterProposalProvider):
        def propose_all(self, story):
            calls.append("character")
            assert story.outline_context["chapter"]["execution_contract"]["chapter_number"] == 1
            return super().propose_all(story)
    class Review:
        def complete(self, request):
            calls.append("review")
            return {"issues": []}
    monkeypatch.setattr(pipeline, "_default_consistency_runtime", lambda _: Review())
    director = _StubDirectorRuntime()
    writer = _StubWriterRuntime(_long_body("林照") + "\n" + opening_payloads()["chapter_outline_1"]["chapter"]["ending_hook"])
    orchestrator = StoryOrchestrator(use_modular_agents=True, project_root=store.root)
    class Engine:
        def generate_next_chapter(self, story):
            return orchestrator.generate_next_chapter(story, director_runtime=director,
                writer_runtime=writer, character_agent=CharacterAgent(), fact_extractor=FactExtractor())
    result = store.generate_next_chapter(engine=Engine(), persist=False)
    candidate = store.candidate_store.get(result["candidate"]["candidate_id"])
    assert writer.calls == 1
    assert "character" in calls and "review" in calls
    stages = {path.name for path in (store.story_system_dir / "workflow").glob("*/*.json")}
    assert {"character-intent.json", "director.json", "writer.json", "fact-extractor.json"}.issubset(stages)
    assert candidate.continuity_delta is not None
    assert candidate.submission_payload["quality_report"]["modular_pipeline"]["director_artifact_present"]
    assert store.chapter_numbers() == []
