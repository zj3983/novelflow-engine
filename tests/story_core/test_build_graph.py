from __future__ import annotations

from pathlib import Path

import pytest

from packages.story_core.build_graph import (
    BuildDefinitionError,
    BuildDiagnostic,
    BuildGraphDefinition,
    BuildGraphService,
    BuildGraphStore,
    BuildOwnershipViolation,
    BuildRevisionConflict,
    BuildRunConflict,
    BuildTaskDefinition,
)
from packages.story_core.file_project_store import FileProjectStore


def _task(
    task_id: str,
    *,
    dependencies: tuple[str, ...] = (),
    required: bool = False,
    review_policy: str = "auto",
    validator_id: str | None = None,
    owns: tuple[str, ...] | None = None,
    forbidden_writes: tuple[str, ...] = (),
) -> BuildTaskDefinition:
    return BuildTaskDefinition(
        task_id=task_id,
        title=task_id.replace("_", " ").title(),
        dependencies=dependencies,
        owns=owns or (f"domain.{task_id}",),
        forbidden_writes=forbidden_writes,
        validator_id=validator_id,
        review_policy=review_policy,
        required_for_readiness=required,
    )


def _definition(*, with_validator: bool = False) -> BuildGraphDefinition:
    return BuildGraphDefinition(
        graph_id="synthetic-build",
        tasks=(
            _task("foundation", required=True, validator_id="foundation" if with_validator else None),
            _task("world_rules", dependencies=("foundation",), required=True),
            _task("characters", dependencies=("world_rules",)),
            _task("book_outline", dependencies=("characters", "world_rules")),
            _task("economy", dependencies=("world_rules",)),
        ),
    )


def _service(
    tmp_path: Path,
    *,
    definition: BuildGraphDefinition | None = None,
    validators=None,
) -> BuildGraphService:
    return BuildGraphService(
        definition or _definition(),
        store=BuildGraphStore(tmp_path),
        validators=validators,
    )


def _commit(
    service: BuildGraphService,
    task_id: str,
    revision: int | None = None,
    *,
    source: str = "llm",
    payload: dict | None = None,
):
    return service.commit_candidate(
        task_id,
        payload or {"task": task_id, "revision": revision},
        expected_revision=revision,
        source=source,
        requested_writes=(f"domain.{task_id}",),
    )


def _commit_chain_to_economy(service: BuildGraphService) -> None:
    _commit(service, "foundation")
    _commit(service, "world_rules")
    _commit(service, "economy")


def _commit_full_graph(service: BuildGraphService) -> None:
    _commit(service, "foundation")
    _commit(service, "world_rules")
    _commit(service, "characters")
    _commit(service, "book_outline")
    _commit(service, "economy")


def test_valid_dag_has_deterministic_dependency_order(tmp_path: Path):
    definition = _definition()

    assert definition.ordered_task_ids == (
        "foundation",
        "world_rules",
        "characters",
        "book_outline",
        "economy",
    )
    assert definition.to_dict()["tasks"][0]["task_id"] == "foundation"


@pytest.mark.parametrize(
    ("tasks", "code"),
    [
        (
            (_task("foundation", dependencies=("missing",)),),
            "build_graph_unknown_dependency",
        ),
        (
            (_task("foundation", dependencies=("foundation",)),),
            "build_graph_self_dependency",
        ),
        (
            (
                _task("a", dependencies=("c",)),
                _task("b", dependencies=("a",)),
                _task("c", dependencies=("b",)),
            ),
            "build_graph_cycle",
        ),
    ],
)
def test_invalid_dag_is_rejected_deterministically(tasks, code):
    with pytest.raises(BuildDefinitionError) as error:
        BuildGraphDefinition(graph_id="invalid", tasks=tasks)

    assert error.value.code == code
    assert error.value.diagnostics[0].code == code


def test_overlapping_ownership_is_rejected_at_definition_time():
    with pytest.raises(BuildDefinitionError) as error:
        BuildGraphDefinition(
            graph_id="overlap",
            tasks=(
                _task("a", owns=("world.power_system",)),
                _task("b", owns=("world.power_system.stages",)),
            ),
        )

    assert error.value.code == "build_ownership_overlap"


