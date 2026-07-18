from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import _apply_ledger_updates, _extract_equipment_ledger_updates, _sync_character_game_panels


def test_protagonist_game_panel_syncs_from_progression_ledger():
    story = StoryState(
        story_id="s-panel",
        outline="网游开服，夜烬低调发育。",
        genre="网游",
        style="升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["安全升到10级"],
            )
        ],
    )

    _apply_ledger_updates(
        story,
        {
            "protagonist": {"level": 1, "exp": "65/100", "class_path": "元素法师学徒"},
            "economy": {"currency": "0金币10银币35铜币", "inventory": {"灰狼毒腺": 0}},
            "equipment": {"weapon": "粗糙的木法杖（耐久98%）", "armor": "粗布衣（耐久95%）"},
            "skills": ["火苗术（Lv.1）"],
            "quests": {"元素回廊前置": "毒腺样本5/5，线索1/3"},
            "pressure": {"market_anomaly": 1, "guild_attention": 0},
        },
    )
    _sync_character_game_panels(story, 1)

    panel = story.characters[0].game_panel
    assert panel.game_id == "夜烬"
    assert panel.level == 1
    assert panel.class_path == "元素法师学徒"
    assert panel.exp == "65/100"
    assert panel.currency == "0金币10银币35铜币"
    assert panel.inventory == {"灰狼毒腺": 0}
    assert panel.equipment["weapon"] == "粗糙的木法杖（耐久98%）"
    assert panel.skills == ["火苗术（Lv.1）"]
    assert panel.quests["元素回廊前置"] == "毒腺样本5/5，线索1/3"
    assert panel.risk["market_anomaly"] == 1
    assert panel.updated_chapter == 1
    assert story.characters[0].memory[0].startswith("角色面板：ID 夜烬 / Lv.1")


def test_protagonist_game_panel_replaces_question_mark_identity_placeholder():
    story = StoryState(
        story_id="s-panel-placeholder",
        outline="web game opening",
        genre="web game",
        style="plain",
        characters=[
            CharacterState(
                name="苏叶",
                role="protagonist",
                game_id="??",
            )
        ],
        progression_ledger={
            "protagonist": {"game_id": "??", "level": 1, "class_path": "元素法师学徒", "exp": "0/100"},
            "economy": {"currency": "0金币0银币0铜币"},
        },
    )

    _sync_character_game_panels(story, 1)

    panel = story.characters[0].game_panel
    assert panel.game_id == "夜烬"
    assert story.characters[0].game_id == "夜烬"
    assert "ID ??" not in story.characters[0].memory[0]
    assert story.characters[0].memory[0].startswith("角色面板：ID 夜烬 / Lv.1")


def test_protagonist_game_panel_normalizes_real_name_identity_and_defaults_attributes():
    story = StoryState(
        story_id="s-panel-real-name",
        outline="网游开服，夜烬低调发育。",
        genre="网游",
        style="升级流",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="苏叶",
                goals=["安全升到10级"],
            )
        ],
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "元素法师学徒", "exp": "15/100"},
            "economy": {"currency": "0金币0银币0铜币"},
            "equipment": {"weapon": "补给门槛：粗布衣/木法杖基础修理费2铜币/次。耐久低于30%强制降级。"},
            "skills": {"active": ["元素回廊试炼"]},
            "quests": {"active": ["元素回廊前置"]},
        },
    )

    _sync_character_game_panels(story, 1)

    panel = story.characters[0].game_panel
    assert panel.game_id == "夜烬"
    assert story.characters[0].game_id == "夜烬"
    assert panel.hp == "92/100"
    assert panel.mp == "61/80"
    assert panel.attributes == {"力量": 3, "敏捷": 4, "智力": 9, "体质": 5}
    assert panel.equipment["主武器"] == "新手法杖"
    assert panel.equipment["护甲"] == "粗布衣"
    assert panel.inventory == {"灰鼠毒腺": "18份", "灰鼠皮": "3张"}


def test_ledger_extraction_deducts_submitted_material_from_panel_inventory():
    body = """
【背包：灰狼毒腺×5】
洛婶接过苏叶递过去的五份毒腺，完成任务登记。
【当前状态结算】
【任务：元素回廊前置（已提交5/5，进度锁定）】
"""

    updates = _extract_equipment_ledger_updates(body)

    assert updates["economy"]["inventory"] == {"灰狼毒腺": 0}


