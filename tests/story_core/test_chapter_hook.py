from packages.story_core.chapter_hook import (
    HOOK_STRENGTHS,
    HOOK_TYPES,
    parse_chapter_end_hook,
    review_chapter_hook,
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


# ---------------------------------------------------------------------------
# parse_chapter_end_hook
# ---------------------------------------------------------------------------


def test_parse_empty_value_returns_blank_triple():
    out = parse_chapter_end_hook(None)
    assert out == {"type": None, "strength": None, "content": ""}
    assert parse_chapter_end_hook("")["content"] == ""


def test_parse_string_strips_field_label_prefix():
    raw = "explicit_chapter_end_hook: 倒计时只剩三天，债主就要上门。"
    out = parse_chapter_end_hook(raw)
    assert out["content"].startswith("倒计时")
    # Strong markers ("倒计时") + crisis vocabulary → 危机钩 / strong
    assert out["type"] == "危机钩"
    assert out["strength"] == "strong"


def test_parse_dict_passes_through_with_inference_for_missing_fields():
    out = parse_chapter_end_hook({"content": "她抬头看他，眼眶湿了一圈。"})
    assert out["type"] == "情绪钩"
    assert out["strength"] in HOOK_STRENGTHS


def test_parse_dict_keeps_explicit_type_when_canonical():
    out = parse_chapter_end_hook(
        {"type": "选择钩", "strength": "medium", "content": "去还是留，他要在天亮前决定。"}
    )
    assert out == {"type": "选择钩", "strength": "medium", "content": "去还是留，他要在天亮前决定。"}


def test_parse_dict_drops_invalid_type_and_re_infers():
    out = parse_chapter_end_hook(
        {"type": "不存在的钩", "strength": "strong", "content": "失踪的银针在桌上躺了一整夜。"}
    )
    assert out["type"] == "悬念钩"  # re-inferred
    assert out["strength"] == "strong"


def test_parse_string_weak_markers_drop_strength():
    out = parse_chapter_end_hook("也许之后再去找那扇门。")
    assert out["strength"] == "weak"


# ---------------------------------------------------------------------------
# review_chapter_hook — landing
# ---------------------------------------------------------------------------


def test_review_passes_when_hook_lands_in_last_quarter():
    body = (
        "夜烬走过村口。" * 30
        + "\n\n他把催租单按进抽屉，倒计时还剩三天。"
    )
    hook = parse_chapter_end_hook("倒计时三天，债主即将上门。")

    review = review_chapter_hook(body, hook, GENERIC_PROFILE)

    # Hook content "倒计时" / "债主" / "上门" appears in last quarter
    # (specifically "倒计时" lands). Type ('危机钩') is in generic preferences.
    assert review["pass"] is True
    assert "hook_landed" not in review["scores"]


def test_review_flags_hook_not_landing_in_body():
    body = "夜烬走到村口。" * 60  # plenty of body, but no hook content
    hook = parse_chapter_end_hook("失踪的银针在抽屉里躺了一整夜。")

    review = review_chapter_hook(body, hook, GENERIC_PROFILE)

    assert review["pass"] is False
    assert review["scores"].get("hook_landed") == 5
    assert any("未在正文末段落地" in issue for issue in review["issues"])


def test_review_skips_landing_check_when_hook_too_generic():
    body = "夜烬走到村口。" * 60
    # Only generic stop-words → reviewer can't verify, must not false-positive
    hook = parse_chapter_end_hook("主角继续推进")

    review = review_chapter_hook(body, hook, GENERIC_PROFILE)

    assert review["scores"].get("hook_landed") != 5


# ---------------------------------------------------------------------------
# review_chapter_hook — type vs profile
# ---------------------------------------------------------------------------


def test_review_flags_type_mismatch_with_genre():
    # 渴望钩 in suspense profile (which prefers 悬念/选择/危机) → soft warn
    body = "他在档案室翻到名字。" * 40
    hook = parse_chapter_end_hook("即将拿到那枚徽章，名利双收。")

    from packages.story_core.genre_profile import SUSPENSE_PROFILE

    review = review_chapter_hook(body, hook, SUSPENSE_PROFILE)

    assert review["scores"].get("hook_type_match") == 6
    assert any("题材偏好不符" in issue for issue in review["issues"])


def test_review_accepts_type_match():
    # 危机钩 in game profile (危机钩 is preferred[0]) → no warning
    body = "夜烬贴在墙后。" * 40 + "公会追兵就在门口。"
    hook = parse_chapter_end_hook("公会追兵迫近，下一章必须撤离。")

    review = review_chapter_hook(body, hook, GAME_PROFILE)

    assert review["scores"].get("hook_type_match") != 6


# ---------------------------------------------------------------------------
# review_chapter_hook — strength vs baseline
# ---------------------------------------------------------------------------


def test_review_flags_weak_hook_in_strong_baseline_genre():
    body = "他抬眼望向远山。" * 40
    hook = {"type": "悬念钩", "strength": "weak", "content": "也许那座山后还有什么。"}

    review = review_chapter_hook(body, hook, XIANXIA_PROFILE)  # baseline=strong

    assert review["scores"].get("hook_strength") == 6
    assert any("强度偏弱" in issue for issue in review["issues"])


def test_review_accepts_strength_at_or_above_baseline():
    body = "她退后半步。" * 40
    hook = {"type": "情绪钩", "strength": "medium", "content": "他还是没有回头。"}

    review = review_chapter_hook(body, hook, ROMANCE_PROFILE)  # baseline=medium

    assert review["scores"].get("hook_strength") != 6


# ---------------------------------------------------------------------------
# Severity classification — hook keys must be registered correctly
# ---------------------------------------------------------------------------


def test_hook_landed_is_hard_other_hook_keys_are_soft():
    assert "hook_landed" in HARD_REVIEWERS
    assert "hook_type_match" in SOFT_REVIEWERS
    assert "hook_strength" in SOFT_REVIEWERS


def test_hook_landed_failure_alone_triggers_revision():
    body = "夜烬走到村口。" * 80
    hook = parse_chapter_end_hook("失踪的银针在抽屉里躺了一整夜。")
    hook_review = review_chapter_hook(body, hook, GENERIC_PROFILE)

    aggregate = review_critical_prose_rules(
        body,
        extra_subreviews=[hook_review],
    )

    assert aggregate["severity_summary"]["has_hard_violation"] is True
    assert aggregate["requires_revision"] is True


def test_hook_type_mismatch_alone_does_not_trigger_revision():
    # Build a clean body with no other issues — and crucially, make the hook
    # content visibly land in the last quarter so the only remaining violation
    # is the soft type-mismatch warning.
    body = (
        "他从屋檐下走出。" * 30
        + "\n\n他走到铺子门口。"
        + "他把铜币按在柜面上，账目对得整齐。"
        + "他即将拿到那枚徽章，名利双收。"
    )
    # Suspense expects 悬念/选择/危机; we feed a 渴望钩.
    hook = {"type": "渴望钩", "strength": "strong", "content": "他即将拿到那枚徽章。"}
    from packages.story_core.genre_profile import SUSPENSE_PROFILE

    hook_review = review_chapter_hook(body, hook, SUSPENSE_PROFILE)

    aggregate = review_critical_prose_rules(
        body,
        extra_subreviews=[hook_review],
    )

    assert aggregate["severity_summary"]["has_hard_violation"] is False
    # Single soft violation < threshold (3) → no revision.
    assert aggregate["requires_revision"] is False
