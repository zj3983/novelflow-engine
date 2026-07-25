from packages.story_core.book_style import (
    BOOK_STYLE_OPTIONS,
    book_style_prompt,
    normalize_book_style,
)


def test_book_style_options_are_small_and_explicit():
    assert BOOK_STYLE_OPTIONS == ("幽默", "轻松", "热血", "冷峻", "细腻")


def test_unselected_and_legacy_plain_styles_normalize_to_empty():
    assert normalize_book_style("") == ""
    assert normalize_book_style(None) == ""
    assert normalize_book_style("白描、现代中文") == ""
    assert normalize_book_style("克制白描，人物说话自然") == ""
    assert normalize_book_style("未知风格") == ""


def test_supported_book_style_keeps_its_label():
    assert normalize_book_style(" 幽默 ") == "幽默"
    assert normalize_book_style("细腻") == "细腻"


def test_unselected_style_has_no_prompt():
    assert book_style_prompt("") == ""
    assert book_style_prompt("白描、现代中文") == ""


def test_selected_style_has_one_short_expression_prompt():
    prompt = book_style_prompt("幽默")

    assert prompt.startswith("幽默：")
    assert len(prompt) <= 80
    assert "任务" not in prompt
    assert "剧情" not in prompt
    assert "题材" not in prompt
