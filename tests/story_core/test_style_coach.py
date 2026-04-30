from packages.story_core.style_coach import build_style_guidance, enrich_performance_cards


def test_build_style_guidance_returns_web_game_opening_playbook():
    guidance = build_style_guidance(
        genre="网游",
        chapter_number=1,
        world_events=[{"template_id": "market_weak_trace"}],
        scene_cards=[],
    )

    assert guidance["profile_id"] == "web_game_leveling_opening"
    assert "现实压力" in guidance["chapter_pattern"]
    assert any("交易规则通过界面" in item for item in guidance["show_rules"])
    assert any("机械短段" in item for item in guidance["avoid_rules"])


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
