from copy import deepcopy
from dataclasses import replace
import json

import pytest

from packages.story_core.models import NovelProject
from packages.story_core.opening_build import runtime
from packages.story_core.opening_build.definition import opening_graph
from packages.story_core.outline_planning import PlanningCharacterCard
from packages.story_core.world_build.definition import build_world_build_graph
from packages.story_core.world_build.tasks import build_input_contract, build_task_prompt, input_fingerprint
from tests.story_core.test_world_build_graph import _store, _generic_payloads
from tests.story_core.test_outline_planning import valid_payload, _add_chapter_contracts


def opening_payloads():
    plan = valid_payload.__wrapped__()
    _add_chapter_contracts(plan)
    motives = ["替父亲洗去旧案罪名", "守住清点祖祠的独占权", "保住朋友交托的账册", "阻止封档规则被公开推翻"]
    voices = ["说话先报证据出处", "把宗门规条逐项念给对方", "先用家乡俗语缓和局面", "只问对方愿意付出什么代价"]
    actions = ["随身抄录每个证人的原话", "先封锁现场再安排人核账", "把重要材料分别交给邻居", "让下属先试探证人的底线"]
    for i, card in enumerate(plan["characters"]):
        card["story_drive"]["motivation"] = motives[i]
        card["story_drive"]["long_term_goal"] = motives[i] + "，留下不可撤销的记录"
        card["performance_profile"]["speech_style"] = voices[i]
        card["performance_profile"]["action_style"] = actions[i]
        card["relationship_notes"] = [{"target": plan["characters"][(i + 1) % 4]["name"],
            "relation_type": "旧案利益冲突", "history": "曾共同参与祖祠清点", "current_attitude": "保持警惕", "shared_interest_or_conflict": "争夺名册保管权"}]
    cards = [PlanningCharacterCard.model_validate(card).model_dump(mode="json") for card in plan["characters"]]
    seeds = [{
        **{key: card[key] for key in ("name", "role", "character_tier", "importance", "narrative_function", "profile_status", "first_appearance")},
        "current_identity": card["identity_profile"]["current_identity"],
        "origin": card["identity_profile"]["origin"],
        "immediate_goal": card["story_drive"]["immediate_goal"],
        "failure_stakes": card["story_drive"]["failure_stakes"],
    } for card in cards]
    overall = plan["outline"]["overall"]
    payloads = {task: values[0] for task, values in _generic_payloads().items()}
    payloads.update({
        "story_core": {"story_core": {"title": "合成开局", "logline": overall["story"],
            "protagonist_goal": overall["protagonist_goal"], "main_conflict": overall["main_conflict"],
            "failure_stakes": "证据销毁后主角会被逐出宗门", "ending_direction": overall["ending_direction"]}},
        "character_seeds": {"character_seeds": seeds},
        "detailed_characters": {"characters": cards},
        "relationships": {"relationships": [{"id": "rel-lin-zhao", "source": "林照", "target": "赵衡", "relation_type": "对手"}]},
        "longform_story_engine": {"story_engine": {"core_loop": "取证后承担公开代价", "escalation": ["封档升级"], "relationship_pressure": ["证人被威胁"], "ending_payoff": "旧案公开"}},
        "book_outline": {"overall": overall},
        "volume_plan": {"arcs": plan["outline"]["arcs"]},
        "event_chains": {"event_chains": [{"arc_id": arc["id"], "nodes": arc["story_nodes"]} for arc in plan["outline"]["arcs"]]},
    })
    for chapter in plan["outline"]["chapters"][:3]:
        payloads[f"chapter_outline_{chapter['chapter_number']}"] = {"chapter": chapter}
    return payloads


def opening_store(tmp_path):
    store = _store(tmp_path, plugin_id="generic_webnovel")
    runtime.activate(store, None)
    project = NovelProject.model_validate(store.project())
    graph = opening_graph(project)
    service = store.build_graph_service(graph.definition, validators=runtime.validators_for(store, project))
    return store, graph, service


