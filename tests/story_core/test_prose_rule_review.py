import pytest

from packages.story_core.prose_rule_review import (
    CRITICAL_PROMPT_RULES,
    review_critical_prose_rules,
    review_ai_flavor,
    review_diagnostic_terms_in_body,
    review_npc_boundary_violation,
    review_paragraph_opener_repetition,
    review_pov_breach,
    review_system_tag_density,
)


def test_critical_prompt_rules_name_actual_quality_gates():
    joined = "\n".join(CRITICAL_PROMPT_RULES)

    assert "段首主语不得连续3段相同" in joined
    assert "NPC只能讲岗位范围内的信息" in joined
    assert "公会内部频道" in joined
    assert "暴露度" in joined
    assert "【系统提示：】每章最多4次" in joined


def test_review_flags_fact_template_backend_terms_and_guide_terms():
    body = "他前世做外包测试时养成习惯。暴露度1。公会关注1。系统风险0。微光弹的施法前摇变长，伤害数字从15跌到12。"

    review = review_diagnostic_terms_in_body(body)

    assert not review["pass"]
    assert any("事实模板错误" in issue for issue in review["issues"])
    assert any("后台/审稿术语" in issue for issue in review["issues"])
    assert any("攻略说明" in issue for issue in review["issues"])


def test_review_flags_planning_language_materialized_as_a_location():
    body = "周满站在前置条件边，等林照开口。"

    review = review_diagnostic_terms_in_body(body)

    assert review["pass"] is False
    assert any("站在前置条件边" in issue for issue in review["issues"])
    assert review["scores"]["planning_meta_leak"] == 5
    assert any("实际门" in item and "任务要求" in item for item in review["revision_plan"])


def test_review_allows_planning_words_used_as_actual_task_requirements():
    body = "这个任务需要先完成前置条件，赵管事才肯放人。"

    review = review_diagnostic_terms_in_body(body)

    assert review["pass"] is True
    assert review["scores"]["planning_meta_leak"] == 8


def test_review_allows_vr_prose_that_reads_a_task_requirement():
    review = review_diagnostic_terms_in_body("他看向任务说明里的前置条件。")

    assert review["pass"] is True
    assert review["scores"]["planning_meta_leak"] == 8


@pytest.mark.parametrize(
    "body",
    [
        "隐藏职业让他绕过任务前置条件，直接进入副本。",
        "隐藏职业让他跨过任务前置条件，直接进入副本。",
        "迈出前置条件满足后的第一步。",
    ],
)
def test_review_allows_abstract_rules_and_longer_phrases(body):
    review = review_diagnostic_terms_in_body(body)

    assert review["pass"] is True
    assert review["scores"]["planning_meta_leak"] == 8


@pytest.mark.parametrize(
    "body",
    [
        "视线停在任务前置条件后续说明上。",
        "任务进度停在前置条件后续检查阶段。",
        "他站在前置条件边界之外思考规则。",
    ],
)
def test_review_does_not_truncate_longer_words_as_location_suffixes(body):
    review = review_diagnostic_terms_in_body(body)

    assert review["pass"] is True
    assert review["scores"]["planning_meta_leak"] == 8


def test_review_does_not_treat_another_characters_gaze_as_a_ui_subject():
    body = "周满迎着赵管事的视线推开了前置条件。"

    review = review_critical_prose_rules(body)

    assert review["scores"]["planning_meta_leak"] == 5
    assert review["severity_summary"]["has_hard_violation"] is True
    assert any("推开了前置条件" in issue for issue in review["hard_issues"])


@pytest.mark.parametrize(
    ("body", "expected_hit"),
    [
        ("周满站在前置条件旁边，等林照开口。", "站在前置条件旁边"),
        ("周满站在前置条件边上。", "站在前置条件边上"),
        ("周满站在前置条件边上的台阶。", "站在前置条件边上"),
        ("周满站在前置条件旁边的人身后。", "站在前置条件旁边"),
        ("周满站在前置条件的旁边。", "站在前置条件的旁边"),
        ("周满走到剧情节点的后面。", "走到剧情节点的后面"),
        ("周满站在前置条件后方。", "站在前置条件后方"),
        ("周满站在前置条件前方。", "站在前置条件前方"),
    ],
)
def test_review_flags_compound_planning_meta_locations(body, expected_hit):
    review = review_diagnostic_terms_in_body(body)

    assert review["pass"] is False
    assert review["scores"]["planning_meta_leak"] == 5
    assert any(expected_hit in issue for issue in review["issues"])


@pytest.mark.parametrize("continuation", ["时", "后", "前", "之后", "以前", "的时候"])
def test_review_flags_planning_meta_actions_with_sentence_continuations(continuation):
    phrase = f"推开前置条件{continuation}"
    review = review_diagnostic_terms_in_body(f"周满{phrase}，林照退了一步。")

    assert review["pass"] is False
    assert review["scores"]["planning_meta_leak"] == 5
    assert any(phrase in issue for issue in review["issues"])


