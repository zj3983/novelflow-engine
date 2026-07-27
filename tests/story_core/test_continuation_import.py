from __future__ import annotations

from pathlib import Path

import pytest


def _write(path: Path, text: str, encoding: str = "utf-8") -> None:
    path.write_text(text, encoding=encoding)


def test_scans_gbk_text_with_two_chapters_and_source_offsets(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "novel.txt"
    text = "第1章 初见\n山门初开。\n第2章 夜雨\n雨落长街。\n"
    source.write_bytes(text.encode("gbk"))

    result = scan_continuation_source(source)

    assert result.encoding == "gb18030"
    assert [chapter.number for chapter in result.chapters] == [1, 2]
    assert [chapter.title for chapter in result.chapters] == ["第1章 初见", "第2章 夜雨"]
    assert [chapter.body for chapter in result.chapters] == ["山门初开。", "雨落长街。"]
    assert text[result.chapters[0].source_start : result.chapters[0].source_end] == "山门初开。\n"
    assert result.can_analyze is True


def test_directory_uses_natural_numeric_order(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    _write(tmp_path / "第10章.txt", "第10章 归来\n这是第十章正文。\n")
    _write(tmp_path / "第2章.txt", "第2章 出发\n这是第二章正文。\n")

    result = scan_continuation_source(tmp_path)

    assert result.source_kind == "directory"
    assert [chapter.number for chapter in result.chapters] == [2, 10]
    assert [chapter.source_name for chapter in result.chapters] == ["第2章.txt", "第10章.txt"]


def test_directory_filenames_define_chapters_for_plain_body_files(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    _write(tmp_path / "第10章.txt", "这是第十章的正文。\n")
    _write(tmp_path / "第2章.txt", "这是第二章的正文。\n")

    result = scan_continuation_source(tmp_path)

    assert [chapter.number for chapter in result.chapters] == [2, 10]
    assert [chapter.title for chapter in result.chapters] == ["第2章", "第10章"]
    assert [chapter.body for chapter in result.chapters] == ["这是第二章的正文。", "这是第十章的正文。"]
    assert "chapter_boundaries_unconfirmed" not in result.warnings
    assert result.can_analyze is True


def test_directory_scans_short_gbk_body_files(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    (tmp_path / "第10章.txt").write_bytes("夜雨长街".encode("gbk"))
    (tmp_path / "第2章.txt").write_bytes("风起云涌".encode("gbk"))

    result = scan_continuation_source(tmp_path)

    assert result.encoding == "gb18030"
    assert [chapter.number for chapter in result.chapters] == [2, 10]
    assert [chapter.body for chapter in result.chapters] == ["风起云涌", "夜雨长街"]
    assert result.can_analyze is True


def test_natural_sort_ties_are_stable_for_recursive_creation_orders(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import _natural_key, scan_continuation_source

    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    for root, directory_order, file_order in (
        (first_root, ["part2", "part02"], ["chapter2.txt", "chapter02.txt"]),
        (second_root, ["part02", "part2"], ["chapter02.txt", "chapter2.txt"]),
    ):
        for directory in directory_order:
            (root / directory).mkdir(parents=True)
        for index, directory in enumerate(directory_order, start=1):
            _write(root / directory / "chapter.txt", f"第{index}章 递归\n正文 {directory}。\n")
        (root / "partA").mkdir()
        for index, name in enumerate(file_order, start=3):
            _write(root / "partA" / name, f"第{index}章 文件\n正文 {name}。\n")

    first_names = [chapter.source_name for chapter in scan_continuation_source(first_root).chapters]
    second_names = [chapter.source_name for chapter in scan_continuation_source(second_root).chapters]

    assert _natural_key(first_root / "part02" / "chapter.txt", first_root) < _natural_key(
        first_root / "part2" / "chapter.txt", first_root
    )
    assert first_names == second_names
    assert first_names == [
        "part02/chapter.txt",
        "part2/chapter.txt",
        "partA/chapter02.txt",
        "partA/chapter2.txt",
    ]


def test_duplicate_content_is_grouped_and_blocks_analysis(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "duplicate.txt"
    _write(source, "第1章 甲\n相同正文。\n第2章 乙\n相同正文。\n")

    result = scan_continuation_source(source)

    assert result.duplicate_groups == [[chapter.chapter_id for chapter in result.chapters]]
    assert "duplicate_chapters" in result.warnings
    assert result.can_analyze is False


def test_markdown_headings_define_chapters(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "novel.md"
    _write(source, "# 第1章 风起\n\n风从海上来。\n## 第2章 潮生\n潮声渐近。\n")

    result = scan_continuation_source(source)

    assert [chapter.title for chapter in result.chapters] == ["第1章 风起", "第2章 潮生"]
    assert [chapter.body for chapter in result.chapters] == ["风从海上来。", "潮声渐近。"]
    assert result.can_analyze is True


def test_markdown_nested_sections_remain_in_chapter_body(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "nested.md"
    _write(source, "# 第一章 起\n正文。\n## 场景一\n场景正文。\n# 第二章 转\n后文。\n")

    result = scan_continuation_source(source)

    assert [chapter.title for chapter in result.chapters] == ["第一章 起", "第二章 转"]
    assert "## 场景一" in result.chapters[0].body


def test_markdown_same_level_interlude_is_a_chapter_boundary(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "interlude.md"
    _write(source, "# 第一章 开始\n开篇正文。\n# 幕间\n幕间正文。\n# 第二章 继续\n后续正文。\n")

    result = scan_continuation_source(source)

    assert [chapter.title for chapter in result.chapters] == ["第一章 开始", "幕间", "第二章 继续"]
    assert [chapter.body for chapter in result.chapters] == ["开篇正文。", "幕间正文。", "后续正文。"]
    assert all("# " not in chapter.body for chapter in result.chapters)


def test_markdown_interlude_matches_adjacent_explicit_heading_level(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "mixed-levels.md"
    _write(
        source,
        "# 第一章 开始\n开篇。\n## 第二章 转折\n转折。\n## 幕间\n幕间。\n## 第三章 继续\n继续。\n",
    )

    result = scan_continuation_source(source)

    assert [chapter.title for chapter in result.chapters] == [
        "第一章 开始",
        "第二章 转折",
        "幕间",
        "第三章 继续",
    ]
    assert [chapter.body for chapter in result.chapters] == ["开篇。", "转折。", "幕间。", "继续。"]


def test_markdown_fenced_headings_do_not_split_chapters(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "fenced.md"
    _write(
        source,
        "# 第一章 示例\n```markdown\n# 第99章 代码示例\n```\n围栏之后。\n# 第二章 正文\n结束。\n",
    )

    result = scan_continuation_source(source)

    assert [chapter.number for chapter in result.chapters] == [1, 2]
    assert "# 第99章 代码示例" in result.chapters[0].body


def test_markdown_ordinary_headings_use_one_level_after_preface(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "preface.md"
    _write(source, "# 前言\n导语。\n## 背景\n背景正文。\n# 正文部分\n正文。\n")

    result = scan_continuation_source(source)

    assert [chapter.title for chapter in result.chapters] == ["前言", "正文部分"]
    assert "## 背景" in result.chapters[0].body


def test_markdown_closed_heading_strips_closing_hashes(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "closed.md"
    _write(source, "### 第一章 标题 ###\n正文。\n### 第二章 后续 ###\n后文。\n")

    result = scan_continuation_source(source)

    assert [chapter.title for chapter in result.chapters] == ["第一章 标题", "第二章 后续"]


def test_chinese_chapter_numbers_and_numbering_gap(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "novel.txt"
    _write(source, "第一章 起\n开篇。\n第三章 转\n转折。\n第十二章 终\n收束。\n")

    result = scan_continuation_source(source)

    assert [chapter.number for chapter in result.chapters] == [1, 3, 12]
    assert result.numbering_gaps == [2, 4, 5, 6, 7, 8, 9, 10, 11]
    assert "numbering_gaps" in result.warnings


def test_chinese_digit_strings_and_large_unit_numbers(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "numbers.txt"
    _write(
        source,
        "第二〇二四章 新纪元\n正文一。\n第一万零二十四章 远行\n正文二。\n",
    )

    result = scan_continuation_source(source)

    assert [chapter.number for chapter in result.chapters] == [2024, 10024]


def test_mixed_arabic_and_chinese_number_is_not_a_chapter_boundary(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "invalid-number.txt"
    text = "第12三章 非法编号\n仍是待确认正文。\n"
    _write(source, text)

    result = scan_continuation_source(source)

    assert len(result.chapters) == 1
    assert result.chapters[0].body.splitlines() == text.strip().splitlines()
    assert "chapter_boundaries_unconfirmed" in result.warnings


def test_empty_chapter_blocks_analysis(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "novel.txt"
    _write(source, "第1章 空\n第2章 实\n有正文。\n")

    result = scan_continuation_source(source)

    assert result.chapters[0].body == ""
    assert "empty_chapters" in result.warnings
    assert result.can_analyze is False


def test_unheaded_long_text_is_one_unconfirmed_candidate(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "draft.txt"
    text = "这是一段没有章节标题的长篇正文。" * 100
    _write(source, text)

    result = scan_continuation_source(source)

    assert len(result.chapters) == 1
    assert result.chapters[0].body == text
    assert result.warnings == ["chapter_boundaries_unconfirmed"]
    assert result.can_analyze is False


@pytest.mark.parametrize("kind", ["unsupported", "empty_directory"])
def test_sources_without_supported_content_cannot_be_analyzed(tmp_path: Path, kind: str) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    if kind == "unsupported":
        source = tmp_path / "novel.pdf"
        source.write_bytes(b"not a novel")
    else:
        source = tmp_path

    result = scan_continuation_source(source)

    assert result.chapters == []
    assert result.total_chars == 0
    assert "no_supported_files" in result.warnings
    assert result.can_analyze is False
    assert result.source_path == str(source.resolve())


def test_forced_encoding_succeeds_and_failures_are_stable() -> None:
    from packages.story_core.continuation_import import decode_novel_bytes

    payload = "章节正文".encode("gbk")

    assert decode_novel_bytes(payload, forced_encoding="gbk") == ("章节正文", "gbk")
    with pytest.raises(ValueError, match="^source_encoding_unknown$"):
        decode_novel_bytes(payload, forced_encoding="utf-8")
    with pytest.raises(ValueError, match="^source_encoding_unknown$"):
        decode_novel_bytes(payload, forced_encoding="definitely-not-an-encoding")


def test_encoding_detection_distinguishes_bom_and_plain_utf8() -> None:
    from packages.story_core.continuation_import import decode_novel_bytes

    text = "第一章 编码\n正文。\n"

    assert decode_novel_bytes(text.encode("utf-8")) == (text, "utf-8")
    assert decode_novel_bytes(text.encode("utf-8-sig")) == (text, "utf-8-sig")
    with pytest.raises(ValueError, match="^source_encoding_unknown$"):
        decode_novel_bytes(text.encode("utf-16"))
    with pytest.raises(ValueError, match="^source_encoding_unknown$"):
        decode_novel_bytes(text.encode("utf-32"))
    assert decode_novel_bytes(text.encode("utf-16"), forced_encoding="utf-16") == (text, "utf-16")


def test_short_gbk_text_is_selected_over_implausible_diagnostics() -> None:
    from packages.story_core.continuation_import import decode_novel_bytes

    text = "章节正文"

    assert decode_novel_bytes(text.encode("gbk")) == (text, "gb18030")


def test_default_and_diagnostic_encoding_contracts_are_separate(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import (
        DEFAULT_ENCODINGS,
        DIAGNOSTIC_ENCODINGS,
        decode_novel_bytes,
        scan_continuation_source,
    )

    assert DEFAULT_ENCODINGS == ("utf-8-sig", "utf-8", "gb18030", "gbk")
    assert DIAGNOSTIC_ENCODINGS == ("big5", "utf-16-le", "utf-16-be")

    text = "魑魅魍魉"
    assert decode_novel_bytes(text.encode("gbk")) == (text, "gb18030")

    (tmp_path / "第1章.txt").write_bytes(text.encode("gbk"))
    result = scan_continuation_source(tmp_path)

    assert result.encoding == "gb18030"
    assert result.chapters[0].body == text
    assert result.can_analyze is True


def test_ambiguous_legacy_and_bomless_utf16_encodings_are_rejected() -> None:
    from packages.story_core.continuation_import import decode_novel_bytes

    with pytest.raises(ValueError, match="^source_encoding_unknown$"):
        decode_novel_bytes("第一章 繁體小說\n這是正文。\n".encode("big5"))
    with pytest.raises(ValueError, match="^source_encoding_unknown$"):
        decode_novel_bytes("第一章 UTF16\n正文。\n".encode("utf-16-le"))


@pytest.mark.parametrize(
    ("text", "encoding"),
    [
        ("繁體中文", "big5"),
        ("章节正文", "utf-16-le"),
    ],
)
def test_ambiguous_short_legacy_text_requires_forced_encoding(text: str, encoding: str) -> None:
    from packages.story_core.continuation_import import decode_novel_bytes

    payload = text.encode(encoding)

    with pytest.raises(ValueError, match="^source_encoding_unknown$"):
        decode_novel_bytes(payload)
    assert decode_novel_bytes(payload, forced_encoding=encoding) == (text, encoding)


def test_binary_controls_are_blocked_by_scan_after_successful_decode(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import decode_novel_bytes, scan_continuation_source

    payload = b"# Chapter 1\nbody\x00\x01\x02\n"
    decoded = "# Chapter 1\nbody\x00\x01\x02\n"
    assert decode_novel_bytes(payload) == (decoded, "utf-8")
    assert decode_novel_bytes(payload, forced_encoding="utf-8") == (decoded, "utf-8")

    (tmp_path / "chapter.txt").write_bytes(payload)
    result = scan_continuation_source(tmp_path, forced_encoding="utf-8")

    assert "source_text_unsafe" in result.warnings
    assert result.can_analyze is False


def test_dangerous_unicode_format_controls_are_blocked_by_scan(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import decode_novel_bytes, scan_continuation_source

    text = "第一章 安全\n正文\u202e隐藏。\n"
    payload = text.encode("utf-8")

    assert decode_novel_bytes(payload) == (text, "utf-8")
    assert decode_novel_bytes(payload, forced_encoding="utf-8") == (text, "utf-8")

    source = tmp_path / "unsafe.txt"
    source.write_bytes(payload)
    result = scan_continuation_source(source)

    assert "source_text_unsafe" in result.warnings
    assert result.can_analyze is False


def test_normal_unicode_joiners_and_variation_selectors_are_safe(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "emoji.txt"
    _write(source, "第一章 技术\n👩‍💻正在工作\u200c，状态正常️。\n")

    result = scan_continuation_source(source)

    assert "source_text_unsafe" not in result.warnings
    assert result.can_analyze is True


def test_unheaded_directory_file_uses_the_file_as_a_chapter_boundary(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    _write(tmp_path / "chapter-1.txt", "没有可靠标题的正文。\n")

    result = scan_continuation_source(tmp_path)

    assert "chapter_boundaries_unconfirmed" not in result.warnings
    assert result.can_analyze is True


def test_empty_file_cannot_be_analyzed(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "empty.md"
    _write(source, "")

    result = scan_continuation_source(source)

    assert result.chapters == []
    assert "empty_source" in result.warnings
    assert result.can_analyze is False


def test_ids_and_fingerprints_are_stable_across_scans(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "novel.txt"
    _write(source, "第1章 稳定\n不会变化的正文。\n")

    first = scan_continuation_source(source)
    second = scan_continuation_source(source)

    assert first.chapters[0].chapter_id == second.chapters[0].chapter_id
    assert first.chapters[0].fingerprint == second.chapters[0].fingerprint
    assert len(first.chapters[0].fingerprint) == 64


def test_chapter_ids_survive_source_move_rename_and_preface(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "original.txt"
    novel = "第一章 稳定\n正文甲。\n第二章 继续\n正文乙。\n"
    _write(source, novel)
    original_ids = [chapter.chapter_id for chapter in scan_continuation_source(source).chapters]

    nested = tmp_path / "nested"
    nested.mkdir()
    moved = nested / "renamed.md"
    source.rename(moved)
    _write(moved, "作品说明，不属于章节。\n" + novel)
    moved_ids = [chapter.chapter_id for chapter in scan_continuation_source(moved).chapters]

    assert moved_ids == original_ids


def test_identical_logical_chapters_use_stable_occurrence_ids(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "duplicates.txt"
    novel = "第一章 同名\n相同正文。\n第一章 同名\n相同正文。\n"
    _write(source, novel)
    first_ids = [chapter.chapter_id for chapter in scan_continuation_source(source).chapters]

    _write(source, "前置说明。\n" + novel)
    second_ids = [chapter.chapter_id for chapter in scan_continuation_source(source).chapters]

    assert len(set(first_ids)) == 2
    assert second_ids == first_ids
