"""Tests for the Markdown-canonical chapter body.

After the migration the chapter JSON only carries ``body_path`` and
``body_sha256``; the actual prose lives in a sibling Markdown file
under ``chapters/NNNN-{title}.md``. Reads hydrate the body from
Markdown; writes compute the hash before serialising the metadata.
Legacy JSON-only chapters still load transparently so the workbench
does not break for users who have not re-confirmed a chapter yet.
"""

from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.generation_progress import generation_progress


def _long_body(tag: str) -> str:
    return (f"{tag}章节。" * 800)[:5200]


def _seed_and_confirm(
    store: FileProjectStore,
    *,
    chapter_number: int,
    title: str,
    body: str,
    operation: str = "generate",
) -> None:
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
    store.confirm_candidate(candidate.candidate_id)


def test_new_chapter_metadata_points_at_markdown_file(tmp_path):
    store = FileProjectStore(tmp_path)
    body = _long_body("MD候选稿")
    _seed_and_confirm(
        store, chapter_number=1, title="第一章", body=body
    )

    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    chapter = json.loads(chapter_path.read_text(encoding="utf-8"))
    assert "body" not in chapter, "metadata JSON must not duplicate the body"
    assert "body_path" in chapter, "metadata must point at the Markdown file"
    assert "body_sha256" in chapter
    assert chapter["body_chars"] == len("".join(body.split()))
    # The body_path is relative to the project root so the project
    # is portable. The Markdown file actually exists and has the
    # expected hash.
    body_path = store.root / chapter["body_path"]
    assert body_path.is_file()
    assert chapter["body_sha256"] == hashlib.sha256(body.encode("utf-8")).hexdigest()


def test_chapter_index_counts_existing_markdown_body_without_cached_length(tmp_path):
    store = FileProjectStore(tmp_path)
    body = "第一段正文。\n\n第二段正文。"
    markdown_path = store.root / "chapters" / "0001-第一章.md"
    markdown_path.parent.mkdir(parents=True, exist_ok=True)
    markdown_path.write_text(body, encoding="utf-8")
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    chapter_path.write_text(
        json.dumps(
            {
                "chapter_number": 1,
                "chapter_title": "第一章",
                "body_path": "chapters/0001-第一章.md",
                "body_sha256": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert store.chapter_index()[0]["body_chars"] == len("".join(body.split()))


def test_read_chapter_hydrates_body_from_markdown(tmp_path):
    store = FileProjectStore(tmp_path)
    body = _long_body("MD正文")
    _seed_and_confirm(store, chapter_number=1, title="第一章", body=body)

    # ``read_chapter`` returns the metadata dict. The Markdown
    # body can be re-hydrated by either ``read_chapter_body`` or
    # by following ``body_path`` directly.
    chapter = store.chapter_store.read_chapter(1)
    assert chapter["body_path"]
    hydrated = store.chapter_store.read_chapter_body(1)
    assert hydrated == body


def test_legacy_json_only_chapter_still_loads(tmp_path):
    store = FileProjectStore(tmp_path)
    # Hand-craft a legacy record: ``body`` in the JSON, no
    # Markdown file. The chapter must still be readable, with the
    # body returned from the JSON field.
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "schema_version": "chapter/v1",
        "chapter_number": 1,
        "chapter_title": "第一章",
        "body": "旧版正文。",
        "updated_story": {"current_chapter": 1},
    }
    chapter_path.write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    chapter = store.chapter_store.read_chapter(1)
    assert chapter["body"] == "旧版正文。"
    # The legacy read path returns the body directly. The
    # ``read_chapter_body`` helper is graceful: it falls back to
    # the JSON body when no Markdown is present.
    assert store.chapter_store.read_chapter_body(1) == "旧版正文。"


def test_legacy_chapter_migrates_to_markdown_on_next_save(tmp_path):
    store = FileProjectStore(tmp_path)
    chapter_path = store.story_system_dir / "chapters" / "0001.json"
    chapter_path.parent.mkdir(parents=True, exist_ok=True)
    legacy = {
        "schema_version": "chapter/v1",
        "chapter_number": 1,
        "chapter_title": "第一章",
        "body": "旧版正文。",
        "updated_story": {"current_chapter": 1},
    }
    chapter_path.write_text(
        json.dumps(legacy, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    # Re-confirming a new chapter on top of the legacy one
    # migrates the legacy body into Markdown and removes the
    # ``body`` field from the metadata.
    _seed_and_confirm(
        store,
        chapter_number=1,
        title="第一章",
        body=_long_body("新版本正文"),
    )

    chapter = json.loads(chapter_path.read_text(encoding="utf-8"))
    # The legacy body field is gone — the migration overwrites the
    # chapter. The new body lives in a Markdown file pointed at by
    # ``body_path``.
    assert "body" not in chapter
    assert "body_path" in chapter
    assert "body_sha256" in chapter
    assert (store.root / chapter["body_path"]).is_file()


def test_markdown_hash_mismatch_is_detected(tmp_path):
    store = FileProjectStore(tmp_path)
    body = _long_body("hash候选稿")
    _seed_and_confirm(store, chapter_number=1, title="第一章", body=body)

    # Tamper with the Markdown file: rewrite it with a different
    # body. ``read_chapter`` should warn (or expose the mismatch)
    # rather than silently return the modified prose.
    chapter = store.chapter_store.read_chapter(1)
    markdown_path = store.root / chapter["body_path"]
    markdown_path.write_text("被篡改的正文。", encoding="utf-8")

    mismatch = store.chapter_store.detect_markdown_mismatch(1)
    assert mismatch is not None
    assert mismatch["expected_sha256"] == chapter["body_sha256"]
    assert mismatch["actual_sha256"] != chapter["body_sha256"]


def test_read_chapter_with_include_body_false_skips_markdown_load(tmp_path):
    store = FileProjectStore(tmp_path)
    body = _long_body("省去正文")
    _seed_and_confirm(store, chapter_number=1, title="第一章", body=body)

    # List endpoints should be able to ask for metadata-only reads
    # to avoid loading every chapter body.
    metadata_only = store.chapter_store.read_chapter(1, include_body=False)
    assert "body_path" in metadata_only
    # The metadata-only read does not embed the body in the dict.
    assert "body" not in metadata_only
