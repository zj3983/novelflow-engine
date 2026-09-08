from __future__ import annotations

from copy import deepcopy

import pytest

from packages.story_core.outline_planning_generation import (
    PlanningCharacterSeed,
    _expand_character_seed,
    _failed_character_names_from_quality_error,
    _merge_repaired_character_rows,
    _validate_character_seed_roster_quality,
)


def _seed(
    name: str = "苏叶",
    *,
    target: str = "林澈",
    role: str = "protagonist",
    character_tier: str = "protagonist",
    importance: str | None = None,
    narrative_function: str | None = None,
    profile_status: str | None = None,
    first_appearance: int = 1,
    motivation: str = "哥哥因同类异常失踪，他不愿让最后一条线索再次被系统抹掉",
    immediate_goal: str = "在结算前找到异常日志保存位置并做一份离线副本",
    long_term_goal: str = "查清混沌协议来源并摆脱幕后组织对现实身份的控制",
    authority_scope: str = "只能控制自己的账号、设备和个人调查资料",
    main_conflict_reason: str = "审计组要删除异常记录，而他必须保住能追查哥哥失踪的原始证据",
    speech_style: str = "先确认事实再表态，熟人面前会直接说明担心和理由",
    action_style: str = "先留证据，再做低风险试探，确认异常后才扩大行动",
    personality: str = "谨慎但不逃避风险，遇到证据冲突时会优先复核而不是争辩",
    hidden_matter: str = "他没有告诉队友哥哥的失踪与同类异常有关",
) -> dict[str, object]:
    payload: dict[str, object] = {
        "name": name,
        "role": role,
        "character_tier": character_tier,
        "first_appearance": first_appearance,
        "age": 24,
        "origin": "临海市旧城区长大，大学退学后靠自由职业维生",
        "current_identity": "自由职业者兼《天启之门》玩家",
        "occupation": "自由职业者",
        "authority_scope": authority_scope,
        "immediate_problem": "隐藏协议正在留下可能被公会审计追踪的异常日志",
        "immediate_goal": immediate_goal,
        "motivation": motivation,
        "long_term_goal": long_term_goal,
        "failure_stakes": "账号会被永久冻结，哥哥失踪前留下的调查线索也会一起消失",
        "main_conflict_reason": main_conflict_reason,
        "personality": personality,
        "speech_style": speech_style,
        "action_style": action_style,
        "emotional_trigger": "有人试图删除或否认已经出现的异常证据",
        "decision_rule": "可逆风险先试探，不可逆风险先备份证据再行动",
        "hidden_matter": hidden_matter,
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
    if importance is not None:
        payload["importance"] = importance
    if narrative_function is not None:
        payload["narrative_function"] = narrative_function
    if profile_status is not None:
        payload["profile_status"] = profile_status
    return payload


def test_missing_motivation_turns_legacy_core_seed_into_stub_then_quality_rejects_it() -> None:
    payload = _seed()
    payload.pop("motivation")

    seed = PlanningCharacterSeed.model_validate(payload)

    assert seed.profile_status == "stub"
    with pytest.raises(ValueError, match="core_requires_ready"):
        _validate_character_seed_roster_quality([seed], existing_names={"林澈"})


def test_missing_relationship_turns_legacy_core_seed_into_stub_then_quality_rejects_it() -> None:
    payload = _seed()
    payload["relationship_notes"] = []

    seed = PlanningCharacterSeed.model_validate(payload)

    assert seed.profile_status == "stub"
    with pytest.raises(ValueError, match="core_requires_ready"):
        _validate_character_seed_roster_quality([seed])


def test_expand_character_seed_preserves_distinct_motivation_relationship_and_taxonomy() -> None:
    seed = PlanningCharacterSeed.model_validate(_seed())

    card = _expand_character_seed(seed)

    assert card.story_drive.immediate_goal == "在结算前找到异常日志保存位置并做一份离线副本"
    assert card.story_drive.motivation == "哥哥因同类异常失踪，他不愿让最后一条线索再次被系统抹掉"
    assert card.story_drive.motivation != card.story_drive.immediate_goal
    assert card.importance == "core"
    assert card.narrative_function == "protagonist"
    assert card.profile_status == "ready"
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


def test_character_seed_quality_rejects_generic_ready_personality() -> None:
    seed = PlanningCharacterSeed.model_validate(
        _seed(personality="冷静、聪明、谨慎", profile_status="ready")
    )

    with pytest.raises(ValueError, match=r"generic:personality"):
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
            importance="major",
            narrative_function="ally",
            profile_status="ready",
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
            importance="major",
            narrative_function="ally",
            profile_status="ready",
            motivation="她曾因犹豫错过一次救援窗口，因此无法接受线索再次在眼前消失",
            immediate_goal="在审计组封锁副本前确认异常坐标对应的真实入口",
            long_term_goal="建立不依赖公会后台的异常事件情报网络",
            speech_style="对熟人会先说结论再补担忧，遇到陌生人则用问题确认对方掌握多少",
            action_style="倾向先抢时间窗口，再用队友留下的证据补足风险控制",
        )
    )

    _validate_character_seed_roster_quality([first, second])


