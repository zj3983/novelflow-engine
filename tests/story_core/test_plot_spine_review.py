from packages.story_core.orchestrator import _review_chapter_body
from packages.story_core.plot_spine_review import review_plot_spine_completion
from packages.story_core.prose_rule_review import HARD_REVIEWERS, SOFT_REVIEWERS


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
