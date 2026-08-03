from packages.story_core.equipment_cards import (
    equipment_cards_for_context,
    merge_equipment_cards,
    normalize_equipment_card,
)


def test_normalize_equipment_card_preserves_lore_and_builds_stable_id() -> None:
    card = normalize_equipment_card(
        {
            "name": "暮色裁决",
            "equipment_type": "武器",
            "rarity": "史诗",
            "description": "钟声响起时，持剑者已经没有退路。",
            "lore": "传闻由旧王庭最后一位铸剑师打造。",
            "lore_status": "rumor",
            "base_attributes": {"攻击": "+120"},
            "special_effects": ["夜间暴击率提高"],
        },
        chapter_number=8,
    )

    assert card["id"].startswith("equipment-")
    assert card["name"] == "暮色裁决"
    assert card["lore_status"] == "rumor"
    assert card["first_appearance_chapter"] == 8
    assert card["last_update_chapter"] == 8


def test_normalize_equipment_card_rejects_material_currency_and_consumable() -> None:
    assert normalize_equipment_card({"name": "灰狼毒腺", "equipment_type": "材料"}) == {}
    assert normalize_equipment_card({"name": "三十铜币", "equipment_type": "货币"}) == {}
    assert normalize_equipment_card({"name": "小法力药水", "equipment_type": "消耗品"}) == {}
    assert normalize_equipment_card({"equipment_type": "武器"}) == {}


def test_merge_equipment_cards_updates_mutable_state_without_erasing_facts() -> None:
    existing = [{
        "name": "暮色裁决",
        "equipment_type": "武器",
        "rarity": "史诗",
        "current_owner": "夜烬",
        "durability": "80/100",
        "lore": "旧王庭遗物",
        "lore_status": "confirmed",
        "first_appearance_chapter": 8,
        "last_update_chapter": 8,
    }]
    updates = [{
        "name": "暮色裁决",
        "equipment_type": "武器",
        "current_owner": "拍卖行",
        "durability": "",
        "status": "寄售中",
        "last_update_chapter": 12,
    }]

    result = merge_equipment_cards(existing, updates)

    assert len(result.cards) == 1
    assert result.cards[0]["current_owner"] == "拍卖行"
    assert result.cards[0]["durability"] == "80/100"
    assert result.cards[0]["lore"] == "旧王庭遗物"
    assert result.cards[0]["lore_status"] == "confirmed"
    assert result.cards[0]["last_update_chapter"] == 12


def test_merge_equipment_cards_keeps_incompatible_same_name_as_conflict() -> None:
    result = merge_equipment_cards(
        [{"name": "月影", "equipment_type": "武器", "slot": "主手"}],
        [{"name": "月影", "equipment_type": "饰品", "slot": "项链"}],
    )

    assert len(result.cards) == 2
    assert len(result.conflicts) == 1
    assert result.cards[1]["status"] == "待确认：同名装备冲突"
    assert result.cards[0]["id"] != result.cards[1]["id"]


def test_unconfirmed_update_cannot_promote_lore_to_confirmed() -> None:
    result = merge_equipment_cards(
        [{"name": "暮色裁决", "equipment_type": "武器", "lore_status": "unknown"}],
        [{"name": "暮色裁决", "equipment_type": "武器", "lore": "王庭遗物", "lore_status": "confirmed"}],
    )

    assert result.cards[0]["lore"] == "王庭遗物"
    assert result.cards[0]["lore_status"] == "rumor"


def test_equipment_context_prefers_named_and_owned_cards() -> None:
    cards = [
        {"name": "暮色裁决", "equipment_type": "武器", "current_owner": "夜烬"},
        {"name": "冻原守望", "equipment_type": "护甲", "current_owner": "沈墨璃"},
        {"name": "商店铁剑", "equipment_type": "武器", "current_owner": "铁匠铺"},
    ]

    selected = equipment_cards_for_context(cards, names=["冻原守望"], owners=["夜烬"], limit=2)

    assert [card["name"] for card in selected] == ["冻原守望", "暮色裁决"]
