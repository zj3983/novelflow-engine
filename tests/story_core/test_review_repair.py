import pytest

from packages.story_core.review_repair import apply_review_edits, review_repaired_body


def test_review_edits_preserve_every_untouched_character_and_use_original_offsets():
    body = "门口原样。\n\n他仿佛石头。\n\n她如同寒冰。\n\n收好箱子。"
    revised, edits = apply_review_edits(body, {"edits": [
        {"before": "他仿佛石头。", "after": "他一动不动。", "reason": "删比喻"},
        {"before": "她如同寒冰。", "after": "她没有应声。", "reason": "直接叙述"},
    ]})
    assert revised == "门口原样。\n\n他一动不动。\n\n她没有应声。\n\n收好箱子。"
    assert len(edits) == 2


@pytest.mark.parametrize("body,edits,error", [
    ("重复。重复。", [{"before": "重复。", "after": "变化。"}], "ambiguous"),
    ("甲甲甲", [{"before": "甲甲", "after": "变化"}], "ambiguous"),
    ("原文。", [{"before": "不存在。", "after": "变化。"}], "not_found"),
    ("原文。", [{"before": "原文。", "after": "原文。"}], "no_change"),
    ("甲乙丙丁。", [{"before": "甲乙丙", "after": "甲"}, {"before": "乙丙丁", "after": "乙"}], "overlap"),
    ("原" * 2000, [{"before": "原" * 2000, "after": "新" * 2000}], "scope"),
])
def test_review_edits_reject_unsafe_patch(body, edits, error):
    with pytest.raises(ValueError, match=error):
        apply_review_edits(body, {"edits": edits})


def test_review_reruns_simile_rule_but_keeps_unverified_findings():
    quality = {"ok": False, "issues": ["writing_review"], "writing_review": {
        "pass": False, "issues": ["style.simile_stacking", "canon.other"], "blocking": [
            {"code": "style.simile_stacking", "message": "比喻过密", "source": "deterministic"},
            {"code": "canon.other", "message": "伤势待复核", "source": "model"},
        ],
    }}
    fixed = review_repaired_body("他按下开关。", quality, [])
    assert fixed["writing_review"]["issues"] == ["canon.other"]
    assert fixed["ok"] is False
    still_bad = review_repaired_body("仿佛" * 9, quality, [])
    assert "style.simile_stacking" not in still_bad["writing_review"]["issues"]
    assert still_bad["style_rule_signals"]
    assert "canon.other" in still_bad["writing_review"]["issues"]


def test_review_reruns_length_and_clears_resolved_length_codes():
    quality = {"ok": False, "issues": ["chapter.length_too_long"], "writing_review": {
        "pass": False, "issues": ["chapter.length_too_long"], "blocking": [
            {"code": "chapter.length_too_long", "message": "超长", "source": "deterministic"},
        ],
    }}
    fixed = review_repaired_body("字" * 4400, quality, [])
    assert fixed["ok"] is True
    assert fixed["writing_review"]["issues"] == []


def test_review_preserves_unverified_v2_soft_findings():
    quality = {"review_result": {"schema_version": "review-result/v2", "issues": [
        {"code": "prose.uncertain", "message": "待复核", "blocking": False},
    ]}}
    fixed = review_repaired_body("他按下开关。", quality, [])
    assert fixed["ok"] is False
    assert "prose.uncertain" in str(fixed["writing_review"]["issues"])


def test_repair_refreshes_ai_checks_and_does_not_keep_stale_style_report():
    previous = {"ai_flavor_review": {"pass": False, "issues": ["旧AI味问题"]},
                "prose_style_review": {"pass": False, "issues": ["旧套话问题"]}}
    fixed = review_repaired_body("他按下开关。", previous, [])
    assert fixed["ai_flavor_review"]["pass"] is True
    assert fixed["prose_style_review"]["pass"] is True
    assert "旧AI味问题" not in str(fixed)
    assert previous["ai_flavor_review"]["pass"] is False
