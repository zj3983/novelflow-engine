import json
import os
from pathlib import Path

import pytest

from packages.story_core.file_project_store import FileProjectStore


EXPECTED_EMPTY = {
    "schema_version": "publishing-assets/v1",
    "synopsis": None,
    "cover": None,
}


def _make_store(root: Path, *, project: dict | None = None) -> FileProjectStore:
    project = project or {
        "project_id": "p-file",
        "title": "File Novel",
        "active_story_id": "s-file",
    }
    (root / ".story-system").mkdir(parents=True)
    (root / ".webnovel").mkdir()
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(project, ensure_ascii=False), encoding="utf-8"
    )
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"schema_version": "story-system-master-setting/v1", "project": project}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text("{}", encoding="utf-8")
    return FileProjectStore(root)


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _mirror_payloads(root: Path) -> tuple[dict, dict]:
    project = _read(root / ".webnovel" / "project.json")
    master = _read(root / ".story-system" / "MASTER_SETTING.json")
    return project["publishing_assets"], master["project"]["publishing_assets"]


def _assert_no_transaction_files(root: Path) -> None:
    assert not list(root.rglob("*.tmp"))
    assert not list(root.rglob("*.rollback"))


def test_publishing_assets_normalizes_legacy_data_without_read_mutation(tmp_path):
    store = _make_store(tmp_path / "novel")
    project_path = store.webnovel_dir / "project.json"
    master_path = store.story_system_dir / "MASTER_SETTING.json"
    before = (project_path.read_bytes(), master_path.read_bytes())

    assert store.publishing_assets() == EXPECTED_EMPTY
    assert (project_path.read_bytes(), master_path.read_bytes()) == before

    malformed = {"publishing_assets": {"schema_version": 8, "synopsis": "bad", "cover": []}}
    project_path.write_text(json.dumps(malformed), encoding="utf-8")
    assert store.publishing_assets() == EXPECTED_EMPTY
    assert project_path.read_text(encoding="utf-8") == json.dumps(malformed)


def test_cover_paths_are_fixed_project_descendants(tmp_path):
    store = _make_store(tmp_path / "novel")

    assert store.cover_base_path == store.root / ".webnovel" / "assets" / "cover-base.png"
    assert store.rendered_cover_path == store.root / ".webnovel" / "assets" / "cover.png"
    assert store.cover_base_path.is_relative_to(store.root)
    assert store.rendered_cover_path.is_relative_to(store.root)


def test_save_synopsis_mirrors_metadata_and_preserves_cover(tmp_path):
    store = _make_store(tmp_path / "novel")
    store.save_cover_prompt("bright fantasy cover")
    synopsis = {"title": "File Novel", "summary": "A crisp story.", "tags": ["fantasy"]}

    saved = store.save_synopsis(synopsis)

    assert saved == {
        "schema_version": "publishing-assets/v1",
        "synopsis": synopsis,
        "cover": {"prompt": "bright fantasy cover"},
    }
    assert store.publishing_assets() == saved
    assert _mirror_payloads(store.root) == (saved, saved)


def test_prompt_only_state_survives_cover_save_and_uses_project_title(tmp_path):
    store = _make_store(tmp_path / "novel", project={"project_id": "p-file", "title": "Rendered Title"})
    prompt_state = store.save_cover_prompt("  cinematic city at night  ")

    assert prompt_state["cover"] == {"prompt": "cinematic city at night"}
    saved = store.save_cover(
        prompt="cinematic city at night",
        base_image=b"base-png",
        rendered_image=b"rendered-png",
        model="cover-model/v1",
    )

    assert store.cover_base_path.read_bytes() == b"base-png"
    assert store.rendered_cover_path.read_bytes() == b"rendered-png"
    assert saved["cover"] == {
        "prompt": "cinematic city at night",
        "model": "cover-model/v1",
        "base_path": "assets/cover-base.png",
        "rendered_path": "assets/cover.png",
        "schema_version": "cover/v1",
        "rendered_title": "Rendered Title",
    }
    assert _mirror_payloads(store.root) == (saved, saved)
    assert str(store.root) not in json.dumps(saved)


def test_update_project_preserves_publishing_assets_and_repeated_cover_replaces_both(tmp_path):
    store = _make_store(tmp_path / "novel")
    store.save_synopsis({"summary": "kept"})
    first = store.save_cover(prompt="one", base_image=b"base-one", rendered_image=b"cover-one", model="m1")

    store.update_project({"title": "New Project Title"})
    second = store.save_cover(prompt="two", base_image=b"base-two", rendered_image=b"cover-two", model="m2")

    assert first["synopsis"] == second["synopsis"] == {"summary": "kept"}
    assert store.cover_base_path.read_bytes() == b"base-two"
    assert store.rendered_cover_path.read_bytes() == b"cover-two"
    assert second["cover"]["rendered_title"] == "New Project Title"
    assert _mirror_payloads(store.root) == (second, second)


