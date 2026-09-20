from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.story_core.agents import _runtime_common
from packages.story_core.agents.pipeline import _character_intents_for_context
from packages.story_core.agents.pipeline_artifacts import record_character_intent_stage
from packages.story_core.character_agent import CharacterAgent, OpenAICharacterProposalProvider
from packages.story_core.context.director_context import DirectorContext
from packages.story_core.model_gateway import ModelRequest, ModelResponse
from packages.story_core.models import CharacterProposal, CharacterState, StoryState
from packages.story_core.persistence.workflow_artifact_store import StageArtifactRecord, WorkflowArtifactStore
from packages.story_core.prompt_call_log import PromptCallLog, prompt_call_recording


def _runtime(monkeypatch):
    monkeypatch.setattr(
        _runtime_common,
        "_resolve_stage_settings",
        lambda stage: SimpleNamespace(provider_id="custom_openai", model="k3", protocol="openai_compatible", temperature=0.7),
    )


def test_character_full_request_uses_planner_binding_and_canonical_call_log(tmp_path, monkeypatch):
    _runtime(monkeypatch)

    class Gateway:
        def complete_stage(self, stage, request):
            self.stage, self.request = stage, request
            return ModelResponse.success(request, text='{"proposals": []}')

    gateway = Gateway()
    provider = OpenAICharacterProposalProvider(model_gateway=gateway)
    request = ModelRequest(
        prompt="character user prompt", system_prompt="character system prompt",
        messages=({"role": "user", "content": "extra"},),
        provider="stale_provider", model="stale_character_model", operation="character",
        temperature=0.7, max_tokens=1620, json_mode=True, timeout_seconds=19,
        metadata={"chapter_number": 5, "custom": "kept"},
    )
    log = PromptCallLog(tmp_path, project_id="file:test")
    with prompt_call_recording(log):
        assert provider.complete(request).ok
    assert gateway.stage == "planner"
    assert gateway.request.provider == "custom_openai"
    assert gateway.request.model == "k3"
    assert gateway.request.system_prompt == request.system_prompt
    assert gateway.request.messages == request.messages
    assert gateway.request.max_tokens == 1620
    assert gateway.request.json_mode is True
    assert gateway.request.timeout_seconds == 19
    assert gateway.request.metadata == request.metadata
    assert gateway.request.operation == "character"
    detail = log.get(log.list(chapter_number=5)[0]["call_id"])
    assert (detail["stage"], detail["agent"], detail["provider"], detail["protocol"], detail["model"]) == (
        "planner", "character", "custom_openai", "openai_compatible", "k3"
    )
    assert detail["status"] == "succeeded"
    assert detail["temperature"] == 0.7
    assert detail["system_prompt"] == "character system prompt"
    assert detail["user_prompt"] == "character user prompt"


def test_character_logged_effective_temperature_after_compat_retry(tmp_path, monkeypatch):
    _runtime(monkeypatch)

    class Gateway:
        def complete_stage(self, stage, request):
            return ModelResponse(
                ok=True, text='{"proposals": []}', provider=request.provider,
                model=request.model, operation=request.operation, temperature_omitted=True,
            )

    request = ModelRequest(prompt="prompt", provider="old", model="old", operation="character", temperature=0.7)
    log = PromptCallLog(tmp_path, project_id="file:test")
    with prompt_call_recording(log):
        OpenAICharacterProposalProvider(model_gateway=Gateway()).complete(request)
    assert log.list()[0]["temperature"] is None


def test_failed_character_model_call_is_logged_under_planner(tmp_path, monkeypatch):
    _runtime(monkeypatch)

    class Gateway:
        def complete_stage(self, stage, request):
            return ModelResponse.failure(request, "authentication_failed")

    log = PromptCallLog(tmp_path, project_id="file:test")
    request = ModelRequest(prompt="intent prompt", provider="old", model="old", operation="character", system_prompt="intent system")
    with prompt_call_recording(log):
        assert not OpenAICharacterProposalProvider(model_gateway=Gateway()).complete(request).ok
    detail = log.get(log.list()[0]["call_id"])
    assert detail["stage"] == "planner" and detail["agent"] == "character"
    assert detail["status"] == "failed" and detail["error"] == "authentication_failed"
    assert detail["system_prompt"] == "intent system"


def _story():
    return StoryState(
        story_id="source-test", outline="比试后", genre="玄幻", style="自然",
        current_chapter=2,
        outline_context={"chapter": {"chapter_number": 3, "cast": ["林渊"]}},
        characters=[CharacterState(name="林渊", role="protagonist")],
    )


def _context():
    return DirectorContext(
        chapter_number=3, volume={}, book_outline_summary="",
        nearby_outline=[{"number": 3, "cast": ["林渊"]}],
    )


@pytest.mark.parametrize("llm_fails,rule_fails,expected", [
    (False, False, "llm"), (True, False, "rule_fallback"), (True, True, "empty"),
])
def test_character_stage_result_source_matches_actual_provider(tmp_path, llm_fails, rule_fails, expected):
    proposal = CharacterProposal(name="林渊", goal="守住名次", action="观察")

    class Provider:
        def __init__(self, fails):
            self.fails = fails

        def propose_all(self, story):
            if self.fails:
                raise RuntimeError("unavailable")
            return [proposal]

    story = _story()
    story.agent_settings.mode = "LLM-assisted"
    agent = CharacterAgent(llm_provider=Provider(llm_fails), rule_provider=Provider(rule_fails))
    source = {}
    intents = _character_intents_for_context(story, _context(), 3, agent=agent, result_source_out=source)
    assert source["result_source"] == expected
    assert len(intents) == (0 if expected == "empty" else 1)
    store = WorkflowArtifactStore(tmp_path)
    record_character_intent_stage(store=store, job_id="chapter-3", intents=intents, result_source=source["result_source"], provider="custom_openai", model="k3")
    saved = store.read_stage("chapter-3", "character-intent")
    assert saved is not None and saved.result_source == expected
    assert (saved.provider, saved.model) == ("custom_openai", "k3")
    assert StageArtifactRecord.from_dict({"stage_id": "character-intent", "agent_id": "CharacterAgent", "status": "done"}).result_source == ""
