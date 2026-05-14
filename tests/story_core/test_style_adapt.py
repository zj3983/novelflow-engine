"""Tests for whole-chapter style adaptation (Stage 2B)."""
from packages.story_core.segmented_writing import (
    build_style_adapt_prompt,
    style_adapt_safety_check,
)


# ---------------------------------------------------------------------------
# build_style_adapt_prompt
# ---------------------------------------------------------------------------


def test_style_adapt_prompt_states_facts_frozen_contract():
    body = "夜烬走到药剂铺。\n\n洛婶说：'十份。'\n\n他放下5铜。"
    plan = {
        "craft_pack": {
            "show_vs_tell": {"conversions": [{"tell": "他很谨慎", "show": "他先看耐久"}]}
        }
    }

    prompt = build_style_adapt_prompt(body, plan)

    # Hard contract — style pass must be facts-frozen
    assert "不改事实" in prompt
    assert "硬禁止" in prompt
    assert "改名字" in prompt
    assert "改数字" in prompt
    assert "改面板数据" in prompt
    # Original body must be embedded verbatim
    assert body in prompt
    # Style brief embedded as JSON
    assert "show_vs_tell_conversions" in prompt or "show_vs_tell" in prompt


def test_style_adapt_prompt_pulls_voice_from_protagonist():
    body = "短篇。"
    plan = {
        "protagonist": {
            "name": "苏叶",
            "voice": {"signature_phrases": ["先算账"], "self_reference": "我"},
        }
    }
    prompt = build_style_adapt_prompt(body, plan)
    assert "voice_guidance" in prompt
    assert "苏叶" in prompt or "先算账" in prompt


def test_style_adapt_prompt_handles_missing_craft_pack():
    body = "占位文本。"
    prompt = build_style_adapt_prompt(body, {})
    # Should still emit the contract; style brief just won't have craft fields
    assert "不改事实" in prompt
    assert body in prompt


# ---------------------------------------------------------------------------
# style_adapt_safety_check
# ---------------------------------------------------------------------------


def test_safety_accepts_well_behaved_rewrite():
    original = (
        "夜烬走到药剂铺。\n\n"
        "洛婶头也不抬：'十份。'\n\n"
        "他从荷包里取出5铜，放在柜台上。\n\n"
        "【交易完成：-5铜】\n\n"
        "余额：23铜。"
    )
    candidate = (
        "夜烬停在药剂铺门口，目光扫过柜台。\n\n"
        "洛婶低头不语，只吐出两个字：'十份。'\n\n"
        "他默默从荷包里摸出5铜，轻轻放在柜台上。\n\n"
        "【交易完成：-5铜】\n\n"
        "余额：23铜。"
    )

    report = style_adapt_safety_check(original, candidate)

    assert report["accept"] is True
    assert report["reason"] == "ok"


def test_safety_rejects_invented_numbers():
    original = "他放下5铜。【交易完成：-5铜】"
    candidate = "他放下7铜。【交易完成：-7铜】"  # numbers changed

    report = style_adapt_safety_check(original, candidate)

    assert report["accept"] is False
    assert report["reason"] == "invented_numbers"
    assert "7" in report["mismatch"]["invented"]


def test_safety_rejects_changed_panel_tags():
    original = "【系统提示：获得灰狼毒腺×2】\n\n他点头。"
    candidate = "【系统提示：获得灰狼毒腺×3】\n\n他点头。"  # panel content changed

    report = style_adapt_safety_check(original, candidate)

    assert report["accept"] is False
    assert report["reason"] in ("panel_tags_changed", "invented_numbers")


def test_safety_rejects_drastic_length_drift():
    original = "他走到铺子前。" * 200  # ~1400 chars
    candidate = "他走。"  # collapsed to nothing

    report = style_adapt_safety_check(original, candidate)

    assert report["accept"] is False
    assert report["reason"] == "candidate_too_short"


def test_safety_rejects_empty_candidate():
    report = style_adapt_safety_check("原章正文。", "")

    assert report["accept"] is False
    assert report["reason"] == "candidate_empty"


def test_safety_accepts_minor_length_change_within_band():
    """Style adapt may grow or shrink prose modestly without tripping length guard."""
    original = "他放下5铜。" * 50
    candidate = "他默默放下5铜。" * 50  # +1 char per repetition

    report = style_adapt_safety_check(original, candidate)

    assert report["accept"] is True


def test_safety_rejects_too_long_candidate():
    original = "短文。" * 5
    candidate = "他做了很多事情。" * 200  # ~10x growth

    report = style_adapt_safety_check(original, candidate)

    assert report["accept"] is False
    assert report["reason"] == "candidate_too_long"