def complete_opening(store, graph, service):
    payloads = opening_payloads()
    for task_id in graph.definition.ordered_task_ids:
        spec = graph.spec(task_id)
        if task_id == "opening_input":
            candidate = runtime.settings(store)["author_input"]
        elif spec.kind == "deterministic":
            candidate = runtime.deterministic_candidate(store, task_id, NovelProject.model_validate(store.project()), graph)
        else:
            candidate = payloads[task_id]
        result = service.commit_candidate(task_id, candidate, source="imported" if spec.kind == "imported" else "deterministic" if spec.kind == "deterministic" else "llm", requested_writes=spec.task.owns)
        assert result.artifact is not None, (task_id, result.validation.to_dict())


def test_complete_opening_canonical_handoff_and_atomic_publication(tmp_path):
    store, graph, service = opening_store(tmp_path)
    complete_opening(store, graph, service)
    old_revision = runtime.source_revision(store)
    assert not (store.webnovel_dir / "outline.json").exists()
    runtime.publish(store, graph, service, old_revision)
    outline = json.loads((store.webnovel_dir / "outline.json").read_text(encoding="utf-8"))
    assert [item["chapter_number"] for item in outline["chapters"]] == [1, 2, 3]
    handoff = store.build_artifact("outline_execution_contract")["payload"]["outline_execution_contract"]
    assert handoff[0]["planned_hook"] == outline["chapters"][0]["ending_hook"]
    assert store.project()["pipeline_stage"] == "environment_ready"
    assert len(store.project()["character_profiles"]) == 4
    assert set(store.build_graph_materialization()["artifact_revisions"]) == set(graph.specs)
    runtime.assert_sources_current(store)


def test_story_edit_stales_world_and_entire_opening_chain(tmp_path):
    store, graph, service = opening_store(tmp_path)
    complete_opening(store, graph, service)
    previous = service.inspect_artifact("story_core")
    changed = deepcopy(previous.payload)
    changed["story_core"]["main_conflict"] = "作者调整为公开记录的归属争议"
    service.edit_artifact("story_core", changed, expected_revision=1, requested_writes=graph.spec("story_core").task.owns)
    assert service.inspect_artifact("story_core").source == "human"
    assert service.inspect_artifact("story_core", 1) == previous
    for task_id in ("character_seeds", "world_input", "world_core_rules", "detailed_characters", "chapter_outline_3", "outline_execution_contract"):
        assert service.inspect_task(task_id).status == "stale"


def test_explicit_migration_retains_world_artifact_history(tmp_path):
    store = _store(tmp_path, plugin_id="generic_webnovel")
    world = build_world_build_graph(NovelProject.model_validate(store.project()))
    old_service = store.build_graph_service(world.definition)
    # Seed an artifact using the normal canonical world validator.
    from packages.story_core.world_build.validators import make_world_validators
    from packages.story_core.world_build.tasks import canonical_world_input
    old_service = store.build_graph_service(world.definition, validators=make_world_validators(NovelProject.model_validate(store.project())))
    old_service.commit_candidate("world_input", canonical_world_input(NovelProject.model_validate(store.project())), source="imported")
    original = old_service.inspect_artifact("world_input")
    runtime.activate(store, old_service.inspect_graph().graph_revision)
    assert store.build_graph_store().read_artifact("world_input", 1) == original
    assert store.build_graph_store().read_state().tasks["world_input"].status == "stale"
    assert list((store.webnovel_dir / "build_graph_archives").glob("opening-*/build_graph.json"))


def test_invalid_opening_payload_and_unknown_fields_do_not_mutate(tmp_path):
    store, graph, service = opening_store(tmp_path)
    service.commit_candidate("opening_input", runtime.settings(store)["author_input"], source="imported")
    before = service.inspect_graph().to_dict()
    candidate = deepcopy(opening_payloads()["story_core"])
    candidate["unowned"] = "must reject"
    assert not service.validate("story_core", candidate).passed
    assert service.inspect_graph().to_dict() == before
    assert service.inspect_artifact("story_core") is None


