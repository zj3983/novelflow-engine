from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from apps.api.storage import SQLiteStoryStore
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import NovelProject, StoryState


MODULE_PATH = Path(__file__).parents[1] / "scripts" / "migrate_project_genre.py"


def _migration_module():
    assert MODULE_PATH.exists(), "migration module does not exist"
    spec = importlib.util.spec_from_file_location("migrate_project_genre", MODULE_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _mojibake(text: str) -> str:
    return text.encode("gbk").decode("latin1")


def _fixture_store(
    tmp_path: Path,
    *,
    body: str = "林照接下祖祠守炉的差事。",
    title: str = "祖祠守炉",
) -> SQLiteStoryStore:
    store = SQLiteStoryStore(str(tmp_path / "stories.db"))
    story = StoryState(
        story_id="s-incense",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描、现代中文",
        author_constraints=["后续默认围绕渡劫和飞升展开", "对话要自然"],
        writing_lessons=["主线写长生求道", "场面要由人物行动推动"],
        world_facts=["修仙默认方向：灵根、渡劫、飞升", "祖祠香炉已经断裂"],
        progression_ledger={
            "cultivation": {"realm": "外门候选"},
            "clues": {"third_brick": "未挖"},
            "market": {"newbie_materials": {"price_copper": 2}},
            "persistent_world": {"guild_intel": {"white_robe_guild": {}}},
            "world_pulse": {"latest": {"action": "service_counter updates player material price"}},
            "reality": {},
        },
    )
    store.create(story)
    store.create_project(
        NovelProject(
            project_id="p-incense",
            title="断香炉",
            active_story_id=story.story_id,
            seed_outline="林照看守断香炉。",
            world_summary=_mojibake("宗门祖祠里有一座断香炉。"),
            current_focus="查清香炉断裂的原因。",
            author_constraints=["后续默认围绕渡劫和飞升展开", "对话要自然"],
            character_profiles=[{"name": _mojibake("林照"), "role": "protagonist"}],
            world_blueprint={
                "genre_plugin_ids": ["xianxia"],
                "writing_rules": ["主线写长生求道和灵根", "冲突必须具体"],
                "progression_ledger": {
                    "cultivation": {"realm": "外门候选"},
                    "clues": {"third_brick": "未挖"},
                },
            },
        )
    )
    store.attach_story_to_project("p-incense", story.story_id)
    updated = story.model_copy(deep=True)
    updated.current_chapter = 1
    store.append_chapter_bundle(
        story.story_id,
        ChapterBundle(
            chapter_number=1,
            chapter_title=title,
            body=body,
            next_outline="赵管事来清点祖祠。",
            updated_story=updated,
        ),
    )
    return store


def _project_genre_from_db(db_path: Path, project_id: str) -> str:
    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            "SELECT project_json FROM novel_projects WHERE project_id = ?",
            (project_id,),
        ).fetchone()
    assert row is not None
    return json.loads(row[0])["world_blueprint"]["genre_plugin_ids"][0]


def _append_chapter(
    store: SQLiteStoryStore,
    *,
    chapter_number: int,
    title: str,
    body: str,
) -> None:
    record = store.get("s-incense")
    assert record is not None
    updated = record.story.model_copy(deep=True)
    updated.current_chapter = chapter_number
    store.append_chapter_bundle(
        "s-incense",
        ChapterBundle(
            chapter_number=chapter_number,
            chapter_title=title,
            body=body,
            next_outline=f"第{chapter_number + 1}章继续查香炉。",
            updated_story=updated,
        ),
    )


def test_repair_gbk_mojibake_recursively_and_leaves_normal_chinese_unchanged():
    migration = _migration_module()
    value = {
        "summary": _mojibake("林照看守断香炉"),
        "items": [_mojibake("宗门"), "正常中文", 3],
        "nested": {"focus": _mojibake("查清来历")},
    }

    repaired = migration.repair_gbk_mojibake(value)

    assert repaired == {
        "summary": "林照看守断香炉",
        "items": ["宗门", "正常中文", 3],
        "nested": {"focus": "查清来历"},
    }


def test_migration_backs_up_first_switches_type_and_preserves_every_chapter(tmp_path: Path):
    migration = _migration_module()
    store = _fixture_store(tmp_path)

    result = migration.migrate_project_genre(
        store=store,
        project_id="p-incense",
        target_genre="xuanhuan",
        repair_mojibake=True,
    )

    project = store.get_project("p-incense")
    record = store.get("s-incense")
    assert project is not None and record is not None
    assert project.world_blueprint["genre_plugin_ids"] == ["xuanhuan"]
    assert project.world_summary == "宗门祖祠里有一座断香炉。"
    assert project.character_profiles[0]["name"] == "林照"
    assert project.author_constraints == ["对话要自然"]
    assert project.world_blueprint["writing_rules"] == ["冲突必须具体"]
    assert record.story.genre == "xuanhuan"
    assert record.story.writing_lessons == ["场面要由人物行动推动"]
    assert record.story.progression_ledger == {
        "cultivation": {"realm": "外门候选"},
        "clues": {"third_brick": "未挖"},
    }
    assert record.history[0].chapter_title == "祖祠守炉"
    assert record.history[0].body == "林照接下祖祠守炉的差事。"
    assert result["before_genre"] == "xianxia"
    assert result["target_genre"] == "xuanhuan"
    assert result["chapter_count"] == 1
    assert result["before_body_sha256"] == result["after_body_sha256"]
    backup_path = Path(result["backup_path"])
    assert backup_path.exists()
    assert _project_genre_from_db(backup_path, "p-incense") == "xianxia"


