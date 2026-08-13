from __future__ import annotations

import json
from pathlib import Path

import pytest

from packages.story_core.volume_detail_checkpoints import (
    VolumeDetailCheckpointStore,
)


def _fingerprint_inputs(*, guidance: str = "") -> dict[str, object]:
    return {
        "volume_range": [153, 182],
        "story_nodes": [
            {
                "start_chapter": 153,
                "end_chapter": 167,
                "objective": "查明灵井故障",
            },
            {
                "start_chapter": 168,
                "end_chapter": 182,
                "objective": "修复灵井并承担代价",
            },
        ],
        "existing_outline_version": "outline-v7",
        "user_guidance": guidance,
    }


def _chapter_rows(start: int, end: int) -> list[dict[str, object]]:
    return [
        {"chapter_number": number, "title": f"第{number}章", "summary": "细纲"}
        for number in range(start, end + 1)
    ]


def test_checkpoint_manifest_contains_one_entry_per_volume_batch(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)

    manifest = store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    assert manifest["schema_version"] == "volume-detail-checkpoints/v1"
    assert [item["id"] for item in manifest["batches"]] == [
        "0153-0167",
        "0168-0182",
    ]
    assert [item["status"] for item in manifest["batches"]] == [
        "waiting",
        "waiting",
    ]
    assert (tmp_path / "v3" / "manifest.json").is_file()


def test_prepare_rejects_batch_longer_than_fifteen_chapters(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)

    with pytest.raises(ValueError, match="batch_too_large"):
        store.prepare(
            volume_id="v3",
            batches=[[153, 168]],
            **_fingerprint_inputs(),
        )


def test_prepare_allows_sparse_non_overlapping_batches(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)

    manifest = store.prepare(
        volume_id="v3",
        batches=[[153, 157], [168, 172]],
        **_fingerprint_inputs(),
    )

    assert [item["id"] for item in manifest["batches"]] == [
        "0153-0157",
        "0168-0172",
    ]


