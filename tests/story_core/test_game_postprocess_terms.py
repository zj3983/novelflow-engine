from packages.story_core.genre_stages.game_webnovel.postprocess import _normalize_web_game_terms


def test_web_game_postprocess_normalizes_real_currency_abbreviations():
    body = "当前兑换价1银币=20.00 RMB，手续费7.50 CNY，预计到账1492.50 RMB。"

    normalized = _normalize_web_game_terms(body)

    assert "RMB" not in normalized
    assert "CNY" not in normalized
    assert "20.00元" in normalized
    assert "7.50元" in normalized
    assert "1492.50元" in normalized


def test_web_game_postprocess_repairs_free_attribute_point_phrase():
    body = "夜烬将5点自由分配属性点全部加到了智力上，确认后可用属性点清零。"

    normalized = _normalize_web_game_terms(body)

    assert normalized == "夜烬把5点自由属性点都加到了智力上，确认后可用属性点清零。"
