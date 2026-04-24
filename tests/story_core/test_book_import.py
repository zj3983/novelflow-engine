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

    assert [character.name for character in result.bootstrap.characters] == ["Lin Yue", "Old Archivist"]


def test_scan_book_folder_extracts_markdown_character_profiles(tmp_path: Path) -> None:
    from packages.story_core.book_import import scan_book_folder

    _write(tmp_path, "current_focus.md", "Current focus:\n- Keep the hero hidden.\n")
    _write(tmp_path, "volume_outline.md", "Volume outline:\n- Act I\n")
    _write(
        tmp_path,
        "story_bible.md",
        "# Sample Story Bible\n\n## 01_World\n\n- **Core**: A game economy changes real life.\n",
    )
    _write(
        tmp_path,
        "character_matrix.md",
        "\n".join(
            [
                "## Su Ye",
                "- **定位**: 主角",
                "- **当前**: Level 3, avoiding the guild patrol.",
                "",
                "## Zhao Pangzi",
                "- **动机**: Profit from long-term equipment trading.",
            ]
        ),
    )

    result = scan_book_folder(tmp_path)

    assert result.bootstrap.world_summary == "World：Core: A game economy changes real life."
    assert [character.model_dump() for character in result.bootstrap.characters] == [
        {"name": "Su Ye", "goal": "Level 3, avoiding the guild patrol."},
        {"name": "Zhao Pangzi", "goal": "Profit from long-term equipment trading."},
    ]


def test_scan_book_folder_builds_structured_world_blueprint(tmp_path: Path) -> None:
    from packages.story_core.book_import import scan_book_folder

    _write(tmp_path, "current_focus.md", "FOCUS: Let the reborn player secure the first hidden quest.\n")
    _write(tmp_path, "volume_outline.md", "VOLUME: Early arc follows a cautious solo start before guild conflict.\n")
    _write(
        tmp_path,
        "story_bible.md",
        "\n".join(
            [
                "# Divine Gate Story Bible",
                "- Game: Divine Gate is a 100% immersive global VRMMO.",
                "- Rule: game currency can be exchanged with real money.",
                "- Power: levels, skills, equipment, professions, and hidden quests shape advancement.",
                "- Faction: the Dawn Guild hunts rare first-clear rewards.",
                "- Location: Novice Village is the first resource bottleneck.",
                "- Arc: Su Ye uses rebirth knowledge to stay low-profile and seize compounding advantages.",
            ]
        ),
    )
    _write(
        tmp_path,
        "character_matrix.md",
        "\n".join(
            [
                "## Su Ye",
                "- **Role**: protagonist",
                "- **Current**: Level 3 and avoiding guild scouts.",
                "- **Motivation**: Use rebirth knowledge without exposing the secret.",
                "- **Personality**: cautious, patient, opportunistic",
                "- **Speech**: short and plain",
                "",
                "## Dawn Guild",
                "- **Role**: antagonist faction",
                "- **Goal**: monopolize the first hidden quest chain.",
            ]
        ),
    )

    result = scan_book_folder(tmp_path)

    blueprint = result.bootstrap.world_blueprint
    assert blueprint.premise == "Divine Gate Story Bible"
    assert any("game currency can be exchanged with real money" in rule for rule in blueprint.world_rules)
    assert "levels, skills, equipment" in blueprint.power_system[0]
    assert blueprint.factions[0].name == "Dawn Guild"
    assert blueprint.locations[0].name == "Novice Village"
    assert blueprint.current_arc.startswith("Su Ye uses rebirth knowledge")
    assert result.bootstrap.character_profiles[0].name == "Su Ye"
    assert result.bootstrap.character_profiles[0].role == "protagonist"
    assert result.bootstrap.character_profiles[0].motivation == "Use rebirth knowledge without exposing the secret."