def test_game_ledger_updates_game_state_without_changing_real_state():
    story = StoryState(
        story_id="s-isolated-ledger",
        outline="网游开服。",
        genre="网游",
        style="白描",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                real_state={
                    "current": {"balance": "27.60元"},
                    "recent_changes": [],
                },
                game_state={
                    "current": {"currency": "0铜币"},
                    "recent_changes": [],
                },
            )
        ],
    )

    _apply_ledger_updates(
        story,
        {
            "protagonist": {"level": "Lv.2", "exp": "20/200", "hp": "80/100", "mp": "40/60"},
            "economy": {"game_currency": "30铜币", "inventory": {"灰狼毒腺": 3}},
            "equipment": {"weapon": "新手法杖", "durability": "90/100"},
            "quests": {"清道夫委托": "已提交"},
        },
    )

    character = story.characters[0]
    assert character.real_state == {"current": {"balance": "27.60元"}, "recent_changes": []}
    assert character.game_state["current"]["level"] == "Lv.2"
    assert character.game_state["current"]["currency"] == "30铜币"
    assert character.game_state["current"]["inventory"] == {"灰狼毒腺": 3}
    assert character.game_panel.level == "Lv.2"
    assert character.game_panel.currency == "30铜币"


def test_game_ledger_sync_records_changed_fields_once_with_chapter_fact():
    story = StoryState(
        story_id="s-game-history",
        current_chapter=7,
        outline="网游开服。",
        genre="网游",
        style="白描",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )

    _apply_ledger_updates(story, {"protagonist": {"level": "Lv.2", "exp": "20/200"}})
    _sync_character_game_panels(story, 7)
    character = story.characters[0]
    changes = character.game_state["recent_changes"]

    assert changes
    assert changes[-1]["chapter"] == 7
    assert "level" in changes[-1]["fact"] or "等级" in changes[-1]["fact"]
    count = len(changes)
    _sync_character_game_panels(story, 7)
    assert len(character.game_state["recent_changes"]) == count


def test_game_state_current_wins_over_legacy_panel_and_ledger():
    story = StoryState(
        story_id="s-game-authority",
        outline="网游开服。",
        genre="网游",
        style="白描",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                game_state={"current": {"level": "Lv.9", "currency": "99铜币"}},
            )
        ],
        progression_ledger={
            "protagonist": {"level": "Lv.2"},
            "economy": {"game_currency": "20铜币"},
        },
    )
    story.characters[0].game_panel.level = 1
    story.characters[0].game_panel.currency = "1铜币"

    _sync_character_game_panels(story, 8)

    character = story.characters[0]
    assert character.game_state["current"]["level"] == "Lv.9"
    assert character.game_state["current"]["currency"] == "99铜币"
    assert character.game_panel.level == "Lv.9"
    assert character.game_panel.currency == "99铜币"


def test_flat_legacy_ledger_fills_missing_game_state_fields_without_overwriting_current():
    story = StoryState(
        story_id="s-flat-ledger",
        outline="网游开服。",
        genre="网游",
        style="白描",
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_state={"current": {"level": "Lv.9"}},
            )
        ],
        progression_ledger={
            "level": "Lv.2",
            "class_path": "元素法师",
            "exp": "20/200",
            "currency": "20铜币",
            "quests": ["后坡巡查"],
        },
    )

    _sync_character_game_panels(story, 10)

    character = story.characters[0]
    current = character.game_state["current"]
    assert current["level"] == "Lv.9"
    assert current["class_path"] == "元素法师"
    assert current["currency"] == "20铜币"
    assert current["quests"] == ["后坡巡查"]
    assert character.game_panel.quests == {"active": ["后坡巡查"]}


def test_list_quests_are_preserved_in_current_and_wrapped_for_legacy_panel():
    story = StoryState(
        story_id="s-list-quests",
        outline="网游开服。",
        genre="网游",
        style="白描",
        characters=[CharacterState(name="苏叶", role="主角")],
        progression_ledger={"quests": ["清道夫委托", "后坡巡查"]},
    )

    _sync_character_game_panels(story, 11)

    character = story.characters[0]
    assert character.game_state["current"]["quests"] == ["清道夫委托", "后坡巡查"]
    assert character.game_panel.quests == {"active": ["清道夫委托", "后坡巡查"]}