def test_ownership_and_forbidden_writes_are_hard_boundaries(tmp_path: Path):
    definition = BuildGraphDefinition(
        graph_id="ownership",
        tasks=(
            _task(
                "root",
                owns=("world.core",),
                forbidden_writes=("world.core.secret",),
            ),
        ),
    )
    service = _service(tmp_path, definition=definition)

    with pytest.raises(BuildOwnershipViolation) as error:
        service.commit_candidate(
            "root",
            {"value": 1},
            expected_revision=None,
            requested_writes=("world.core.secret",),
        )

    assert error.value.code == "build_ownership_violation"
    assert service.inspect_artifact("root") is None


def test_validation_failure_persists_diagnostics_without_new_artifact(tmp_path: Path):
    def reject_invalid(payload):
        if payload.get("invalid"):
            return [
                {
                    "code": "synthetic.invalid",
                    "path": "domain.foundation",
                    "message": "synthetic candidate is invalid",
                    "severity": "blocking",
                }
            ]
        return True

    service = _service(
        tmp_path,
        definition=_definition(with_validator=True),
        validators={"foundation": reject_invalid},
    )
    result = service.commit_candidate(
        "foundation",
        {"invalid": True},
        expected_revision=None,
        requested_writes=("domain.foundation",),
    )

    assert result.disposition == "FAIL"
    assert result.artifact is None
    assert result.task_state.status == "validation_failed"
    assert service.inspect_artifact("foundation") is None
    persisted = service.inspect_task("foundation")
    assert persisted.diagnostics[0].code == "synthetic.invalid"
    assert persisted.validation_status == "failed"

    recovered = _commit(service, "foundation", payload={"invalid": False})
    assert recovered.artifact is not None
    assert recovered.artifact.revision == 1


def test_valid_commit_records_revision_dependencies_and_provenance(tmp_path: Path):
    service = _service(tmp_path)
    foundation = _commit(service, "foundation", source="human")
    world_rules = service.commit_candidate(
        "world_rules",
        {"rules": ["one"]},
        expected_revision=None,
        source="ai_repair",
        provider="openai-compatible",
        model="k3",
        prompt_call_id="call-1",
        requested_writes=("domain.world_rules",),
    )

    assert foundation.artifact.revision == 1
    assert world_rules.artifact.dependency_revisions == {"foundation": 1}
    assert world_rules.artifact.source == "ai_repair"
    assert world_rules.artifact.provider == "openai-compatible"
    assert world_rules.artifact.model == "k3"
    assert world_rules.artifact.prompt_call_id == "call-1"


def test_expected_revision_mismatch_never_last_write_wins(tmp_path: Path):
    service = _service(tmp_path)
    _commit(service, "foundation")
    service.edit_artifact(
        "foundation",
        {"task": "foundation", "revision": 2},
        expected_revision=1,
        requested_writes=("domain.foundation",),
    )

    with pytest.raises(BuildRevisionConflict) as error:
        service.edit_artifact(
            "foundation",
            {"task": "foundation", "revision": "stale-client"},
            expected_revision=1,
            requested_writes=("domain.foundation",),
        )

    assert error.value.code == "build_revision_conflict"
    assert service.inspect_artifact("foundation").payload["revision"] == 2


def test_two_runs_and_upstream_change_cannot_commit_old_ai_result(tmp_path: Path):
    service = _service(tmp_path)
    _commit(service, "foundation")
    run = service.start_run("world_rules")
    service.edit_artifact(
        "foundation",
        {"task": "foundation", "revision": 2},
        expected_revision=1,
        requested_writes=("domain.foundation",),
    )

    with pytest.raises(BuildRunConflict) as error:
        service.commit_run(
            run.run_id,
            {"rules": "old"},
            requested_writes=("domain.world_rules",),
        )

    assert error.value.code == "build_run_conflict"
    assert service.inspect_task("world_rules").status == "stale"
    assert service.inspect_artifact("world_rules") is None


def test_transitive_stale_propagation_preserves_history(tmp_path: Path):
    service = _service(tmp_path)
    _commit_full_graph(service)
    service.edit_artifact(
        "foundation",
        {"task": "foundation", "revision": 2},
        expected_revision=1,
        requested_writes=("domain.foundation",),
    )

    assert service.inspect_task("foundation").status == "completed"
    assert service.inspect_task("world_rules").status == "stale"
    assert service.inspect_task("characters").status == "stale"
    assert service.inspect_task("book_outline").status == "stale"
    assert service.inspect_task("economy").status == "stale"
    assert service.inspect_artifact("world_rules", 1) is not None
    assert len(service.artifact_history("book_outline")) == 1


