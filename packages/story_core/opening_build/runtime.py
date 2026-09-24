"""Domain contracts, explicit migration and atomic opening materialization."""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json
from types import SimpleNamespace
from uuid import uuid4

from pydantic import ValidationError

from packages.story_core.build_graph.contracts import (
    BUILD_GRAPH_STATE_SCHEMA, BuildGraphState, BuildTaskState, BuildDiagnostic,
)
from packages.story_core.models import NovelProject
from packages.story_core.persistence.project_locking import project_update_lock
from packages.story_core.world_build.definition import build_world_build_graph
from packages.story_core.world_build.validators import make_world_validators
from packages.story_core.world_build.tasks import bounded_json_projection
from packages.story_core.story_core_card import StoryCoreCard, story_core_projection, merge_story_core_into_overall
from packages.story_core.outline_planning import validate_generated_opening_plan, validate_concrete_chapter_contract
from packages.story_core.volume_outline import validate_volume_structure
from packages.story_core.agents.director.prompt import build_outline_execution_contract
from .contracts import output_model
from .definition import CHAPTER_COUNT, opening_graph


SETTINGS = "opening_build.json"
SOURCE_FILES = ("outline.json", "opening_brief.json", "opening_directions.json", "story_core.json")


def settings(store):
    return store.snapshot_store.read_json(store.webnovel_dir / SETTINGS, None)


def enabled(store):
    return hasattr(store, "webnovel_dir") and hasattr(store, "snapshot_store") and bool(settings(store))


def graph_for(store, project):
    from packages.story_core.world_build.definition import build_world_build_graph
    return opening_graph(project) if enabled(store) else build_world_build_graph(project)


