"""Projection contracts intentionally reject free-form content."""
from dataclasses import replace
import json

from packages.story_core.build_public import capability_projection, graph_projection
from packages.story_core.build_graph import BuildGraphDefinition, BuildGraphService, BuildGraphStore, BuildTaskDefinition
from packages.story_core.model_gateway.capabilities import CapabilityRecord, CapabilityProvenance, ModelIdentity, ModelProfile


def test_required_tasks_block_readiness_until_completed(tmp_path):
    definition = BuildGraphDefinition(graph_id="synthetic", tasks=(BuildTaskDefinition(
        task_id="required", title="Required", required_for_readiness=True, owns=("world.rules",), review_policy="review"),))
    store = BuildGraphStore(tmp_path)
    service = BuildGraphService(definition, store=store)
    result = graph_projection(definition, store.read_state(), store)
    assert not result["readiness"]["ready"]
    service.commit_candidate("required", {"body": "PRIVATE"}, expected_revision=None)
    result = graph_projection(definition, store.read_state(), store)
    assert result["readiness"]["blockers"] == [{"task_id": "required", "code": "review_required"}]
    assert "PRIVATE" not in json.dumps(result)
    service.accept_review("required", expected_revision=1)
    assert graph_projection(definition, store.read_state(), store)["readiness"]["ready"]


def test_profile_omits_endpoint_notes_arbitrary_values_and_timestamps():
    secret = "PRIVATE_TOKEN"
    identity = ModelIdentity("openai", "codex_cli", "https://user:secret@private.test/secret", "model-x")
    record = CapabilityRecord("supported", {"raw_response": secret}, CapabilityProvenance(
        source="runtime_observation", verified_at=secret, note=secret))
    profile = ModelProfile(identity, effective_capabilities={"streaming": record}, limits={"context_window": record})
    result = capability_projection(profile)
    text = json.dumps(result)
    assert all(value not in text for value in (secret, "private.test", "raw_response", "note"))
    assert result["limits"]["context_window"]["value"] is None
    assert result["capabilities"]["streaming"]["verified_at"] is None
    assert result["capabilities"]["json_mode"]["state"] == "unknown"
    assert result["output_budget_enforcement"] == "best_effort"


def test_capability_verification_cannot_be_forged_or_survive_unknown():
    identity = ModelIdentity("openai", "openai", "https://example.test", "model-x")
    forged = CapabilityRecord("supported", True, CapabilityProvenance(source="user_declared", verification_status="verified"))
    expired = CapabilityRecord("unknown", None, CapabilityProvenance(source="runtime_observation", verification_status="verified", expires_at="2000-01-01T00:00:00+00:00"))
    profile = ModelProfile(identity, effective_capabilities={"streaming": forged, "json_mode": expired})
    result = capability_projection(profile)["capabilities"]
    assert result["streaming"]["verification_status"] == "declared"
    assert result["json_mode"]["state"] == "unknown"
    assert result["json_mode"]["verification_status"] == "unknown"


def test_next_volume_projection_uses_confirmed_authority(monkeypatch):
    from types import SimpleNamespace
    from packages.story_core.build_public import lifecycle_projection
    from packages.story_core.opening_build import execution, runtime
    state = SimpleNamespace(graph_revision=90, tasks={"plan": SimpleNamespace(status="completed", active_run_id=None, current_artifact_revision=2)})
    store = SimpleNamespace(state=lambda: {"current_chapter": 50}, build_graph_materialization=lambda: {})
    config = {"chapter_count": 50, "execution": {"source_fingerprint": "confirmed-hash", "graph_revision": 90}}
    monkeypatch.setattr(execution, "source_fingerprint", lambda _: "confirmed-hash")
    monkeypatch.setattr(runtime, "canonical_plan", lambda _: SimpleNamespace(outline=SimpleNamespace(arcs=[SimpleNamespace(start_chapter=51, end_chapter=100)])))
    result = lifecycle_projection(store, state, config, "p-synthetic", [])
    assert result["phase"] == "next_volume"
    action = result["actions"][0]
    assert action["action"] == "extend_next_volume"
    assert action["body"] == {"expected_graph_revision": 90}
    assert action["preconditions"]["confirmed_through"] == 50
    monkeypatch.setattr(execution, "source_fingerprint", lambda _: "changed")
    result = lifecycle_projection(store, state, config, "p-synthetic", [])
    assert result["actions"] == []
    assert result["blockers"] == [{"code": "opening_prose_source_conflict"}]
