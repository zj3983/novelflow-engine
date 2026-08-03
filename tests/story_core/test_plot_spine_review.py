import pytest

from packages.story_core.orchestrator import _review_chapter_body
from packages.story_core.plot_spine_review import review_plot_spine_completion
from packages.story_core.prose_rule_review import HARD_REVIEWERS, SOFT_REVIEWERS
from packages.story_core.simplified_review import build_simplified_review


def _plot_plan():
    return {
        "plot_simulation": {
            "reader_hook": "读者要看到夜烬暗中领先。",
            "chapter_desire": "夜烬想补齐清道夫委托还差的两份毒腺。",
            "obstacle_chain": ["蓝量不够", "法杖耐久快见底"],
            "choice_point": "他要决定先交任务，还是先把来源藏住。",
            "payoff": "清道夫委托进度必须有明确变化。",
            "cost": "至少付出蓝量、耐久或铜币中的一项。",
            "emotional_turn": "从缺资源的紧绷转成小领先后的警惕。",
            "outsider_misread": "外人只能以为他运气好。",
            "ending_hook": "章末落到后坡巡查前置任务。",
        }
    }


def _longform_plan():
    plan = _plot_plan()
    plan["longform_plot_contract"] = {
        "payoff_requirement": "每章至少让一项账本向前滚：等级、技能、装备、铜币、任务权限、材料渠道或现实收入。",
        "anti_drag_rule": "不要连续铺垫，只观察不兑现。",
        "future_use_rule": "本章新增道具、人物、任务和线索都要说明能怎样继续推动后续。",
        "reader_reason_to_continue": "章末必须留下下一章立刻能执行的动作。",
    }
    plan["plot_simulation"]["payoff_requirement"] = plan["longform_plot_contract"]["payoff_requirement"]
    plan["plot_simulation"]["future_use_rule"] = plan["longform_plot_contract"]["future_use_rule"]
    plan["plot_simulation"]["reader_reason_to_continue"] = plan["longform_plot_contract"]["reader_reason_to_continue"]
    return plan


def _trope_plan(current_beat="雨夜接下挑战"):
    return {
        "trope_contract": {
            "template_id": "trial",
            "name": "Trial Stage",
            "trigger": "rain invitation",
            "current_beat": current_beat,
            "payoff": "赢得信任且不暴露底牌",
            "avoid": ["不要换套路", "不要提前解决整条主线"],
        }
    }


def test_plot_spine_review_fails_when_core_plot_beats_are_missing():
    body = "夜烬站在村口看了一会儿，觉得后坡还可以去。他没有多说，转身走了。"

    review = review_plot_spine_completion(body, _plot_plan())

    assert review["pass"] is False
    assert review["scores"]["plot_spine_critical"] == 4
    assert any("剧情主线" in issue for issue in review["issues"])
    assert "主角目标" in review["diagnostics"]["missing_labels"]
    assert "爽点兑现" in review["diagnostics"]["missing_labels"]


def test_plot_spine_review_passes_when_goal_cost_payoff_and_hook_land():
    body = (
        "夜烬把背包打开，灰狼毒腺还差两份，清道夫委托的牌子就卡在那里。"
        "他没有立刻去柜台交材料，而是先绕到修理铺，摸了摸快裂开的新手法杖。"
        "蓝条只剩一点，耐久也掉到红字，他只能花掉几枚铜币补药。"
        "旁边玩家看见他排队，只当他运气好，没人知道他把多出来的毒腺压在背包底下。"
        "等委托进度跳了一格，他才看见后坡巡查的前置任务亮了出来。"
    )

    review = review_plot_spine_completion(body, _plot_plan())

    assert review["pass"] is True
    assert review["scores"] == {}