def test_backup_destination_is_explicitly_closed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    migration = _migration_module()
    store = _fixture_store(tmp_path)
    real_connect = migration.sqlite3.connect
    opened = []

    class TrackingConnection(sqlite3.Connection):
        close_called = False

        def close(self):
            self.close_called = True
            return super().close()

    def tracking_connect(database, *args, **kwargs):
        connection = real_connect(database, *args, factory=TrackingConnection, **kwargs)
        opened.append(connection)
        return connection

    monkeypatch.setattr(migration.sqlite3, "connect", tracking_connect)

    backup_path = migration._backup_database(store, tmp_path / "backups")

    assert opened and opened[-1].close_called is True
    backup_path.unlink()
    assert not backup_path.exists()


def test_migration_keeps_xianxia_terms_that_are_already_established_in_chapters(tmp_path: Path):
    migration = _migration_module()
    store = _fixture_store(tmp_path, body="林照的灵根早已在宗门登记。")

    migration.migrate_project_genre(
        store=store,
        project_id="p-incense",
        target_genre="xuanhuan",
        repair_mojibake=False,
    )

    project = store.get_project("p-incense")
    assert project is not None
    assert "主线写长生求道和灵根" in project.world_blueprint["writing_rules"]
    assert "后续默认围绕渡劫和飞升展开" not in project.author_constraints


def test_migration_preserves_multiple_chapter_titles_bodies_and_count(tmp_path: Path):
    migration = _migration_module()
    store = _fixture_store(tmp_path, title="第一炉香", body="林照接下祖祠差事。")
    _append_chapter(
        store,
        chapter_number=2,
        title="灰里的铜片",
        body="他从冷灰里找出一枚刻字铜片。",
    )
    _append_chapter(
        store,
        chapter_number=3,
        title="管事登门",
        body="赵管事带着账册来到祖祠。",
    )
    before = [
        (bundle.chapter_number, bundle.chapter_title, bundle.body)
        for bundle in store.get("s-incense").history
    ]

    result = migration.migrate_project_genre(
        store=store,
        project_id="p-incense",
        target_genre="xuanhuan",
        repair_mojibake=False,
    )

    migrated = store.get("s-incense")
    assert migrated is not None
    after = [
        (bundle.chapter_number, bundle.chapter_title, bundle.body)
        for bundle in migrated.history
    ]
    assert result["chapter_count"] == 3
    assert before == after
    assert result["before_body_sha256"] == result["after_body_sha256"]


def test_sync_failure_restores_project_story_and_chapters_from_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    migration = _migration_module()
    store = _fixture_store(tmp_path)
    before = store.get("s-incense")
    assert before is not None
    before_chapters = [
        (bundle.chapter_number, bundle.chapter_title, bundle.body)
        for bundle in before.history
    ]

    def fail_sync(project_id: str):
        raise RuntimeError(f"sync failed for {project_id}")

    monkeypatch.setattr(store, "sync_project_context", fail_sync)

    with pytest.raises(RuntimeError) as exc_info:
        migration.migrate_project_genre(
            store=store,
            project_id="p-incense",
            target_genre="xuanhuan",
            repair_mojibake=False,
        )

    assert "backup_path=" in str(exc_info.value)
    project = store.get_project("p-incense")
    restored = store.get("s-incense")
    assert project is not None and restored is not None
    assert project.world_blueprint["genre_plugin_ids"] == ["xianxia"]
    assert restored.story.genre == "xianxia"
    assert [
        (bundle.chapter_number, bundle.chapter_title, bundle.body)
        for bundle in restored.history
    ] == before_chapters


def test_migration_fails_if_a_chapter_title_or_body_changes(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    migration = _migration_module()
    store = _fixture_store(tmp_path)
    original_sync = store.sync_project_context

    def sync_then_corrupt(project_id: str):
        synced = original_sync(project_id)
        record = store.get("s-incense")
        assert record is not None
        changed = record.history[0].model_copy(deep=True)
        changed.chapter_title = "被改坏的标题"
        store.replace_chapter_bundle("s-incense", changed)
        return synced

    monkeypatch.setattr(store, "sync_project_context", sync_then_corrupt)

    with pytest.raises(RuntimeError, match="chapter content changed"):
        migration.migrate_project_genre(
            store=store,
            project_id="p-incense",
            target_genre="xuanhuan",
            repair_mojibake=False,
        )


def test_cli_migrates_the_requested_project_and_prints_json(tmp_path: Path):
    store = _fixture_store(tmp_path)
    env = dict(os.environ)
    env["NOVEL_AUTOGROWTH_DB_PATH"] = store._db_path

    completed = subprocess.run(
        [
            sys.executable,
            str(MODULE_PATH),
            "p-incense",
            "--target-genre",
            "xuanhuan",
            "--repair-gbk-mojibake",
        ],
        cwd=MODULE_PATH.parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    result = json.loads(completed.stdout)
    assert result["before_genre"] == "xianxia"
    assert result["target_genre"] == "xuanhuan"
    assert result["chapter_count"] == 1
    assert result["before_body_sha256"] == result["after_body_sha256"]