def test_opening_prompt_preserves_schema_and_fingerprint_matches_model_input(tmp_path):
    store, graph, service = opening_store(tmp_path)
    service.commit_candidate("opening_input", runtime.settings(store)["author_input"], source="imported")
    contract = build_input_contract(NovelProject.model_validate(store.project()), graph, service, "story_core")
    prompt = build_task_prompt(graph, "story_core", contract)
    assert "existing_candidate" not in prompt
    assert "$defs" in prompt and "failure_stakes" in prompt
    assert "build.opening.opening_input" in prompt
    other = deepcopy(contract)
    other["reads"][0]["value"]["seed_outline"] += "changed"
    assert input_fingerprint(contract) != input_fingerprint(other)


def test_source_edit_blocks_publication_and_explicit_sync_versions_root(tmp_path):
    store, graph, service = opening_store(tmp_path)
    complete_opening(store, graph, service)
    expected = runtime.source_revision(store)
    store.update_project({"seed_outline": "作者的新开局"})
    with pytest.raises(ValueError, match="project_world_changed"):
        runtime.publish(store, graph, service, expected)
    runtime.sync_input(store, service.inspect_graph().graph_revision)
    assert service.inspect_artifact("opening_input").revision == 2
    assert service.inspect_task("story_core").status == "stale"
    runtime.assert_sources_current(store)


def test_publication_failure_does_not_partially_publish_outline_or_readiness(tmp_path, monkeypatch):
    store, graph, service = opening_store(tmp_path)
    complete_opening(store, graph, service)
    original = store.project()
    replace_transaction = store.snapshot_store.replace_json_transaction

    def fail_before_publication(payloads):
        if store.webnovel_dir / "outline.json" in payloads:
            raise OSError("synthetic transaction failure")
        return replace_transaction(payloads)

    monkeypatch.setattr(store.snapshot_store, "replace_json_transaction", fail_before_publication)
    with pytest.raises(OSError, match="synthetic transaction failure"):
        runtime.publish(store, graph, service, runtime.source_revision(store))
    assert store.project() == original
    assert not (store.webnovel_dir / "outline.json").exists()
    assert store.build_graph_materialization() is None


@pytest.mark.parametrize("initial", ["generic_webnovel", "game_webnovel"])
def test_iteration_zero_settings_recover_read_only_then_migrate(tmp_path, initial):
    store = _store(tmp_path, plugin_id=initial)
    runtime.activate(store, None)
    legacy = opening_graph(NovelProject.model_validate(store.project()), bind_topology=False)
    state = replace(store.build_graph_store().read_state(), definition_fingerprint=legacy.definition.definition_fingerprint)
    config = runtime.settings(store)
    config.pop("topology")
    config["author_input"].pop("power_progression_mode")
    store.snapshot_store.replace_json_transaction({store.build_graph_store().state_path: state.to_dict(), store.webnovel_dir / runtime.SETTINGS: config})
    store.update_project({"world_blueprint": {"genre_plugin_ids": ["game_webnovel"], "power_progression_mode": "traditional_class"}})
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    assert runtime.graph_for(store, NovelProject.model_validate(store.project())).definition.definition_fingerprint == state.definition_fingerprint
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before
    runtime.sync_input(store, state.graph_revision)
    assert runtime.settings(store)["topology"]["power_progression_mode"] == "traditional_class"
    runtime.assert_sources_current(store)


