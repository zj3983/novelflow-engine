import json
import os
import tempfile
from pathlib import Path

import pytest

from packages.story_core.file_project_store import FileProjectStore, _PinnedPublishingFilesystem


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

    assert saved["schema_version"] == "publishing-assets/v1"
    assert saved["synopsis"] == synopsis
    assert saved["cover"]["prompt"] == "bright fantasy cover"
    assert saved["updated_at"]
    assert store.publishing_assets() == saved
    assert _mirror_payloads(store.root) == (saved, saved)


def test_prompt_only_state_survives_cover_save_and_uses_project_title(tmp_path):
    store = _make_store(tmp_path / "novel", project={"project_id": "p-file", "title": "Rendered Title"})
    prompt_state = store.save_cover_prompt("  cinematic city at night  ")

    assert prompt_state["cover"]["prompt"] == "cinematic city at night"
    assert prompt_state["cover"]["updated_at"]
    saved = store.save_cover(
        prompt="cinematic city at night",
        base_image=b"base-png",
        rendered_image=b"rendered-png",
        model="cover-model/v1",
    )

    assert store.cover_base_path.read_bytes() == b"base-png"
    assert store.rendered_cover_path.read_bytes() == b"rendered-png"
    assert {key: value for key, value in saved["cover"].items() if key not in {"image_version", "mime_type", "updated_at"}} == {
        "prompt": "cinematic city at night",
        "model": "cover-model/v1",
        "base_path": "assets/cover-base.png",
        "rendered_path": "assets/cover.png",
        "schema_version": "cover/v1",
        "rendered_title": "Rendered Title",
    }
    assert saved["cover"]["image_version"]
    assert saved["cover"]["mime_type"] == "image/png"
    assert saved["cover"]["updated_at"]
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