def test_revalidate_stale_creates_deterministic_revision_with_new_dependencies(tmp_path: Path):
    service = _service(tmp_path)
    _commit_chain_to_economy(service)
    service.edit_artifact(
        "world_rules",
        {"rules": ["changed"]},
        expected_revision=1,
        requested_writes=("domain.world_rules",),
    )

    result = service.revalidate_current("economy")

    assert result.artifact.revision == 2
    assert result.artifact.parent_revision == 1
    assert result.artifact.source == "deterministic"
    assert result.artifact.payload == {"task": "economy", "revision": None}
    assert result.artifact.dependency_revisions == {"world_rules": 2}
    assert service.inspect_task("economy").status == "completed"
    assert [item.revision for item in service.artifact_history("economy")] == [1, 2]


def test_human_edit_uses_same_version_and_stale_boundary(tmp_path: Path):
    service = _service(tmp_path)
    _commit_chain_to_economy(service)
    result = service.edit_artifact(
        "world_rules",
        {"rules": ["human"]},
        expected_revision=1,
        requested_writes=("domain.world_rules",),
    )

    assert result.artifact.source == "human"
    assert result.artifact.revision == 2
    assert service.inspect_task("economy").status == "stale"


def test_review_policy_requires_acceptance_but_auto_completes(tmp_path: Path):
    review_definition = BuildGraphDefinition(
        graph_id="review",
        tasks=(_task("reviewed", review_policy="review", required=True),),
    )
    review_service = _service(tmp_path / "review", definition=review_definition)
    result = _commit(review_service, "reviewed")
    assert result.disposition == "PASS_REVIEW"
    assert review_service.inspect_task("reviewed").status == "review_required"
    assert not review_service.build_readiness().ready
    review_service.accept_review("reviewed", expected_revision=1)
    assert review_service.inspect_task("reviewed").status == "completed"
    assert review_service.build_readiness().ready

    chained_review_definition = BuildGraphDefinition(
        graph_id="review-chain",
        tasks=(
            _task("reviewed", review_policy="review"),
            _task("downstream", dependencies=("reviewed",)),
        ),
    )
    chained = _service(tmp_path / "review-chain", definition=chained_review_definition)
    _commit(chained, "reviewed")
    assert chained.inspect_task("downstream").status == "blocked"
    chained.accept_review("reviewed", expected_revision=1)
    assert chained.inspect_task("downstream").status == "ready"

    auto_definition = BuildGraphDefinition(
        graph_id="auto",
        tasks=(_task("automatic", required=True),),
    )
    auto_service = _service(tmp_path / "auto", definition=auto_definition)
    assert _commit(auto_service, "automatic").disposition == "PASS_AUTO"
    assert auto_service.inspect_task("automatic").status == "completed"


def test_readiness_distinguishes_required_and_optional_failures(tmp_path: Path):
    definition = BuildGraphDefinition(
        graph_id="readiness",
        tasks=(
            _task("required", required=True),
            _task("optional", validator_id="reject"),
        ),
    )
    service = _service(
        tmp_path,
        definition=definition,
        validators={"reject": lambda payload: False},
    )
    assert service.build_readiness().blocked_by == ("required",)
    _commit(service, "required")
    assert service.build_readiness().ready
    optional = _commit(service, "optional")
    assert optional.disposition == "FAIL"
    assert service.build_readiness().ready


def test_unsafe_task_ids_and_paths_are_rejected(tmp_path: Path):
    with pytest.raises(BuildDefinitionError) as task_error:
        BuildGraphDefinition(
            graph_id="unsafe",
            tasks=(_task("../escape"),),
        )
    assert task_error.value.code == "build_unsafe_task_id"

    with pytest.raises(BuildDefinitionError) as path_error:
        BuildGraphDefinition(
            graph_id="unsafe-path",
            tasks=(_task("root", owns=("../escape",)),),
        )
    assert path_error.value.code == "build_path_invalid"

    service = _service(tmp_path)
    with pytest.raises(BuildDefinitionError) as persisted_path_error:
        service.store.artifact_path("../escape", 1)
    assert persisted_path_error.value.code == "build_unsafe_path"


