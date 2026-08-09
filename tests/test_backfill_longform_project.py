from __future__ import annotations

import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.project_backfill import (
    apply_backfill_preview,
    build_backfill_preview,
    protected_chapter_hashes,
    validate_backfill_preview,
    verify_backfill_hashes,
)
from scripts import backfill_longform_project as cli
from scripts.backfill_longform_project import main


def test_script_entrypoint_runs_outside_repository(tmp_path: Path) -> None:
    script = Path(__file__).parents[1] / "scripts" / "backfill_longform_project.py"

    completed = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert "--check-preview" in completed.stdout


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _project(tmp_path: Path, *, chapter_count: int = 2) -> Path:
    root = tmp_path / "long-project"
    _write_json(
        root / ".webnovel" / "project.json",
        {
            "project_id": "file:p-long",
            "title": "Repairer",
            "genre": "xuanhuan",
            "unknown_project": {"keep": True},
        },
    )
    _write_json(
        root / ".webnovel" / "outline.json",
        {
            "schema_version": "project-outline/v1",
            "overall": {"story": "old"},
            "arcs": [],
            "chapters": [],
            "unknown_outline": "keep",
        },
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "current_chapter": chapter_count,
            "chapter_summaries": [{"chapter_number": 1, "summary": "old"}],
            "unknown_state": ["keep"],
        },
    )
    for number in range(1, chapter_count + 1):
        body = f"chapter {number}\r\n".encode("utf-8")
        markdown = root / "chapters" / f"{number:04d}-chapter-{number}.md"
        markdown.parent.mkdir(parents=True, exist_ok=True)
        markdown.write_bytes(body)
        _write_json(
            root / ".story-system" / "chapters" / f"{number:04d}.json",
            {
                "schema_version": "chapter/v2",
                "chapter_number": number,
                "chapter_title": f"chapter-{number}",
                "body_path": markdown.relative_to(root).as_posix(),
                "chapter_summary": {"summary": f"summary {number}"},
            },
        )
    return root


def _payload() -> dict[str, object]:
    return {
        "story_core": {"title": "Repairer", "logline": "Repair the broken worlds."},
        "master_outline": {
            "overall": {"story": "new story", "theme_statement": "repair"},
            "arcs": [
                {
                    "id": "arc-1",
                    "title": "First arc",
                    "start_chapter": 1,
                    "end_chapter": 2,
                    "goal": "survive",
                }
            ],
            "chapters": [],
        },
        "world_blueprint": {"setting": "cultivation", "rules": ["costs matter"]},
        "characters": [
            {
                "name": "Lin Xiu",
                "entity_type": "character",
                "first_appearance_chapter": 1,
                "current_state": {"injury": "right hand numb"},
            }
        ],
        "relationships": [],
        "foreshadowing": [],
        "continuity": {
            "current_chapter": 1,
            "current_focus": "escape the shrine",
            "chapter_summaries": [{"chapter_number": 2, "summary": "latest"}],
            "timeline": [{"chapter_number": 2, "summary": "at shrine"}],
            "continuity_notes": ["do not heal the hand yet"],
        },
    }


def _all_managed_bytes(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for directory in (root / "chapters", root / ".story-system" / "chapters")
        for path in sorted(directory.glob("*"))
        if path.is_file()
    }


def test_protected_hashes_cover_markdown_and_chapter_json_raw_bytes(tmp_path: Path) -> None:
    root = _project(tmp_path)

    digest = protected_chapter_hashes(root)

    assert digest["chapter_count"] == 2
    assert digest["file_count"] == 4
    assert digest["non_empty_hash_count"] == 4
    assert set(digest["files"]) == {
        "chapters/0001-chapter-1.md",
        "chapters/0002-chapter-2.md",
        ".story-system/chapters/0001.json",
        ".story-system/chapters/0002.json",
    }
    expected = hashlib.sha256((root / "chapters/0001-chapter-1.md").read_bytes()).hexdigest()
    assert digest["files"]["chapters/0001-chapter-1.md"] == expected
    assert len(digest["total_hash"]) == 64


