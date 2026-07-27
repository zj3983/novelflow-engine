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


def test_chinese_chapter_numbers_and_numbering_gap(tmp_path: Path) -> None:
    from packages.story_core.continuation_import import scan_continuation_source

    source = tmp_path / "novel.txt"
    _write(source, "第一章 起\n开篇。\n第三章 转\n转折。\n第十二章 终\n收束。\n")

    result = scan_continuation_source(source)

    assert [chapter.number for chapter in result.chapters] == [1, 3, 12]
    assert result.numbering_gaps == [2, 4, 5, 6, 7, 8, 9, 10, 11]
    assert "numbering_gaps" in result.warnings


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
