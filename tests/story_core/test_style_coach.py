from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards


def test_build_style_guidance_does_not_infer_style_from_genre():
    guidance = build_style_guidance(
        genre="网游",
        chapter_number=1,
        world_events=[{"template_id": "market_weak_trace"}],
        scene_cards=[],
    )

    assert guidance == {}


def test_enrich_performance_cards_adds_market_writing_instructions():
    cards = [
        {
            "scene_id": "s5-c1-market",
            "template_id": "market_weak_trace",
            "must_show": ["价格", "数量", "手续费", "到账"],
        }
    ]
    guidance = build_style_guidance(
        genre="网游",
        chapter_number=1,
        world_events=[{"template_id": "market_weak_trace"}],
        scene_cards=cards,
    )

    enriched = enrich_performance_cards(cards, guidance)

    assert enriched[0]["template_id"] == "market_weak_trace"
    assert "界面操作" in enriched[0]["write_as"]
    assert "解释市场规则" in enriched[0]["avoid"]
    assert any("余额" in item or "手续费" in item for item in enriched[0]["fact_locks"])


def test_build_style_guidance_is_empty_when_book_style_is_unselected():
    guidance = build_style_guidance(
        genre="都市",
        style="",
        chapter_number=2,
        world_events=[],
        scene_cards=[],
    )

    assert guidance == {}


def test_build_style_guidance_uses_only_selected_book_style():
    guidance = build_style_guidance(
        genre="悬疑",
        style="幽默",
        chapter_number=2,
        world_events=[],
        scene_cards=[],
    )

    assert guidance == {
        "profile_id": "book_style:幽默",
        "style": "幽默",
        "voice": "幽默：让笑点来自人物反应、处境反差和顺口接话，不刻意抖包袱。",
    }
