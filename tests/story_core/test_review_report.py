"""Tests for the review_report markdown formatter."""
from packages.story_core.review_report import format_review_report


def _build_review(
    *,
    pass_=False,
    issues=None,
    hard=None,
    soft=None,
    revision_plan=None,
    pacing=None,
    hook=None,
    scores=None,
    profile_id="game_webnovel",
):
    issues = issues or []
    hard = hard or []
    soft = soft or []
    revision_plan = revision_plan or []
    return {
        "pass": pass_,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores or {"webnovel_hook": 8, "background_integration": 8},
        "genre_profile_id": profile_id,
        "critical_review": {
            "pass": not hard and not soft,
            "issues": [*hard, *soft],
            "hard_issues": hard,
            "soft_issues": soft,
            "requires_revision": bool(hard) or len(soft) >= 3,
            "severity_summary": {
                "has_hard_violation": bool(hard),
                "soft_violation_count": len(soft),
                "soft_threshold": 3,
            },
        },
        "hook_review": hook or {
            "scores": {},
            "issues": [],
            "hook_meta": {"type": "危机钩", "strength": "strong", "content": "倒计时三天，债主上门。"},
            "profile_id": profile_id,
        },
        "pacing_review": pacing or {
            "scores": {},
            "issues": [],
            "diagnostics": {
                "profile_id": profile_id,
                "stagnation_run": 0,
                "quest_only_run": 1,
                "emotion_gap": 1,
                "transition_run": 0,
                "window_size": 5,
            },
        },
    }


# ---------------------------------------------------------------------------
# Header / overall structure
# ---------------------------------------------------------------------------


def test_header_includes_chapter_profile_pass_state_and_chars():
    review = _build_review(pass_=True)
    md = format_review_report(review, chapter_number=1, body_chars=9876)

    assert "# 第 1 章 审稿报告" in md
    assert "`game_webnovel`" in md
    assert "9,876" in md
    assert "✅ 通过" in md


def test_header_when_failing():
    review = _build_review(pass_=False, hard=["主角全章没有可识别的开口对话"])
    md = format_review_report(review, chapter_number=2)

    assert "❌ 待修" in md
    assert "**触发改稿**: 是" in md


def test_header_omits_body_chars_when_not_provided():
    review = _build_review(pass_=True)
    md = format_review_report(review, chapter_number=3)

    assert "正文字数" not in md


# ---------------------------------------------------------------------------
# Severity summary
# ---------------------------------------------------------------------------


def test_severity_summary_counts_hard_and_soft_correctly():
    review = _build_review(
        hard=["HARD-1", "HARD-2"],
        soft=["SOFT-1", "SOFT-2"],
    )
    md = format_review_report(review, chapter_number=1)

    assert "🔴 HARD | 2" in md
    assert "🟡 SOFT | 2" in md
    assert "差 1 条" in md  # threshold=3, 2 soft → diff 1


def test_severity_summary_marks_soft_triggered_when_threshold_met():
    review = _build_review(soft=["a", "b", "c"])
    md = format_review_report(review, chapter_number=1)

    # Find the SOFT row and check it shows "是"
    lines = [line for line in md.splitlines() if "🟡 SOFT" in line]
    assert lines
    assert "是" in lines[0]


# ---------------------------------------------------------------------------
# HARD / SOFT blocks
# ---------------------------------------------------------------------------


def test_hard_block_lists_each_hard_issue():
    review = _build_review(hard=["主角全章没有可识别的开口对话", "正文混入后台术语"])
    md = format_review_report(review, chapter_number=1)

    assert "## 🔴 HARD 违规（必修）" in md
    assert "- 主角全章没有可识别的开口对话" in md
    assert "- 正文混入后台术语" in md


def test_hard_block_shows_empty_placeholder_when_no_violations():
    review = _build_review(soft=["minor"])
    md = format_review_report(review, chapter_number=1)

    assert "（本章无 HARD 违规）" in md


def test_soft_block_lists_each_soft_warning():
    review = _build_review(soft=["段落形态过碎", "比喻配额超标"])
    md = format_review_report(review, chapter_number=1)

    assert "## 🟡 SOFT 警告" in md
    assert "- 段落形态过碎" in md
    assert "- 比喻配额超标" in md


# ---------------------------------------------------------------------------
# Hook section
# ---------------------------------------------------------------------------


