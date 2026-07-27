import packages.story_core.orchestrator as orchestrator_module
import pytest

from packages.story_core.cold_reader_review import review_cold_reader_experience
from packages.story_core.orchestrator import _review_chapter_body


def test_cold_reader_review_passes_clear_payoff_and_hook():
    body = (
        "苏叶关掉催租短信，登录游戏。\n"
        "夜烬杀掉第五只灰狼时，地上多出一枚灰色晶核。\n"
        "背包提示跳了一下：稀有材料，未鉴定。\n"
        "他没有卖，先收进背包。\n"
        "村口木牌上写着：散人材料收购，今晚只开一小时。\n"
        "手机又震了一下，房租倒计时还剩二十三小时。"
    )

    review = review_cold_reader_experience(body, genre_context={"genre": "网游"})

    assert review["reviewer"] == "cold_reader/v1"
    assert review["pass"] is True
    assert review["scores"]["page_turn"] >= 4
    assert not review["issues"]


def test_cold_reader_review_flags_missing_hook_and_low_reason_to_care():
    body = (
        "夜烬打开面板。\n"
        "他刷了五只灰狼。\n"
        "背包里多了几份材料。\n"
        "第一笔账还没赚到。\n"
        "成本已经先到了。"
    )

    review = review_cold_reader_experience(body, genre_context={"genre": "网游"})

    assert review["pass"] is False
    assert review["scores"]["page_turn"] <= 2
    assert any(issue["type"] == "missing_specific_hook" for issue in review["issues"])
    assert any(issue["type"] == "weak_why_care" for issue in review["issues"])


def test_cold_reader_review_flags_cognitive_overload():
    body = (
        "混沌之种、底层协议、灰烬王庭、星门议会、灵魂链路、七阶职业、"
        "天启拍卖行、白塔公会、神格碎片、深渊税则同时浮出。"
    )

    review = review_cold_reader_experience(body, genre_context={"genre": "网游"})

    assert review["pass"] is False
    assert review["scores"]["cognitive_load"] <= 2
    assert any(issue["type"] == "cognitive_overload" for issue in review["issues"])


def test_cold_reader_review_uses_xuanhuan_profile_without_game_advice():
    body = "他反复运转功法，却迟迟没有突破，也不知道下一步该去哪里。"

    review = review_cold_reader_experience(
        body,
        genre_context={"genre_plugin_ids": ["xianxia"]},
    )

    revision_text = "\n".join(review["revision_plan"])
    assert "修炼" in revision_text or "宗门" in revision_text
    assert all(term not in revision_text for term in ("交易行", "公会", "NPC", "材料异动"))


def test_cold_reader_review_counts_only_xuanhuan_overload_terms():
    body = "天命道骨、太虚剑宗、九幽魔域、无相灵根、归墟古印同时现世。"

    xuanhuan = review_cold_reader_experience(body, genre_context={"genre": "玄幻"})
    game = review_cold_reader_experience(body, genre_context={"genre": "虚拟现实"})

    assert any(issue["type"] == "cognitive_overload" for issue in xuanhuan["issues"])
    assert not any(issue["type"] == "cognitive_overload" for issue in game["issues"])


@pytest.mark.parametrize(
    ("plugin_id", "body", "expected_advice", "excluded_advice"),
    (
        ("game_webnovel", "任务指向交易行，代价已经明确。", "现实期限", "人物处境"),
        ("xuanhuan", "修炼遇到突破，代价已经明确。", "人物处境", "现实期限"),
        ("xianxia", "修炼遇到突破，代价已经明确。", "人物处境", "现实期限"),
    ),
)
def test_cold_reader_review_resolves_genre_plugin_ids(
    plugin_id,
    body,
    expected_advice,
    excluded_advice,
):
    review = review_cold_reader_experience(
        body,
        genre_context={"genre_plugin_ids": [plugin_id]},
    )

    revision_text = "\n".join(review["revision_plan"])
    assert review["scores"]["page_turn"] >= 3
    assert expected_advice in revision_text
    assert excluded_advice not in revision_text