def test_plot_spine_scores_are_classified_for_revision_gate():
    assert "plot_spine_critical" in HARD_REVIEWERS
    assert "plot_spine_partial" in SOFT_REVIEWERS
    assert "longform_payoff_missing" in HARD_REVIEWERS
    assert "longform_followup_weak" in SOFT_REVIEWERS
    assert "trope_beat_missing" not in HARD_REVIEWERS
    assert "trope_beat_missing" in SOFT_REVIEWERS


def test_longform_contract_fails_when_chapter_only_observes_without_payoff():
    body = (
        "夜烬沿着村墙看了一圈，把后坡入口和任务牌都记下来。"
        "他没有急着交任务，也没有买东西，只是确认这里以后能用。"
        "旁边玩家还在排队，他转身离开，准备再看看情况。"
    )

    review = review_plot_spine_completion(body, _longform_plan())

    assert review["pass"] is False
    assert review["scores"]["longform_payoff_missing"] == 4
    assert "本章兑现" in review["diagnostics"]["contract_missing"]


def test_longform_contract_passes_when_payoff_and_followup_land():
    body = (
        "夜烬把十份灰狼毒腺递进窗口，清道夫委托的进度当场亮满。"
        "洛婶按牌子发了30铜，任务完成的经验也跳出来，他升到Lv.2。"
        "他没有在柜台前多停，把铜币拆成修理费和两瓶小法力药水。"
        "旁边玩家只当他运气好，没人知道多出来的材料还压在背包里。"
        "任务牌最下方，后坡巡查的前置条件亮了一行，他下一步就能去登记。"
    )

    review = review_plot_spine_completion(body, _longform_plan())

    assert review["pass"] is True
    assert "longform_payoff_missing" not in review["scores"]
    assert review["diagnostics"]["contract_missing"] == []


def test_chapter_body_review_exposes_plot_spine_review():
    body = "夜烬站在村口看了一会儿，觉得后坡还可以去。他没有多说，转身走了。"

    review = _review_chapter_body(
        2,
        body,
        {"next_focus": "后坡巡查"},
        ["网游"],
        _plot_plan(),
        [],
        [],
    )

    assert "plot_spine_review" in review
    assert review["plot_spine_review"]["pass"] is False
    assert review["scores"]["plot_spine_critical"] == 4


def test_scheduled_trope_beat_fails_when_not_covered():
    body = "林站在屋檐下想了想明天的安排，最后没有回应邀请就离开了。"

    review = review_plot_spine_completion(body, _trope_plan())

    assert review["pass"] is False
    assert review["scores"]["trope_beat_missing"] <= 5
    assert any("套路节点未兑现" in issue for issue in review["issues"])
    assert any(
        "雨夜接下挑战" in item and "赢得信任且不暴露底牌" in item
        for item in review["revision_plan"]
    )
    assert review["diagnostics"]["trope_beat_covered"] is False
    assert review["diagnostics"]["trope_beat_coverage"] < 0.25


def test_scheduled_trope_beat_passes_when_covered_and_keeps_avoid_guidance():
    body = "林在雨夜接下挑战，赢得信任且不暴露底牌，也把更大的对抗留到后面。"

    review = review_plot_spine_completion(body, _trope_plan())

    assert review["pass"] is True
    assert not any("套路节点未兑现" in issue for issue in review["issues"])
    assert review["diagnostics"]["trope_beat_covered"] is True
    assert review["diagnostics"]["trope_avoid"] == ["不要换套路", "不要提前解决整条主线"]


def test_structural_payoff_trope_uses_concrete_plot_payoff_instead_of_meta_words():
    body = (
        "林修终于看清了阵心石下的结构。雪山神殿本身就是第三件神器的外壳，"
        "残镜只是脱落的核心碎件，小乐的血也不是开门的钥匙，而是辨认真伪的校验印。"
    )
    plan = {
        "plot_simulation": {
            "payoff": "林修确认雪山神殿本身就是第三件神器的外壳，残镜只是核心碎件，小乐的血不是钥匙而是校验印。",
        },
        "trope_contract": {
            "template_id": "chapter_hook_escalation",
            "current_beat": "兑现本章收益",
            "payoff": "章节有闭环，也有继续读的理由。",
        },
    }

    review = review_plot_spine_completion(body, plan)

    assert review["pass"] is True
    assert review["diagnostics"]["trope_beat_covered"] is True
    assert "trope_beat_missing" not in review["scores"]


