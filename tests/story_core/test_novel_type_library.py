from dataclasses import replace
import json

import pytest

from packages.story_core.novel_type_library import (
    NovelTypeLibrary,
    NovelTypeRecord,
    resolve_genre_plugin,
    update_novel_type,
)
from packages.story_core.genre_plugins import select_genre_plugins
from packages.story_core.models import NovelProject


@pytest.fixture(autouse=True)
def isolated_novel_type_path(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_NOVEL_TYPES_PATH", str(tmp_path / "novel_types.json"))


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


def test_record_rejects_blank_id_and_name_and_normalizes_rulebook():
    with pytest.raises(ValueError, match="ID"):
        NovelTypeRecord(id=" ", name="有效名称")
    with pytest.raises(ValueError, match="name"):
        NovelTypeRecord(id="valid", name=" ")

    record = NovelTypeRecord(id="valid", name="有效名称", rulebook={"chapter_formula": ["推进冲突"]})

    assert record.rulebook["chapter_formula"] == ("推进冲突",)
    assert record.rulebook["economy_rules"] == ()


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
