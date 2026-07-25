from apps.api.storage import (
    _project_genre_selection,
    _sync_project_character_profiles,
    _sync_project_generation_context,
)
from packages.story_core.models import NovelProject, StoryState
from packages.story_core.memory import _is_game_story_for_cards


def test_project_genre_selection_distinguishes_missing_unknown_and_known_values():
    missing = NovelProject(project_id="p-missing", title="无类型", world_blueprint={})
    unknown = NovelProject(
        project_id="p-unknown",
        title="未知类型",
        world_blueprint={"genre_plugin_ids": ["future_genre"]},
    )
    known = NovelProject(
        project_id="p-known",
        title="东方玄幻",
        world_blueprint={"genre_plugin_ids": ["东方玄幻", "XUANHUAN"]},
    )

    assert _project_genre_selection(missing) == ([], False)
    assert _project_genre_selection(unknown) == ([], True)
    assert _project_genre_selection(known) == (["xuanhuan"], True)


def test_project_character_sync_preserves_dual_state_history_and_author_fields():
    project = NovelProject(
        project_id="p-dual-state",
        title="网游小说",
        character_profiles=[
            {
                "name": "苏叶",
                "role": "protagonist",
                "real_state": {
                    "current": {
                        "identity": "profile identity",
                        "income": "兼职",
                    },
                    "recent_changes": [{"chapter": 2, "fact": "profile reality fact"}],
                },
                "game_state": {
                    "current": {
                        "level": 3,
                        "class_path": "元素法师",
                        "exp": "120/300",
                        "hp": "80/100",
                        "mp": "40/60",
                        "attributes": {"智力": 12},
                        "skills": ["火球术"],
                        "equipment": {"武器": "新手法杖"},
                        "inventory": {"灰狼毒腺": 8},
                        "currency": "30铜币",
                        "quests": {"主线": "调查灰狼坡"},
                        "risk": {"失败代价": "掉经验"},
                    },
                    "recent_changes": [{"chapter": 3, "fact": "profile game fact"}],
                },
                "game_panel": {"game_id": "夜烬", "level": 1, "legacy_extension": "keep"},
            }
        ],
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    from packages.story_core.models import CharacterState, GamePanel

    character = CharacterState(
        name="苏叶",
        role="protagonist",
        real_state={"current": {"identity": "author confirmed"}},
        game_panel=GamePanel(game_id="夜烬", level=1),
    )
    story = StoryState(
        story_id="s-dual-state",
        outline="夜烬开服。",
        genre="game_webnovel",
        style="白描、现代中文",
        characters=[character],
    )

    _sync_project_character_profiles(story, project)

    synced = story.characters[0]
    assert synced.real_state == {
        "current": {"identity": "author confirmed", "income": "兼职"},
        "recent_changes": [{"chapter": 2, "fact": "profile reality fact"}],
    }
    assert synced.game_state["recent_changes"] == [
        {"chapter": 3, "fact": "profile game fact"}
    ]
    game_current = synced.game_state["current"]
    game_panel = synced.game_panel.model_dump()
    for field in (
        "game_id",
        "level",
        "class_path",
        "exp",
        "hp",
        "mp",
        "attributes",
        "skills",
        "equipment",
        "inventory",
        "currency",
        "quests",
        "risk",
    ):
        assert game_panel[field] == game_current[field]


def test_non_game_project_sync_does_not_materialize_legacy_game_panel_as_game_state():
    project = NovelProject(
        project_id="p-real-only",
        title="现实小说",
        character_profiles=[
            {
                "name": "林照",
                "role": "protagonist",
                "game_panel": {"game_id": "不应出现", "level": 9},
            }
        ],
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )
    story = StoryState(
        story_id="s-real-only",
        outline="林照守着祖祠。",
        genre="xianxia",
        style="白描、现代中文",
    )

    _sync_project_character_profiles(story, project)

    synced = story.characters[0]
    assert synced.game_state == {}
    assert synced.game_panel.game_id == ""


def test_game_project_sync_writes_legacy_profile_panel_back_to_runtime_character():
    from packages.story_core.models import GamePanel

    project = NovelProject(
        project_id="p-game-panel-compat",
        title="网游小说",
        character_profiles=[
            {
                "name": "苏叶",
                "role": "protagonist",
                "game_panel": {"game_id": "夜烬", "level": 7},
            }
        ],
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )
    story = StoryState(
        story_id="s-game-panel-compat",
        outline="夜烬开服。",
        genre="game_webnovel",
        style="白描、现代中文",
    )

    _sync_project_character_profiles(story, project)

    synced = story.characters[0]
    assert isinstance(synced.game_panel, GamePanel)
    assert synced.game_panel.game_id == "夜烬"
    assert synced.game_panel.level == 7
    assert synced.game_state["current"]["game_id"] == "夜烬"
    assert synced.game_state["current"]["level"] == 7


def test_project_context_replaces_placeholder_story_metadata_after_chapter_exists():
    project = NovelProject(
        project_id="p-xianxia",
        title="修仙小说",
        seed_outline="林照在外门看守断香炉。",
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )
    story = StoryState(
        story_id="s-xianxia",
        current_chapter=1,
        outline="????????",
        genre="??",
        style="????????",
    )

    _sync_project_generation_context(story, project, has_history=True)

    assert story.outline == project.seed_outline
    assert story.genre == "xianxia"
    assert story.style == ""


def test_xianxia_negative_game_constraints_do_not_activate_game_character_defaults():
    story = StoryState(
        story_id="s-xianxia-card",
        outline="修仙外门日常，不写游戏面板、玩家和掉落。",
        genre="xianxia",
        style="白描、现代中文",
        world_facts=["小说类型：xianxia"],
    )

    assert _is_game_story_for_cards(story) is False


def test_project_context_does_not_replace_real_story_outline_after_history_exists():
    project = NovelProject(
        project_id="p-xianxia-real",
        title="修仙小说",
        seed_outline="项目总纲",
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )
    story = StoryState(
        story_id="s-xianxia-real",
        current_chapter=1,
        outline="已经写过的章节大纲",
        genre="xianxia",
        style="白描、现代中文",
    )

    _sync_project_generation_context(story, project, has_history=True)

    assert story.outline == "已经写过的章节大纲"


def test_project_context_updates_explicit_genre_without_replacing_real_writing_context():
    project = NovelProject(
        project_id="p-xuanhuan-migrated",
        title="玄幻小说",
        seed_outline="项目新总纲",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    story = StoryState(
        story_id="s-xuanhuan-migrated",
        current_chapter=3,
        outline="已经写过的真实大纲",
        genre="xianxia",
        style="克制白描，人物说话自然",
    )

    _sync_project_generation_context(story, project, has_history=True)

    assert story.genre == "xuanhuan"
    assert story.outline == "已经写过的真实大纲"
    assert story.style == ""


def test_project_context_replaces_incompatible_ledger_and_non_game_profile_state():
    project = NovelProject(
        project_id="p-xianxia-ledger",
        title="修仙小说",
        character_profiles=[
            {
                "name": "林照",
                "role": "protagonist",
                "motivation": "先把祖祠差事做完",
                "personality": "做事先问清责任",
                "speech_style": "说话完整直接",
            }
        ],
        world_blueprint={
            "genre_plugin_ids": ["xianxia"],
            "progression_ledger": {"cultivation": {"realm": "外门"}, "clues": {"old_brick": "未查"}},
        },
    )
    story = StoryState(
        story_id="s-xianxia-ledger",
        outline="",
        genre="",
        style="",
        progression_ledger={"economy": {}, "market": {}, "systems": {}},
    )
    character = story.characters[0] if story.characters else None
    if character is None:
        from packages.story_core.models import CharacterState

        character = CharacterState(name="林照", role="protagonist", game_id="nightfall")
        character.core_motivation = "先验证爆率，再考虑现实余额"
        character.social_profile = {"class_pressure": "现实余额和房租"}
        story.characters.append(character)

    _sync_project_generation_context(story, project, has_history=True)
    _sync_project_character_profiles(story, project)

    assert set(story.progression_ledger) == {"cultivation", "clues"}
    assert story.characters[0].game_id == ""
    assert story.characters[0].core_motivation == "先把祖祠差事做完"
    assert story.characters[0].social_profile == {}


def test_legacy_game_story_without_explicit_project_genre_keeps_game_state():
    from packages.story_core.models import CharacterState, GamePanel

    project = NovelProject(
        project_id="p-legacy-game",
        title="旧网游小说",
        character_profiles=[
            {
                "name": "苏叶",
                "role": "protagonist",
                "personality": "做事谨慎",
            }
        ],
        world_blueprint={},
    )
    panel = GamePanel(
        game_id="夜烬",
        level=3,
        class_path="元素法师",
        inventory={"灰狼毒腺": 8},
    )
    character = CharacterState(
        name="苏叶",
        role="protagonist",
        game_id="夜烬",
        game_panel=panel,
    )
    story = StoryState(
        story_id="s-legacy-game",
        outline="夜烬进入灰狼坡练级。",
        genre="game_webnovel",
        style="白描、现代中文",
        characters=[character],
    )

    _sync_project_generation_context(story, project, has_history=True)
    _sync_project_character_profiles(story, project)

    assert story.genre == "game_webnovel"
    assert story.characters[0].game_id == "夜烬"
    assert story.characters[0].game_panel == panel


def test_unrecognized_explicit_project_genre_does_not_fall_back_or_clear_game_state():
    from packages.story_core.models import CharacterState, GamePanel

    project = NovelProject(
        project_id="p-unknown-explicit-genre",
        title="待迁移小说",
        character_profiles=[{"name": "苏叶", "personality": "遇事先核实"}],
        world_blueprint={"genre_plugin_ids": ["future_genre"]},
    )
    panel = GamePanel(game_id="夜烬", level=4, inventory={"狼皮": 7})
    character = CharacterState(
        name="苏叶",
        role="protagonist",
        game_id="夜烬",
        game_panel=panel,
    )
    story = StoryState(
        story_id="s-unknown-explicit-genre",
        outline="已有故事内容。",
        genre="xianxia",
        style="白描、现代中文",
        characters=[character],
    )

    _sync_project_generation_context(story, project, has_history=True)
    _sync_project_character_profiles(story, project)

    assert story.genre == "xianxia"
    assert story.characters[0].game_id == "夜烬"
    assert story.characters[0].game_panel == panel
    assert story.characters[0].behavior_logic == "遇事先核实"


def test_explicit_non_game_genre_ignores_stale_profile_game_id():
    from packages.story_core.models import CharacterState, GamePanel

    project = NovelProject(
        project_id="p-xuanhuan-stale-profile",
        title="玄幻小说",
        character_profiles=[
            {
                "name": "林照",
                "role": "protagonist",
                "game_id": "残留账号",
                "motivation": "查清祖祠异火的来历",
                "personality": "谨慎但不退缩",
                "speech_style": "说话直接，熟人面前会开玩笑",
            }
        ],
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    character = CharacterState(
        name="林照",
        role="protagonist",
        game_id="旧账号",
        game_panel=GamePanel(game_id="旧账号", level=6, class_path="法师"),
    )
    story = StoryState(
        story_id="s-xuanhuan-stale-profile",
        outline="林照看守祖祠。",
        genre="xuanhuan",
        style="白描、现代中文",
        characters=[character],
    )

    _sync_project_generation_context(story, project, has_history=True)
    _sync_project_character_profiles(story, project)

    assert story.characters[0].game_id == ""
    assert story.characters[0].game_panel == GamePanel()
    assert story.characters[0].core_motivation == "查清祖祠异火的来历"
    assert story.characters[0].behavior_logic == "谨慎但不退缩"
    assert story.characters[0].interaction_mode == "说话直接，熟人面前会开玩笑"


def test_non_game_context_removes_stale_game_writing_state():
    from packages.story_core.models import CharacterState

    project = NovelProject(
        project_id="p-xianxia-clean",
        title="修仙小说",
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )
    character = CharacterState(name="林照", role="protagonist", game_id="夜烬")
    character.goals = ["去交易行卖掉落", "查清第三块青砖"]
    character.memory = ["背包里有狼皮", "残香提到青砖"]
    story = StoryState(
        story_id="s-xianxia-clean",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描、现代中文",
        characters=[character],
        writing_lessons=["写清公会能看到什么", "对话要完整自然"],
    )

    _sync_project_generation_context(story, project, has_history=True)

    assert story.writing_lessons == ["对话要完整自然"]
    assert story.characters[0].game_id == ""
    assert story.characters[0].goals == ["查清第三块青砖"]
    assert story.characters[0].memory == ["残香提到青砖"]


def test_xuanhuan_context_reuses_non_game_state_cleanup():
    from packages.story_core.models import CharacterState

    project = NovelProject(
        project_id="p-xuanhuan-clean",
        title="玄幻小说",
        world_blueprint={"genre_plugin_ids": ["xuanhuan"]},
    )
    character = CharacterState(name="林照", role="protagonist", game_id="夜烬")
    character.goals = ["去交易行出售掉落", "查清祖祠青砖的来历"]
    character.memory = ["背包里还有狼皮", "残香提到祖祠青砖"]
    story = StoryState(
        story_id="s-xuanhuan-clean",
        outline="林照看守祖祠。",
        genre="xianxia",
        style="白描、现代中文",
        characters=[character],
        writing_lessons=["交代玩家如何分配掉落", "对话要完整自然"],
    )

    _sync_project_generation_context(story, project, has_history=True)

    assert story.genre == "xuanhuan"
    assert story.writing_lessons == ["对话要完整自然"]
    assert story.characters[0].game_id == ""
    assert story.characters[0].goals == ["查清祖祠青砖的来历"]
    assert story.characters[0].memory == ["残香提到祖祠青砖"]


def test_non_game_context_removes_stale_character_panel_memory():
    from packages.story_core.models import CharacterState

    project = NovelProject(
        project_id="p-xianxia-panel-clean",
        title="修仙小说",
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )
    character = CharacterState(name="林照", role="protagonist")
    character.memory = [
        "角色面板：Lv.Lv.1 / 见习冒险者（未转职） / 经验45/100 / 5铜",
        "林照已经接下祖祠差事",
    ]
    story = StoryState(
        story_id="s-xianxia-panel-clean",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描、现代中文",
        characters=[character],
    )

    _sync_project_generation_context(story, project, has_history=True)

    assert story.characters[0].memory == ["林照已经接下祖祠差事"]
