from dataclasses import replace
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

import pytest

from packages.story_core.novel_type_library import (
    NovelTypeLibrary,
    NovelTypeRecord,
    resolve_genre_plugin,
    update_novel_type,
)
from packages.story_core.genre_plugins import select_genre_plugins
from packages.story_core.models import NovelProject


def test_builtin_types_are_marked_builtin():
    records = NovelTypeLibrary().list()

    assert records
    assert all(record.builtin for record in records)
    assert "eastern_fantasy" not in {record.id for record in records}


def test_editing_builtin_type_preserves_id():
    library = NovelTypeLibrary()
    original = library.get("xuanhuan")
    assert original is not None

    updated = library.update("xuanhuan", replace(original, id="renamed", name="新版东方玄幻"))

    assert updated.id == "xuanhuan"
    assert updated.name == "新版东方玄幻"
    assert updated.builtin is True


def test_custom_type_survives_library_reconstruction():
    created = NovelTypeLibrary().create(
        NovelTypeRecord(id="sports", name="竞技体育", keywords=("联赛", "冠军"))
    )

    reloaded = NovelTypeLibrary().get("sports")

    assert reloaded == created
    assert reloaded is not None
    assert reloaded.builtin is False


def test_duplicate_id_fails():
    library = NovelTypeLibrary()
    library.create({"id": "sports", "name": "竞技体育"})

    with pytest.raises(ValueError, match="already exists"):
        library.create({"id": "sports", "name": "另一个竞技类型"})


def test_builtin_type_cannot_be_deleted():
    with pytest.raises(ValueError, match="built-in"):
        NovelTypeLibrary().delete("xuanhuan")


def test_custom_type_can_be_deleted():
    library = NovelTypeLibrary()
    library.create({"id": "sports", "name": "竞技体育"})

    library.delete("sports")

    assert NovelTypeLibrary().get("sports") is None


def test_resolve_genre_plugin_uses_edited_core_promise():
    update_novel_type("xuanhuan", {"core_promises": ["每次力量提升都必须改变外部关系。"]})

    plugin = resolve_genre_plugin("xuanhuan")

    assert plugin is not None
    assert plugin.core_promises == ("每次力量提升都必须改变外部关系。",)


def test_genre_selection_uses_edited_generic_plugin():
    update_novel_type(
        "generic_webnovel",
        {"name": "全局通用类型", "core_promises": ["每章都兑现一次明确变化。"]},
    )
    project = NovelProject(
        project_id="p-edited-generic",
        title="通用类型测试",
        seed_outline="主角处理一件具体差事。",
        world_blueprint={"genre_plugin_ids": ["generic_webnovel"]},
    )

    generic = select_genre_plugins(project)[0]

    assert generic.plugin_id == "generic_webnovel"
    assert generic.name == "全局通用类型"
    assert generic.core_promises == ("每章都兑现一次明确变化。",)


def test_record_rejects_blank_id_and_name_and_normalizes_rulebook():
    with pytest.raises(ValueError, match="ID"):
        NovelTypeRecord(id=" ", name="有效名称")
    with pytest.raises(ValueError, match="name"):
        NovelTypeRecord(id="valid", name=" ")

    record = NovelTypeRecord(id="valid", name="有效名称", rulebook={"chapter_formula": ["推进冲突"]})

    assert record.rulebook["chapter_formula"] == ("推进冲突",)
    assert record.rulebook["economy_rules"] == ()


def test_record_rejects_unknown_payload_fields():
    with pytest.raises((TypeError, ValueError), match="core_promise"):
        NovelTypeRecord.from_payload(
            {"id": "sports", "name": "竞技体育", "core_promise": ["拼写错误"]}
        )


def test_storage_contains_only_builtin_overrides_and_custom_types():
    library = NovelTypeLibrary()
    library.update("xuanhuan", {"description": "用户修改后的说明"})
    library.create({"id": "sports", "name": "竞技体育"})

    stored = json.loads(library.path.read_text(encoding="utf-8"))

    assert stored["overrides"] == {"xuanhuan": {"description": "用户修改后的说明"}}
    assert set(stored["custom"]) == {"sports"}
    assert "generic_webnovel" not in stored["custom"]


def test_custom_type_is_used_for_explicit_and_keyword_selection():
    NovelTypeLibrary().create(
        {"id": "sports", "name": "竞技体育", "keywords": ["联赛", "冠军"]}
    )
    explicit = NovelProject(
        project_id="p-sports-explicit",
        title="新赛季",
        seed_outline="主角加入职业队。",
        world_blueprint={"genre_plugin_ids": ["sports"]},
    )
    inferred = NovelProject(
        project_id="p-sports-inferred",
        title="冠军联赛",
        seed_outline="主角在联赛中争夺冠军。",
    )

    assert [plugin.plugin_id for plugin in select_genre_plugins(explicit)] == [
        "generic_webnovel",
        "sports",
    ]
    assert [plugin.plugin_id for plugin in select_genre_plugins(inferred)] == [
        "generic_webnovel",
        "sports",
    ]


