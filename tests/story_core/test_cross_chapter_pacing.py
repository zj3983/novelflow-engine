"""Tests for cross_chapter_pacing_review."""
from packages.story_core.cross_chapter_pacing_review import (
    _classify_strands,
    _is_transition,
    _progress_score,
    review_cross_chapter_pacing,
)
from packages.story_core.genre_profile import (
    GAME_PROFILE,
    GENERIC_PROFILE,
    ROMANCE_PROFILE,
    XIANXIA_PROFILE,
)
from packages.story_core.prose_rule_review import (
    HARD_REVIEWERS,
    SOFT_REVIEWERS,
    review_critical_prose_rules,
)


def _bundle(
    n: int,
    *,
    summary: str = "",
    facts: list[str] | None = None,
    next_focus: str = "",
    turn: str = "",
    pivot: str = "",
    landing: str = "",
    title: str = "",
) -> dict:
    """Build a chapter bundle dict for tests (matches ChapterBundle shape)."""
    return {
        "chapter_number": n,
        "chapter_title": title or f"第{n}章",
        "next_outline": "",
        "chapter_summary": {
            "summary": summary,
            "facts": facts or [],
            "next_focus": next_focus,
            "event_beat": {"turn": turn, "pivot": pivot, "landing": landing},
        },
    }


# ---------------------------------------------------------------------------
# Strand classifier
# ---------------------------------------------------------------------------


def test_strand_quest_classification():
    bundle = _bundle(
        1,
        summary="他完成了任务，挂单成交，经验提升。",
        facts=["材料×3", "铜币+15"],
    )
    assert _classify_strands(bundle) == {"quest"}


def test_strand_emotion_classification():
    bundle = _bundle(
        2,
        summary="她终于鼓起勇气，对他承诺要等他回来。",
        facts=["关系靠近", "误会化解"],
    )
    assert _classify_strands(bundle) == {"emotion"}


def test_strand_world_classification():
    bundle = _bundle(
        3,
        summary="公会的传闻牵出秘境的真相。",
        facts=["势力角力", "古卷线索"],
    )
    assert _classify_strands(bundle) == {"world"}


def test_strand_mixed_classification():
    bundle = _bundle(
        4,
        summary="他完成任务后与她对话，公会传闻随之而来。",
        facts=["挂单×2", "试探眼神", "势力档案"],
    )
    assert _classify_strands(bundle) == {"quest", "emotion", "world"}


# ---------------------------------------------------------------------------
# Transition detection
# ---------------------------------------------------------------------------


def test_transition_detected_by_keyword():
    bundle = _bundle(5, summary="路上无事，赶路回村休整。", turn="", pivot="")
    assert _is_transition(bundle) is True


def test_transition_detected_by_empty_event_beat():
    bundle = _bundle(6, summary="他做了一些杂事。", turn="", pivot="", landing="")
    assert _is_transition(bundle) is True


def test_non_transition_with_real_beat():
    bundle = _bundle(
        7,
        summary="夜烬试出爆率异常，付出耐久代价。",
        turn="发现千倍爆率",
        pivot="耐久空了",
    )
    assert _is_transition(bundle) is False


# ---------------------------------------------------------------------------
# Progress score
# ---------------------------------------------------------------------------


def test_progress_score_high_with_beat_and_facts():
    bundle = _bundle(
        1,
        summary="清晰的进展。",
        facts=["a", "b", "c", "d"],
        turn="转折点",
        pivot="支点",
    )
    assert _progress_score(bundle, prev_bundle=None) > 0.7


def test_progress_score_low_when_focus_repeats():
    prev = _bundle(1, next_focus="下一章去找散人渠道，处理材料")
    cur = _bundle(2, next_focus="下一章去找散人渠道，处理材料")
    # Empty event_beat + repeated focus + no facts → very low score
    assert _progress_score(cur, prev_bundle=prev) < 0.4


# ---------------------------------------------------------------------------
# Review: stagnation HARD
# ---------------------------------------------------------------------------


def test_pacing_stagnation_fires_when_run_exceeds_threshold():
    # XIANXIA stagnation_threshold=2 — 3 stagnant chapters in a row trips it.
    history = [
        _bundle(1, next_focus="去找碎玉"),  # stagnant
        _bundle(2, next_focus="去找碎玉"),  # stagnant (repeated focus)
        _bundle(3, next_focus="去找碎玉"),  # stagnant
    ]
    review = review_cross_chapter_pacing(history, XIANXIA_PROFILE, target_chapter=4)
    assert review["scores"].get("pacing_stagnation") == 4
    assert review["pass"] is False
    assert any("节奏停滞" in issue for issue in review["issues"])