@pytest.mark.parametrize(
    ("body", "expected_hit"),
    [
        ("周满推开前置条件后继续前进。", "推开前置条件后"),
        ("周满把剧情节点推开后继续前进。", "把剧情节点推开后"),
    ],
)
def test_review_flags_action_continuations_without_punctuation(body, expected_hit):
    review = review_diagnostic_terms_in_body(body)

    assert review["pass"] is False
    assert review["scores"]["planning_meta_leak"] == 5
    assert any(expected_hit in issue for issue in review["issues"])


@pytest.mark.parametrize(
    "phrase",
    [
        "站在“前置条件”边",
        "站在 前置条件 边",
        "站在【前置条件】边",
        "站在（前置条件）旁",
        "走到了剧情节点旁",
        "推开了章节前置条件",
        "把剧情节点推开",
        "将剧情节点推开",
    ],
)
def test_review_flags_planning_language_materialization_variants(phrase):
    review = review_diagnostic_terms_in_body(f"周满{phrase}，等林照开口。")

    assert review["pass"] is False
    assert review["scores"]["planning_meta_leak"] == 5
    assert any(phrase in issue for issue in review["issues"])


def test_review_deduplicates_repeated_planning_meta_leak_phrases():
    phrase = "推开了章节前置条件"
    review = review_diagnostic_terms_in_body(f"周满{phrase}，转身又{phrase}。")

    assert review["pass"] is False
    planning_issue = next(issue for issue in review["issues"] if phrase in issue)
    assert planning_issue.count(phrase) == 1


def test_review_flags_planning_language_materialized_as_an_action_target():
    review = review_diagnostic_terms_in_body("周满走到剧情节点旁，抬手推开章节前置条件。")

    assert review["pass"] is False
    assert any("走到剧情节点旁" in issue for issue in review["issues"])
    assert any("推开章节前置条件" in issue for issue in review["issues"])
    assert review["scores"]["planning_meta_leak"] == 5


def test_review_flags_npc_boundary_overreach():
    body = (
        "洛婶把两瓶药剂推过来。\n\n"
        "药剂师说：“白袍公会的警戒线在东坡，刷新点已经被他们控住。元素回廊任务要10级以后才稳，开服市场也会被商人重塑。”"
    )

    review = review_npc_boundary_violation(body)

    assert not review["pass"]
    assert any("信息边界" in issue for issue in review["issues"])


def test_review_flags_pov_breach_and_omniscient_market_summary():
    body = (
        "白袍的通讯频道里，冷静的汇报声此起彼伏：“记录：散人刷怪频率异常。上报：外围刷新点已控制。”\n\n"
        "开服初期的供需关系正在被公会和商人重塑，散人的生存空间被压缩。"
    )

    review = review_pov_breach(body)

    assert not review["pass"]
    assert any("限知视角越界" in issue for issue in review["issues"])
    assert any("全知局势宣告" in issue for issue in review["issues"])


def test_review_flags_paragraph_opener_repetition():
    body = "\n\n".join(
        [
            "夜烬压低法杖，往坡下走。",
            "夜烬停在灌木旁，数了数背包。",
            "夜烬没有立刻出手，只把药瓶挪到手边。",
        ]
    )

    review = review_paragraph_opener_repetition(body)

    assert not review["pass"]
    assert any("段首主语连续重复" in issue for issue in review["issues"])


def test_review_flags_system_tag_density():
    body = "\n".join(f"【系统提示：获得草药×{index}】" for index in range(6))

    review = review_system_tag_density(body)

    assert not review["pass"]
    assert any("标签过密" in issue for issue in review["issues"])


def test_hard_violation_alone_triggers_revision():
    # POV breach is HARD. Even one hard issue must flip requires_revision.
    body = "\n\n".join(
        [
            "夜烬走到村口。",
            "白袍公会的内部频道里，有人上报说：外围刷新点已控制。",
            "他没有靠近。",
        ]
    )

    review = review_critical_prose_rules(body)

    assert review["requires_revision"] is True
    assert review["severity_summary"]["has_hard_violation"] is True
    assert any("公会" in issue or "上报" in issue or "限知" in issue for issue in review["hard_issues"])


def test_planning_language_materialized_as_action_is_a_hard_violation():
    review = review_critical_prose_rules("周满说完，迈出前置条件。")

    assert review["scores"]["planning_meta_leak"] == 5
    assert review["severity_summary"]["has_hard_violation"] is True
    assert review["requires_revision"] is True
    assert any("迈出前置条件" in issue for issue in review["hard_issues"])