def test_payload_builds_preview_only_and_preserves_all_chapter_bytes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    payload_path = tmp_path / "generated.json"
    _write_json(payload_path, _payload())
    metadata_before = {
        name: (root / ".webnovel" / name).read_bytes()
        for name in ("project.json", "outline.json", "state.json")
    }
    chapters_before = _all_managed_bytes(root)

    assert main([str(root), "--payload", str(payload_path)]) == 0

    preview_path = root / ".story-system" / "backfill-preview.json"
    preview = json.loads(preview_path.read_text(encoding="utf-8"))
    assert preview["schema_version"] == "longform-backfill-preview/v1"
    assert preview["project_root"] == str(root.resolve())
    assert preview["project_id"] == "file:p-long"
    assert preview["genre"] == "xuanhuan"
    assert set(preview["patch"]) == {
        "story_core",
        "master_outline",
        "world_blueprint",
        "characters",
        "relationships",
        "foreshadowing",
        "continuity",
    }
    assert _all_managed_bytes(root) == chapters_before
    for name, content in metadata_before.items():
        assert (root / ".webnovel" / name).read_bytes() == content


def test_default_without_payload_has_clear_error_and_does_not_write(tmp_path: Path, capsys) -> None:
    root = _project(tmp_path)

    assert main([str(root)]) == 2

    assert "payload_required" in capsys.readouterr().err
    assert not (root / ".story-system" / "backfill-preview.json").exists()


def test_hash_only_is_read_only(tmp_path: Path, capsys) -> None:
    root = _project(tmp_path)
    before = _all_managed_bytes(root)

    assert main([str(root), "--hash-only"]) == 0

    output = json.loads(capsys.readouterr().out)
    assert output["chapter_count"] == 2
    assert output["non_empty_hash_count"] == 4
    assert _all_managed_bytes(root) == before
    assert not (root / ".story-system" / "backfill-hashes.json").exists()


