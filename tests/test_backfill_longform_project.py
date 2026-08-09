from __future__ import annotations

import hashlib
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
