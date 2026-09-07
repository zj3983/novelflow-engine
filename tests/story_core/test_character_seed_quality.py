from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.story_core.outline_planning_generation import (
    PlanningCharacterSeed,
    _expand_character_seed,
    _validate_character_seed_roster_quality,
)


def _seed(
    name: str = "苏叶",
    *,
    target: str = "林澈",
    role: str = "protagonist",
    character_tier: str = "protagonist",
    motivation: str = "哥哥因同类异常失踪，他不愿让最后一条线索再次被系统抹掉",
    immediate_goal: str = "在结算前找到异常日志保存位置并做一份离线副本",
    long_term_goal: str = "查清混沌协议来源并摆脱幕后组织对现实身份的控制",
    speech_style: str = "先确认事实再表态，熟人面前会直接说明担心和理由",
    action_style: str = "先留证据，再做低风险试探，确认异常后才扩大行动",
) -> dict[str, object]:
    return {
        "name": name,
        "role": role,
        "character_tier": character_tier,
        "first_appearance": 1,
        "age": 24,
        "origin": "临海市旧城区长大，大学退学后靠自由职业维生",
        "current_identity": "自由职业者兼《天启之门》玩家",
        "occupation": "自由职业者",
        "authority_scope": "只能控制自己的账号、设备和个人调查资料",
        "immediate_problem": "隐藏协议正在留下可能被公会审计追踪的异常日志",
        "immediate_goal": immediate_goal,
        "motivation": motivation,
        "long_term_goal": long_term_goal,
        "failure_stakes": "账号会被永久冻结，哥哥失踪前留下的调查线索也会一起消失",
        "personality": "谨慎但不逃避风险，遇到证据冲突时会优先复核而不是争辩",
        "speech_style": speech_style,
        "action_style": action_style,
        "emotional_trigger": "有人试图删除或否认已经出现的异常证据",
        "decision_rule": "可逆风险先试探，不可逆风险先备份证据再行动",
        "hidden_matter": "他没有告诉队友哥哥的失踪与同类异常有关",
        "dialogue_examples": [
            "先别交任务，我把这条异常日志的时间戳抄下来。",
            "如果后台记录也能改，我们手里就必须留一份系统外的证据。",
        ],
        "relationship_notes": [
            {
                "target": target,
                "relation_type": "ally",
                "history": "两人在新手副本因共享隐藏任务认识，并共同保住过一次异常掉落记录",
                "current_attitude": "认可对方的判断力，但还没有完全坦白哥哥失踪的旧事",
                "shared_interest_or_conflict": "都想查清异常来源，但苏叶更重视留证，林澈更愿意快速追击",
                "known_facts": ["林澈知道苏叶在追查异常日志"],
                "unknown_facts": ["林澈不知道苏叶哥哥的失踪与异常有关"],
            }
        ],
    }


def test_character_seed_requires_independent_motivation() -> None:
    payload = _seed()
    payload.pop("motivation")

    with pytest.raises(ValidationError):
        PlanningCharacterSeed.model_validate(payload)


def test_character_seed_requires_at_least_one_relationship_note() -> None:
    payload = _seed()
    payload["relationship_notes"] = []

    with pytest.raises(ValidationError):
        PlanningCharacterSeed.model_validate(payload)


def test_expand_character_seed_preserves_distinct_motivation_and_relationship() -> None:
    seed = PlanningCharacterSeed.model_validate(_seed())

    card = _expand_character_seed(seed)

    assert card.story_drive.immediate_goal == "在结算前找到异常日志保存位置并做一份离线副本"
    assert card.story_drive.motivation == "哥哥因同类异常失踪，他不愿让最后一条线索再次被系统抹掉"
    assert card.story_drive.motivation != card.story_drive.immediate_goal
    assert len(card.relationship_notes) == 1
    assert card.relationship_notes[0].target == "林澈"
    assert card.relationship_notes[0].history.startswith("两人在新手副本")


def test_character_seed_quality_rejects_goal_copied_as_motivation() -> None:
    payload = _seed()
    payload["motivation"] = payload["immediate_goal"]
    seed = PlanningCharacterSeed.model_validate(payload)

    with pytest.raises(ValueError, match="motivation_duplicates_immediate_goal"):
        _validate_character_seed_roster_quality([seed], existing_names={"林澈"})


def test_character_seed_quality_rejects_generic_motivation() -> None:
    seed = PlanningCharacterSeed.model_validate(_seed(motivation="为了变强"))

    with pytest.raises(ValueError, match=r"generic:story_drive\.motivation"):
        _validate_character_seed_roster_quality([seed], existing_names={"林澈"})


def test_character_seed_quality_rejects_self_only_relationship() -> None:
    seed = PlanningCharacterSeed.model_validate(_seed(target="苏叶"))

    with pytest.raises(ValueError, match="relationship_targets_self"):
        _validate_character_seed_roster_quality([seed])


def test_character_seed_quality_rejects_exact_cross_character_homogeneity() -> None:
    first = PlanningCharacterSeed.model_validate(_seed())
    second = PlanningCharacterSeed.model_validate(
        _seed(
            "林澈",
            target="苏叶",
            role="ally",
            character_tier="supporting",
        )
    )

    with pytest.raises(ValueError, match="duplicate:story_drive.motivation"):
        _validate_character_seed_roster_quality([first, second])


def test_character_seed_quality_accepts_distinct_reciprocal_roster() -> None:
    first = PlanningCharacterSeed.model_validate(_seed())
    second = PlanningCharacterSeed.model_validate(
        _seed(
            "林澈",
            target="苏叶",
            role="ally",
            character_tier="supporting",
            motivation="她曾因犹豫错过一次救援窗口，因此无法接受线索再次在眼前消失",
            immediate_goal="在审计组封锁副本前确认异常坐标对应的真实入口",
            long_term_goal="建立不依赖公会后台的异常事件情报网络",
            speech_style="对熟人会先说结论再补担忧，遇到陌生人则用问题确认对方掌握多少",
            action_style="倾向先抢时间窗口，再用队友留下的证据补足风险控制",
        )
    )

    _validate_character_seed_roster_quality([first, second])