def test_check_preview_rejects_bad_sections_and_game_fields(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"].pop("relationships")
    with pytest.raises(ValueError, match="preview_patch_sections"):
        validate_backfill_preview(root, preview)

    preview = build_backfill_preview(root, _payload())
    preview["patch"]["world_blueprint"]["game_panel"] = {"level": 9}
    with pytest.raises(ValueError, match="foreign_genre_field:game_panel"):
        validate_backfill_preview(root, preview)


def test_preview_rejects_embedded_chapter_body_and_tampered_genre(tmp_path: Path) -> None:
    root = _project(tmp_path)
    payload = _payload()
    payload["continuity"]["chapter_body"] = "full prose must not enter preview"  # type: ignore[index]

    with pytest.raises(ValueError, match="preview_contains_prose:chapter_body"):
        build_backfill_preview(root, payload)

    preview = build_backfill_preview(root, _payload())
    preview["genre"] = "game"
    with pytest.raises(ValueError, match="preview_genre_mismatch"):
        validate_backfill_preview(root, preview)


def test_verify_and_apply_reject_changed_chapter_bytes(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    (root / "chapters" / "0002-chapter-2.md").write_text("changed", encoding="utf-8")

    with pytest.raises(ValueError, match="chapter_hash_mismatch"):
        validate_backfill_preview(root, preview)
    with pytest.raises(ValueError, match="chapter_hash_mismatch"):
        apply_backfill_preview(root, preview)


def test_verify_hashes_rejects_preview_from_another_project_with_same_bytes(tmp_path: Path) -> None:
    first = _project(tmp_path / "first")
    second = _project(tmp_path / "second")
    preview = build_backfill_preview(first, _payload())

    with pytest.raises(ValueError, match="preview_project_root_mismatch"):
        validate_backfill_preview(second, preview)
    with pytest.raises(ValueError, match="preview_project_root_mismatch"):
        verify_backfill_hashes(second, preview)


def test_apply_backs_up_and_maps_patch_to_three_metadata_files(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    before = _all_managed_bytes(root)

    result = apply_backfill_preview(root, preview)

    backup = Path(result["backup_path"])
    assert backup.parent == root / ".story-system" / "backfill-backups"
    assert {path.name for path in backup.iterdir()} == {
        "project.json",
        "outline.json",
        "state.json",
    }
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    outline = json.loads((root / ".webnovel" / "outline.json").read_text(encoding="utf-8"))
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert project["story_core"]["logline"] == "Repair the broken worlds."
    assert project["master_outline"]["overall"]["story"] == "new story"
    assert project["world_blueprint"]["setting"] == "cultivation"
    assert project["character_profiles"][0]["name"] == "Lin Xiu"
    assert project["current_chapter"] == 2
    assert project["current_focus"] == "escape the shrine"
    assert outline["overall"]["story"] == "new story"
    assert outline["unknown_outline"] == "keep"
    assert state["characters"][0]["name"] == "Lin Xiu"
    assert state["current_chapter"] == 2
    assert state["current_focus"] == "escape the shrine"
    assert state["continuity_notes"] == ["do not heal the hand yet"]
    assert project["unknown_project"] == {"keep": True}
    assert state["unknown_state"] == ["keep"]
    assert _all_managed_bytes(root) == before


def test_apply_rolls_back_all_metadata_when_second_replace_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    paths = [root / ".webnovel" / name for name in ("project.json", "outline.json", "state.json")]
    before = {path: path.read_bytes() for path in paths}
    real_replace = SnapshotStore._replace_file
    calls = 0

    def fail_second(source: str | Path, target: str | Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second replace failed")
        real_replace(source, target)

    monkeypatch.setattr(SnapshotStore, "_replace_file", staticmethod(fail_second))

    with pytest.raises(OSError, match="second replace failed"):
        apply_backfill_preview(root, preview)

    assert {path: path.read_bytes() for path in paths} == before


def test_post_apply_hash_change_rolls_back_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    paths = [root / ".webnovel" / name for name in ("project.json", "outline.json", "state.json")]
    before = {path: path.read_bytes() for path in paths}
    from packages.story_core import project_backfill

    real_hashes = project_backfill.protected_chapter_hashes
    calls = 0

    def change_after_commit(project_root: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        result = real_hashes(project_root)
        if calls >= 3:
            result["total_hash"] = "0" * 64
        return result

    monkeypatch.setattr(project_backfill, "protected_chapter_hashes", change_after_commit)

    with pytest.raises(ValueError, match="chapter_hash_mismatch"):
        apply_backfill_preview(root, preview)

    assert {path: path.read_bytes() for path in paths} == before


def test_cli_check_verify_and_apply_use_existing_preview(tmp_path: Path, capsys) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    _write_json(root / ".story-system" / "backfill-preview.json", preview)

    assert main([str(root), "--check-preview"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "preview_valid"
    assert main([str(root), "--verify-hashes"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "hashes_match"
    assert main([str(root), "--apply"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "applied"


def test_repeated_apply_is_idempotent(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())

    apply_backfill_preview(root, preview)
    first = {
        name: json.loads((root / ".webnovel" / name).read_text(encoding="utf-8"))
        for name in ("project.json", "outline.json", "state.json")
    }
    apply_backfill_preview(root, preview)
    second = {
        name: json.loads((root / ".webnovel" / name).read_text(encoding="utf-8"))
        for name in ("project.json", "outline.json", "state.json")
    }

    assert second == first


def test_apply_rejects_backup_directory_symlink_outside_project(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    outside = tmp_path / "outside-backups"
    outside.mkdir()
    link = root / ".story-system" / "backfill-backups"
    try:
        os.symlink(outside, link, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="unsafe_project_path"):
        apply_backfill_preview(root, preview)

    assert list(outside.iterdir()) == []


@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("continuity", "start_chapter"),
        ("continuity", "end_chapter"),
        ("continuity", "from_chapter"),
        ("continuity", "to_chapter"),
        ("continuity", "chapter_start"),
        ("continuity", "chapter_end"),
    ],
)
def test_preview_rejects_common_chapter_fields_beyond_current_chapter(
    tmp_path: Path, section: str, key: str
) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"][section]["nested"] = {key: 3}

    with pytest.raises(ValueError, match="preview_chapter_out_of_range"):
        validate_backfill_preview(root, preview)


def test_preview_rejects_outline_arc_beyond_current_chapter(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"]["master_outline"]["arcs"][0]["end_chapter"] = 3

    with pytest.raises(ValueError, match="preview_chapter_out_of_range"):
        validate_backfill_preview(root, preview)


@pytest.mark.parametrize("key", ["body", "content", "chapter_text", "full_text", "prose", "draft"])
def test_preview_rejects_semantic_prose_keys(tmp_path: Path, key: str) -> None:
    root = _project(tmp_path)
    payload = _payload()
    payload["continuity"][key] = "chapter prose"  # type: ignore[index]

    with pytest.raises(ValueError, match=f"preview_contains_prose:{key}"):
        build_backfill_preview(root, payload)


def test_preview_rejects_long_prose_like_string_but_keeps_normal_outline_notes(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    payload = _payload()
    payload["continuity"]["editor_note"] = "A" * 2500  # type: ignore[index]
    build_backfill_preview(root, payload)

    payload["continuity"]["raw_material"] = "B" * 12000  # type: ignore[index]
    with pytest.raises(ValueError, match="preview_contains_long_text:raw_material"):
        build_backfill_preview(root, payload)


def test_apply_deep_merges_nested_unknown_fields_and_replaces_lists(tmp_path: Path) -> None:
    root = _project(tmp_path)
    project_path = root / ".webnovel" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project.update(
        {
            "story_core": {"legacy_nested": {"keep": 1}},
            "master_outline": {"legacy_nested": {"keep": 2}},
            "world_blueprint": {
                "nested": {"keep": "project", "replace": "old"},
                "rules": ["old rule"],
            },
        }
    )
    _write_json(project_path, project)
    outline_path = root / ".webnovel" / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["overall"]["legacy_nested"] = {"keep": "outline"}
    _write_json(outline_path, outline)
    state_path = root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["continuity_meta"] = {"keep": "state", "replace": "old"}
    state["timeline"] = [{"chapter_number": 1, "summary": "old"}]
    _write_json(state_path, state)
    payload = _payload()
    payload["world_blueprint"] = {
        "nested": {"replace": "new"},
        "rules": ["new rule"],
    }
    payload["continuity"]["continuity_meta"] = {"replace": "new"}  # type: ignore[index]
    preview = build_backfill_preview(root, payload)

    apply_backfill_preview(root, preview)

    project = json.loads(project_path.read_text(encoding="utf-8"))
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert project["story_core"]["legacy_nested"] == {"keep": 1}
    assert project["master_outline"]["legacy_nested"] == {"keep": 2}
    assert project["world_blueprint"]["nested"] == {"keep": "project", "replace": "new"}
    assert project["world_blueprint"]["rules"] == ["new rule"]
    assert outline["overall"]["legacy_nested"] == {"keep": "outline"}
    assert state["continuity_meta"] == {"keep": "state", "replace": "new"}
    assert state["timeline"] == [
        {"chapter_number": 1, "summary": "old"},
        {"chapter_number": 2, "summary": "at shrine"},
    ]


def test_post_apply_rollback_restores_original_metadata_bytes_exactly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)
    paths = [root / ".webnovel" / name for name in ("project.json", "outline.json", "state.json")]
    for index, path in enumerate(paths):
        payload = json.loads(path.read_text(encoding="utf-8"))
        raw = "\ufeff" + json.dumps(payload, ensure_ascii=False, indent=index + 1) + "\r\n"
        path.write_bytes(raw.replace("\n", "\r\n").encode("utf-8"))
    original = {path: path.read_bytes() for path in paths}
    preview = build_backfill_preview(root, _payload())
    from packages.story_core import project_backfill

    real_hashes = project_backfill.protected_chapter_hashes
    calls = 0

    def change_after_commit(project_root: Path) -> dict[str, object]:
        nonlocal calls
        calls += 1
        result = real_hashes(project_root)
        if calls >= 3:
            result["total_hash"] = "f" * 64
        return result

    monkeypatch.setattr(project_backfill, "protected_chapter_hashes", change_after_commit)

    with pytest.raises(ValueError, match="chapter_hash_mismatch"):
        apply_backfill_preview(root, preview)

    assert {path: path.read_bytes() for path in paths} == original


def test_repeated_apply_returns_already_applied_without_new_backup(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    first = apply_backfill_preview(root, preview)
    backup_root = root / ".story-system" / "backfill-backups"
    backups_before = sorted(backup_root.iterdir())
    metadata_before = {
        name: (root / ".webnovel" / name).read_bytes()
        for name in ("project.json", "outline.json", "state.json")
    }

    second = apply_backfill_preview(root, preview)

    assert first["status"] == "applied"
    assert second["status"] == "already_applied"
    assert sorted(backup_root.iterdir()) == backups_before
    assert {
        name: (root / ".webnovel" / name).read_bytes()
        for name in ("project.json", "outline.json", "state.json")
    } == metadata_before


def test_cli_reconfigures_windows_console_streams_for_utf8(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = _project(tmp_path)

    class RecordingStream(io.StringIO):
        def __init__(self) -> None:
            super().__init__()
            self.configuration: tuple[str, str] | None = None

        def reconfigure(self, *, encoding: str, errors: str) -> None:
            self.configuration = (encoding, errors)

    stdout = RecordingStream()
    stderr = RecordingStream()
    monkeypatch.setattr(cli.sys, "stdout", stdout)
    monkeypatch.setattr(cli.sys, "stderr", stderr)

    assert cli.main([str(root), "--hash-only"]) == 0
    assert stdout.configuration == ("utf-8", "replace")
    assert stderr.configuration == ("utf-8", "replace")


def test_preview_rejects_unknown_manuscript_with_four_thousand_prose_chars(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    payload = _payload()
    payload["continuity"]["manuscript"] = "He opened the door and spoke.\n" * 140  # type: ignore[index]

    with pytest.raises(ValueError, match="preview_contains_long_text:manuscript"):
        build_backfill_preview(root, payload)


def test_preview_allows_normal_one_thousand_character_outline_description(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    payload = _payload()
    payload["continuity"]["arc_explanation"] = "structured outline note; " * 45  # type: ignore[index]

    preview = build_backfill_preview(root, payload)

    assert len(preview["patch"]["continuity"]["arc_explanation"]) < 1200


@pytest.mark.parametrize(
    "key",
    [
        "chapter",
        "last_review_chapter",
        "core_ending_chapter",
        "extension_ceiling_chapter",
        "chapter_checkpoint",
    ],
)
def test_preview_uses_generic_chapter_number_key_matching(tmp_path: Path, key: str) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"]["continuity"]["generic"] = {key: 3}

    with pytest.raises(ValueError, match="preview_chapter_out_of_range"):
        validate_backfill_preview(root, preview)


@pytest.mark.parametrize(
    "key",
    [
        "chapter_count",
        "total_chapters",
        "planned_chapters",
        "published_chapters",
        "max_chapters",
        "chapter_total",
    ],
)
def test_preview_does_not_treat_chapter_counts_as_chapter_references(
    tmp_path: Path, key: str
) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"]["continuity"][key] = 300

    validate_backfill_preview(root, preview)


def test_apply_merges_stable_list_items_and_preserves_unmatched_entries(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    project_path = root / ".webnovel" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["character_profiles"] = [
        {"name": "Lin Xiu", "legacy_character": {"keep": True}},
        {"name": "Old Mentor", "legacy_only": True},
    ]
    project["relationship_graph"] = [
        {
            "source": "Lin Xiu",
            "target": "Mei",
            "relation_type": "ally",
            "legacy_relationship": {"keep": True},
        }
    ]
    _write_json(project_path, project)
    outline_path = root / ".webnovel" / "outline.json"
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    outline["arcs"] = [
        {
            "id": "arc-1",
            "title": "Old arc title",
            "start_chapter": 1,
            "end_chapter": 2,
            "legacy_arc": {"keep": True},
        }
    ]
    outline["chapters"] = [
        {"chapter_number": 1, "title": "Old title", "legacy_chapter": {"keep": True}}
    ]
    _write_json(outline_path, outline)
    state_path = root / ".webnovel" / "state.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    state["characters"] = [{"name": "Lin Xiu", "legacy_state": {"keep": True}}]
    state["foreshadowing"] = [
        {
            "text": "the copper key",
            "first_chapter": 1,
            "last_touched_chapter": 1,
            "status": "open",
            "legacy_clue": {"keep": True},
        }
    ]
    _write_json(state_path, state)
    payload = _payload()
    payload["master_outline"]["chapters"] = [  # type: ignore[index]
        {"chapter_number": 1, "title": "New title", "goal": "find the key"}
    ]
    payload["characters"] = [
        {"name": "Lin Xiu", "entity_type": "character", "occupation": "repairer"},
        {"name": "Mei", "entity_type": "character", "occupation": "guard"},
    ]
    payload["relationships"] = [
        {"source": "Lin Xiu", "target": "Mei", "relation_type": "trusted ally"}
    ]
    payload["foreshadowing"] = [
        {
            "text": "the copper key",
            "first_chapter": 1,
            "last_touched_chapter": 2,
            "status": "reinforced",
        }
    ]
    preview = build_backfill_preview(root, payload)

    apply_backfill_preview(root, preview)

    project = json.loads(project_path.read_text(encoding="utf-8"))
    outline = json.loads(outline_path.read_text(encoding="utf-8"))
    state = json.loads(state_path.read_text(encoding="utf-8"))
    lin_project = next(item for item in project["character_profiles"] if item["name"] == "Lin Xiu")
    relation = project["relationship_graph"][0]
    lin_state = next(item for item in state["characters"] if item["name"] == "Lin Xiu")
    clue = state["foreshadowing"][0]
    assert lin_project["legacy_character"] == {"keep": True}
    assert any(item["name"] == "Old Mentor" for item in project["character_profiles"])
    assert relation["legacy_relationship"] == {"keep": True}
    assert relation["relation_type"] == "trusted ally"
    assert outline["arcs"][0]["legacy_arc"] == {"keep": True}
    assert outline["chapters"][0]["legacy_chapter"] == {"keep": True}
    assert outline["chapters"][0]["title"] == "New title"
    assert lin_state["legacy_state"] == {"keep": True}
    assert clue["legacy_clue"] == {"keep": True}
    assert clue["status"] == "reinforced"


def test_preview_rejects_body_fragment_under_unknown_key_without_prose_markers(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    body = ("repaircircuitwithoutspaces" * 90)[:2100]
    (root / "chapters" / "0002-chapter-2.md").write_text(body, encoding="utf-8")
    payload = _payload()
    payload["continuity"]["foo"] = body[250:1750]  # type: ignore[index]

    with pytest.raises(ValueError, match="body_content_forbidden"):
        build_backfill_preview(root, payload)


def test_preview_validates_numeric_string_chapter_references(tmp_path: Path) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"]["continuity"]["last_review_chapter"] = "999"

    with pytest.raises(ValueError, match="preview_chapter_out_of_range"):
        validate_backfill_preview(root, preview)


@pytest.mark.parametrize("key", ["target_chapter", "total_ending_chapter"])
def test_preview_does_not_exclude_singular_chapter_references(
    tmp_path: Path, key: str
) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"]["continuity"][key] = "999"

    with pytest.raises(ValueError, match="preview_chapter_out_of_range"):
        validate_backfill_preview(root, preview)


@pytest.mark.parametrize(
    "key",
    [
        "words_per_chapter",
        "target_chapters",
        "chapter_length",
        "chapter_word_count",
        "total_published_chapters",
    ],
)
def test_preview_allows_chapter_count_and_length_fields(tmp_path: Path, key: str) -> None:
    root = _project(tmp_path)
    preview = build_backfill_preview(root, _payload())
    preview["patch"]["continuity"][key] = 3000

    validate_backfill_preview(root, preview)


def test_apply_generically_merges_identified_world_locations(tmp_path: Path) -> None:
    root = _project(tmp_path)
    project_path = root / ".webnovel" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["world_blueprint"] = {
        "locations": [
            {
                "code": "shrine",
                "name": "Old Shrine",
                "danger": "old",
                "legacy_location": {"keep": True},
            },
            {"code": "village", "name": "Village", "legacy_only": True},
        ]
    }
    _write_json(project_path, project)
    payload = _payload()
    payload["world_blueprint"] = {
        "locations": [
            {"code": "shrine", "name": "Snow Shrine", "danger": "new"},
            {"code": "market", "name": "Market"},
        ]
    }
    preview = build_backfill_preview(root, payload)

    apply_backfill_preview(root, preview)

    project = json.loads(project_path.read_text(encoding="utf-8"))
    locations = {item["code"]: item for item in project["world_blueprint"]["locations"]}
    assert locations["shrine"]["name"] == "Snow Shrine"
    assert locations["shrine"]["danger"] == "new"
    assert locations["shrine"]["legacy_location"] == {"keep": True}
    assert locations["village"]["legacy_only"] is True
    assert locations["market"]["name"] == "Market"


def test_apply_does_not_merge_list_items_with_conflicting_strong_identities(
    tmp_path: Path,
) -> None:
    root = _project(tmp_path)
    project_path = root / ".webnovel" / "project.json"
    project = json.loads(project_path.read_text(encoding="utf-8"))
    project["world_blueprint"] = {
        "locations": [
            {"code": "old-shrine", "name": "Shrine", "legacy_only": True},
        ]
    }
    _write_json(project_path, project)
    payload = _payload()
    payload["world_blueprint"] = {
        "locations": [
            {"code": "new-shrine", "name": "Shrine", "danger": "new"},
        ]
    }
    preview = build_backfill_preview(root, payload)

    apply_backfill_preview(root, preview)

    project = json.loads(project_path.read_text(encoding="utf-8"))
    locations = {item["code"]: item for item in project["world_blueprint"]["locations"]}
    assert locations["old-shrine"]["legacy_only"] is True
    assert locations["new-shrine"]["danger"] == "new"
