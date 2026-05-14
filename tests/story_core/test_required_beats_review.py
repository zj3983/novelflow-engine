"""Tests for required_beats completion reviewer."""
from packages.story_core.prose_rule_review import (
    HARD_REVIEWERS,
    SOFT_REVIEWERS,
    review_critical_prose_rules,
)
from packages.story_core.required_beats_review import (
    _beat_content_terms,
    _beat_coverage,
    _beat_label,
    review_required_beats_completion,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def test_beat_label_extracts_prefix_before_colon():
    assert _beat_label("现实入口：说明主角现实职业") == "现实入口"
    assert _beat_label("登录建号：写出游戏ID、职业选择") == "登录建号"
    # No colon → first 12 chars
    assert _beat_label("没有冒号的节拍内容") == "没有冒号的节拍内容"


def test_beat_content_terms_drops_instructional_stopwords():
    terms = _beat_content_terms("现实入口：说明主角现实职业/技能来源/压力，不只写缺钱。")
    # Should include actual content
    assert "现实入口" in terms
    assert "现实" in terms
    assert "职业" in terms
    assert "技能" in terms
    assert "来源" in terms
    assert "压力" in terms
    assert "缺钱" in terms
    # Should drop instructional words
    assert "说明" not in terms
    assert "主角" not in terms
    assert "不只" not in terms


def test_beat_coverage_full_match():
    body = "他从外包测试员的现实职业里抽出技能，把压力压在身上。这次入口很特殊，不能再缺钱。"
    beat = "现实入口：说明主角现实职业/技能来源/压力，不只写缺钱。"
    assert _beat_coverage(body, beat) >= 0.5


def test_beat_coverage_zero_when_body_unrelated():
    body = "夜烬走过药剂铺，洛婶头也不抬。" * 20
    beat = "登录建号：写出游戏ID、职业选择和第一版角色面板。"
    # body has nothing about login / id / panel → low coverage
    assert _beat_coverage(body, beat) < 0.25


# ---------------------------------------------------------------------------
# Review function
# ---------------------------------------------------------------------------


def test_review_no_op_when_simulation_plan_has_no_required_beats():
    review = review_required_beats_completion("anything", {"required_beats": []})
    assert review["pass"] is True
    assert review["scores"] == {}


def test_review_no_op_when_simulation_plan_missing():
    review = review_required_beats_completion("anything", None)
    assert review["pass"] is True
    assert review["scores"] == {}


def test_review_passes_when_all_beats_covered():
    body = (
        "他从外包测试员的现实职业里抽出技能，把压力压在身上，缺钱是真的。"
        "登录界面弹出，他敲下游戏ID，选择职业进入角色面板。"
        "灰狼掉落两份毒腺，验证了千倍爆率。"
        "洛婶在药剂铺给出药材服务和信息边界。"
    ) * 4
    plan = {
        "required_beats": [
            "现实入口：说明主角现实职业/技能来源/压力，不只写缺钱。",
            "登录建号：写出游戏ID、职业选择和第一版角色面板。",
            "小额验证：用低级怪、低级材料或任务反馈验证千倍爆率。",
            "一个NPC服务节点：完整展开命名NPC，交代职责、服务和信息边界。",
        ],
    }
    review = review_required_beats_completion(body, plan)
    assert review["pass"] is True
    diag = review["diagnostics"]
    assert diag["covered"] >= 3
    assert diag["completion"] >= 0.7


def test_review_triggers_hard_when_majority_missing():
    # Body unrelated to all beats → all missing → HARD
    body = "他在某个完全不相关的世界里走过陌生街道。" * 30
    plan = {
        "required_beats": [
            "现实入口：现实职业/技能来源/压力。",
            "登录建号：游戏ID、职业选择、角色面板。",
            "小额验证：低级怪、千倍爆率。",
            "一个NPC服务节点：命名NPC、信息边界。",
            "交易行弱钩子：手续费、到账、行情。",
        ],
    }
    review = review_required_beats_completion(body, plan)
    assert review["pass"] is False
    assert review["scores"].get("required_beats_critical") == 4
    assert any("严重不足" in issue for issue in review["issues"])


def test_review_triggers_soft_when_some_partial_or_missing():
    body = (
        "他从外包测试员的现实职业里抽出技能，压力压在身上。" * 5
        + "登录界面弹出，他敲下游戏ID，选择职业进入角色面板。" * 5
        # 没有提小额验证 / NPC服务
    )
    plan = {
        "required_beats": [
            "现实入口：说明主角现实职业/技能来源/压力。",
            "登录建号：写出游戏ID、职业选择和第一版角色面板。",
            "小额验证：用低级怪、千倍爆率验证异常。",
            "一个NPC服务节点：洛婶药剂铺信息边界。",
        ],
    }
    review = review_required_beats_completion(body, plan)
    # 2/4 covered → 50% completion → not majority missing → SOFT
    assert review["pass"] is False
    assert review["scores"].get("required_beats_partial") == 6
    assert review["scores"].get("required_beats_critical") is None


def test_review_diagnostics_include_missing_labels():
    body = "完全无关的内容。" * 30
    plan = {
        "required_beats": [
            "登录建号：游戏ID选择",
            "小额验证：低级怪掉落",
        ],
    }
    review = review_required_beats_completion(body, plan)
    diag = review["diagnostics"]
    assert "登录建号" in diag["missing_labels"]
    assert "小额验证" in diag["missing_labels"]


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------


def test_required_beats_score_keys_classified_correctly():
    assert "required_beats_critical" in HARD_REVIEWERS
    assert "required_beats_partial" in SOFT_REVIEWERS


def test_required_beats_critical_alone_triggers_revision():
    plan = {
        "required_beats": ["现实入口：现实职业", "登录建号：游戏ID", "小额验证：千倍爆率", "NPC服务"],
    }
    body = "完全不相关。" * 30
    beats_review = review_required_beats_completion(body, plan)
    aggregate = review_critical_prose_rules(
        body * 5,
        extra_subreviews=[beats_review],
    )
    assert aggregate["severity_summary"]["has_hard_violation"] is True
    assert aggregate["requires_revision"] is True


def test_required_beats_partial_alone_does_not_trigger_revision():
    body = (
        "他从外包测试员的现实职业里抽出技能，压力压在身上。" * 8
        + "登录界面弹出，他敲下游戏ID，进入角色面板。" * 8
    )
    plan = {
        "required_beats": [
            "现实入口：现实职业/技能/压力",
            "登录建号：游戏ID/职业/面板",
            "小额验证：千倍爆率/低级怪",
            "NPC服务节点：信息边界",
        ],
    }
    beats_review = review_required_beats_completion(body, plan)
    aggregate = review_critical_prose_rules(
        body,
        extra_subreviews=[beats_review],
    )
    # Only SOFT trigger, single sub-review → soft count 1 < threshold 3
    assert aggregate["severity_summary"]["has_hard_violation"] is False
    assert aggregate["requires_revision"] is False
