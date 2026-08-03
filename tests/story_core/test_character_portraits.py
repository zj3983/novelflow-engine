import ast
import inspect

import pytest

from packages.story_core.character_portraits import _portrait_kind, complete_character_portrait
from packages.story_core.models import CharacterState, NPCBehaviorProfile, PersonalityPortrait


def test_character_state_defaults_to_an_empty_personality_portrait():
    portrait = CharacterState(name="Lin", role="supporting").personality_portrait

    assert portrait == PersonalityPortrait()


def test_internal_supporting_role_does_not_leak_into_chinese_portrait():
    character = CharacterState(
        name="小乐",
        role="supporting",
        personality_portrait=PersonalityPortrait.model_validate(
            {
                "temperament": {
                    "outward_impression": "在修仙中以supporting的立场参与局面",
                    "values": ["围绕supporting行动"],
                },
                "psychology": {"desire": "围绕supporting行动"},
                "growth": {
                    "invariants": ["保留独立驱动力：围绕supporting行动"],
                    "stage_direction": "围绕supporting调整个人目标与关系位置",
                },
            }
        ),
    )

    completed = complete_character_portrait(character, genre="修仙")
    serialized = completed.personality_portrait.model_dump_json()

    assert "supporting" not in serialized
    assert "自身目标与当前关系" in serialized


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


@pytest.mark.parametrize(
    "role",
    ["protagonist", "main character", "lead character", "主角", "男主", "女主"],
)
def test_protagonist_classification_accepts_only_normalized_labels(role):
    assert _portrait_kind(CharacterState(name="Lin", role=f"  {role}  "), "") == "protagonist"


@pytest.mark.parametrize(
    ("role", "story_function"),
    [
        ("misleading witness", "reveals a contradiction"),
        ("merchant prince", "funds an expedition"),
        ("bodyguard and confidant", "protects an old friend"),
        ("NPC", "mechanic"),
    ],
)
def test_broad_english_substrings_do_not_change_character_kind(role, story_function):
    character = CharacterState(name="Mara", role=role)

    assert _portrait_kind(character, story_function) == "recurring_support"


def test_non_blank_npc_service_role_takes_priority_after_stripping():
    character = CharacterState(
        name="Mara",
        role="recurring NPC",
        npc_profile=NPCBehaviorProfile(service_role="  archive keeper  "),
    )

    assert _portrait_kind(character, "") == "service_npc"


def test_blank_npc_service_role_does_not_force_service_classification():
    character = CharacterState(
        name="Mara",
        role="NPC",
        npc_profile=NPCBehaviorProfile(service_role="   "),
    )

    assert _portrait_kind(character, "") == "recurring_support"


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

    assert _portrait_kind(character, "") == "recurring_support"


def test_recurring_support_template_changes_with_genre():
    character = CharacterState(
        name="Mara",
        role="recurring NPC",
        character_type="long-term NPC",
        core_motivation="查清旧友失踪的真相",
    )

    cultivation = complete_character_portrait(character, "修仙")
    urban_mystery = complete_character_portrait(character, "都市悬疑")

    assert cultivation.personality_portrait != urban_mystery.personality_portrait
    assert "修仙" in cultivation.personality_portrait.temperament.outward_impression
    assert "都市悬疑" in urban_mystery.personality_portrait.temperament.outward_impression
    assert (
        cultivation.personality_portrait.behavior.pressure_mode
        != urban_mystery.personality_portrait.behavior.pressure_mode
    )
    assert (
        cultivation.personality_portrait.behavior.decision_tendency
        != urban_mystery.personality_portrait.behavior.decision_tendency
    )


def test_character_story_function_can_identify_an_explicit_service_npc():
    character = CharacterState(
        name="Mara",
        role="NPC",
        story_function="archive clerk / 档案登记服务",
    )

    assert _portrait_kind(character, "") == "service_npc"


def test_mentor_needs_an_explicit_service_duty_to_use_service_template():
    life_mentor = CharacterState(name="Mara", role="mentor", story_function="人生导师与长期盟友")
    trial_clerk = CharacterState(name="Iris", role="导师", story_function="在柜台办理试炼登记")

    assert _portrait_kind(life_mentor, "") == "recurring_support"
    assert _portrait_kind(trial_clerk, "") == "service_npc"


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


def test_service_roles_and_incentives_produce_distinct_behavior():
    characters = [
        CharacterState(
            name="Mara",
            role="商人",
            npc_profile=NPCBehaviorProfile(service_role="商人", incentives=["保持利润和稳定货源"]),
        ),
        CharacterState(
            name="Iris",
            role="守卫",
            npc_profile=NPCBehaviorProfile(service_role="守卫", incentives=["守住入口并避免同伴受伤"]),
        ),
        CharacterState(
            name="Noa",
            role="药剂师",
            npc_profile=NPCBehaviorProfile(service_role="药剂师", incentives=["保住药材并维持配方信誉"]),
        ),
    ]

    portraits = [
        complete_character_portrait(character, "都市").personality_portrait
        for character in characters
    ]

    assert len({portrait.behavior.decision_tendency for portrait in portraits}) == 3
    for character, portrait in zip(characters, portraits):
        assert character.npc_profile.incentives[0] in (
            portrait.psychology.desire + portrait.behavior.decision_tendency
        )
        assert character.npc_profile.service_role in portrait.behavior.decision_tendency


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


def test_completion_replaces_whitespace_only_portrait_strings():
    character = CharacterState(
        name="Lin",
        role="main character",
        personality_portrait=PersonalityPortrait.model_validate(
            {
                "psychology": {"desire": "   "},
                "behavior": {"pressure_mode": "\t"},
            }
        ),
    )

    completed = complete_character_portrait(character, "悬疑")

    assert completed.personality_portrait.psychology.desire.strip()
    assert completed.personality_portrait.behavior.pressure_mode.strip()


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

    imports = set()
    for node in ast.walk(ast.parse(inspect.getsource(module))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.add(node.module)
            imports.update(alias.name for alias in node.names)

    assert not any("provider" in imported.lower() for imported in imports)
