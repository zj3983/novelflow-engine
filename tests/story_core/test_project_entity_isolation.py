import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.chapter_entity_projection import ChapterEntityProjectionMixin


@pytest.mark.parametrize("implementation", [FileProjectStore, ChapterEntityProjectionMixin])
@pytest.mark.parametrize("body", [
    '一个灰街的老妇人问老秦：“这是干啥的？”',
    '药剂铺里有一位药剂师。',
])
def test_generic_mentions_do_not_invent_npc_cards(tmp_path, implementation, body):
    store = FileProjectStore(tmp_path / "novel")
    cards = implementation._chapter_entity_cards(store, {
        "chapter_number": 64, "body": body,
    })
    assert store._merge_character_cards([], cards) == []


@pytest.mark.parametrize("implementation", [FileProjectStore, ChapterEntityProjectionMixin])
def test_no_global_character_aliases(tmp_path, implementation):
    store = FileProjectStore(tmp_path / "novel")
    assert implementation._canonical_character_name(store, "老妇人") == "老妇人"
    assert implementation._canonical_character_name(store, "铁栓") == "铁栓"


@pytest.mark.parametrize("alias_fields", [
    {"aliases": ["洛婶"]},
    {"identity_profile": {"aliases": ["洛婶"]}},
])
def test_only_current_roster_supplies_aliases(tmp_path, alias_fields):
    store = FileProjectStore(tmp_path / "novel")
    roster = [{"name": "药剂师洛婶", "role": "服务NPC", **alias_fields}]
    cards = store._merge_character_cards(roster, [{"name": "洛婶", "memory": ["本章问路。"]}])
    assert [card["name"] for card in cards] == ["药剂师洛婶"]
    assert cards[0]["memory"] == ["本章问路。"]
    assert store._merge_character_cards([], [{"name": "洛婶"}])[0]["name"] == "洛婶"


def test_ambiguous_alias_does_not_merge_distinct_people(tmp_path):
    store = FileProjectStore(tmp_path / "novel")
    roster = [
        {"name": "张婶", "aliases": ["老妇人"]},
        {"name": "李婶", "aliases": ["老妇人"]},
    ]
    assert store._canonical_character_name("老妇人", roster) == "老妇人"
    assert store._canonical_character_name("李婶", [
        {"name": "张婶", "aliases": ["李婶"]}, {"name": "李婶"},
    ]) == "李婶"
