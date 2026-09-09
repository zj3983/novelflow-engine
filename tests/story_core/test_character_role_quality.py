from __future__ import annotations

import pytest

from packages.story_core.character_profiles import character_profile_quality_issues
from packages.story_core.models import CharacterState
from packages.story_core.outline_planning import PlanningCharacterCard
from packages.story_core.outline_planning_generation import (
    _validate_character_card_roster_quality,
)


def _card(
    *,
    name: str = "苏叶",
    role: str = "protagonist",
    character_tier: str = "protagonist",
    importance: str = "core",
    narrative_function: str = "protagonist",
    profile_status: str = "ready",
) -> dict[str, object]:
    return {
        "name": name,
        "role": role,
        "character_tier": character_tier,
        "importance": importance,
        "narrative_function": narrative_function,
        "profile_status": profile_status,
        "identity_profile": {
            "origin": "临海旧城区长大，退学后靠接外包维生",
            "current_identity": "自由职业者兼《天启之门》玩家",
            "occupation": "自由职业者",
        },
        "background_profile": {},
        "current_life_profile": {
            "authority_scope": "只能控制自己的设备、账号和个人调查资料",
            "immediate_problem": "异常日志即将被公会审计程序清理",
        },
        "story_drive": {
            "long_term_goal": "查清哥哥失踪和混沌协议之间的联系",
            "immediate_goal": "在下一次结算前复制异常日志",
            "motivation": "哥哥失踪前留下的最后线索就在同类异常日志里",
            "failure_stakes": "日志被删后，他将失去唯一能继续追查哥哥的证据",
            "main_conflict_reason": "审计组要删除异常记录，而他必须保留原始证据",
            "hidden_matters": ["他没有告诉队友哥哥也遇到过相同异常"],
        },
        "performance_profile": {
            "speech_style": "先确认事实再表态，对熟人会把担心和理由说完整",
            "action_style": "先留证据，再做可逆试探，最后扩大行动",
        },
        "dialogue_examples": [
            "先别交任务，我把这条异常日志的时间戳抄下来。",
            "如果后台也能改记录，我们就得留一份系统外证据。",
        ],
        "relationship_notes": [
            {
                "target": "林澈",
                "relation_type": "ally",
                "history": "两人在新手副本共同保住过一次异常掉落记录",
                "current_attitude": "认可对方判断力，但尚未坦白哥哥失踪的旧事",
                "shared_interest_or_conflict": "都想追查异常来源，但风险偏好不同",
            }
        ],
    }


def test_protagonist_ready_card_requires_origin_voice_behavior_and_hidden_information() -> None:
    card = _card()
    card["identity_profile"] = {"current_identity": "玩家"}
    card["performance_profile"] = {"speech_style": "", "action_style": ""}
    card["story_drive"] = {
        **card["story_drive"],
        "hidden_matters": [],
    }

    issues = character_profile_quality_issues(card)

    assert "missing:identity_profile.origin" in issues
    assert "missing:performance_profile.speech_style" in issues
    assert "missing:performance_profile.action_style" in issues
    assert "missing:story_drive.hidden_matters" in issues


def test_stage_antagonist_ready_card_requires_power_conflict_reason_and_tactics() -> None:
    card = _card(
        name="赵衡",
        role="stage antagonist",
        character_tier="stage_antagonist",
        importance="major",
        narrative_function="stage_antagonist",
    )
    card["current_life_profile"] = {
        "immediate_problem": "审计席位将在本周重新评定",
        "authority_scope": "",
    }
    card["story_drive"] = {
        "long_term_goal": "进入正式审计组",
        "immediate_goal": "拿到苏叶的异常副本坐标",
        "motivation": "只有交出异常账号，他才能换到正式席位",
        "failure_stakes": "会被移出候选名单并追查违规权限调用",
        "main_conflict_reason": "",
        "hidden_matters": [],
    }
    card["performance_profile"] = {
        "speech_style": "先给可接受条件，再逐步收紧选择",
        "action_style": "",
    }

    issues = character_profile_quality_issues(card)

    assert "missing:current_life_profile.authority_scope" in issues
    assert "missing:story_drive.main_conflict_reason" in issues
    assert "missing:performance_profile.action_style" in issues