def test_interrupted_topology_sync_is_blocked_readable_and_retryable(tmp_path, monkeypatch):
    from packages.story_core.build_graph.service import BuildGraphService
    store, graph, service = opening_store(tmp_path)
    complete_opening(store, graph, service)
    runtime.publish(store, graph, service, runtime.source_revision(store))
    marker_path = store.webnovel_dir / "build_graph_materialization.json"
    marker = marker_path.read_bytes()
    original = store.build_graph_store().read_artifact("opening_input", 1)
    store.update_project({"world_blueprint": {"genre_plugin_ids": ["game_webnovel"]}})
    commit = BuildGraphService.commit_candidate
    def fail_commit(*args, **kwargs):
        raise OSError("synthetic interruption after definition migration")
    monkeypatch.setattr(BuildGraphService, "commit_candidate", fail_commit)
    with pytest.raises(OSError, match="synthetic interruption"):
        runtime.sync_input(store, service.inspect_graph().graph_revision)
    assert store.project()["pipeline_stage"] == "world_ready"
    assert marker_path.read_bytes() == marker
    with pytest.raises(ValueError, match="opening_source_changed_sync_required"):
        runtime.assert_sources_current(store)
    migrated = runtime.graph_for(store, NovelProject.model_validate(store.project()))
    store.build_graph_store().initialize(migrated.definition)
    monkeypatch.setattr(BuildGraphService, "commit_candidate", commit)
    runtime.sync_input(store, store.build_graph_store().read_state().graph_revision)
    runtime.assert_sources_current(store)
    assert store.build_graph_store().read_artifact("opening_input", 1) == original
    assert store.build_graph_store().read_artifact("opening_input").revision == 2
    assert marker_path.read_bytes() == marker


def test_active_run_blocks_sync_without_mutation(tmp_path):
    store, graph, service = opening_store(tmp_path)
    service.commit_candidate("opening_input", runtime.settings(store)["author_input"], source="imported")
    service.start_run("story_core")
    store.update_project({"world_blueprint": {"genre_plugin_ids": ["game_webnovel"]}})
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    with pytest.raises(ValueError, match="build_run_in_progress"):
        runtime.sync_input(store, service.inspect_graph().graph_revision)
    assert {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()} == before


def test_removed_task_can_return_without_overwriting_artifact_history(tmp_path):
    store = _store(tmp_path, plugin_id="game_webnovel")
    runtime.activate(store, None)
    runtime.sync_input(store, 0)
    def commit_foundation():
        project = NovelProject.model_validate(store.project())
        graph = runtime.graph_for(store, project)
        service = store.build_graph_service(graph.definition, validators=runtime.validators_for(store, project))
        payloads = opening_payloads()
        payloads["power_system_foundation"] = {"name": "印记体系", "origin": ["先民留下的精神印记"]}
        for task_id in ("story_core", "character_seeds", "world_input", "world_core_rules", "power_system_foundation"):
            payload = runtime.deterministic_candidate(store, task_id, project, graph) if task_id == "world_input" else payloads[task_id]
            result = service.commit_candidate(task_id, payload, requested_writes=graph.spec(task_id).task.owns,
                expected_revision=service.inspect_task(task_id).current_artifact_revision)
            assert result.artifact is not None, result.validation
    commit_foundation()
    old = store.build_graph_store().read_artifact("power_system_foundation", 1)
    for genre in ("generic_webnovel", "game_webnovel"):
        store.update_project({"world_blueprint": {"genre_plugin_ids": [genre]}})
        runtime.sync_input(store, store.build_graph_store().read_state().graph_revision)
    assert store.build_graph_store().read_state().tasks["power_system_foundation"].current_artifact_revision == 1
    commit_foundation()
    assert store.build_graph_store().read_artifact("power_system_foundation", 1) == old
    assert store.build_graph_store().read_artifact("power_system_foundation").revision == 2


def test_author_story_core_edit_preserves_downstream_and_requires_sync(tmp_path):
    store, graph, service = opening_store(tmp_path)
    complete_opening(store, graph, service)
    runtime.publish(store, graph, service, runtime.source_revision(store))
    outline = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
    card = opening_payloads()["story_core"]["story_core"]
    card["main_conflict"] = "作者修改的故事核心冲突"
    store.update_story_core(card)
    updated = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
    assert updated["arcs"] == outline["arcs"]
    assert updated["chapters"] == outline["chapters"]
    with pytest.raises(ValueError, match="opening_source_changed_sync_required"):
        runtime.assert_sources_current(store)
    runtime.sync_input(store, service.inspect_graph().graph_revision)
    assert store.build_graph_store().read_artifact("opening_input").payload["story_core"]["main_conflict"] == card["main_conflict"]
