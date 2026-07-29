from packages.story_core.chapter_continuity import build_continuity_interface


def test_interface_uses_previous_tail_and_confirmed_facts():
    result = build_continuity_interface(
        144,
        previous={
            "chapter_number": 143,
            "body": "开头" + "中" * 1200 + "沈墨璃离开神殿。",
            "chapter_summary": {
                "facts": ["沈墨璃离开神殿。"],
                "unresolved_threads": ["六个光点正在合围。"],
            },
        },
        next_chapter=None,
    )

    assert result["previous_chapter_number"] == 143
    assert result["previous_tail"].endswith("沈墨璃离开神殿。")
    assert not result["previous_tail"].startswith("开头")
    assert result["previous_facts"] == ["沈墨璃离开神殿。"]
    assert result["previous_threads"] == ["六个光点正在合围。"]
    assert "next_opening" not in result


def test_interface_includes_next_opening_for_historical_rewrite():
    result = build_continuity_interface(
        144,
        previous=None,
        next_chapter={"chapter_number": 145, "body": "下一章开头" + "后" * 900},
    )

    assert result["next_chapter_number"] == 145
    assert result["next_opening"].startswith("下一章开头")
    assert len(result["next_opening"]) <= 700
    assert result["fact_priority"] == ["已发生剧情", "本章计划", "静态人物设定", "后续旧稿"]


def test_interface_is_empty_at_first_chapter_without_future_draft():
    assert build_continuity_interface(1, previous=None, next_chapter=None) == {}