def test_single_soft_violation_does_not_trigger_revision():
    # Only a metaphor-density bump (SOFT). Should NOT trigger revision.
    body = (
        "夜烬走到村口。"
        "他停住脚，像影子贴住墙，像风停了一秒，像水面收住光，像被截住的呼吸，像不肯出口的话。"
    )

    review = review_critical_prose_rules(body)

    # Five metaphor markers tripped only the metaphor_density soft reviewer;
    # no hard category triggered.
    assert review["severity_summary"]["soft_violation_count"] == 1
    assert review["severity_summary"]["has_hard_violation"] is False
    # Below the soft threshold of 3 → revision NOT required, even though
    # `pass` may be False (issues exist but are not actionable enough).
    assert review["requires_revision"] is False


def test_three_soft_violations_trigger_revision():
    # Triggers metaphor-density + judgment-crutch + paragraph-opener-repetition.
    body = "\n\n".join(
        [
            "他像影子，像风，像水，像火，像旧梦，像未结的弦。",
            "他低头看了一眼。这是他的判断。",
            "他停住脚。这是他的选择。",
            "他抬起手。这就是他的回答。",
            "他没有回头。这不是他的错。",
        ]
    )

    review = review_critical_prose_rules(body)

    assert review["severity_summary"]["soft_violation_count"] >= 3
    assert review["severity_summary"]["has_hard_violation"] is False
    assert review["requires_revision"] is True


def test_emotion_quota_recognises_body_pain_and_weight_idioms():
    """Reviewer must catch 热得发疼 / 红痕 / 压着肩膀 as emotion anchors."""
    from packages.story_core.prose_rule_review import review_emotion_quota

    # Open with an early emotion hit (first 25% of body) so the
    # distribution check passes and we isolate the dictionary expansion.
    body = (
        "勒得喉咙发紧。\n\n"
        + "他坐在桌前。" * 25
        + "\n\n他停下脚。" * 25
        + "\n\n肩带压着肩膀，热得发疼。\n\n"
        + "掌心那道红痕还烫着。"
    )
    review = review_emotion_quota(body)
    # 喉咙发紧 / 压着肩 / 热得发 / 红痕 — at least 4 distinct hits
    assert len(review["hits"]) >= 4
    assert review["pass"] is True


def test_emotion_quota_flags_distribution_failure_when_all_hits_in_back_half():
    """A chapter with all 4 emotion hits piled into the last 30% should fail."""
    from packages.story_core.prose_rule_review import review_emotion_quota

    front = "他算了一遍账。" * 200  # cold opening, no emotion tokens
    back = (
        "\n\n勒得喉咙发紧。\n\n"
        "肩带压着肩膀。\n\n"
        "热得发疼。\n\n"
        "掌心那道红痕。"
    )
    body = front + back
    review = review_emotion_quota(body)
    assert review["pass"] is False
    assert any("分布失衡" in issue for issue in review["issues"])
    assert review["scores"]["emotion_quota"] == 6


def test_critical_review_aggregates_all_rule_scores():
    body = "\n\n".join(
        [
            "夜烬前世做测试。暴露度1。",
            "夜烬听见公会频道里有人上报：锁定外围刷新点。",
            "夜烬看着伤害数字从15跌到12。",
            "【系统提示：获得草药×1】",
            "【系统提示：获得草药×2】",
            "【系统提示：获得草药×3】",
            "【系统提示：获得草药×4】",
            "【系统提示：获得草药×5】",
        ]
    )

    review = review_critical_prose_rules(body)

    assert not review["pass"]
    assert review["scores"]["diagnostic_terms"] == 5
    assert review["scores"]["pov_boundary"] == 5
    assert review["scores"]["system_tag_density"] == 5


def test_review_flags_ai_flavor_formulaic_negation_and_abstract_terms():
    body = "\n\n".join(
        [
            "他不是为了多拿一点，而是为了确认这件事是否成立。",
            "这不是一次选择，而是一次边界验证。",
            "风险很清楚，逻辑也很完整。",
            "他需要在可见性和稳定性之间找到答案。",
        ]
    )

    review = review_ai_flavor(body)

    assert not review["pass"]
    assert review["scores"]["ai_flavor"] < 8
    assert any("AI味" in issue or "模型腔" in issue for issue in review["issues"])


def test_critical_review_includes_ai_flavor_as_soft_gate():
    body = "\n\n".join(
        [
            "他不是为了赢，而是为了看清楚。",
            "他不是害怕，而是需要一个答案。",
            "他不是停下，而是换一种方式继续。",
        ]
    )

    review = review_critical_prose_rules(body)

    assert "ai_flavor" in review["scores"]
    assert review["scores"]["ai_flavor"] < 8
    assert review["severity_summary"]["has_hard_violation"] is False
