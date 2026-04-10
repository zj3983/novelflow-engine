from __future__ import annotations

from pathlib import Path


def _write(path: Path, name: str, content: str) -> None:
    (path / name).write_text(content, encoding="utf-8")


def test_scan_complete_book_folder_can_bootstrap_and_has_no_warnings(tmp_path: Path) -> None:
    from packages.story_core.book_import import scan_book_folder

    _write(tmp_path, "author_intent.md", "Author intent: write a tight thriller.\n")
    _write(tmp_path, "book_rules.md", "Rules: keep chapters short.\n")
    _write(tmp_path, "story_bible.md", "Bible: noir city, rain, secrets.\n")
    _write(tmp_path, "volume_outline.md", "Volume outline:\n- Act I: Setup\n")
    _write(tmp_path, "current_focus.md", "Current focus: reveal the hidden witness.\n")
    _write(tmp_path, "current_state.md", "State: Chapter 3 drafted.\n")
    _write(tmp_path, "pending_hooks.md", "Hooks: missing key, broken watch.\n")
    _write(tmp_path, "subplot_board.md", "Subplots: A vs B.\n")
    _write(tmp_path, "character_matrix.md", "| Name | Role |\n| --- | --- |\n| Lin Yue | Protagonist |\n")

    result = scan_book_folder(tmp_path)

    assert result.report.exists is True
    assert result.report.missing_required_files == []
    assert result.report.can_bootstrap is True
    assert "reveal the hidden witness" in result.bootstrap.outline
    assert result.report.warnings == []


def test_scan_incomplete_book_folder_reports_missing_required_files_but_preserves_documents(
    tmp_path: Path,
) -> None:
    from packages.story_core.book_import import scan_book_folder

    # Omits current_focus.md and volume_outline.md (required).
    _write(tmp_path, "author_intent.md", "Author intent: epic romance.\n")
    _write(tmp_path, "book_rules.md", "Rules: no deus ex machina.\n")
    _write(tmp_path, "story_bible.md", "Bible: floating islands.\n")
    _write(tmp_path, "current_state.md", "State: Chapter 1 planned.\n")
    _write(tmp_path, "pending_hooks.md", "Hooks: broken promise.\n")
    _write(tmp_path, "subplot_board.md", "Subplots: family feud.\n")
    _write(tmp_path, "character_matrix.md", "- Lin Yue\n- Old Archivist\n")

    result = scan_book_folder(tmp_path)

    assert sorted(result.report.missing_required_files) == ["current_focus.md", "volume_outline.md"]
    assert result.report.can_bootstrap is False
    assert "epic romance" in result.report.documents.get("author_intent.md", "")
    assert "floating islands" in result.report.documents.get("story_bible.md", "")


def test_scan_book_folder_marks_required_empty_file_as_unusable(tmp_path: Path) -> None:
    from packages.story_core.book_import import scan_book_folder

    _write(tmp_path, "author_intent.md", "Author intent: thriller.\n")
    _write(tmp_path, "book_rules.md", "Rules: keep tension high.\n")
    _write(tmp_path, "story_bible.md", "Bible: rain-soaked city.\n")
    _write(tmp_path, "volume_outline.md", "Volume outline:\n- Act I\n")
    _write(tmp_path, "current_focus.md", "")

    result = scan_book_folder(tmp_path)

    assert result.report.can_bootstrap is False
    assert "current_focus.md" in result.report.unusable_required_files
    assert "current_focus.md" in result.report.empty_files


def test_scan_book_folder_marks_required_directory_as_unusable(tmp_path: Path) -> None:
    from packages.story_core.book_import import scan_book_folder

    (tmp_path / "current_focus.md").mkdir()
    _write(tmp_path, "volume_outline.md", "Volume outline:\n- Act I\n")

    result = scan_book_folder(tmp_path)

    assert result.report.can_bootstrap is False
    assert "current_focus.md" in result.report.unusable_required_files
    assert "current_focus.md" not in result.report.missing_required_files


def test_scan_book_folder_skips_markdown_alignment_rows(tmp_path: Path) -> None:
    from packages.story_core.book_import import scan_book_folder

    _write(tmp_path, "current_focus.md", "Current focus: keep the witness safe.\n")
    _write(tmp_path, "volume_outline.md", "Volume outline: chapter plan.\n")
    _write(
        tmp_path,
        "character_matrix.md",
        "| Name | Role |\n| :--- | ---: |\n| Lin Yue | Protagonist |\n| Old Archivist | Support |\n",
    )

    result = scan_book_folder(tmp_path)

    assert result.bootstrap.characters == ["Lin Yue", "Old Archivist"]