def test_artifact_history_is_immutable_and_readable(tmp_path: Path):
    service = _service(tmp_path)
    _commit(service, "foundation", payload={"nested": {"value": 1}})
    service.edit_artifact(
        "foundation",
        {"nested": {"value": 2}},
        expected_revision=1,
        requested_writes=("domain.foundation",),
    )

    history = service.artifact_history("foundation")
    assert [item.revision for item in history] == [1, 2]
    assert history[0].payload == {"nested": {"value": 1}}
    assert service.inspect_artifact("foundation", 1).payload == {"nested": {"value": 1}}
    assert (tmp_path / ".webnovel" / "build_artifacts" / "foundation" / "1.json").exists()


def test_run_failure_preserves_previous_artifact_and_persists_diagnostics(tmp_path: Path):
    service = _service(tmp_path)
    _commit(service, "foundation")
    run = service.start_run("world_rules")
    failure = service.fail_run(
        run.run_id,
        [BuildDiagnostic("synthetic.failure", "domain.world_rules", "failed")],
    )

    assert failure.status == "failed"
    assert service.inspect_task("world_rules").status == "validation_failed"
    assert service.inspect_artifact("world_rules") is None
    assert service.store.read_run(run.run_id).diagnostics[0].code == "synthetic.failure"


def test_opt_in_run_failure_preserves_existing_task_state_and_artifact(tmp_path: Path):
    service = _service(tmp_path)
    _commit(service, "foundation")
    _commit(service, "world_rules", payload={"task": "world_rules", "revision": 1})
    base_state = service.inspect_task("world_rules")
    run = service.start_run("world_rules", allow_completed_with_artifact=True)

    failure = service.fail_run(
        run.run_id,
        [BuildDiagnostic("repair.failure", "domain.world_rules", "repair failed")],
        preserve_task_state=base_state,
    )

    current = service.inspect_task("world_rules")
    assert failure.status == "failed"
    assert current.status == base_state.status == "completed"
    assert current.validation_status == base_state.validation_status == "passed"
    assert current.diagnostics == base_state.diagnostics
    assert current.current_artifact_revision == 1
    assert current.active_run_id is None
    assert service.inspect_artifact("world_rules").payload == {"task": "world_rules", "revision": 1}
    assert service.inspect_graph().runs[run.run_id].diagnostics[0].code == "repair.failure"


def test_opt_in_commit_validation_failure_preserves_task_state_and_skips_precommit(tmp_path: Path):
    invalid = False

    def validate_foundation(_payload):
        if invalid:
            return (BuildDiagnostic("foundation.invalid", "domain.foundation", "invalid candidate"),)
        return ()

    service = _service(
        tmp_path,
        definition=_definition(with_validator=True),
        validators={"foundation": validate_foundation},
    )
    _commit(service, "foundation", payload={"task": "foundation", "revision": 1})
    base_state = service.inspect_task("foundation")
    run = service.start_run("foundation", allow_completed_with_artifact=True)
    invalid = True
    before_commit_calls = []

    result = service.commit_run(
        run.run_id,
        {"task": "foundation", "revision": 2},
        requested_writes=("domain.foundation",),
        source="ai_repair",
        preserve_task_state_on_failure=base_state,
        before_commit=lambda: before_commit_calls.append(True),
    )

    current = service.inspect_task("foundation")
    assert result.artifact is None
    assert result.validation.diagnostics[0].code == "foundation.invalid"
    assert before_commit_calls == []
    assert current.status == base_state.status == "completed"
    assert current.validation_status == base_state.validation_status == "passed"
    assert current.current_artifact_revision == 1
    assert current.diagnostics == base_state.diagnostics
    assert service.inspect_artifact("foundation").payload == {"task": "foundation", "revision": 1}
    assert service.inspect_graph().runs[run.run_id].status == "failed"


def test_file_project_store_exposes_separate_build_graph_persistence(tmp_path: Path):
    project_store = FileProjectStore(tmp_path)
    definition = BuildGraphDefinition(
        graph_id="file-project",
        tasks=(_task("foundation", required=True),),
    )
    service = project_store.build_graph_service(definition)
    _commit(service, "foundation")

    state = project_store.build_graph_state()
    artifact = project_store.build_artifact("foundation")
    history = project_store.build_artifact_history("foundation")
    assert state["schema_version"] == "build-graph-state/v1"
    assert artifact["revision"] == 1
    assert history[0]["artifact_id"] == "foundation:1"
    assert (tmp_path / ".webnovel" / "build_graph.json").exists()
    assert (tmp_path / ".webnovel" / "build_artifacts" / "foundation" / "1.json").exists()
    assert not (tmp_path / ".webnovel" / "world_build_artifacts.json").exists()


