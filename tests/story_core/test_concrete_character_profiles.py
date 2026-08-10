from __future__ import annotations

import pytest

from packages.story_core.character_profiles import (
    filter_character_cards,
    is_placeholder_character_name,
    is_non_character_card,
    merge_character_alias_cards,
    merge_character_profile,
    normalize_character_profile,
    normalize_speech_style_for_writing,
    project_character_for_writer,
    remove_cross_character_aliases,
)


@pytest.mark.parametrize(
    "name",
    ["底层执行者", "幕后黑手", "幕后黑手（开发商高层）", "数据分析师"],
)
def test_placeholder_role_label_is_not_accepted_as_character_name(name: str) -> None:
    assert is_placeholder_character_name(name)


@pytest.mark.parametrize("name", ["刘大军", "赵衡", "林警官"])
def test_concrete_person_name_is_not_treated_as_placeholder(name: str) -> None:
    assert not is_placeholder_character_name(name)


def test_functional_market_entity_is_not_a_character_card() -> None:
    cards = filter_character_cards(
        [
            {"name": "白河仓库收购方", "role": "收购方NPC"},
            {"name": "药剂师洛婶", "role": "服务NPC"},
        ]
    )

    assert is_non_character_card({"name": "白河仓库收购方", "role": "收购方NPC"})
    assert [card["name"] for card in cards] == ["药剂师洛婶"]
from packages.story_core.models import CharacterState


def test_character_state_accepts_concrete_identity_and_life_details() -> None:
    character = CharacterState(
        name="林照",
        role="protagonist",
        character_tier="protagonist",
        first_appearance=1,
        identity_profile={
            "age": 19,
            "birthplace": "青石镇",
            "origin": "镇上木匠的次子",
            "current_identity": "外门杂役",
            "occupation": "看守祖祠",
        },
        background_profile={
            "family": "父亲仍在青石镇做木匠",
            "education_or_training": "只学过三个月外门吐纳",
        },
        current_life_profile={
            "residence": "外门西院通铺",
            "livelihood": "靠宗门杂役份例生活",
            "immediate_problem": "守住断香炉并弄清第三块青砖",
        },
        story_drive={
            "long_term_goal": "在宗门站稳并查清旧案",
            "immediate_goal": "阻止赵衡挖开青砖",
            "failure_stakes": "失去外门身份并被当作毁祠者",
        },
        dialogue_examples=["赵管事，祖祠昨夜有人来过，我得先把这件事报清楚。"],
    )

    payload = character.model_dump()

    assert payload["identity_profile"]["age"] == 19
    assert payload["identity_profile"]["occupation"] == "看守祖祠"
    assert payload["background_profile"]["family"]
    assert payload["current_life_profile"]["livelihood"]
    assert payload["story_drive"]["failure_stakes"]
    assert payload["dialogue_examples"][0].endswith("报清楚。")


def test_generated_patch_never_overwrites_non_empty_user_fields() -> None:
    existing = {
        "name": "林照",
        "role": "protagonist",
        "identity_profile": {"age": 19, "occupation": "守祠杂役", "origin": ""},
        "dialogue_examples": ["我先把来龙去脉问清楚。"],
    }
    generated = {
        "name": "林照",
        "role": "主角",
        "identity_profile": {"age": 18, "occupation": "外门弟子", "origin": "木匠之子"},
        "dialogue_examples": ["我不答应。"],
    }

    merged = merge_character_profile(existing, generated)

    assert merged["role"] == "protagonist"
    assert merged["identity_profile"] == {
        "age": 19,
        "occupation": "守祠杂役",
        "origin": "木匠之子",
    }
    assert merged["dialogue_examples"] == ["我先把来龙去脉问清楚。"]


