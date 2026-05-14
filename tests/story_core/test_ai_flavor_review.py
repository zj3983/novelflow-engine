from packages.story_core.ai_flavor_review import review_ai_flavor


def test_ai_flavor_review_returns_metrics_and_cuts_for_model_voice():
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
    assert review["metrics"]["formula_count"] >= 2
    assert review["metrics"]["abstract_count"] >= 4
    assert review["metrics"]["concrete_density"] < 0.35
    assert review["cuts"]
    assert all("target_text" in cut and "suggestion" in cut for cut in review["cuts"])


def test_ai_flavor_review_passes_grounded_webnovel_prose():
    body = (
        "夜烬把灰狼毒腺拖回背包，先看了一眼法杖耐久。"
        "木杖还剩七点，背包格子已经亮起黄边。"
        "仓库窗口后，铁栓把账本往旁边一推：“一格一铜，先付。”"
        "夜烬没再问，转身去看村务牌。"
    )

    review = review_ai_flavor(body)

    assert review["pass"]
    assert review["scores"]["ai_flavor"] == 8
    assert review["metrics"]["concrete_density"] >= 0.35
    assert review["cuts"] == []