def test_second_asset_temp_prepare_failure_cleans_up_and_keeps_all_targets_unchanged(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    before_metadata = (
        (store.webnovel_dir / "project.json").read_bytes(),
        (store.story_system_dir / "MASTER_SETTING.json").read_bytes(),
    )
    original_prepare = store._prepare_publishing_temp
    calls = 0

    def fail_second_prepare(path, content, *, suffix=".tmp"):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second temp preparation failed")
        return original_prepare(path, content, suffix=suffix)

    monkeypatch.setattr(store, "_prepare_publishing_temp", fail_second_prepare)
    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_cover(prompt="new", base_image=b"new-base", rendered_image=b"new-rendered", model="new")

    assert not store.cover_base_path.exists()
    assert not store.rendered_cover_path.exists()
    assert (
        (store.webnovel_dir / "project.json").read_bytes(),
        (store.story_system_dir / "MASTER_SETTING.json").read_bytes(),
    ) == before_metadata
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


def test_synopsis_and_prompt_writes_preserve_forward_compatible_cover_fields(tmp_path):
    store = _make_store(tmp_path / "novel")
    initial = store.save_cover(prompt="old", base_image=b"base", rendered_image=b"rendered", model="m")
    extras = {
        "image_version": "image/v3",
        "width": 1024,
        "height": 1536,
        "mime_type": "image/png",
        "updated_at": "2026-07-31T12:00:00Z",
        "future": {"palette": ["blue", "gold"]},
    }
    for path in (store.webnovel_dir / "project.json", store.story_system_dir / "MASTER_SETTING.json"):
        document = _read(path)
        target = document if path.name == "project.json" else document["project"]
        target["publishing_assets"]["cover"].update(extras)
        path.write_text(json.dumps(document, ensure_ascii=False), encoding="utf-8")

    after_synopsis = store.save_synopsis({"summary": "new"})
    after_prompt = store.save_cover_prompt("new prompt")

    assert after_synopsis["cover"] == {**initial["cover"], **extras}
    assert {key: value for key, value in after_prompt["cover"].items() if key != "updated_at"} == {
        **{key: value for key, value in initial["cover"].items() if key != "updated_at"},
        **{key: value for key, value in extras.items() if key != "updated_at"},
        "prompt": "new prompt",
    }
    assert after_prompt["cover"]["updated_at"]
    mirrored_project, mirrored_master = _mirror_payloads(store.root)
    assert mirrored_project == mirrored_master == after_prompt


def test_malicious_fixed_cover_paths_are_discarded_without_read_mutation(tmp_path):
    store = _make_store(tmp_path / "novel")
    project_path = store.webnovel_dir / "project.json"
    raw = _read(project_path)
    raw["publishing_assets"] = {
        "schema_version": "publishing-assets/v1",
        "synopsis": None,
        "cover": {
            "prompt": "valid prompt",
            "base_path": "C:/outside/cover-base.png",
            "rendered_path": "../../outside/cover.png",
            "image_version": "future/v2",
        },
    }
    project_path.write_text(json.dumps(raw), encoding="utf-8")
    before = project_path.read_bytes()

    visible = store.publishing_assets()

    assert visible["cover"] == {"prompt": "valid prompt", "image_version": "future/v2"}
    assert project_path.read_bytes() == before


def test_metadata_failure_with_failed_asset_recovery_retains_backups_and_diagnostics(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-rendered", model="old")
    monkeypatch.setattr(store, "_replace_metadata", lambda *_args: (_ for _ in ()).throw(OSError("metadata failed")))
    monkeypatch.setattr(
        store,
        "_restore_publishing_backup",
        lambda *_args: (_ for _ in ()).throw(OSError("asset recovery failed")),
    )

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$") as error:
        store.save_cover(prompt="new", base_image=b"new-base", rendered_image=b"new-rendered", model="new")

    assert error.value.__cause__ is not None
    assert "metadata failed" in repr(error.value.__cause__)
    assert "asset recovery failed" in repr(error.value.__cause__)
    assert list(store.root.rglob("*.rollback"))


@pytest.mark.parametrize("broken", ["project", "master"])
def test_mutation_rejects_corrupt_metadata_without_rewriting_it(tmp_path, broken):
    store = _make_store(tmp_path / "novel")
    path = store.webnovel_dir / "project.json" if broken == "project" else store.story_system_dir / "MASTER_SETTING.json"
    path.write_text("{not-json", encoding="utf-8")
    before = path.read_bytes()

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis({"summary": "new"})

    assert path.read_bytes() == before


@pytest.mark.parametrize("missing", ["project", "master"])
def test_mutation_reconstructs_one_missing_metadata_mirror_from_the_valid_one(tmp_path, missing):
    store = _make_store(tmp_path / "novel")
    path = store.webnovel_dir / "project.json" if missing == "project" else store.story_system_dir / "MASTER_SETTING.json"
    path.unlink()

    saved = store.save_synopsis({"summary": "new"})

    assert _mirror_payloads(store.root) == (saved, saved)


def test_metadata_only_write_rejects_redirected_webnovel_directory(tmp_path):
    store = _make_store(tmp_path / "novel")
    outside = tmp_path / "outside"
    store.webnovel_dir.rename(outside)
    try:
        os.symlink(outside, store.webnovel_dir, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")
    before = (outside / "project.json").read_bytes()

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis({"summary": "new"})

    assert (outside / "project.json").read_bytes() == before


def test_mutations_add_versions_timestamps_and_preserve_safe_future_top_level_fields(tmp_path):
    store = _make_store(tmp_path / "novel")
    first = store.save_cover(prompt="one", base_image=b"base-one", rendered_image=b"cover-one", model="m")
    second = store.save_cover(prompt="two", base_image=b"base-two", rendered_image=b"cover-two", model="m")
    project = _read(store.webnovel_dir / "project.json")
    project["publishing_assets"]["audiobook"] = {"narrator": "Future Voice"}
    project["publishing_assets"]["cover"]["thumbnail_path"] = "../../escape.png"
    (store.webnovel_dir / "project.json").write_text(json.dumps(project), encoding="utf-8")

    prompt_saved = store.save_cover_prompt("three")

    assert first["cover"]["image_version"] != second["cover"]["image_version"]
    assert second["updated_at"] and second["cover"]["updated_at"]
    assert prompt_saved["cover"]["image_version"] == second["cover"]["image_version"]
    assert prompt_saved["cover"]["updated_at"]
    assert prompt_saved["audiobook"] == {"narrator": "Future Voice"}
    assert "thumbnail_path" not in prompt_saved["cover"]


def test_success_cleanup_unlink_failure_does_not_fail_committed_write(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    original_unlink = Path.unlink

    def fail_rollback_unlink(path, *args, **kwargs):
        if path.suffix == ".rollback":
            raise OSError("cleanup blocked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_rollback_unlink)

    saved = store.save_cover(prompt="one", base_image=b"base", rendered_image=b"rendered", model="m")

    assert saved["cover"]["prompt"] == "one"


def test_failure_cleanup_unlink_failure_does_not_mask_write_failure(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-rendered", model="m")
    original_unlink = Path.unlink
    monkeypatch.setattr(store, "_replace_metadata", lambda *_args: (_ for _ in ()).throw(OSError("write failed")))

    def fail_rollback_unlink(path, *args, **kwargs):
        if path.suffix == ".rollback":
            raise OSError("cleanup blocked")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_rollback_unlink)
    with pytest.raises(ValueError, match="^publishing_asset_write_failed$") as error:
        store.save_cover(prompt="new", base_image=b"new-base", rendered_image=b"new-rendered", model="m")

    assert "write failed" in repr(error.value.__cause__)


@pytest.mark.parametrize(
    "synopsis",
    [
        {"deep": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": {"x": "too-deep"}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}}},
        {"oversized": "x" * 16_001},
        {"nan": float("nan")},
    ],
)
def test_publishing_input_limits_fail_before_writes(tmp_path, synopsis):
    store = _make_store(tmp_path / "novel")
    before = (store.webnovel_dir / "project.json").read_bytes()

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis(synopsis)

    assert (store.webnovel_dir / "project.json").read_bytes() == before


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


def test_asset_parent_swap_at_replace_never_writes_external_directory(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    outside = tmp_path / "outside"
    outside.mkdir()
    original_replace = store._replace_asset
    swapped = False
    rename_attempted = False
    rename_completed = False
    replace_reached = False
    final_replace_calls = []
    original_os_replace = os.replace

    def record_final_replace(source, target, *args, **kwargs):
        final_replace_calls.append((source, target))
        return original_os_replace(source, target, *args, **kwargs)

    def swap_then_replace(source, target):
        nonlocal swapped, rename_attempted, rename_completed, replace_reached
        if not swapped:
            swapped = True
            assets = store.webnovel_dir / "assets"
            staged_bytes = source.read_bytes()
            rename_attempted = True
            assets.rename(tmp_path / "displaced-assets")
            rename_completed = True
            os.symlink(outside, assets, target_is_directory=True)
            (outside / source.name).write_bytes(staged_bytes)
        replace_reached = True
        original_replace(source, target)

    monkeypatch.setattr(store, "_replace_asset", swap_then_replace)
    monkeypatch.setattr(os, "replace", record_final_replace)
    try:
        with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
            store.save_cover(prompt="one", base_image=b"base", rendered_image=b"rendered", model="m")
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    assert not (outside / "cover-base.png").exists()
    assert not (outside / "cover.png").exists()
    assert rename_attempted
    assert not final_replace_calls
    if os.name == "nt":
        assert not rename_completed
        assert not replace_reached
    else:
        assert rename_completed
        assert replace_reached


def test_metadata_parent_swap_at_replace_never_writes_external_directory(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    outside = tmp_path / "outside"
    outside.mkdir()
    before = (outside / "project.json")
    before.write_bytes(b"external metadata")
    original_replace = store._replace_metadata
    swapped = False

    def swap_then_replace(source, target):
        nonlocal swapped
        if not swapped:
            swapped = True
            staged_bytes = source.read_bytes()
            store.webnovel_dir.rename(tmp_path / "displaced-webnovel")
            os.symlink(outside, store.webnovel_dir, target_is_directory=True)
            (outside / source.name).write_bytes(staged_bytes)
        original_replace(source, target)

    monkeypatch.setattr(store, "_replace_metadata", swap_then_replace)
    try:
        with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
            store.save_synopsis({"summary": "new"})
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    assert before.read_bytes() == b"external metadata"


def test_normalization_recursively_drops_future_path_values_but_keeps_safe_values(tmp_path):
    store = _make_store(tmp_path / "novel")
    project_path = store.webnovel_dir / "project.json"
    project = _read(project_path)
    project["publishing_assets"] = {
        "schema_version": "publishing-assets/v1",
        "synopsis": {"nested": {"output_path": "../escape", "summary": "safe"}},
        "cover": {"base_path": "assets/cover-base.png", "rendered_path": "assets/cover.png"},
        "future": {
            "nested": {"output_path": "../../escape", "safe": "kept"},
            "absolute_file": "C:/escape",
            "url": "https://example.invalid/escape",
            "untrusted_path_value": "../../escape",
            "untrusted_absolute_value": "/escape",
            "items": [{"uri": "file:///escape", "safe": 3}, "../escape", {"note": "safe"}],
        },
    }
    project_path.write_text(json.dumps(project), encoding="utf-8")

    visible = store.publishing_assets()

    assert visible["future"] == {"nested": {"safe": "kept"}, "items": [{"safe": 3}, {"note": "safe"}]}
    assert visible["synopsis"] == {"nested": {"summary": "safe"}}
    assert visible["cover"]["base_path"] == "assets/cover-base.png"


def test_prepare_temp_preserves_fsync_error_when_cleanup_also_fails(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    original_unlink = Path.unlink

    monkeypatch.setattr(os, "fsync", lambda _fd: (_ for _ in ()).throw(OSError("fsync failed")))
    monkeypatch.setattr(
        Path,
        "unlink",
        lambda path, *args, **kwargs: (_ for _ in ()).throw(OSError("unlink failed"))
        if path.suffix == ".tmp"
        else original_unlink(path, *args, **kwargs),
    )

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$") as error:
        store.save_cover(prompt="one", base_image=b"base", rendered_image=b"rendered", model="m")

    assert "fsync failed" in repr(error.value.__cause__)


@pytest.mark.parametrize("missing", ["project", "master"])
def test_missing_metadata_mirror_rejects_empty_identity_counterpart(tmp_path, missing):
    store = _make_store(tmp_path / "novel")
    missing_path = store.webnovel_dir / "project.json" if missing == "project" else store.story_system_dir / "MASTER_SETTING.json"
    missing_path.unlink()
    counterpart = store.story_system_dir / "MASTER_SETTING.json" if missing == "project" else store.webnovel_dir / "project.json"
    payload = _read(counterpart)
    target = payload["project"] if missing == "project" else payload
    target["title"] = "   "
    counterpart.write_text(json.dumps(payload), encoding="utf-8")
    before = counterpart.read_bytes()

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis({"summary": "new"})

    assert counterpart.read_bytes() == before
    assert not missing_path.exists()


def test_missing_project_mirror_rejects_counterpart_with_wrong_master_schema(tmp_path):
    store = _make_store(tmp_path / "novel")
    project_path = store.webnovel_dir / "project.json"
    project_path.unlink()
    master_path = store.story_system_dir / "MASTER_SETTING.json"
    master = _read(master_path)
    master["schema_version"] = "untrusted/v1"
    master_path.write_text(json.dumps(master), encoding="utf-8")

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis({"summary": "new"})

    assert not project_path.exists()


@pytest.mark.parametrize("missing", ["project", "master"])
def test_dangling_metadata_symlink_is_not_treated_as_missing(tmp_path, missing):
    store = _make_store(tmp_path / "novel")
    path = store.webnovel_dir / "project.json" if missing == "project" else store.story_system_dir / "MASTER_SETTING.json"
    path.unlink()
    try:
        os.symlink(tmp_path / "does-not-exist.json", path)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis({"summary": "new"})

    assert os.path.lexists(path)


def test_cover_byte_cap_rejects_before_creating_assets_or_changing_metadata(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    before = (store.webnovel_dir / "project.json").read_bytes()
    monkeypatch.setattr(FileProjectStore, "PUBLISHING_ASSET_MAX_BYTES", 3)

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_cover(prompt="one", base_image=b"four", rendered_image=b"ok", model="m")

    assert not (store.webnovel_dir / "assets").exists()
    assert (store.webnovel_dir / "project.json").read_bytes() == before


def test_parent_fsync_close_failure_is_best_effort(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    target = tmp_path / "parent" / "file"
    target.parent.mkdir()
    monkeypatch.setattr(os, "open", lambda *_args, **_kwargs: 99)
    monkeypatch.setattr(os, "fsync", lambda _fd: None)
    monkeypatch.setattr(os, "close", lambda _fd: (_ for _ in ()).throw(OSError("close failed")))

    store._best_effort_fsync_parent(target)


def test_failed_removal_of_first_new_asset_is_a_rollback_failure_and_retains_backups(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    original_replace = store._replace_asset
    original_unlink = _PinnedPublishingFilesystem.unlink
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("second asset replace failed")
        original_replace(source, target)

    def fail_strict_base_removal(filesystem, path):
        if path == store.cover_base_path:
            raise OSError("strict rollback unlink failed")
        return original_unlink(filesystem, path)

    monkeypatch.setattr(store, "_replace_asset", fail_second_replace)
    monkeypatch.setattr(_PinnedPublishingFilesystem, "unlink", fail_strict_base_removal)

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$") as error:
        store.save_cover(prompt="new", base_image=b"base", rendered_image=b"rendered", model="m")

    assert isinstance(error.value.__cause__, ExceptionGroup)
    assert "second asset replace failed" in repr(error.value.__cause__)
    assert "strict rollback unlink failed" in repr(error.value.__cause__)
    assert list(store.root.rglob("*.rollback"))


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor mode semantics")
def test_pinned_publishing_transaction_preserves_existing_file_modes_on_commit_and_rollback(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    store.save_cover(prompt="old", base_image=b"old-base", rendered_image=b"old-rendered", model="m")
    targets = [
        store.cover_base_path,
        store.rendered_cover_path,
        store.webnovel_dir / "project.json",
        store.story_system_dir / "MASTER_SETTING.json",
    ]
    for target in targets:
        os.chmod(target, 0o640)

    store.save_cover(prompt="new", base_image=b"new-base", rendered_image=b"new-rendered", model="m")
    assert [target.stat().st_mode & 0o777 for target in targets] == [0o640] * len(targets)

    original_metadata_replace = store._replace_metadata
    monkeypatch.setattr(store, "_replace_metadata", lambda *_args: (_ for _ in ()).throw(OSError("metadata replace failed")))
    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_cover(prompt="again", base_image=b"again-base", rendered_image=b"again-rendered", model="m")
    assert [target.stat().st_mode & 0o777 for target in targets] == [0o640] * len(targets)
    monkeypatch.setattr(store, "_replace_metadata", original_metadata_replace)


@pytest.mark.skipif(os.name != "nt", reason="Windows handle acquisition semantics")
def test_windows_pin_acquisition_closes_unregistered_handle_on_final_path_failure(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    monkeypatch.setattr(
        _PinnedPublishingFilesystem,
        "_windows_final_path",
        staticmethod(lambda _handle: (_ for _ in ()).throw(OSError("final path failed"))),
    )

    with pytest.raises(OSError, match="final path failed"):
        with _PinnedPublishingFilesystem(root):
            pass

    root.rename(tmp_path / "renamed-root")


@pytest.mark.skipif(os.name == "nt", reason="POSIX procfs semantics")
def test_procfs_less_posix_fails_closed_before_publishing_writes(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    before = (store.webnovel_dir / "project.json").read_bytes()
    original_exists = os.path.exists
    monkeypatch.setattr(os.path, "exists", lambda path: False if str(path) == "/proc/self/fd" else original_exists(path))

    with pytest.raises(ValueError, match="^publishing_asset_write_failed$"):
        store.save_synopsis({"summary": "new"})

    assert (store.webnovel_dir / "project.json").read_bytes() == before
    store.root.rename(tmp_path / "renamed-novel")


@pytest.mark.skipif(os.name == "nt", reason="POSIX descriptor acquisition semantics")
def test_posix_pin_acquisition_closes_root_fd_when_proc_read_fails(tmp_path, monkeypatch):
    root = tmp_path / "root"
    root.mkdir()
    original_readlink = os.readlink
    monkeypatch.setattr(
        os,
        "readlink",
        lambda path, *args, **kwargs: (_ for _ in ()).throw(OSError("proc read failed"))
        if str(path).startswith("/proc/self/fd/")
        else original_readlink(path, *args, **kwargs),
    )

    with pytest.raises(OSError, match="proc read failed"):
        with _PinnedPublishingFilesystem(root):
            pass

    root.rename(tmp_path / "renamed-root")


@pytest.mark.skipif(os.name != "nt", reason="Windows mkstemp/fdopen ownership")
def test_windows_prepare_closes_raw_descriptor_when_fdopen_construction_fails(tmp_path, monkeypatch):
    store = _make_store(tmp_path / "novel")
    filesystem = _PinnedPublishingFilesystem(store.root)
    opened: list[tuple[int, Path]] = []
    real_mkstemp = tempfile.mkstemp
    real_unlink = Path.unlink

    def track_mkstemp(*args, **kwargs):
        descriptor, name = real_mkstemp(*args, **kwargs)
        opened.append((descriptor, Path(name)))
        return descriptor, name

    monkeypatch.setattr(tempfile, "mkstemp", track_mkstemp)
    monkeypatch.setattr(os, "fdopen", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("fdopen failed")))

    with filesystem:
        with pytest.raises(OSError, match="fdopen failed"):
            filesystem.prepare(store.cover_base_path, b"cover", suffix=".tmp")

    descriptor, temp_path = opened[-1]
    with pytest.raises(OSError):
        os.fstat(descriptor)
    assert not temp_path.exists()

    # Cleanup failure remains best-effort and cannot replace the fdopen error.
    monkeypatch.setattr(Path, "unlink", lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("unlink failed")))
    with _PinnedPublishingFilesystem(store.root) as retry_filesystem:
        with pytest.raises(OSError, match="fdopen failed"):
            retry_filesystem.prepare(store.cover_base_path, b"cover", suffix=".tmp")
    _, retained_temp = opened[-1]
    real_unlink(retained_temp, missing_ok=True)