def test_contract_diagnostics_round_trip():
    diagnostic = BuildDiagnostic("example.code", "a.b[1]", "message", "warning")
    assert BuildDiagnostic.from_dict(diagnostic.to_dict()) == diagnostic


def test_same_task_ids_but_changed_dependencies_reject_existing_state(tmp_path: Path):
    original = BuildGraphDefinition(
        graph_id="definition-compat",
        tasks=(_task("a"), _task("b")),
    )
    changed = BuildGraphDefinition(
        graph_id="definition-compat",
        tasks=(_task("a"), _task("b", dependencies=("a",))),
    )
    BuildGraphService(original, store=BuildGraphStore(tmp_path))

    with pytest.raises(BuildDefinitionError) as error:
        BuildGraphService(changed, store=BuildGraphStore(tmp_path))

    assert error.value.code == "build_graph_definition_mismatch"


def test_same_task_ids_but_changed_ownership_reject_existing_state(tmp_path: Path):
    original = BuildGraphDefinition(
        graph_id="ownership-compat",
        tasks=(_task("root", owns=("domain.root",)),),
    )
    changed = BuildGraphDefinition(
        graph_id="ownership-compat",
        tasks=(_task("root", owns=("domain.root.changed",)),),
    )
    BuildGraphService(original, store=BuildGraphStore(tmp_path))

    with pytest.raises(BuildDefinitionError) as error:
        BuildGraphService(changed, store=BuildGraphStore(tmp_path))

    assert error.value.code == "build_graph_definition_mismatch"


def test_changed_review_and_readiness_semantics_reject_existing_state(tmp_path: Path):
    original = BuildGraphDefinition(
        graph_id="policy-compat",
        tasks=(_task("root", required=False, review_policy="auto"),),
    )
    changed = BuildGraphDefinition(
        graph_id="policy-compat",
        tasks=(_task("root", required=True, review_policy="review"),),
    )
    BuildGraphService(original, store=BuildGraphStore(tmp_path))

    with pytest.raises(BuildDefinitionError) as error:
        BuildGraphService(changed, store=BuildGraphStore(tmp_path))

    assert error.value.code == "build_graph_definition_mismatch"


def test_unsupported_persisted_graph_state_schema_is_rejected(tmp_path: Path):
    definition = BuildGraphDefinition(
        graph_id="schema-compat",
        tasks=(_task("root"),),
    )
    store = BuildGraphStore(tmp_path)
    BuildGraphService(definition, store=store)
    raw = store.snapshot_store.read_json(store.state_path, {})
    raw["schema_version"] = "build-graph-state/v999"
    store.snapshot_store.write_json_atomic(store.state_path, raw)

    with pytest.raises(BuildDefinitionError) as error:
        BuildGraphService(definition, store=store)

    assert error.value.code == "build_graph_state_schema_unsupported"


def test_human_edit_atomically_supersedes_active_run_in_manifest_and_run_file(tmp_path: Path):
    service = _service(tmp_path)
    run = service.start_run("foundation")

    result = service.edit_artifact(
        "foundation",
        {"edited": True},
        expected_revision=None,
        requested_writes=("domain.foundation",),
    )

    manifest = service.inspect_graph()
    manifest_run = manifest.runs[run.run_id]
    persisted_run = service.store.read_run(run.run_id)
    assert result.artifact.revision == 1
    assert manifest_run.status == "conflict"
    assert persisted_run.status == "conflict"
    assert service.inspect_task("foundation").active_run_id is None


def test_stale_run_cannot_turn_into_validation_failure_via_fail_run(tmp_path: Path):
    service = _service(tmp_path)
    _commit(service, "foundation")
    run = service.start_run("world_rules")
    service.edit_artifact(
        "foundation",
        {"task": "foundation", "revision": 2},
        expected_revision=1,
        requested_writes=("domain.foundation",),
    )

    with pytest.raises(BuildRunConflict) as error:
        service.fail_run(
            run.run_id,
            [BuildDiagnostic("stale.failure", "domain.world_rules", "old run failed")],
        )

    assert error.value.code == "build_run_conflict"
    assert service.inspect_graph().runs[run.run_id].status == "conflict"
    assert service.store.read_run(run.run_id).status == "conflict"
    assert service.inspect_task("world_rules").status == "stale"
    assert service.inspect_task("world_rules").validation_status != "failed"