def test_concurrent_creates_from_separate_instances_are_both_preserved(monkeypatch):
    original_write = NovelTypeLibrary._write

    def slow_write(self, payload):
        time.sleep(0.05)
        original_write(self, payload)

    monkeypatch.setattr(NovelTypeLibrary, "_write", slow_write)
    start = threading.Barrier(2)

    def create(type_id):
        start.wait()
        NovelTypeLibrary().create({"id": type_id, "name": type_id})

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(create, type_id) for type_id in ("sports", "history")]
        for future in futures:
            future.result()

    assert {"sports", "history"}.issubset(
        {record.id for record in NovelTypeLibrary().list()}
    )


def test_corrupt_main_file_recovers_from_valid_backup():
    library = NovelTypeLibrary()
    backup_path = library.path.with_name(f"{library.path.name}.bak")
    library.path.parent.mkdir(parents=True, exist_ok=True)
    backup_path.write_text(
        json.dumps(
            {"overrides": {}, "custom": {"sports": {"id": "sports", "name": "竞技体育"}}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    library.path.write_text("{broken", encoding="utf-8")

    recovered = library.get("sports")

    assert recovered is not None
    assert recovered.name == "竞技体育"


def test_corrupt_main_without_backup_still_selects_builtin():
    library = NovelTypeLibrary()
    library.path.parent.mkdir(parents=True, exist_ok=True)
    library.path.write_text("{broken", encoding="utf-8")
    project = NovelProject(
        project_id="p-corrupt-library",
        title="凡人修仙",
        seed_outline="主角进入宗门修炼灵根，争夺境界突破资源。",
    )

    selected = select_genre_plugins(project)

    assert [plugin.plugin_id for plugin in selected] == [
        "generic_webnovel",
        "eastern_fantasy",
        "xianxia",
    ]


def test_writes_maintain_a_valid_backup():
    library = NovelTypeLibrary()
    library.create({"id": "sports", "name": "竞技体育"})
    backup_path = library.path.with_name(f"{library.path.name}.bak")

    stored = json.loads(backup_path.read_text(encoding="utf-8"))

    assert stored["custom"]["sports"]["name"] == "竞技体育"


def test_backup_write_failure_does_not_commit_main_file(monkeypatch):
    library = NovelTypeLibrary()
    library.create({"id": "sports", "name": "竞技体育"})
    original_main = library.path.read_text(encoding="utf-8")
    original_atomic_write = NovelTypeLibrary._atomic_write

    def fail_backup(path, payload):
        if path.name.endswith(".bak"):
            raise OSError("injected backup failure")
        original_atomic_write(path, payload)

    monkeypatch.setattr(NovelTypeLibrary, "_atomic_write", staticmethod(fail_backup))

    with pytest.raises(OSError, match="injected backup failure"):
        NovelTypeLibrary().create({"id": "history", "name": "历史架空"})

    assert library.path.read_text(encoding="utf-8") == original_main
    assert NovelTypeLibrary().get("history") is None
    assert NovelTypeLibrary().get("sports") is not None


def test_custom_id_rejects_builtin_case_and_alias_collisions():
    library = NovelTypeLibrary()

    for colliding_id in ("XUANHUAN", "东方玄幻"):
        with pytest.raises(ValueError, match="already exists"):
            library.create({"id": colliding_id, "name": "重复玄幻类型"})

    project = NovelProject(
        project_id="p-canonical-xuanhuan",
        title="东方幻想",
        seed_outline="主角发现一件古老遗物。",
        world_blueprint={"genre_plugin_ids": ["XUANHUAN"]},
    )
    selected_ids = [plugin.plugin_id for plugin in select_genre_plugins(project)]

    assert selected_ids == ["generic_webnovel", "eastern_fantasy", "xuanhuan"]
    assert selected_ids.count("xuanhuan") == 1


def test_genre_selection_loads_one_consistent_library_snapshot(monkeypatch):
    calls = 0
    original_stored_data = NovelTypeLibrary._stored_data

    def counted_stored_data(self):
        nonlocal calls
        calls += 1
        return original_stored_data(self)

    monkeypatch.setattr(NovelTypeLibrary, "_stored_data", counted_stored_data)
    project = NovelProject(
        project_id="p-one-snapshot",
        title="凡人修仙",
        seed_outline="主角进入宗门修炼灵根，争夺境界突破资源。",
    )

    select_genre_plugins(project)

    assert calls == 1


def test_returned_records_are_mutable_isolated_copies():
    library = NovelTypeLibrary()
    first = library.get("xuanhuan")
    assert first is not None

    first.name = "仅本地修改"
    first.rulebook["chapter_formula"] = ("仅本地规则",)
    second = library.get("xuanhuan")

    assert second is not None
    assert second.name == "东方玄幻"
    assert second.rulebook["chapter_formula"] != ("仅本地规则",)
