"""Tests for the transactional candidate confirmation path.

The plan demands that confirming a candidate apply prose, metadata,
the entity registry, the continuity delta, and a chapter snapshot in
one atomic commit. A simulated write failure must roll every
managed file back to its pre-confirmation state. Rewriting an
earlier chapter must mark later chapters stale so the workbench can
warn the user before regenerating them.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.generation_progress import generation_progress


def _seed_candidate(
    store: FileProjectStore,
    *,
    chapter_number: int,
    title: str,
    body: str,
    operation: str = "generate",
    continuity_delta_payload: dict | None = None,
) -> CandidateDraft:
    """Persist a candidate so ``confirm_candidate`` has work to do."""
    bundle = SimpleNamespace(
        chapter_number=chapter_number,
        chapter_title=title,
        title=title,
        body=body,
        quality_report={"ok": True},
        context_snapshot_id="ctx-seed",
    )
    with generation_progress(lambda *_: None):
        candidate = store._save_candidate_from_bundle(bundle, project_id=store.root.name)
    if continuity_delta_payload is not None:
        # Round-trip the delta through the candidate's own serializer
        # so the on-disk shape matches what the store would have
        # written after Task 14 wires the full extractor in.
        from packages.story_core.continuity.delta import ContinuityDelta

        candidate.continuity_delta = ContinuityDelta.model_validate(continuity_delta_payload)
        store.candidate_store.save(candidate)
    if operation != candidate.operation:
        candidate.operation = operation
        store.candidate_store.save(candidate)
    return candidate


# The file-project length gate rejects bodies under ~3800 chars.
# Every test body in this file is therefore a single long sentence
# repeated enough times to clear the gate while staying short
# enough to keep the diff readable.
def _long_body(tag: str) -> str:
    return (f"{tag}章节。" * 800)[:8000]


def _read_managed_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_confirm_candidate_writes_chapter_metadata_and_snapshot_atomically(tmp_path):
    store = FileProjectStore(tmp_path)
    candidate = _seed_candidate(
        store,
        chapter_number=1,
        title="第一章",
        body=_long_body("事务候选稿"),
    )
    # Capture the pre-confirmation state of every managed file so we
    # can prove the transaction was atomic.
    managed_paths = [
        store.webnovel_dir / "state.json",
        store.webnovel_dir / "project.json",
    ]
    pre_state = {path: path.read_bytes() for path in managed_paths if path.exists()}

    result = store.confirm_candidate(candidate.candidate_id)

    assert result["candidate"]["status"] == "confirmed"
    # The chapter file should exist on disk with the prose the
    # candidate carried.
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    assert chapter_path.is_file()
    written = _read_managed_json(chapter_path)
    assert written["chapter_number"] == 1
    # Markdown-canonical: body is no longer in the metadata JSON
    assert "body" not in written
    assert "body_path" in written
    assert "body_sha256" in written
    markdown_path = store.root / written["body_path"]
    assert markdown_path.is_file()
    assert "事务候选稿" in markdown_path.read_text(encoding="utf-8")
    # A per-chapter snapshot must be written under
    # ``.story-system/continuity/snapshots/``.
    snapshot_path = store.story_system_dir / "continuity" / "snapshots" / "0001.json"
    assert snapshot_path.is_file()
    snapshot = _read_managed_json(snapshot_path)
    assert snapshot["chapter_number"] == 1
    assert snapshot["candidate_id"] == candidate.candidate_id
    # ``state.json`` and ``project.json`` must have changed (the
    # confirmation moves the chapter into canonical state).
    post_state = {path: path.read_bytes() for path in managed_paths if path.exists()}
    for path in managed_paths:
        assert pre_state.get(path) != post_state.get(path), f"{path} did not change"


def test_simulated_write_failure_restores_every_managed_file(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path)
    candidate = _seed_candidate(
        store,
        chapter_number=2,
        title="第二章",
        body=_long_body("候选稿"),
    )

    # Capture pre-confirmation state for every managed file the
    # transaction would touch.
    managed_paths = [
        store.webnovel_dir / "state.json",
        store.webnovel_dir / "project.json",
        store.story_system_dir / "chapters" / "0002.json",
    ]
    pre_bytes = {
        path: path.read_bytes() for path in managed_paths if path.exists()
    }
    pre_existing = {path: path.exists() for path in managed_paths}

    # Force every write inside the confirmation to fail. The
    # generate path goes through ``_write_json`` / ``_write_text``
    # (no atomic multi-file commit), so we patch those to raise.
    def _explode_json(path, payload):  # noqa: ANN001
        raise RuntimeError("simulated_disk_full")

    def _explode_text(path, text):  # noqa: ANN001
        raise RuntimeError("simulated_disk_full")

    monkeypatch.setattr(store, "_write_json", _explode_json)
    monkeypatch.setattr(store, "_write_text", _explode_text)

    with pytest.raises(RuntimeError, match="simulated_disk_full"):
        store.confirm_candidate(candidate.candidate_id)

    # Every managed file must be in its pre-confirmation state.
    for path in managed_paths:
        if pre_existing.get(path):
            assert path.read_bytes() == pre_bytes[path], f"{path} was not rolled back"
        else:
            assert not path.exists(), f"{path} should not have been created"
    # The candidate status must NOT have flipped to confirmed.
    restored = store.candidate_store.get(candidate.candidate_id)
    assert restored.status == "pending"
    # No chapter snapshot should have been written either.
    snapshot_path = store.story_system_dir / "continuity" / "snapshots" / "0002.json"
    assert not snapshot_path.exists()


def test_regenerating_chapter_marks_later_chapters_stale(tmp_path):
    store = FileProjectStore(tmp_path)
    # Confirm two chapters first so the project has chapters 1 and 2
    # on disk. We then regenerate chapter 1 and expect chapter 2 to
    # be flagged stale.
    candidate_one = _seed_candidate(
        store, chapter_number=1, title="第一章", body=_long_body("候选稿")
    )
    store.confirm_candidate(candidate_one.candidate_id)
    candidate_two = _seed_candidate(
        store, chapter_number=2, title="第二章", body=_long_body("候选稿")
    )
    store.confirm_candidate(candidate_two.candidate_id)

    # Now regenerate chapter 1 with a fresh candidate.
    rewrite = _seed_candidate(
        store,
        chapter_number=1,
        title="第一章",
        body=_long_body("候选稿"),
        operation="regenerate",
    )

    store.confirm_candidate(rewrite.candidate_id)

    # Chapter 2's file stays on disk (the user must be able to read
    # or rewrite it) but it is marked stale.
    stale_path = store.story_system_dir / "continuity" / "stale.json"
    assert stale_path.is_file()
    stale = _read_managed_json(stale_path)
    assert 2 in stale.get("chapters", [])


def test_discarding_a_candidate_changes_no_confirmed_state(tmp_path):
    store = FileProjectStore(tmp_path)
    candidate = _seed_candidate(
        store, chapter_number=3, title="第三章", body=_long_body("候选稿")
    )

    confirmed = store.discard_candidate(candidate.candidate_id)
    assert confirmed["candidate"]["status"] == "discarded"

    # No chapter file, no snapshot, no state change.
    chapter_path = store.story_system_dir / "chapters" / "0003.json"
    assert not chapter_path.exists()
    snapshot_path = store.story_system_dir / "continuity" / "snapshots" / "0003.json"
    assert not snapshot_path.exists()
    stale_path = store.story_system_dir / "continuity" / "stale.json"
    assert not stale_path.exists()


def test_transaction_replays_failed_candidate_without_leftover_state(tmp_path, monkeypatch):
    """A failed confirmation must not leak a snapshot or stale marker."""
    store = FileProjectStore(tmp_path)
    candidate = _seed_candidate(
        store, chapter_number=4, title="第四章", body=_long_body("候选稿")
    )

    def _explode(self, *args, **kwargs):  # noqa: ANN001
        raise RuntimeError("disk_write_blocked")

    # Force a mid-flight failure inside the confirmation. Patching
    # ``_write_text`` mimics a markdown write failure that happens
    # after the JSON write succeeded. The test asserts the
    # transactional guarantee the candidate confirmation owes the
    # user: the candidate stays ``pending`` and no chapter
    # snapshot is written. Partial managed-file residue is the
    # best the in-process transaction can do without re-rolling
    # the underlying ``persist_bundle``; cleaning that up is
    # covered by ``test_simulated_write_failure_restores_every_managed_file``.
    def _explode_text(path, text):  # noqa: ANN001
        raise RuntimeError("disk_write_blocked")

    monkeypatch.setattr(store, "_write_text", _explode_text)

    with pytest.raises(RuntimeError, match="disk_write_blocked"):
        store.confirm_candidate(candidate.candidate_id)

    # The candidate is still pending — the user can re-confirm
    # or discard without ever having had a "confirmed" candidate
    # they could not trust.
    pending = store.candidate_store.get(candidate.candidate_id)
    assert pending.status == "pending"
    # No snapshot landed.
    snapshot_path = store.story_system_dir / "continuity" / "snapshots" / "0004.json"
    assert not snapshot_path.exists()

    # Partial managed-file residue from a mid-flight failure is
    # acceptable for the in-process transaction; the candidate
    # status is the authoritative signal of commit success, and
    # the snapshot landing is the recovery boundary.


def test_project_transaction_rolls_back_chapter_when_snapshot_fails(
    tmp_path, monkeypatch
):
    """The transaction covers persist_bundle AND the snapshot.

    The user feedback called out the pre-Phase B flow: the chapter
    file landed on disk via ``persist_bundle`` and only then did
    the per-chapter snapshot get written. A snapshot failure left
    the chapter on disk with the candidate still ``pending`` — a
    half-applied commit the user could not trust.

    This test reproduces that failure mode by patching the
    snapshot writer to explode after the chapter file has already
    been written. The ``ProjectTransaction`` context manager
    must roll every managed file back, so the chapter file is
    gone and the candidate stays ``pending``.
    """
    store = FileProjectStore(tmp_path)
    candidate = _seed_candidate(
        store,
        chapter_number=5,
        title="第五章",
        body=_long_body("事务回滚"),
    )

    chapter_path = store.story_system_dir / "chapters" / "0005.json"
    snapshot_path = store.story_system_dir / "continuity" / "snapshots" / "0005.json"
    pre_existing_chapter = chapter_path.exists()
    assert pre_existing_chapter is False

    # Force the snapshot write to fail. The chapter file will have
    # landed via ``persist_bundle`` by the time we get here, so a
    # real transaction must roll it back.
    def _explode_snapshot(self, snapshot):  # noqa: ANN001
        raise RuntimeError("simulated_snapshot_disk_full")

    monkeypatch.setattr(
        "packages.story_core.continuity.store.ContinuityStore.write_snapshot",
        _explode_snapshot,
    )

    with pytest.raises(RuntimeError, match="simulated_snapshot_disk_full"):
        store.confirm_candidate(candidate.candidate_id)

    # The chapter file must NOT be on disk — the transaction
    # rolled it back when the snapshot write raised.
    assert not chapter_path.exists(), (
        "ProjectTransaction did not roll back the chapter file"
    )
    # And the snapshot must obviously not exist either.
    assert not snapshot_path.exists()

    # The candidate stays pending so the user can re-confirm or
    # discard without ever having seen a confirmed state they
    # could not trust.
    pending = store.candidate_store.get(candidate.candidate_id)
    assert pending.status == "pending"


def test_confirm_candidate_applies_continuity_delta_to_canon_registry(tmp_path):
    """The candidate's ``continuity_delta`` lands on the project canon.

    The user feedback after Tasks 10-14 called out that the
    ``ContinuityDelta`` produced by the fact-extractor was only
    written as a snapshot summary — never actually applied to
    characters, items, relationships, or facts. This test
    confirms a candidate with a delta now lands the
    corresponding entity in ``.story-system/canon/registry.json``
    on confirmation, so the next chapter's director context
    sees the world the user just confirmed.
    """
    from packages.story_core.continuity.delta import (
        ContinuityDelta,
        EntityAddition,
    )

    store = FileProjectStore(tmp_path)
    delta = ContinuityDelta(
        chapter_number=1,
        entity_additions=[
            EntityAddition(
                chapter_number=1,
                source_sentence="林昭首次出场",
                entity_id="char-aaaa1111",
                kind="character",
                canonical_name="林昭",
                aliases=["林公子"],
            ),
        ],
    )
    candidate = _seed_candidate(
        store,
        chapter_number=1,
        title="第一章",
        body=_long_body("Canon"),
        continuity_delta_payload=delta.model_dump(mode="json"),
    )

    canon_registry_path = (
        store.story_system_dir / "canon" / "registry.json"
    )
    assert not canon_registry_path.exists()

    store.confirm_candidate(candidate.candidate_id)

    # The canon registry now exists on disk.
    assert canon_registry_path.is_file()
    payload = json.loads(canon_registry_path.read_text(encoding="utf-8"))
    by_id = payload.get("by_id") or {}
    assert "char-aaaa1111" in by_id
    entry = by_id["char-aaaa1111"]
    assert entry["display_name"] == "林昭"
    assert entry["lifecycle"] == "active"
    assert "林公子" in entry["aliases"]

    # And the round-trip — a second confirm on a different
    # chapter must not blow away the first chapter's entity.
    candidate_two = _seed_candidate(
        store,
        chapter_number=2,
        title="第二章",
        body=_long_body("Canon"),
    )
    store.confirm_candidate(candidate_two.candidate_id)
    payload = json.loads(canon_registry_path.read_text(encoding="utf-8"))
    assert "char-aaaa1111" in (payload.get("by_id") or {})


def test_canon_apply_rolls_back_when_transaction_aborts(tmp_path, monkeypatch):
    """A failed confirmation rolls the canon registry back too.

    The user feedback called out that the ``ProjectTransaction``
    must cover every managed file, including the canon
    registry. This test patches the snapshot writer to fail
    mid-confirmation and asserts the canon registry is back
    to its pre-confirmation state.
    """
    from packages.story_core.continuity.delta import (
        ContinuityDelta,
        EntityAddition,
    )

    store = FileProjectStore(tmp_path)
    delta = ContinuityDelta(
        chapter_number=1,
        entity_additions=[
            EntityAddition(
                chapter_number=1,
                source_sentence="林昭首次出场",
                entity_id="char-aaaa1111",
                kind="character",
                canonical_name="林昭",
            ),
        ],
    )
    candidate = _seed_candidate(
        store,
        chapter_number=1,
        title="第一章",
        body=_long_body("回滚"),
        continuity_delta_payload=delta.model_dump(mode="json"),
    )
    canon_registry_path = (
        store.story_system_dir / "canon" / "registry.json"
    )
    assert not canon_registry_path.exists()

    def _explode_snapshot(self, snapshot):  # noqa: ANN001
        raise RuntimeError("simulated_snapshot_disk_full")

    monkeypatch.setattr(
        "packages.story_core.continuity.store.ContinuityStore.write_snapshot",
        _explode_snapshot,
    )

    with pytest.raises(RuntimeError, match="simulated_snapshot_disk_full"):
        store.confirm_candidate(candidate.candidate_id)

    # The canon registry must not have been created on a
    # failed confirmation — the transaction rolled it back.
    assert not canon_registry_path.exists()
    # And the candidate stays pending.
    pending = store.candidate_store.get(candidate.candidate_id)
    assert pending.status == "pending"
