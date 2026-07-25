from packages.story_core.models import AgentRuntimeState, AgentSettings, CharacterState, StoryState


def test_agent_settings_defaults_follow_environment_models(monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_DEFAULT_MODEL", "qwen3.6-plus")
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FAST_MODEL", "qwen3.6-plus-fast")

    settings = AgentSettings()

    assert settings.global_model == "qwen3.6-plus"
    assert settings.director_model == "qwen3.6-plus"
    assert settings.writer_model == "qwen3.6-plus"
    assert settings.memory_model == "qwen3.6-plus"
    assert settings.character_model == "qwen3.6-plus-fast"


def test_agent_settings_migrates_provider_configured_mode():
    settings = AgentSettings.model_validate({"mode": "provider-configured"})

    assert settings.mode == "LLM-assisted"


def test_agent_runtime_state_uses_only_writing_stages():
    runtime = AgentRuntimeState()

    assert runtime.model_dump() == {
        "planner": {
            "source": "idle",
            "provider": "",
            "model": "",
            "fallback_reason": "",
            "last_run_chapter": 0,
        },
        "writer": {
            "source": "idle",
            "provider": "",
            "model": "",
            "fallback_reason": "",
            "last_run_chapter": 0,
        },
        "memory": {
            "source": "idle",
            "provider": "",
            "model": "",
            "fallback_reason": "",
            "last_run_chapter": 0,
        },
        "recent_events": [],
    }


def test_agent_runtime_state_migrates_legacy_agents_and_discards_character():
    runtime = AgentRuntimeState.model_validate(
        {
            "character_agent": {"source": "llm", "last_run_chapter": 9},
            "director_agent": {"source": "llm", "last_run_chapter": 3},
            "writer_agent": {
                "source": "fallback",
                "fallback_reason": "writer timeout",
                "last_run_chapter": 3,
            },
            "memory_agent": {"source": "llm", "last_run_chapter": 3},
            "recent_events": ["legacy event"],
        }
    )

    serialized = runtime.model_dump()
    assert serialized["planner"]["source"] == "llm"
    assert serialized["writer"]["fallback_reason"] == "writer timeout"
    assert serialized["memory"]["last_run_chapter"] == 3
    assert "character_agent" not in serialized
    assert "director_agent" not in serialized
    assert "writer_agent" not in serialized
    assert "memory_agent" not in serialized


def test_runtime_module_does_not_expose_retired_agent_reporting():
    from packages.story_core import runtime

    assert not hasattr(runtime, "record_agent_runtime")


def test_story_state_can_store_outline_and_chapter_index():
    story = StoryState(
        story_id="s-001",
        outline="A fallen prince becomes a detective.",
        genre="fantasy",
        style="moody",
        current_chapter=1,
    )
    assert story.story_id == "s-001"
    assert story.current_chapter == 1


def test_character_state_supports_memory_and_goals():
    character = CharacterState(
        name="Lin Yue",
        role="protagonist",
        traits={"impulsive": 0.7, "patient": 0.2},
        goals=["find the truth"],
    )
    assert "find the truth" in character.goals
    assert character.traits["impulsive"] == 0.7


def test_character_state_supports_lifecycle_tracking_fields():
    character = CharacterState(
        name="Old Archivist",
        role="supporting",
        lifecycle_state="proposed",
        last_proposed_chapter=3,
        last_approved_chapter=0,
        introduced_by="Su Wan",
    )

    assert character.lifecycle_state == "proposed"
    assert character.last_proposed_chapter == 3
    assert character.last_approved_chapter == 0
    assert character.introduced_by == "Su Wan"


def test_character_state_normalizes_frozen_lifecycle():
    character = CharacterState(
        name="Old Archivist",
        role="supporting",
        frozen=True,
    )

    assert character.frozen is True
    assert character.lifecycle_state == "frozen"
