from packages.story_core.adversarial_cut_review import (
    build_expression_patch_suggestions,
    review_adversarial_cuts,
)
from packages.story_core.orchestrator import apply_expression_patches_from_review
from packages.story_core.spot_fix_patch import apply_spot_fix_patches


def test_adversarial_cut_review_flags_slogan_summary_as_replaceable_scene_detail():
    body = "旧端口回执出现后，法力少了一点。代价很小，但代价存在。热闹是真的，缺钱也是真的。"

    review = review_adversarial_cuts(body)

    assert not review["pass"]
    assert review["cut_pressure"] >= 40
    cuts = review["cuts"]
    assert any(cut["quote"] == "代价很小，但代价存在" for cut in cuts)
    assert any(cut["action"] == "replace_with_scene_detail" for cut in cuts)
    assert any("具体场景" in cut["suggestion"] for cut in cuts)


def test_adversarial_cut_review_flags_expository_rule_statement():
    body = "洛婶没问他有没有毒腺，也看不见他的背包。她只负责发委托、收材料、给药。"

    review = review_adversarial_cuts(body)

    assert not review["pass"]
    issue = review["cuts"][0]
    assert issue["type"] == "expository_rule_statement"
    assert "看不见他的背包" in issue["quote"]
    assert issue["action"] == "replace_with_scene_detail"


def test_adversarial_cut_review_allows_natural_npc_boundary_action():
    body = "夜烬把毒腺往柜台边缘推了半寸。洛婶没追问，只把账本翻回原页，继续给药瓶贴签。"

    review = review_adversarial_cuts(body)

    assert review["pass"]
    assert review["cuts"] == []


def test_spot_fix_patch_replaces_only_exact_target_and_preserves_rest():
    original = "甲段。代价很小，但代价存在。乙段。"

    result = apply_spot_fix_patches(
        original,
        [
            {
                "target_text": "代价很小，但代价存在。",
                "replacement_text": "夜烬低头看了一眼法力值，少掉的那一截不多，却足够让他把手从第二只灰鼠身上收回来。",
            }
        ],
    )

    assert result["applied"]
    assert result["applied_patch_count"] == 1
    assert result["revised_content"].startswith("甲段。")
    assert result["revised_content"].endswith("乙段。")
    assert "代价很小" not in result["revised_content"]


def test_spot_fix_patch_skips_ambiguous_targets():
    original = "代价很小，但代价存在。中间。代价很小，但代价存在。"

    result = apply_spot_fix_patches(
        original,
        [{"target_text": "代价很小，但代价存在。", "replacement_text": "替换。"}],
    )

    assert not result["applied"]
    assert result["skipped_patch_count"] == 1
    assert result["revised_content"] == original


def test_expression_patch_suggestions_replace_cut_sentences_without_fact_mutation():
    body = "甲段。代价很小，但代价存在。洛婶没问他有没有毒腺，也看不见他的背包。她只负责发委托、收材料、给药。乙段。"
    review = review_adversarial_cuts(body)

    patches = build_expression_patch_suggestions(review)
    result = apply_spot_fix_patches(body, patches)

    assert patches
    assert result["applied"]
    assert "代价很小" not in result["revised_content"]
    assert "看不见他的背包" not in result["revised_content"]
    assert result["revised_content"].startswith("甲段。")
    assert result["revised_content"].endswith("乙段。")
    assert "狼" not in result["revised_content"]
    assert "金币" not in result["revised_content"]


def test_apply_expression_patches_from_review_returns_revised_body_and_patch_report():
    body = "甲段。代价很小，但代价存在。乙段。"
    review = {"adversarial_cut_review": review_adversarial_cuts(body)}

    revised, report = apply_expression_patches_from_review(body, review)

    assert report["applied"]
    assert report["applied_patch_count"] == 1
    assert "代价很小" not in revised
    assert revised.startswith("甲段。")
    assert revised.endswith("乙段。")
