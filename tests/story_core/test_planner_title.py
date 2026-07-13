from packages.story_core.planner import build_chapter_title


def test_web_game_chapter_title_uses_tomato_hook_language():
    title = build_chapter_title(
        3,
        next_focus="补齐两份灰狼毒腺，核算解毒剂与修杖成本",
        genre="网游升级流",
    )

    assert title == "清道夫委托"
    assert not title.startswith("第")
    assert "交锋" not in title


def test_web_game_chapter_title_prioritizes_cost_or_risk():
    title = build_chapter_title(
        4,
        conflict_summary={"summary": "夜烬尝试寄售材料，只换到几枚铜币，下一步要补给。"},
        genre="game_webnovel",
    )

    assert title == "回村补给"
    assert "铜币" not in title
    assert len(title) <= 10


def test_xianxia_chapter_title_uses_the_concrete_chapter_object():
    title = build_chapter_title(
        1,
        next_focus="林照接下祖祠守炉差事，换到残香的第一个可验证反馈。",
        genre="xianxia",
    )

    assert title == "断香炉开口"
    assert "真相" not in title
    assert "道韵" not in title
