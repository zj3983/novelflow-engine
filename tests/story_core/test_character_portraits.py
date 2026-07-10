import ast
import inspect

from packages.story_core.character_portraits import complete_character_portrait
from packages.story_core.models import CharacterState, PersonalityPortrait


def test_character_state_defaults_to_an_empty_personality_portrait():
    portrait = CharacterState(name="Lin", role="supporting").personality_portrait

    assert portrait == PersonalityPortrait()


def test_protagonist_portrait_has_required_detail():
    character = CharacterState(
        name="Lin",
        role="protagonist",
        core_motivation="protect the last safe district",
        behavior_logic="checks the cost before taking a risk",
    )

    completed = complete_character_portrait(
        character,
        genre="urban fantasy",
        story_function="lead the investigation and pay its personal cost",
    )
    portrait = completed.personality_portrait

    assert portrait.temperament.core_traits
    assert portrait.psychology.desire
    assert portrait.psychology.fear
    assert portrait.behavior.pressure_mode
    assert portrait.behavior.conflict_response
    assert portrait.emotion.triggers
    assert portrait.voice.lying_style
    assert portrait.growth.invariants
    assert portrait.writing_limits
    assert "protect the last safe district" in portrait.psychology.desire


def test_service_npc_uses_a_distinct_job_boundary_template():
    protagonist = complete_character_portrait(
        CharacterState(name="Lin", role="protagonist"),
        genre="mystery",
    )
    clerk = complete_character_portrait(
        CharacterState(
            name="Mara",
            role="service NPC",
            behavior_logic="protects the archive before helping visitors",
        ),
        genre="mystery",
        story_function="archive counter clerk who controls record access",
    )

    portrait = clerk.personality_portrait
    assert portrait != protagonist.personality_portrait
    assert "archive counter clerk" in portrait.psychology.desire
    assert portrait.social.strangers
    assert portrait.social.authority
    assert portrait.social.strangers != portrait.social.authority
    assert portrait.temperament.bottom_line
    assert portrait.emotion.mannerisms


def test_recurring_npc_is_classified_as_recurring_support():
    character = CharacterState(
        name="Mara",
        role="recurring NPC",
        character_type="long-term NPC",
        story_function="maintains an independent alliance with the lead",
    )

    completed = complete_character_portrait(character, genre="mystery")

    assert completed.personality_portrait.temperament.core_traits == [
        "有自己的利害判断",
        "重视关系中的对等",
    ]
    assert "岗位利益" not in completed.personality_portrait.temperament.core_traits


def test_service_npc_template_absorbs_motivation_and_genre():
    fantasy_clerk = complete_character_portrait(
        CharacterState(
            name="Mara",
            role="登记员",
            core_motivation="保住家族留下的登记册",
            behavior_logic="先核对凭据，再决定开放哪一层记录",
        ),
        genre="奇幻",
        story_function="档案登记员",
    )
    science_fiction_clerk = complete_character_portrait(
        CharacterState(
            name="Mara",
            role="登记员",
            core_motivation="保住家族留下的登记册",
            behavior_logic="先核对凭据，再决定开放哪一层记录",
        ),
        genre="科幻",
        story_function="档案登记员",
    )

    fantasy_portrait = fantasy_clerk.personality_portrait
    assert "保住家族留下的登记册" in (
        fantasy_portrait.psychology.desire + fantasy_portrait.behavior.decision_tendency
    )
    assert fantasy_portrait != science_fiction_clerk.personality_portrait


def test_complete_character_portrait_accepts_positional_context_arguments():
    completed = complete_character_portrait(
        CharacterState(name="Mara", role="商人"),
        "历史",
        "经营驿站",
    )

    assert completed.personality_portrait.psychology.desire


def test_completion_preserves_every_non_empty_user_field():
    portrait = PersonalityPortrait.model_validate(
        {
            "temperament": {
                "outward_impression": "user outward impression",
                "core_traits": ["user trait"],
            },
            "psychology": {"desire": "user desire"},
            "behavior": {"pressure_mode": "user pressure mode"},
            "emotion": {"triggers": ["user trigger"]},
            "social": {"authority": "user authority stance"},
            "voice": {
                "common_words": ["user phrase"],
                "lying_style": "user lying style",
            },
            "growth": {"invariants": ["user invariant"]},
            "writing_limits": ["user writing limit"],
        }
    )
    character = CharacterState(
        name="Lin",
        role="protagonist",
        personality_portrait=portrait,
    )

    completed = complete_character_portrait(character, genre="science fiction")

    assert completed.personality_portrait.temperament.outward_impression == "user outward impression"
    assert completed.personality_portrait.temperament.core_traits == ["user trait"]
    assert completed.personality_portrait.psychology.desire == "user desire"
    assert completed.personality_portrait.behavior.pressure_mode == "user pressure mode"
    assert completed.personality_portrait.emotion.triggers == ["user trigger"]
    assert completed.personality_portrait.social.authority == "user authority stance"
    assert completed.personality_portrait.voice.common_words == ["user phrase"]
    assert completed.personality_portrait.voice.lying_style == "user lying style"
    assert completed.personality_portrait.growth.invariants == ["user invariant"]
    assert completed.personality_portrait.writing_limits == ["user writing limit"]


def test_completion_returns_a_copy_without_mutating_the_input():
    character = CharacterState(name="Lin", role="protagonist")
    before = character.model_dump()

    completed = complete_character_portrait(character, genre="fantasy")

    assert completed is not character
    assert character.model_dump() == before
    assert character.personality_portrait == PersonalityPortrait()
    assert completed.personality_portrait != character.personality_portrait


def test_character_portraits_module_has_no_model_provider_dependency():
    module = inspect.getmodule(complete_character_portrait)
    assert module is not None

    imports = {
        alias.name
        for node in ast.walk(ast.parse(inspect.getsource(module)))
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }

    assert not any("provider" in imported.lower() for imported in imports)