def test_scheduled_trope_beat_rejects_negated_or_planned_mentions():
    negated = review_plot_spine_completion(
        "林在雨夜没有接下挑战，当场拒绝邀请，只把赢得信任的可能性压到以后。",
        _trope_plan(),
    )
    planned = review_plot_spine_completion(
        "林打算在雨夜接下挑战，也计划赢得信任且不暴露底牌，但这一章只是在心里盘算。",
        _trope_plan(),
    )
    landed = review_plot_spine_completion(
        "林在雨夜接下挑战，当场用一场硬碰硬赢得信任且不暴露底牌。",
        _trope_plan(),
    )

    assert negated["pass"] is False
    assert negated["diagnostics"]["trope_beat_covered"] is False
    assert planned["pass"] is False
    assert planned["diagnostics"]["trope_beat_covered"] is False
    assert landed["pass"] is True
    assert landed["diagnostics"]["trope_beat_covered"] is True


def test_scheduled_trope_beat_allows_unrelated_negation_before_clear_action():
    review = review_plot_spine_completion(
        "他没有犹豫，当场在雨夜接下挑战，赢得信任且不暴露底牌。",
        _trope_plan(),
    )
    nearby_negation = review_plot_spine_completion(
        "他没有接下挑战，只是站在雨夜里等待。",
        _trope_plan(),
    )
    english_nearby_negation = review_plot_spine_completion(
        "Lin didn't claim reward before sunset.",
        _trope_plan(current_beat="claim reward"),
    )

    assert review["pass"] is True
    assert review["diagnostics"]["trope_beat_covered"] is True
    assert nearby_negation["pass"] is False
    assert nearby_negation["diagnostics"]["trope_beat_covered"] is False
    assert english_nearby_negation["pass"] is False
    assert english_nearby_negation["diagnostics"]["trope_beat_covered"] is False


def test_short_chinese_trope_beat_requires_affirmative_action():
    landed = review_plot_spine_completion(
        "他当场开门，看见屋内证据。",
        _trope_plan(current_beat="开门"),
    )
    negated = review_plot_spine_completion(
        "他没有开门，只是在门外等待。",
        _trope_plan(current_beat="开门"),
    )
    questioned = review_plot_spine_completion(
        "他会开门吗？旁人都在猜。",
        _trope_plan(current_beat="开门"),
    )

    assert landed["pass"] is True
    assert landed["diagnostics"]["trope_beat_covered"] is True
    assert negated["pass"] is False
    assert negated["diagnostics"]["trope_beat_covered"] is False
    assert questioned["pass"] is False
    assert questioned["diagnostics"]["trope_beat_covered"] is False


def test_scheduled_trope_beat_handles_english_and_symbol_beats_conservatively():
    plan = _trope_plan(current_beat="unlock VIP-3 badge")

    unrelated = review_plot_spine_completion(
        "Lin checks the empty hallway and closes the app without doing anything.",
        plan,
    )
    landed = review_plot_spine_completion(
        "Lin chooses the public challenge and unlock VIP-3 badge before the crowd can react.",
        plan,
    )

    assert unrelated["pass"] is False
    assert unrelated["diagnostics"]["trope_beat_covered"] is False
    assert unrelated["diagnostics"]["trope_beat_coverage"] < 0.25
    assert landed["pass"] is True
    assert landed["diagnostics"]["trope_beat_covered"] is True