def test_later_supporting_character_can_remain_lightweight_stub() -> None:
    seed = PlanningCharacterSeed.model_validate(
        {
            "name": "周岚",
            "role": "resource contact",
            "character_tier": "supporting",
            "importance": "supporting",
            "narrative_function": "resource_contact",
            "profile_status": "stub",
            "first_appearance": 48,
            "current_identity": "灰港旧货商",
            "relationship_notes": [
                {
                    "target": "苏叶",
                    "relation_type": "resource_contact",
                    "history": "苏叶曾通过林澈拿到她的一次性联络码",
                    "current_attitude": "只愿交换可验证的异常物品情报",
                    "shared_interest_or_conflict": "双方都想避开公会审计，但她不会无条件帮忙",
                }
            ],
        }
    )

    assert seed.profile_status == "stub"
    _validate_character_seed_roster_quality([seed], existing_names={"苏叶"})


def test_failed_character_name_parser_returns_only_failed_names() -> None:
    error = (
        "character_profile_quality_failed:林澈[generic:personality];"
        "赵衡[missing:story_drive.main_conflict_reason,missing:dialogue_examples]"
    )

    assert _failed_character_names_from_quality_error(error) == ["林澈", "赵衡"]
    assert _failed_character_names_from_quality_error("chapter_contract_missing:1") == []


def test_targeted_repair_replaces_only_failed_character_and_preserves_valid_rows() -> None:
    valid_row = {"name": "苏叶", "role": "protagonist", "marker": {"keep": [1, 2, 3]}}
    failed_row = {"name": "赵衡", "role": "stage_antagonist", "motivation": "为了变强"}
    original = {
        "outline": {"overall": {"title": "不要动"}},
        "characters": [deepcopy(valid_row), deepcopy(failed_row)],
    }
    repaired = {
        "characters": [
            {
                "name": "赵衡",
                "role": "stage_antagonist",
                "motivation": "只有交出异常账号，他才能换到审计组正式席位",
            }
        ]
    }

    merged = _merge_repaired_character_rows(original, repaired, ["赵衡"])

    assert merged["outline"] == original["outline"]
    assert merged["characters"][0] == valid_row
    assert merged["characters"][1] == repaired["characters"][0]
    assert original["characters"][1] == failed_row


def test_targeted_repair_rejects_name_mismatch() -> None:
    original = {"characters": [{"name": "赵衡"}, {"name": "林澈"}]}
    repaired = {"characters": [{"name": "另一个人"}]}

    with pytest.raises(ValueError, match="character_repair_name_mismatch"):
        _merge_repaired_character_rows(original, repaired, ["赵衡"])
