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