def test_completed_batches_survive_same_fingerprint_retry(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    first_payload = {"chapters": _chapter_rows(153, 167)}
    store.complete("0153-0167", first_payload)
    store.fail("0168-0182", "timeout")

    retried = store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    assert [item["status"] for item in retried["batches"]] == [
        "completed",
        "failed",
    ]
    assert store.completed_payloads() == {"0153-0167": first_payload}
    assert store.next_incomplete_batch()["id"] == "0168-0182"


def test_changed_fingerprint_invalidates_every_old_batch(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    store.complete("0153-0167", {"chapters": _chapter_rows(153, 167)})

    changed = store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(guidance="第二批加强冲突"),
    )

    assert [item["status"] for item in changed["batches"]] == [
        "waiting",
        "waiting",
    ]
    assert store.completed_payloads() == {}
    assert not (tmp_path / "v3" / "0153-0167.json").exists()


def test_same_fingerprint_with_tampered_batch_layout_rebuilds_manifest(
    tmp_path: Path,
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    store.complete("0153-0167", {"chapters": _chapter_rows(153, 167)})
    manifest_path = tmp_path / "v3" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["batches"][0].update(
        {"id": "0153-0166", "end_chapter": 166, "status": "completed"}
    )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rebuilt = store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    assert [
        (item["id"], item["start_chapter"], item["end_chapter"], item["status"])
        for item in rebuilt["batches"]
    ] == [
        ("0153-0167", 153, 167, "waiting"),
        ("0168-0182", 168, 182, "waiting"),
    ]
    assert not (tmp_path / "v3" / "0153-0167.json").exists()


def test_same_fingerprint_with_tampered_volume_range_rebuilds_manifest(
    tmp_path: Path,
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    manifest_path = tmp_path / "v3" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["volume_range"] = [152, 182]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rebuilt = store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    assert rebuilt["volume_range"] == [153, 182]
    assert all(item["status"] == "waiting" for item in rebuilt["batches"])


def test_prepare_rebuilds_manifest_when_tampered_layout_is_self_invalid(
    tmp_path: Path,
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    manifest_path = tmp_path / "v3" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["volume_range"] = [154, 182]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    rebuilt = store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    assert rebuilt["volume_range"] == [153, 182]
    assert [item["id"] for item in rebuilt["batches"]] == [
        "0153-0167",
        "0168-0182",
    ]


def test_fingerprint_changes_for_every_required_input(tmp_path: Path) -> None:
    def fingerprint(
        root_name: str,
        *,
        volume_id: str = "v3",
        volume_range: list[int] | None = None,
        batches: list[list[int]] | None = None,
        story_nodes: list[dict[str, object]] | None = None,
        existing_outline_version: str = "outline-v7",
        user_guidance: str = "",
    ) -> str:
        inputs = _fingerprint_inputs(guidance=user_guidance)
        manifest = VolumeDetailCheckpointStore(tmp_path / root_name).prepare(
            volume_id=volume_id,
            batches=batches or [[153, 167], [168, 182]],
            volume_range=volume_range or [153, 182],
            story_nodes=story_nodes or inputs["story_nodes"],
            existing_outline_version=existing_outline_version,
            user_guidance=user_guidance,
        )
        return manifest["fingerprint"]

    baseline = fingerprint("baseline")
    assert fingerprint("volume-id", volume_id="v4") != baseline
    assert (
        fingerprint(
            "volume-range",
            volume_range=[153, 183],
            batches=[[153, 167], [169, 183]],
        )
        != baseline
    )
    assert (
        fingerprint(
            "nodes",
            story_nodes=[
                {
                    "start_chapter": 153,
                    "end_chapter": 182,
                    "objective": "改查另一条线",
                }
            ],
        )
        != baseline
    )
    assert fingerprint("version", existing_outline_version="outline-v8") != baseline
    assert fingerprint("guidance", user_guidance="加强冲突") != baseline


def test_running_complete_and_fail_are_persisted(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    store.running("0153-0167")
    first_manifest = json.loads(
        (tmp_path / "v3" / "manifest.json").read_text(encoding="utf-8")
    )
    assert first_manifest["batches"][0]["status"] == "running"

    store.complete("0153-0167", {"chapters": _chapter_rows(153, 167)})
    store.fail("0168-0182", "provider timeout")

    reloaded = VolumeDetailCheckpointStore(tmp_path)
    reloaded.load("v3")
    assert list(reloaded.completed_payloads()) == ["0153-0167"]
    incomplete = reloaded.next_incomplete_batch()
    assert incomplete["id"] == "0168-0182"
    assert incomplete["status"] == "failed"
    assert incomplete["error"] == "provider timeout"


@pytest.mark.parametrize(
    "volume_id",
    [
        "",
        ".",
        "..",
        "../v3",
        "v3/other",
        "v3\\other",
        "C:evil",
        "CON",
        "con.txt",
        "PRN",
        "AUX",
        "NUL",
        "COM1",
        "com9.json",
        "LPT1",
        "lpt9.data",
        "volume.",
        "volume ",
    ],
)
def test_volume_id_cannot_escape_checkpoint_root(
    tmp_path: Path, volume_id: str
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)

    with pytest.raises(ValueError, match="invalid_volume_id"):
        store.prepare(
            volume_id=volume_id,
            batches=[[153, 182]],
            **_fingerprint_inputs(),
        )


def test_volume_directory_rejects_symlink_or_reparse_target(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    root = tmp_path / "checkpoints"
    root.mkdir()
    linked_volume = root / "v3"
    try:
        linked_volume.symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"directory symlink unavailable: {exc}")

    with pytest.raises(ValueError, match="invalid_volume_id"):
        VolumeDetailCheckpointStore(root).prepare(
            volume_id="v3",
            batches=[[153, 167]],
            **_fingerprint_inputs(),
        )


def test_volume_directory_rejects_root_escape_even_if_resolution_is_tampered(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "checkpoints"
    root.mkdir()
    original_resolve = Path.resolve

    def escape_volume(path: Path, *args: object, **kwargs: object) -> Path:
        if path == root / "v3":
            return tmp_path / "outside" / "v3"
        return original_resolve(path, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", escape_volume)

    with pytest.raises(ValueError, match="invalid_volume_id"):
        VolumeDetailCheckpointStore(root).prepare(
            volume_id="v3",
            batches=[[153, 167]],
            **_fingerprint_inputs(),
        )


@pytest.mark.parametrize(
    ("batches", "error"),
    [
        ([], "empty_batches"),
        ([[153]], "invalid_batch"),
        ([[167, 153]], "invalid_batch"),
        ([[153, 167], [160, 174]], "overlapping_batches"),
        ([[0, 15]], "invalid_batch"),
        ([[True, 15]], "invalid_batch"),
    ],
)
def test_prepare_rejects_invalid_batches(
    tmp_path: Path, batches: list[list[int]], error: str
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)

    with pytest.raises(ValueError, match=error):
        store.prepare(
            volume_id="v3",
            batches=batches,
            **_fingerprint_inputs(),
        )


def test_prepare_rejects_batch_outside_declared_volume_range(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)

    with pytest.raises(ValueError, match="batch_outside_volume_range"):
        store.prepare(
            volume_id="v3",
            batches=[[152, 166], [167, 182]],
            **_fingerprint_inputs(),
        )


@pytest.mark.parametrize(
    "chapters",
    [
        _chapter_rows(153, 166),
        _chapter_rows(153, 168),
        _chapter_rows(154, 168),
        [*_chapter_rows(153, 166), _chapter_rows(166, 166)[0]],
    ],
)
def test_complete_rejects_payload_with_wrong_chapter_numbers(
    tmp_path: Path, chapters: list[dict[str, object]]
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    with pytest.raises(ValueError, match="payload_chapter_mismatch"):
        store.complete("0153-0167", {"chapters": chapters})


def test_unknown_batch_is_rejected(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )

    with pytest.raises(ValueError, match="unknown_batch"):
        store.running("../manifest")


def test_load_rejects_manifest_with_path_traversal_batch_id(tmp_path: Path) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    manifest_path = tmp_path / "v3" / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["batches"][0]["id"] = "../outside"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(ValueError, match="invalid_checkpoint_manifest"):
        VolumeDetailCheckpointStore(tmp_path).load("v3")


@pytest.mark.parametrize("damage", ["missing", "invalid_json", "wrong_chapters"])
def test_load_downgrades_unusable_completed_payload_for_retry(
    tmp_path: Path, damage: str
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    store.complete("0153-0167", {"chapters": _chapter_rows(153, 167)})
    payload_path = tmp_path / "v3" / "0153-0167.json"
    if damage == "missing":
        payload_path.unlink()
    elif damage == "invalid_json":
        payload_path.write_text("{broken", encoding="utf-8")
    else:
        payload_path.write_text(
            json.dumps({"chapters": _chapter_rows(154, 167)}), encoding="utf-8"
        )

    reloaded = VolumeDetailCheckpointStore(tmp_path)
    manifest = reloaded.load("v3")

    assert manifest["batches"][0]["status"] == "failed"
    assert reloaded.next_incomplete_batch()["id"] == "0153-0167"
    persisted = json.loads(
        (tmp_path / "v3" / "manifest.json").read_text(encoding="utf-8")
    )
    assert persisted["batches"][0]["status"] == "failed"


def test_completed_payloads_downgrades_payload_damaged_after_load(
    tmp_path: Path,
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    store.complete("0153-0167", {"chapters": _chapter_rows(153, 167)})
    (tmp_path / "v3" / "0153-0167.json").unlink()

    assert store.completed_payloads() == {}
    incomplete = store.next_incomplete_batch()
    assert incomplete["id"] == "0153-0167"
    assert incomplete["status"] == "failed"


def test_failed_atomic_manifest_replace_preserves_previous_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = VolumeDetailCheckpointStore(tmp_path)
    store.prepare(
        volume_id="v3",
        batches=[[153, 167], [168, 182]],
        **_fingerprint_inputs(),
    )
    before = (tmp_path / "v3" / "manifest.json").read_bytes()

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(
        "packages.story_core.volume_detail_checkpoints.os.replace", fail_replace
    )

    with pytest.raises(OSError, match="replace failed"):
        store.running("0153-0167")

    assert (tmp_path / "v3" / "manifest.json").read_bytes() == before