def source_revision(store, *, project=None, outline=None):
    project = project if project is not None else store.project()
    fields = {key: project.get(key) for key in (
        "title", "seed_outline", "world_summary", "current_focus", "author_constraints",
        "world_blueprint", "character_profiles", "relationship_graph",
    )}
    sources = {name: store.snapshot_store.read_json(store.webnovel_dir / name, None) for name in SOURCE_FILES}
    if outline is not None:
        sources["outline.json"] = outline
    sources["current_chapter"] = store.snapshot_store.read_json(store.webnovel_dir / "state.json", {}).get("current_chapter", 0)
    return hashlib.sha256(json.dumps([fields, sources], ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def assert_sources_current(store):
    config = settings(store)
    if config:
        assert_unwritten(store)
    if config and config.get("source_revision") != source_revision(store):
        raise ValueError("opening_source_changed_sync_required")


def assert_unwritten(store):
    if int(store.snapshot_store.read_json(store.webnovel_dir / "state.json", {}).get("current_chapter") or 0) > 0:
        raise ValueError("opening_requires_unwritten_project")


def reject_legacy_generation(store):
    if enabled(store):
        raise ValueError("opening_build_use_workbench")


def author_input(store):
    project = store.project()
    outline = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
    from packages.story_core.story_core_card import story_core_from_overall
    return {
        "title": project.get("title", ""), "seed_outline": project.get("seed_outline", ""),
        "author_constraints": project.get("author_constraints", []),
        "current_focus": project.get("current_focus", ""),
        "genre_plugin_ids": (project.get("world_blueprint") or {}).get("genre_plugin_ids", []),
        "source_premise": (project.get("world_blueprint") or {}).get("source_premise") or (project.get("world_blueprint") or {}).get("imported_premise") or "",
        "story_core": story_core_from_overall(outline.get("overall", {}), title=project.get("title", "")).model_dump(mode="json"),
        "brief": store.snapshot_store.read_json(store.webnovel_dir / "opening_brief.json", {}),
        "chapter_count": CHAPTER_COUNT,
    }


def activate(store, expected_graph_revision):
    """Sanctioned additive migration; only an explicit write action calls this."""
    with project_update_lock(store.root):
        assert_unwritten(store)
        if enabled(store):
            return
        project = NovelProject.model_validate(store.project())
        old_graph = build_world_build_graph(project)
        graph = opening_graph(project)
        old = store.build_graph_store().read_state()
        if (old.graph_revision if old else None) != expected_graph_revision:
            raise ValueError("build_graph_changed")
        if old and (
            old.schema_version != BUILD_GRAPH_STATE_SCHEMA
            or old.definition_fingerprint != old_graph.definition.definition_fingerprint
            or old.graph_id != old_graph.definition.graph_id
            or set(old.tasks) != set(old_graph.definition.ordered_task_ids)
        ):
            raise ValueError("build_graph_state_mismatch")
        if old and any(task.active_run_id for task in old.tasks.values()):
            raise ValueError("build_run_in_progress")
        tasks = {}
        for task_id in graph.definition.ordered_task_ids:
            previous = old.tasks.get(task_id) if old else None
            if previous and previous.current_artifact_revision is not None:
                tasks[task_id] = replace(previous, status="stale", validation_status="unknown", active_run_id=None)
            else:
                tasks[task_id] = BuildTaskState(task_id=task_id, status="blocked" if graph.spec(task_id).task.dependencies else "ready")
        state = BuildGraphState(
            schema_version=BUILD_GRAPH_STATE_SCHEMA, graph_id=graph.definition.graph_id,
            graph_revision=(old.graph_revision + 1 if old else 0), tasks=tasks,
            runs=old.runs if old else {}, definition_fingerprint=graph.definition.definition_fingerprint,
        )
        config = {"schema_version": "opening-build/v1", "chapter_count": CHAPTER_COUNT,
                  "source_revision": source_revision(store), "author_input": author_input(store)}
        _prepared, payloads = store.update_project({"pipeline_stage": "world_ready"}, _commit=False)
        payloads[store.webnovel_dir / SETTINGS] = config
        payloads[store.build_graph_store().state_path] = state.to_dict()
        if old:
            payloads[store.webnovel_dir / "build_graph_archives" / ("opening-" + uuid4().hex) / "build_graph.json"] = old.to_dict()
        store.snapshot_store.replace_json_transaction(payloads)


def _artifact(store, task_id):
    item = store.build_graph_store().read_artifact(task_id)
    if item is None:
        raise ValueError(f"opening_dependency_missing:{task_id}")
    return deepcopy(item.payload)


def sync_input(store, expected_graph_revision):
    with project_update_lock(store.root):
        assert_unwritten(store)
        if not enabled(store):
            raise ValueError("opening_graph_not_enabled")
        config = dict(settings(store))
        graph = opening_graph(NovelProject.model_validate(store.project()))
        state = store.build_graph_store().read_state()
        if state.graph_revision != expected_graph_revision:
            raise ValueError("build_graph_changed")
        if any(task.active_run_id for task in state.tasks.values()):
            raise ValueError("build_run_in_progress")
        current_input = author_input(store)
        validators = validators_for(store, NovelProject.model_validate(store.project()))
        validators["opening.opening_input"] = lambda payload: payload == current_input
        service = store.build_graph_service(graph.definition, validators=validators)
        store.update_project({"pipeline_stage": "world_ready"})
        result = service.commit_candidate(
            "opening_input", current_input, source="imported",
            expected_revision=state.tasks["opening_input"].current_artifact_revision,
            requested_writes=graph.spec("opening_input").task.owns,
        )
        if result.artifact is None:
            raise ValueError("opening_input_invalid")
        config.update(author_input=current_input, source_revision=source_revision(store))
        # On interruption before this record, the previous source hash keeps
        # execution blocked until an explicit retry; no stale input can run.
        store.snapshot_store.replace_json_transaction({store.webnovel_dir / SETTINGS: config})


def assembled_plan(store):
    overall = _artifact(store, "book_outline")["overall"]
    core = StoryCoreCard.model_validate(_artifact(store, "story_core")["story_core"])
    overall = merge_story_core_into_overall(overall, core, overwrite=False)
    arcs = _artifact(store, "volume_plan")["arcs"]
    chains = {item["arc_id"]: item["nodes"] for item in _artifact(store, "event_chains")["event_chains"]}
    for arc in arcs:
        arc["story_nodes"] = chains[arc["id"]]
    return {
        "outline": {"schema_version": "project-outline/v1", "overall": overall, "arcs": arcs,
                    "chapters": [_artifact(store, f"chapter_outline_{n}")["chapter"] for n in range(1, CHAPTER_COUNT + 1)]},
        "characters": _artifact(store, "detailed_characters")["characters"],
    }


def canonical_plan(store):
    return validate_generated_opening_plan(
        assembled_plan(store), expected_chapter_numbers=list(range(1, CHAPTER_COUNT + 1)),
        require_chapter_contracts=True,
    )


def deterministic_candidate(store, task_id, project, graph):
    if task_id == "world_input":
        # Inputs come from the committed author root, not a previous legacy
        # materialization's generated premise or current task output.
        root = _artifact(store, "opening_input")
        candidate = {key: deepcopy(root[key]) for key in (
            "title", "seed_outline", "author_constraints", "current_focus", "genre_plugin_ids", "source_premise",
        )}
        candidate["novel_type_id"] = graph.plugin_id
        candidate["power_progression_mode"] = graph.power_progression_mode
        core = StoryCoreCard.model_validate(_artifact(store, "story_core")["story_core"])
        candidate["story_core"] = story_core_projection(core, "world")
        candidate["character_seeds"] = bounded_json_projection(_artifact(store, "character_seeds")["character_seeds"])
        return candidate
    if task_id == "outline_execution_contract":
        plan = canonical_plan(store)
        chapters = plan.outline.model_dump(mode="json")["chapters"]
        return {"outline_execution_contract": [
            build_outline_execution_contract(SimpleNamespace(chapter_number=n, nearby_outline=chapters)).model_dump(mode="json")
            for n in range(1, CHAPTER_COUNT + 1)
        ]}
    raise ValueError("build_deterministic_task_unknown")


def validators_for(store, project):
    from packages.story_core.world_build.validators import make_world_validators
    validators = make_world_validators(project)
    if not enabled(store):
        return validators
    graph = opening_graph(project)

    def validate(task_id, payload):
        try:
            model = output_model(task_id)
            if model:
                parsed = model.model_validate(payload)
                if task_id == "story_core":
                    for field in ("logline", "protagonist_goal", "main_conflict", "failure_stakes", "ending_direction"):
                        if not getattr(parsed.story_core, field).strip():
                            raise ValueError(f"story_core_missing:{field}")
                elif task_id in {"character_seeds", "detailed_characters"}:
                    cards = parsed.character_seeds if task_id == "character_seeds" else parsed.characters
                    names = [card.name for card in cards]
                    if len(names) != len(set(names)):
                        raise ValueError("duplicate_character_name")
                    if not {"protagonist", "stage_antagonist", "long_term_antagonist"}.issubset({card.character_tier for card in cards}):
                        raise ValueError("missing_character_tier")
                    if task_id == "detailed_characters":
                        if set(names) != {card["name"] for card in _artifact(store, "character_seeds")["character_seeds"]}:
                            raise ValueError("character_seed_roster_mismatch")
                        from packages.story_core.outline_planning_generation import _validate_character_card_roster_quality
                        _validate_character_card_roster_quality(cards)
                elif task_id == "relationships":
                    names = {card["name"] for card in _artifact(store, "detailed_characters")["characters"]}
                    if len({edge.id for edge in parsed.relationships}) != len(parsed.relationships):
                        raise ValueError("duplicate_relationship_id")
                    if any(edge.source not in names or edge.target not in names or edge.source == edge.target for edge in parsed.relationships):
                        raise ValueError("relationship_unknown_character")
                elif task_id == "volume_plan":
                    validate_volume_structure(parsed.arcs, core_ending_chapter=_artifact(store, "book_outline")["overall"]["core_ending_chapter"])
                elif task_id == "book_outline":
                    for field in ("story", "theme_statement", "foreground_story", "background_story", "book_objective", "ending_image", "protagonist_goal", "main_conflict", "growth_path", "ending_direction"):
                        if not getattr(parsed.overall, field).strip():
                            raise ValueError(f"missing_overall_field:{field}")
                elif task_id == "event_chains":
                    arcs = _artifact(store, "volume_plan")["arcs"]
                    if {item.arc_id for item in parsed.event_chains} != {arc["id"] for arc in arcs} or len(parsed.event_chains) != len(arcs):
                        raise ValueError("event_chain_volume_mismatch")
                    for arc in arcs:
                        arc["story_nodes"] = next(item.model_dump(mode="json")["nodes"] for item in parsed.event_chains if item.arc_id == arc["id"])
                    validate_volume_structure(arcs, core_ending_chapter=_artifact(store, "book_outline")["overall"]["core_ending_chapter"])
                elif task_id.startswith("chapter_outline_"):
                    if parsed.chapter.chapter_number != int(task_id.rsplit("_", 1)[1]):
                        raise ValueError("chapter_number_mismatch")
                    validate_concrete_chapter_contract(parsed.chapter)
                    names = {card["name"] for card in _artifact(store, "detailed_characters")["characters"]}
                    if any(name not in names for name in parsed.chapter.cast):
                        raise ValueError("chapter_unknown_character")
            elif task_id == "opening_input":
                if payload != settings(store)["author_input"]:
                    raise ValueError("opening_input_must_match_author_snapshot")
            elif task_id == "outline_execution_contract":
                if payload != deterministic_candidate(store, task_id, project, graph):
                    raise ValueError("outline_contract_mismatch")
            return ()
        except ValidationError as exc:
            return tuple(BuildDiagnostic("opening.invalid", ".".join(map(str, error["loc"])), error["msg"]) for error in exc.errors(include_url=False))
        except (ValueError, KeyError) as exc:
            return (BuildDiagnostic("opening.invalid", task_id, str(exc)),)

    for task_id in graph.specs:
        if (graph.spec(task_id).task.validator_id or "").startswith("opening."):
            validators[f"opening.{task_id}"] = lambda payload, task_id=task_id: validate(task_id, payload)
    return validators


def publish(store, graph, service, expected_revision):
    """Publish all legacy consumers with the same artifact revision marker."""
    from packages.story_core.world_build.materialize import materialize_project, materialization_payload, materialization_path
    from packages.story_core.elastic_outline import validate_outline_for_project
    with project_update_lock(store.root):
        assert_unwritten(store)
        if source_revision(store) != expected_revision:
            raise ValueError("project_world_changed")
        if not service.build_readiness().ready or any(task.status != "completed" for task in service.inspect_graph().tasks.values()):
            raise ValueError("opening_graph_not_ready")
        plan = canonical_plan(store)
        outline = validate_outline_for_project(plan.outline.model_dump(mode="json"), current_chapter=0)
        world = build_world_build_graph(NovelProject.model_validate(store.project()))
        project = materialize_project(NovelProject.model_validate(store.project()), world, service)
        project.character_profiles = [card.model_dump(mode="json") for card in plan.characters]
        project.relationship_graph = _artifact(store, "relationships")["relationships"]
        patch = {key: getattr(project, key) for key in ("world_blueprint", "world_summary", "current_focus", "character_profiles", "relationship_graph")}
        patch["pipeline_stage"] = "environment_ready"
        prepared, payloads = store.update_project(patch, replace_world_blueprint=True, _commit=False)
        payloads[store.webnovel_dir / "outline.json"] = outline
        payloads[store.webnovel_dir / "opening_execution_contracts.json"] = _artifact(store, "outline_execution_contract")
        payloads[materialization_path(store)] = materialization_payload(graph, service, NovelProject.model_validate(prepared))
        config = dict(settings(store))
        config["source_revision"] = source_revision(store, project=prepared, outline=outline)
        payloads[store.webnovel_dir / SETTINGS] = config
        store.snapshot_store.replace_json_transaction(payloads)