def test_cold_reader_review_prefers_recognized_plugin_id_over_genre_alias():
    review = review_cold_reader_experience(
        "他停在原地。",
        genre_context={"genre": "游戏", "genre_plugin_ids": ["xuanhuan"]},
    )

    revision_text = "\n".join(review["revision_plan"])
    assert "人物处境" in revision_text
    assert "现实期限" not in revision_text


def test_cold_reader_review_does_not_infer_genre_from_notes():
    review = review_cold_reader_experience(
        "他停在原地。",
        genre_context={"notes": ["fantasy"]},
    )

    revision_text = "\n".join(review["revision_plan"])
    assert "人物目标" in revision_text
    assert "人物处境" not in revision_text
    assert "现实期限" not in revision_text


def test_cold_reader_review_unknown_plugin_id_falls_back_to_generic_profile():
    review = review_cold_reader_experience(
        "他停在原地。",
        genre_context={"genre_plugin_ids": ["custom_unknown"]},
    )

    revision_text = "\n".join(review["revision_plan"])
    assert "人物目标" in revision_text
    assert "人物处境" not in revision_text
    assert "现实期限" not in revision_text


def test_cold_reader_review_uses_genre_when_plugin_ids_are_unrecognized():
    review = review_cold_reader_experience(
        "他停在原地。",
        genre_context={"genre": "网游", "genre_plugin_ids": ["custom_unknown"]},
    )

    revision_text = "\n".join(review["revision_plan"])
    assert "现实期限" in revision_text
    assert "人物处境" not in revision_text


def test_cold_reader_review_keeps_protocol_as_game_payoff():
    review = review_cold_reader_experience(
        "底层协议浮现，代价已经明确。",
        genre_context={"genre": "网游"},
    )

    assert review["scores"]["page_turn"] >= 4


def test_cold_reader_review_without_genre_uses_only_generic_terms_and_advice():
    body = (
        "交易行、公会、NPC、材料异动、修炼、宗门、天命道骨、太虚剑宗、"
        "九幽魔域、无相灵根、归墟古印都摆在他面前。"
    )

    review = review_cold_reader_experience(body)

    revision_text = "\n".join(review["revision_plan"])
    assert review["scores"]["page_turn"] <= 2
    assert not any(issue["type"] == "cognitive_overload" for issue in review["issues"])
    assert all(
        term not in revision_text
        for term in ("交易行", "公会", "NPC", "材料异动", "修炼", "宗门")
    )


def test_cold_reader_review_keeps_repetitive_loop_advice_in_current_profile():
    game_body = "打开面板。查面板。刷了三轮。成本已经先到了。"
    xuanhuan_body = "运转功法。重复吐纳。再次冲关。境界仍旧未动。"

    game = review_cold_reader_experience(game_body, genre_context={"genre": "游戏"})
    xuanhuan = review_cold_reader_experience(xuanhuan_body, genre_context={"genre": "修仙"})

    game_advice = "\n".join(game["revision_plan"])
    xuanhuan_advice = "\n".join(xuanhuan["revision_plan"])
    assert "异常掉落" in game_advice
    assert "突破" in xuanhuan_advice or "势力" in xuanhuan_advice
    assert all(term not in xuanhuan_advice for term in ("NPC", "掉落", "耐久"))


def test_chapter_review_passes_genre_context_to_cold_reader(monkeypatch):
    genre_context = {"genre_plugin_ids": ["xuanhuan"]}
    captured = {}

    def fake_cold_reader(body, *, previous_summary="", genre_context=None):
        captured["genre_context"] = genre_context
        return {
            "reviewer": "cold_reader/v1",
            "pass": True,
            "scores": {},
            "issues": [],
            "revision_plan": [],
            "previous_summary_used": bool(previous_summary),
        }

    monkeypatch.setattr(orchestrator_module, "review_cold_reader_experience", fake_cold_reader)

    _review_chapter_body(1, "plain body", {}, [], genre_context=genre_context)

    assert captured["genre_context"] is genre_context