def test_pacing_stagnation_does_not_fire_under_threshold():
    history = [
        _bundle(1, next_focus="去找碎玉", turn="发现传闻"),  # progress
        _bundle(2, next_focus="去找碎玉"),                # stagnant
    ]
    review = review_cross_chapter_pacing(history, XIANXIA_PROFILE, target_chapter=3)
    # stagnation_threshold=2 → only 1 stagnant in a row
    assert review["scores"].get("pacing_stagnation") is None


# ---------------------------------------------------------------------------
# Review: emotion gap SOFT (key for romance/dog-blood)
# ---------------------------------------------------------------------------


def test_pacing_emotion_gap_fires_for_romance_after_long_drought():
    # ROMANCE strand_emotion_gap_max=2 — 3 chapters without emotion → fail
    history = [
        _bundle(1, summary="他赶路休整。", turn="路上"),
        _bundle(2, summary="她思考了一下。", turn="想了想"),  # no emotion tokens
        _bundle(3, summary="他继续赶路。", turn="路上"),
        _bundle(4, summary="他到了下一城。", turn="到达"),
    ]
    review = review_cross_chapter_pacing(history, ROMANCE_PROFILE, target_chapter=5)
    assert review["scores"].get("pacing_emotion_gap") == 6
    assert any("情感线断档" in issue for issue in review["issues"])


def test_pacing_emotion_gap_silent_when_recent_emotion_chapter():
    history = [
        _bundle(1, summary="他赶路。", turn="路上"),
        _bundle(2, summary="她对他承诺等他回来。"),  # emotion
        _bundle(3, summary="他到下一城。", turn="到达"),
    ]
    review = review_cross_chapter_pacing(history, ROMANCE_PROFILE, target_chapter=4)
    # Last emotion chapter = 2, target=4, gap = 1 < 2 → no warning
    assert review["scores"].get("pacing_emotion_gap") is None


# ---------------------------------------------------------------------------
# Review: transition run SOFT
# ---------------------------------------------------------------------------


def test_pacing_transition_run_fires_when_too_many_consecutive():
    # GAME profile transition_max_consecutive (let's check actual value)
    transition_max = GAME_PROFILE.pacing.transition_max_consecutive
    history = [
        _bundle(1, summary="开服首日，主角击杀小怪。", turn="首杀验证"),  # not transition
    ]
    for n in range(2, 2 + transition_max + 1):
        history.append(_bundle(n, summary="路上无事。", turn="", pivot=""))  # transition
    review = review_cross_chapter_pacing(history, GAME_PROFILE, target_chapter=len(history) + 1)
    assert review["scores"].get("pacing_transition_run") == 6


# ---------------------------------------------------------------------------
# Empty / missing inputs
# ---------------------------------------------------------------------------


def test_review_returns_pass_when_history_empty():
    review = review_cross_chapter_pacing([], GENERIC_PROFILE, target_chapter=1)
    assert review["pass"] is True
    assert review["scores"] == {}


def test_review_returns_pass_when_profile_none():
    history = [_bundle(1)]
    review = review_cross_chapter_pacing(history, None, target_chapter=2)
    assert review["pass"] is True


def test_review_filters_out_target_chapter_and_beyond():
    history = [
        _bundle(1, next_focus="去找碎玉"),
        _bundle(2, next_focus="去找碎玉"),
        _bundle(3, next_focus="去找碎玉"),  # target=2, this should be filtered
    ]
    # target_chapter=2 → only chapter 1 counted, 1 stagnant ≠ trigger
    review = review_cross_chapter_pacing(history, XIANXIA_PROFILE, target_chapter=2)
    assert review["scores"].get("pacing_stagnation") is None


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------


def test_pacing_score_keys_classified_correctly():
    assert "pacing_stagnation" in HARD_REVIEWERS
    assert "pacing_quest_strand" in SOFT_REVIEWERS
    assert "pacing_emotion_gap" in SOFT_REVIEWERS
    assert "pacing_transition_run" in SOFT_REVIEWERS


def test_pacing_stagnation_alone_triggers_revision():
    history = [
        _bundle(1, next_focus="找碎玉"),
        _bundle(2, next_focus="找碎玉"),
        _bundle(3, next_focus="找碎玉"),
    ]
    pacing_review = review_cross_chapter_pacing(history, XIANXIA_PROFILE, target_chapter=4)
    aggregate = review_critical_prose_rules(
        "占位文本，本测试只关心 extra_subreviews 的严重度路由。" * 30,
        extra_subreviews=[pacing_review],
    )
    assert aggregate["severity_summary"]["has_hard_violation"] is True
    assert aggregate["requires_revision"] is True