@pytest.mark.parametrize("failed_call", [1, 2])
def test_asset_replace_failure_restores_existing_asset_pair(tmp_path, monkeypatch, failed_call):
    store = _make_store(tmp_path / "novel")
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-rendered", model="old")
    original = (store.cover_base_path.read_bytes(), store.rendered_cover_path.read_bytes())
    original_metadata = (store.webnovel_dir / "project.json").read_bytes(), (store.story_system_dir / "MASTER_SETTING.json").read_bytes()
    original_replace = store._replace_asset
    calls = 0

    def fail_on_selected(source, target):
        nonlocal calls
        calls += 1
        if calls == failed_call:
            raise OSError("replace failed")
        original_replace(source, target)

    monkeypatch.setattr(store, "_replace_asset", fail_on_selected)
    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_cover(prompt="new", base_image=b"new-base", rendered_image=b"new-rendered", model="new")

    assert (store.cover_base_path.read_bytes(), store.rendered_cover_path.read_bytes()) == original
    assert ((store.webnovel_dir / "project.json").read_bytes(), (store.story_system_dir / "MASTER_SETTING.json").read_bytes()) == original_metadata
    _assert_no_transaction_files(store.root)


def test_asset_failure_from_initial_absence_leaves_no_assets(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    monkeypatch.setattr(store, "_replace_asset", lambda *_args: (_ for _ in ()).throw(OSError("boom")))

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_cover(prompt="new", base_image=b"new-base", rendered_image=b"new-rendered", model="new")

    assert not store.cover_base_path.exists()
    assert not store.rendered_cover_path.exists()
    assert store.publishing_assets() == EXPECTED_EMPTY
    _assert_no_transaction_files(store.root)


@pytest.mark.parametrize("failed_call", [1, 2])
def test_metadata_write_failure_restores_assets_and_exact_metadata_bytes(tmp_path, monkeypatch, failed_call):
    store = _make_store(tmp_path / "novel")
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-rendered", model="old")
    original_assets = (store.cover_base_path.read_bytes(), store.rendered_cover_path.read_bytes())
    original_metadata = (store.webnovel_dir / "project.json").read_bytes(), (store.story_system_dir / "MASTER_SETTING.json").read_bytes()
    original_replace = store._replace_metadata
    calls = 0

    def fail_on_selected(source, target):
        nonlocal calls
        calls += 1
        if calls == failed_call:
            raise OSError("metadata replace failed")
        original_replace(source, target)

    monkeypatch.setattr(store, "_replace_metadata", fail_on_selected)
    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_cover(prompt="new", base_image=b"new-base", rendered_image=b"new-rendered", model="new")

    assert (store.cover_base_path.read_bytes(), store.rendered_cover_path.read_bytes()) == original_assets
    assert ((store.webnovel_dir / "project.json").read_bytes(), (store.story_system_dir / "MASTER_SETTING.json").read_bytes()) == original_metadata
    _assert_no_transaction_files(store.root)


def test_metadata_only_second_write_failure_restores_both_exactly(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    before = (store.webnovel_dir / "project.json").read_bytes(), (store.story_system_dir / "MASTER_SETTING.json").read_bytes()
    original_replace = store._replace_metadata
    calls = 0

    def fail_second(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("metadata replace failed")
        original_replace(source, target)

    monkeypatch.setattr(store, "_replace_metadata", fail_second)
    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis({"summary": "new"})

    assert ((store.webnovel_dir / "project.json").read_bytes(), (store.story_system_dir / "MASTER_SETTING.json").read_bytes()) == before
    _assert_no_transaction_files(store.root)


def test_assets_are_fsynced_before_any_asset_replace(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    fsync_calls = []
    replace_calls = []
    original_fsync = os.fsync
    original_replace = store._replace_asset

    def record_fsync(fd):
        fsync_calls.append(fd)
        return original_fsync(fd)

    def record_replace(source, target):
        assert len(fsync_calls) >= 2
        replace_calls.append(target)
        original_replace(source, target)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(store, "_replace_asset", record_replace)
    store.save_cover(prompt="one", base_image=b"base", rendered_image=b"rendered", model="m")

    assert replace_calls == [store.cover_base_path, store.rendered_cover_path]


def test_cover_write_rejects_assets_directory_redirected_outside_project(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        os.symlink(outside, store.webnovel_dir / "assets", target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    (outside / "cover-base.png").write_bytes(b"must not be read")
    original_read_bytes = Path.read_bytes
    read_outside = []

    def guard_read(path):
        if path.resolve().is_relative_to(outside):
            read_outside.append(path)
            raise AssertionError("unsafe redirected asset was read")
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", guard_read)

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_cover(prompt="one", base_image=b"base", rendered_image=b"rendered", model="m")

    assert read_outside == []
    assert original_read_bytes(outside / "cover-base.png") == b"must not be read"


@pytest.mark.parametrize(
    "operation,args",
    [
        ("synopsis", ({"bad": {1, 2}},)),
        ("synopsis", ([],)),
        ("prompt", ("   ",)),
        ("prompt", ("x" * 2001,)),
        ("cover", ()),
    ],
)
def test_invalid_publishing_asset_inputs_fail_stably(tmp_path, operation, args):
    store = _make_store(tmp_path / "novel")

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        if operation == "synopsis":
            store.save_synopsis(*args)
        elif operation == "prompt":
            store.save_cover_prompt(*args)
        else:
            store.save_cover(prompt="valid", base_image="not-bytes", rendered_image=b"ok", model="m")