def test_english_control_words_do_not_match_substrings_inside_action_words():
    notice = review_plot_spine_completion(
        "Lin steps onto the stage and receive notice from the tribunal before anyone can object.",
        _trope_plan(current_beat="receive notice"),
    )
    planet = review_plot_spine_completion(
        "Lin fires the final engine, crosses the gate, and reach planet K-7 in full view.",
        _trope_plan(current_beat="reach planet K-7"),
    )

    assert notice["pass"] is True
    assert notice["diagnostics"]["trope_beat_covered"] is True
    assert planet["pass"] is True
    assert planet["diagnostics"]["trope_beat_covered"] is True


@pytest.mark.parametrize(
    "body",
    [
        "Lin didn't unlock VIP-3 badge before the hearing.",
        "Lin doesn't unlock VIP-3 badge before the hearing.",
        "Lin won't unlock VIP-3 badge before the hearing.",
        "Lin can't unlock VIP-3 badge before the hearing.",
        "Lin won’t unlock VIP-3 badge before the hearing.",
    ],
)
def test_english_contracted_negation_rejects_full_beat_mentions(body):
    review = review_plot_spine_completion(body, _trope_plan(current_beat="unlock VIP-3 badge"))

    assert review["pass"] is False
    assert review["diagnostics"]["trope_beat_covered"] is False


def test_scheduled_trope_beat_rejects_question_pending_and_split_mentions():
    questioned = review_plot_spine_completion(
        "林会在雨夜接下挑战吗？旁人只是猜测他能赢得信任。",
        _trope_plan(),
    )
    pending = review_plot_spine_completion(
        "林雨夜尚未接下挑战，只把赢得信任且不暴露底牌写进明天的计划。",
        _trope_plan(),
    )
    split = review_plot_spine_completion(
        "林在雨夜盯着屋檐。另一边有人接下挑战。后来众人谈起赢得信任且不暴露底牌。",
        _trope_plan(),
    )

    assert questioned["pass"] is False
    assert questioned["diagnostics"]["trope_beat_covered"] is False
    assert pending["pass"] is False
    assert pending["diagnostics"]["trope_beat_covered"] is False
    assert split["pass"] is False
    assert split["diagnostics"]["trope_beat_covered"] is False


def test_scheduled_trope_beat_allows_later_positive_action_after_rejection():
    review = review_plot_spine_completion(
        "林起初拒绝邀请，没有接下挑战。雨声变急后，他当场在雨夜接下挑战，赢得信任且不暴露底牌。",
        _trope_plan(),
    )

    assert review["pass"] is True
    assert review["diagnostics"]["trope_beat_covered"] is True


def test_empty_trope_beat_is_not_forced_but_avoid_guidance_is_reported():
    body = "林听见邀请，克制地守住这一阶段的承诺。"

    review = review_plot_spine_completion(body, _trope_plan(current_beat=None))

    assert review["pass"] is True
    assert "trope_beat_missing" not in review["scores"]
    assert not any("套路节点未兑现" in issue for issue in review["issues"])
    assert review["diagnostics"]["trope_beat_covered"] == "not_scheduled"
    assert review["diagnostics"]["trope_avoid"] == ["不要换套路", "不要提前解决整条主线"]

    simplified = build_simplified_review({"writing_review": review})
    assert simplified["needs_revision"] is False
    assert simplified["categories"]["hard"]["count"] == 0


def test_chapter_body_review_retains_scheduled_trope_issue_and_avoid_guidance():
    review = _review_chapter_body(
        2,
        "林站在屋檐下想了想明天的安排，最后没有回应邀请就离开了。",
        {"next_focus": "回应邀请", "world_reactions": ["旁观者等待"]},
        [],
        {
            "review_focus": ["trope beat"],
            "character_performance": {"林": ["犹豫"]},
            **_trope_plan(),
        },
        [],
        [],
    )

    assert any("套路节点未兑现" in issue for issue in review["issues"])
    assert any("雨夜接下挑战" in item for item in review["revision_plan"])
    assert review["plot_spine_review"]["diagnostics"]["trope_avoid"] == [
        "不要换套路",
        "不要提前解决整条主线",
    ]
