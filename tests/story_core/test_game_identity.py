from apps.api.storage import _sync_project_character_profiles
from packages.story_core.memory import add_chapter_memory_index
from packages.story_core.models import CharacterState, NovelProject, StoryState
from packages.story_core.orchestrator import _review_chapter_body, _story_snapshot
from packages.story_core.world_enrichment import _merge_enrichment


def test_game_character_profiles_include_game_ids():
    """网游项目只保留项目自定义角色；题材模板不再注入旧书的固定人物。"""

    project = NovelProject(
        project_id="p-game-ids",
        title="雾海漫游",
        seed_outline="周行驾驶纸舟探索不断变化的雾海。",
        character_profiles=[
            {"name": "周行", "game_id": "行舟", "role": "主角"},
        ],
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    profiles = {profile["name"]: profile for profile in enriched.character_profiles}

    assert "苏叶" not in profiles
    assert "夜烬" not in {str(profile.get("game_id") or "") for profile in profiles.values()}
    assert profiles["周行"]["game_id"] == "行舟"
    assert any("游戏ID" in item for item in enriched.author_constraints)
    assert len(enriched.author_constraints) <= 8


def test_sync_project_profiles_copies_game_id_to_character_state():
    project = NovelProject(
        project_id="p-game-id-sync",
        title="苟在网游里成神",
        character_profiles=[
            {
                "name": "苏叶",
                "game_id": "夜烬",
                "role": "主角",
                "goals": ["隐藏游戏ID和现实身份的关联"],
            }
        ],
    )
    story = StoryState(
        story_id="s-game-id-sync",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
        characters=[CharacterState(name="苏叶", role="protagonist")],
    )

    _sync_project_character_profiles(story, project)

    assert story.characters[0].game_id == "夜烬"
    assert any("游戏ID：夜烬" in item for item in story.characters[0].memory)


def test_story_snapshot_exposes_game_id():
    story = StoryState(
        story_id="s-game-id-snapshot",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
    )

    snapshot = _story_snapshot(story)

    assert snapshot["characters"][0]["game_id"] == "夜烬"


def test_memory_index_extracts_game_id_alias():
    story = StoryState(
        story_id="s-game-id-memory",
        outline="网游开服，主角低调发育。",
        genre="网游",
        style="升级流",
    )

    add_chapter_memory_index(
        story,
        chapter_number=1,
        chapter_title="夜烬登录",
        summary="游戏ID夜烬在灰烬村交易行拆单出售狼皮。",
    )

    assert "夜烬" in story.memory_index[0].characters


def test_opening_review_requires_game_id_identity_layer():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 45

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
        genre_context={"genre_plugin_ids": ["game_webnovel"]},
    )

    assert review["pass"] is False
    assert any("游戏ID" in issue for issue in review["issues"])