def test_hook_section_shows_type_strength_and_check_marks_when_passing():
    review = _build_review()  # default hook with empty scores → all checks pass
    md = format_review_report(review, chapter_number=1)

    assert "## 章末钩子" in md
    assert "| 类型 | 危机钩 |" in md
    assert "| 强度 | strong |" in md
    # All three hook checks should display ✓ since scores={} means each passed
    assert md.count("| 末段落地 | ✓ |") == 1
    assert md.count("| 题材匹配 | ✓ |") == 1
    assert md.count("| 强度达标 | ✓ |") == 1


def test_hook_section_marks_failures():
    review = _build_review(
        hook={
            "scores": {"hook_landed": 5, "hook_strength": 6},
            "issues": ["章末钩子未在正文末段落地"],
            "hook_meta": {"type": "悬念钩", "strength": "weak", "content": "短钩。"},
            "profile_id": "xianxia",
        }
    )
    md = format_review_report(review, chapter_number=1)

    assert "| 末段落地 | ✗ |" in md
    assert "| 强度达标 | ✗ |" in md
    assert "| 题材匹配 | ✓ |" in md  # not in scores → still passing


# ---------------------------------------------------------------------------
# Pacing section
# ---------------------------------------------------------------------------


def test_pacing_section_renders_diagnostic_table():
    review = _build_review(
        pacing={
            "scores": {"pacing_stagnation": 4},
            "issues": ["节奏停滞：连续 3 章无可见推进"],
            "diagnostics": {
                "profile_id": "xianxia",
                "stagnation_run": 3,
                "quest_only_run": 2,
                "emotion_gap": 5,
                "transition_run": 0,
                "window_size": 10,
            },
        }
    )
    md = format_review_report(review, chapter_number=4)

    assert "## 跨章节节奏" in md
    assert "`xianxia`" in md
    assert "最近 10 章" in md
    assert "| 停滞章数 | 3 | 🔴 是 |" in md
    assert "节奏停滞：连续 3 章无可见推进" in md


def test_pacing_soft_uses_yellow_marker():
    review = _build_review(
        pacing={
            "scores": {"pacing_emotion_gap": 6},
            "issues": ["情感线断档"],
            "diagnostics": {
                "profile_id": "romance",
                "stagnation_run": 0,
                "quest_only_run": 0,
                "emotion_gap": 5,
                "transition_run": 0,
                "window_size": 5,
            },
        }
    )
    md = format_review_report(review, chapter_number=4)

    assert "| 情感线断档 | 5 | 🟡 是 |" in md


# ---------------------------------------------------------------------------
# Revision plan + scores table
# ---------------------------------------------------------------------------


def test_revision_plan_renders_numbered_bullets():
    review = _build_review(
        hard=["X"],
        revision_plan=["补一次主角开口", "段落合并"],
    )
    md = format_review_report(review, chapter_number=1)

    assert "## 修订建议" in md
    assert "**1.** 补一次主角开口" in md
    assert "**2.** 段落合并" in md


def test_score_table_groups_keys_by_source():
    review = _build_review(
        pass_=False,
        scores={
            "webnovel_hook": 5,
            "web_game_market_scale": 7,
            "world_event_visibility_boundary": 8,
            "prose_style_metaphor": 6,
            "critical_paragraph_form": 5,
        },
    )
    md = format_review_report(review, chapter_number=1)

    assert "### 内联规则" in md
    assert "### 网游审稿" in md
    assert "### 世界一致性" in md
    assert "### 文风审稿" in md
    assert "### HARD/SOFT 综合" in md
    # 5 → 🔴, 6/7 → 🟡, 8 → ✅
    assert "🔴 5" in md
    assert "🟡 6" in md or "🟡 7" in md
    assert "✅ 8" in md


# ---------------------------------------------------------------------------
# Optional sections gracefully omit
# ---------------------------------------------------------------------------


def test_report_omits_hook_section_when_review_missing():
    review = _build_review()
    review.pop("hook_review")
    md = format_review_report(review, chapter_number=1)

    assert "章末钩子" not in md


def test_report_omits_pacing_section_when_review_missing():
    review = _build_review()
    review.pop("pacing_review")
    md = format_review_report(review, chapter_number=1)

    assert "跨章节节奏" not in md


def test_report_ends_with_newline():
    md = format_review_report(_build_review(), chapter_number=1)
    assert md.endswith("\n")
