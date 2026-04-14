from packages.story_core.character_agent import CharacterAgent
from packages.story_core.models import CharacterProposal, CharacterState, StoryState
from packages.story_core.runtime_config import OpenAIRuntimeSettings


class FakeLLMCharacterProvider:
    def propose_all(self, story: StoryState):
        return [
            CharacterProposal(
                name="Lin Yue",
                goal="seize the witness",
                emotion="alert",
                action="presses the lead harder than the rules allow",
                priority=99,
                new_character_candidates=["Old Archivist"],
            )
        ]


def test_openai_character_provider_uses_runtime_settings(monkeypatch):
    captured = {}

    def fake_runtime_settings(agent_name=None):
        captured["agent_name"] = agent_name
        return OpenAIRuntimeSettings(
            api_key="sk-test-123",
            base_url="https://api.example.com/v1",
        )

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'{"choices":[{"message":{"content":"{\\"proposals\\":[{\\"name\\":\\"Lin Yue\\",\\"goal\\":\\"find the witness\\",\\"emotion\\":\\"alert\\",\\"action\\":\\"presses the lead\\",\\"priority\\":9,\\"new_character_candidates\\":[]}]}"}}]}'
                )

        return _Response()

    monkeypatch.setattr(
        "packages.story_core.agent_base.resolve_openai_runtime_settings",
        fake_runtime_settings,
    )
    monkeypatch.setattr("packages.story_core.http_retry.urllib.request.urlopen", fake_urlopen)

    story = StoryState(
        story_id="s-agent-runtime",
        outline="A court witness arrives under a false name.",
        genre="mystery",
        style="tense",
        agent_settings={"mode": "LLM-assisted"},
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    proposals = CharacterAgent().propose_all(story)

    assert captured["agent_name"] == "character"
    assert captured["url"] == "https://api.example.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-test-123"
    assert proposals[0].name == "Lin Yue"


def test_openai_character_provider_uses_character_specific_runtime_settings(monkeypatch):
    captured = {}

    def fake_runtime_settings(agent_name=None):
        captured.setdefault("calls", []).append(agent_name)
        if agent_name == "character":
            return OpenAIRuntimeSettings(
                api_key="sk-character-123",
                base_url="https://character.example.com/v1",
            )
        return OpenAIRuntimeSettings(
            api_key="sk-global-123",
            base_url="https://api.example.com/v1",
        )

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'{"choices":[{"message":{"content":"{\\"proposals\\":[{\\"name\\":\\"Lin Yue\\",\\"goal\\":\\"find the witness\\",\\"emotion\\":\\"alert\\",\\"action\\":\\"presses the lead\\",\\"priority\\":9,\\"new_character_candidates\\":[]}]}"}}]}'
                )

        return _Response()

    monkeypatch.setattr(
        "packages.story_core.agent_base.resolve_openai_runtime_settings",
        fake_runtime_settings,
    )
    monkeypatch.setattr("packages.story_core.http_retry.urllib.request.urlopen", fake_urlopen)

    story = StoryState(
        story_id="s-agent-runtime-specific",
        outline="A court witness arrives under a false name.",
        genre="mystery",
        style="tense",
        agent_settings={"mode": "LLM-assisted"},
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    proposals = CharacterAgent().propose_all(story)

    assert "character" in captured["calls"]
    assert captured["url"] == "https://character.example.com/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-character-123"
    assert proposals[0].name == "Lin Yue"


def test_character_agent_emits_new_character_candidate_when_secret_mentions_archivist():
    story = StoryState(
        story_id="s-agent-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                secrets=["Old archivist knows where the wax seal came from."],
            )
        ],
    )

    proposal = CharacterAgent().propose(story, story.characters[0])

    assert "Old Archivist" in proposal.new_character_candidates


def test_character_agent_propose_all_filters_non_active_or_frozen_characters():
    story = StoryState(
        story_id="s-agent-002",
        outline="A court drifts toward open fracture.",
        genre="mystery",
        style="tense",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="alert",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                frozen=True,
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                lifecycle_state="proposed",
            ),
        ],
    )

    proposals = CharacterAgent().propose_all(story)

    assert [proposal.name for proposal in proposals] == ["Lin Yue"]


def test_character_agent_uses_injected_llm_provider_when_assisted_mode_is_enabled():
    story = StoryState(
        story_id="s-agent-003",
        outline="A court witness shifts the balance of power.",
        genre="mystery",
        style="tense",
        agent_settings={
            "mode": "LLM-assisted",
        },
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    agent = CharacterAgent(llm_provider=FakeLLMCharacterProvider())
    proposals = agent.propose_all(story)

    assert [proposal.name for proposal in proposals] == ["Lin Yue"]
    assert proposals[0].priority == 99
    assert proposals[0].action == "presses the lead harder than the rules allow"


def test_character_agent_falls_back_to_global_default_model_when_character_model_is_blank(monkeypatch):
    captured = {}

    def fake_runtime_settings(agent_name=None):
        return OpenAIRuntimeSettings(
            api_key="sk-test-123",
            base_url="https://api.example.com/v1",
        )

    def fake_urlopen(request, timeout=30):
        captured["body"] = request.data.decode("utf-8")

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return (
                    b'{"choices":[{"message":{"content":"{\\"proposals\\":[{\\"name\\":\\"Lin Yue\\",\\"goal\\":\\"find the witness\\",\\"emotion\\":\\"alert\\",\\"action\\":\\"presses the lead\\",\\"priority\\":9,\\"new_character_candidates\\":[]}]}"}}]}'
                )

        return _Response()

    monkeypatch.setattr(
        "packages.story_core.agent_base.resolve_openai_runtime_settings",
        fake_runtime_settings,
    )
    monkeypatch.setattr("packages.story_core.http_retry.urllib.request.urlopen", fake_urlopen)

    story = StoryState(
        story_id="s-agent-runtime-global-model",
        outline="A court witness arrives under a false name.",
        genre="mystery",
        style="tense",
        agent_settings={
            "mode": "LLM-assisted",
            "global_model": "gpt-global",
            "character_model": "",
        },
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    proposals = CharacterAgent().propose_all(story)

    assert '"model": "gpt-global"' in captured["body"]
    assert proposals[0].name == "Lin Yue"
