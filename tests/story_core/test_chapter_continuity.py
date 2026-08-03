import pytest

from packages.story_core.chapter_continuity import (
    build_continuity_interface,
    review_chinese_fragments,
    review_continuity_interface,
)


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


def test_review_blocks_departed_character_speaking_without_return():
    interface = {"previous_facts": ["沈墨璃离开神殿，前往沈家。"]}

    review = review_continuity_interface(
        "沈墨璃落在林修身侧。\n“寒毒已经过了肘关。”",
        interface,
    )

    assert review["hard_error"] is True
    assert any("沈墨璃" in issue and "无过程返场" in issue for issue in review["issues"])


def test_review_uses_previous_tail_when_structured_facts_are_missing():
    interface = {
        "previous_tail": "沈墨璃紧随其后踏入西侧密道，身影很快消失在冰壁后。殿门重新合拢。"
    }

    review = review_continuity_interface("沈墨璃落在林修身侧，抬手按住阵心石。", interface)

    assert review["hard_error"] is True


def test_review_allows_explicit_return_before_departed_character_acts():
    interface = {"previous_facts": ["沈墨璃离开神殿，前往沈家。"]}

    review = review_continuity_interface(
        "密道重新开启。沈墨璃带着沈家医修赶回神殿，随后扶住小乐。",
        interface,
    )

    assert review["hard_error"] is False


def test_review_marks_conflicting_next_opening_for_downstream_rewrite():
    interface = {
        "previous_facts": ["沈墨璃离开神殿，前往沈家。"],
        "next_chapter_number": 145,
        "next_opening": "沈墨璃一步挡在小乐与残镜之间。",
    }

    review = review_continuity_interface("林修和小乐留在神殿修阵。", interface)

    assert review["downstream_rewrite_required"] is True
    assert review["downstream_chapter_number"] == 145


@pytest.mark.parametrize(
    "line",
    [
        "我只要她看。",
        "她的意思实打实。",
        "这一次她自己做出的选择。",
        "修，便是在替对方铺路。",
    ],
)
def test_review_flags_compressed_chinese_fragments(line):
    issues = review_chinese_fragments(line)

    assert issues
    assert "中文残句" in issues[0]


def test_review_does_not_create_a_general_short_sentence_ban():
    assert review_chinese_fragments("我知道。先回去，路上再说。") == []
