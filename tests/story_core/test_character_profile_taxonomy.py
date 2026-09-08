from __future__ import annotations

from packages.story_core.character_profiles import (
    character_profile_completeness,
    character_profile_quality_issues,
    find_character_homogeneity_issues,
    infer_character_taxonomy,
    normalize_character_profile,
)


def _complete_core_card(**overrides: object) -> dict[str, object]:
    card: dict[str, object] = {
        "name": "苏叶",
        "role": "protagonist",
        "character_tier": "protagonist",
        "identity_profile": {
            "origin": "临海市旧城区长大，大学退学后靠自由职业维生",
            "current_identity": "自由职业者兼《天启之门》玩家",
            "occupation": "自由职业者",
        },
        "current_life_profile": {
            "immediate_problem": "发现自己的隐藏协议会留下可被公会审计追踪的异常日志",
        },
        "story_drive": {
            "long_term_goal": "查清混沌协议来源并摆脱幕后组织对账号和现实身份的控制",
            "immediate_goal": "在下一次结算前找出异常日志保存位置并做一份离线证据副本",
            "motivation": "三年前哥哥因同类异常被永久封号后失踪，他不愿再次让线索被系统抹掉",
            "failure_stakes": "账号会被永久冻结，哥哥留下的最后一条调查线索也会随日志一起被删除",
            "hidden_matters": ["他没有告诉队友哥哥也遇到过相同异常"],
        },
        "performance_profile": {
            "speech_style": "先确认事实再表态，熟人面前会把担心和理由说完整",
            "action_style": "先留证据，再做可逆试探，确认异常后才扩大行动",
        },
        "dialogue_examples": [
            "先别急着交任务，我要把这条异常日志的时间戳抄下来。",
            "如果他们真能改后台记录，那我们手里必须留一份系统外的证据。",
        ],
        "relationship_notes": [
            {
                "target": "林澈",
                "relation_type": "ally",
                "history": "两人在新手副本因共享隐藏任务认识",
                "current_attitude": "认可对方判断力，但还没有完全坦白哥哥失踪的旧事",
                "shared_interest_or_conflict": "都想查清异常来源，但风险偏好不同",
            }
        ],
    }
    card.update(overrides)
    return card


def test_legacy_character_tier_maps_to_two_axis_taxonomy() -> None:
    importance, narrative_function = infer_character_taxonomy(
        {
            "name": "赵衡",
            "role": "stage antagonist",
            "character_tier": "stage_antagonist",
        }
    )

    assert importance == "major"
    assert narrative_function == "stage_antagonist"


def test_normalizer_adds_taxonomy_status_and_completeness_without_removing_legacy_tier() -> None:
    normalized = normalize_character_profile(_complete_core_card())

    assert normalized["character_tier"] == "protagonist"
    assert normalized["importance"] == "core"
    assert normalized["narrative_function"] == "protagonist"
    assert normalized["profile_status"] == "ready"
    assert normalized["profile_completeness"] >= 80


def test_incomplete_important_character_is_marked_stub_instead_of_ready() -> None:
    normalized = normalize_character_profile(
        {
            "name": "幕后长老",
            "role": "long_term_antagonist",
            "character_tier": "long_term_antagonist",
            "identity_profile": {"current_identity": "执法堂长老"},
            "story_drive": {"long_term_goal": "封死旧案"},
        }
    )

    assert normalized["importance"] == "core"
    assert normalized["narrative_function"] == "long_term_antagonist"
    assert normalized["profile_status"] == "stub"


def test_explicit_ready_is_downgraded_when_role_specific_fields_are_missing() -> None:
    card = _complete_core_card(
        profile_status="ready",
        performance_profile={"speech_style": "", "action_style": ""},
        story_drive={
            **_complete_core_card()["story_drive"],
            "hidden_matters": [],
        },
    )

    normalized = normalize_character_profile(card)

    assert normalized["profile_status"] == "stub"


def test_explicit_new_taxonomy_wins_over_legacy_supporting_bucket() -> None:
    importance, narrative_function = infer_character_taxonomy(
        {
            "name": "林澈",
            "role": "supporting",
            "character_tier": "supporting",
            "importance": "major",
            "narrative_function": "ally",
        }
    )

    assert importance == "major"
    assert narrative_function == "ally"


def test_quality_guard_rejects_goal_copied_as_motivation() -> None:
    card = _complete_core_card()
    card["story_drive"] = {
        "long_term_goal": "查清混沌协议是谁植入账号的",
        "immediate_goal": "找到异常日志的保存位置",
        "motivation": "找到异常日志的保存位置",
        "failure_stakes": "日志会在结算后被清理，哥哥失踪前留下的线索也会断掉",
    }

    issues = character_profile_quality_issues(card)

    assert "motivation_duplicates_immediate_goal" in issues


def test_quality_guard_flags_abstract_character_content() -> None:
    card = _complete_core_card()
    card["story_drive"] = {
        "long_term_goal": "不断成长",
        "immediate_goal": "完成目标",
        "motivation": "为了变强",
        "failure_stakes": "会很惨",
    }

    issues = character_profile_quality_issues(card)

    assert "generic:story_drive.long_term_goal" in issues
    assert "generic:story_drive.immediate_goal" in issues
    assert "generic:story_drive.motivation" in issues
    assert "generic:story_drive.failure_stakes" in issues


def test_homogeneity_guard_reports_only_characters_sharing_exact_generated_content() -> None:
    cards = [
        _complete_core_card(),
        {
            **_complete_core_card(),
            "name": "林澈",
            "role": "ally",
            "character_tier": "supporting",
        },
        {
            **_complete_core_card(),
            "name": "赵衡",
            "role": "stage_antagonist",
            "character_tier": "stage_antagonist",
            "story_drive": {
                "long_term_goal": "拿到公会审计权限并接替现任会长",
                "immediate_goal": "逼苏叶交出异常副本的坐标",
                "motivation": "他只有交出异常账号才能换取审计组正式席位",
                "failure_stakes": "审计组会把他从候选名单除名并追查他私下调用权限的记录",
            },
        },
    ]

    issues = find_character_homogeneity_issues(cards)

    assert "苏叶" in issues
    assert "林澈" in issues
    assert any(item == "duplicate:story_drive.motivation" for item in issues["苏叶"])
    assert "duplicate:story_drive.motivation" not in issues.get("赵衡", [])


def test_completeness_score_does_not_treat_empty_structural_fields_as_content() -> None:
    score = character_profile_completeness(
        {
            "identity_profile": {"current_identity": ""},
            "current_life_profile": {"immediate_problem": ""},
            "story_drive": {
                "long_term_goal": "",
                "immediate_goal": "",
                "motivation": "",
                "failure_stakes": "",
            },
            "dialogue_examples": [],
            "relationship_notes": [],
        }
    )

    assert score == 0


def test_completeness_score_counts_role_specific_fields_and_concrete_relationships() -> None:
    card = _complete_core_card()
    card["identity_profile"] = {
        "current_identity": "自由职业者兼玩家",
        "occupation": "自由职业者",
    }
    card["performance_profile"] = {"speech_style": "", "action_style": ""}
    card["story_drive"] = {
        **card["story_drive"],
        "hidden_matters": [],
    }
    card["relationship_notes"] = [{"target": "林澈"}]

    assert character_profile_completeness(card) < 100