def test_profile_merge_does_not_turn_blank_existing_field_into_null_when_patch_omits_it() -> None:
    existing = {
        "current_life_profile": {
            "residence": "出租屋",
            "economic_state": "",
            "immediate_problem": "",
        },
        "story_drive": {"long_term_goal": "查清异常", "immediate_goal": ""},
    }
    generated = {
        "current_life_profile": {"residence": "出租屋"},
        "story_drive": {"long_term_goal": "查清异常"},
    }

    merged = merge_character_profile(existing, generated)

    assert merged["current_life_profile"]["economic_state"] == ""
    assert merged["current_life_profile"]["immediate_problem"] == ""
    assert merged["story_drive"]["immediate_goal"] == ""


def test_speech_normalizer_softens_quiet_and_short_sentence_synonyms() -> None:
    normalized = normalize_speech_style_for_writing(
        "话不多但说完整，短句起步，关键判断会补一句理由。"
    )

    assert "话不多" not in normalized
    assert "短句起步" not in normalized
    assert "对象、原因和决定要说完整" in normalized


def test_legacy_card_normalizes_without_losing_existing_fields() -> None:
    legacy = {
        "name": "赵管事",
        "role": "outer_manager",
        "motivation": "把责任推出去",
        "personality": "不耐烦",
        "speech_style": "交代差事时会把责任说清楚",
    }

    normalized = normalize_character_profile(legacy)

    assert normalized["motivation"] == "把责任推出去"
    assert normalized["personality"] == "不耐烦"
    assert normalized["identity_profile"]["age"] is None
    assert normalized["story_drive"]["motivation"] == "把责任推出去"
    assert normalized["performance_profile"]["speech_style"] == "交代差事时会把责任说清楚"


def test_remove_cross_character_aliases_keeps_distinct_character_cards_separate() -> None:
    cards = [
        {
            "name": "小乐",
            "identity_profile": {"aliases": ["乐乐", "小哑巴"]},
        },
        {
            "name": "小哑巴",
            "identity_profile": {"aliases": []},
        },
    ]

    cleaned = remove_cross_character_aliases(cards)

    assert cleaned[0]["identity_profile"]["aliases"] == ["乐乐"]
    assert cleaned[1]["identity_profile"]["aliases"] == []


def test_merge_character_alias_cards_joins_real_name_and_game_id() -> None:
    cards = [
        {"name": "夜烬", "role": "主角，现实身份苏叶", "story_drive": {"immediate_goal": "验证异常"}},
        {
            "name": "苏叶",
            "role": "protagonist",
            "game_id": "夜烬",
            "game_state": {"current": {"game_id": "夜烬", "level": 3}},
            "identity_profile": {"occupation": "自由职业者"},
        },
    ]

    merged = merge_character_alias_cards(cards)

    assert len(merged) == 1
    assert merged[0]["name"] == "苏叶"
    assert merged[0]["game_id"] == "夜烬"
    assert merged[0]["story_drive"]["immediate_goal"] == "验证异常"
    assert merged[0]["identity_profile"]["occupation"] == "自由职业者"
    assert merged[0]["identity_profile"]["aliases"] == ["夜烬"]


def test_writer_projection_hides_unreleased_secrets() -> None:
    card = {
        "name": "幕后长老",
        "role": "long_term_antagonist",
        "character_tier": "long_term_antagonist",
        "story_drive": {
            "long_term_goal": "封死旧案",
            "hidden_matters": ["他亲手换掉旧名册", "他控制赵衡"],
        },
        "secrets": ["真实身份是执法堂首座"],
        "relationship_notes": [
            {
                "target": "赵衡",
                "known_facts": ["赵衡替他办事"],
                "unknown_facts": ["赵衡留了旧账副本", "赵衡准备倒戈"],
            }
        ],
    }

    hidden = project_character_for_writer(card)
    partly_revealed = project_character_for_writer(card, allowed_reveals={"他控制赵衡"})

    assert hidden["story_drive"]["hidden_matters"] == []
    assert hidden["secrets"] == []
    assert hidden["relationship_notes"][0]["known_facts"] == ["赵衡替他办事"]
    assert hidden["relationship_notes"][0]["unknown_facts"] == []
    assert partly_revealed["story_drive"]["hidden_matters"] == ["他控制赵衡"]