def test_long_term_antagonist_ready_card_requires_scope_deep_conflict_and_hidden_matter() -> None:
    card = _card(
        name="顾闻舟",
        role="long term antagonist",
        character_tier="long_term_antagonist",
        importance="core",
        narrative_function="long_term_antagonist",
    )
    card["current_life_profile"] = {
        "immediate_problem": "内部审计开始追查旧协议",
        "authority_scope": "",
    }
    card["story_drive"] = {
        "long_term_goal": "控制全部异常协议入口",
        "immediate_goal": "让当前审计只停留在账号违规层面",
        "motivation": "旧协议一旦公开，他经营多年的权限网络会被追溯",
        "failure_stakes": "会失去协议控制权并暴露过去的违规实验",
        "main_conflict_reason": "",
        "hidden_matters": [],
    }

    issues = character_profile_quality_issues(card)

    assert "missing:current_life_profile.authority_scope" in issues
    assert "missing:story_drive.main_conflict_reason" in issues
    assert "missing:story_drive.hidden_matters" in issues


def test_supporting_stub_can_remain_lightweight_without_full_ready_fields() -> None:
    card = {
        "name": "周岚",
        "role": "resource contact",
        "character_tier": "supporting",
        "importance": "supporting",
        "narrative_function": "resource_contact",
        "profile_status": "stub",
        "identity_profile": {"current_identity": "灰港旧货商"},
        "story_drive": {},
        "relationship_notes": [
            {
                "target": "苏叶",
                "relation_type": "resource_contact",
                "history": "苏叶通过林澈拿到她的一次性联络码",
                "current_attitude": "只交换可验证情报",
                "shared_interest_or_conflict": "双方都想避开公会审计",
            }
        ],
    }

    assert character_profile_quality_issues(card) == []


def test_card_roster_quality_rejects_core_stub_and_hollow_relationship_note() -> None:
    card = _card(profile_status="stub")
    card["relationship_notes"] = [{"target": "林澈"}]
    parsed = PlanningCharacterCard.model_validate(card)

    with pytest.raises(ValueError) as exc_info:
        _validate_character_card_roster_quality([parsed], enforce_tier_status=True)

    message = str(exc_info.value)
    assert "core_requires_ready" in message
    assert "missing:relationship_notes.relation_type" in message
    assert "missing:relationship_notes.history" in message
    assert "missing:relationship_notes.current_attitude" in message
    assert "missing:relationship_notes.shared_interest_or_conflict" in message


def test_card_roster_quality_rejects_generic_performance_content() -> None:
    card = _card()
    card["performance_profile"] = {
        "speech_style": "不善言辞",
        "action_style": "观察后行动",
    }
    parsed = PlanningCharacterCard.model_validate(card)

    with pytest.raises(ValueError, match=r"generic:performance_profile\.speech_style"):
        _validate_character_card_roster_quality([parsed], enforce_tier_status=True)


def test_planning_character_card_migrates_legacy_tier_without_manual_new_fields() -> None:
    legacy = _card()
    for field in ("importance", "narrative_function", "profile_status"):
        legacy.pop(field)

    card = PlanningCharacterCard.model_validate(legacy)

    assert card.character_tier == "protagonist"
    assert card.importance == "core"
    assert card.narrative_function == "protagonist"
    assert card.profile_status == "ready"
    assert 0 < card.profile_completeness <= 100


def test_character_state_migrates_legacy_tier_without_manual_new_fields() -> None:
    state = CharacterState(
        name="赵衡",
        role="stage antagonist",
        character_tier="stage_antagonist",
        identity_profile={"current_identity": "公会审计候选人"},
        story_drive={"immediate_goal": "拿到异常副本"},
    )

    assert state.character_tier == "stage_antagonist"
    assert state.importance == "major"
    assert state.narrative_function == "stage_antagonist"
    assert state.profile_status == "stub"
    assert state.profile_completeness > 0


def test_explicit_new_taxonomy_wins_during_legacy_compatible_read() -> None:
    state = CharacterState(
        name="林澈",
        role="supporting",
        character_tier="supporting",
        importance="major",
        narrative_function="ally",
        profile_status="stub",
        profile_completeness=25,
    )

    assert state.character_tier == "supporting"
    assert state.importance == "major"
    assert state.narrative_function == "ally"
    assert state.profile_status == "stub"
    assert state.profile_completeness == 0


def test_character_state_recomputes_stale_ready_and_completeness_metadata() -> None:
    state = CharacterState(
        name="林澈",
        role="protagonist",
        character_tier="protagonist",
        profile_status="ready",
        profile_completeness=99,
        identity_profile={"current_identity": "灰港调查员"},
        story_drive={"immediate_goal": "保住证据"},
    )

    assert state.profile_status == "stub"
    assert state.profile_completeness < 99


def test_explicit_stub_intent_survives_a_complete_card_but_score_is_derived() -> None:
    card = _card(profile_status="stub")
    state = CharacterState.model_validate({**card, "profile_completeness": 100})

    assert state.profile_status == "stub"
    assert state.profile_completeness == 100
