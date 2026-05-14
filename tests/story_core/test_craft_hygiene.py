from packages.story_core.craft import build_craft_pack, enrich_scene_cards_with_craft
from packages.story_core.models import ChapterSummary, StoryState


def test_general_craft_pack_has_no_demo_game_motifs_or_terms():
    story = StoryState(
        story_id="s-general-craft",
        outline="悬疑小说，主角调查旧楼失踪案。",
        genre="悬疑",
        style="冷峻",
    )

    pack = build_craft_pack(story, 1)
    text = str(pack)

    assert pack["genre_mode"] == "general"
    assert "催租单" not in text
    assert "头盔散热口" not in text
    assert "混沌之种" not in text
    assert "交易木牌" not in text
    assert "第一笔账还没赚到" not in text
    assert "打开面板" not in pack["transition_crutch_limits"]


def test_game_craft_pack_is_generic_not_demo_specific():
    story = StoryState(
        story_id="s-game-craft",
        outline="网游开服，主角选择盗贼路线低调验证异常收益。",
        genre="网游",
        style="升级流",
    )

    pack = build_craft_pack(story, 1)
    text = str(pack)

    assert pack["genre_mode"] == "game"
    assert "混沌之种" not in text
    assert "催租单" not in text
    assert "头盔散热口" not in text
    assert "第一笔账还没赚到" not in text
    assert "打开面板" in pack["transition_crutch_limits"]


def test_single_weak_game_word_does_not_trigger_game_craft_pack():
    story = StoryState(
        story_id="s-workplace-not-game",
        outline="女主接到一项职业任务，调查公司内部失踪邮件。",
        genre="职场悬疑",
        style="冷峻",
    )

    pack = build_craft_pack(story, 1)

    assert pack["genre_mode"] == "general"
    assert "打开面板" not in pack["transition_crutch_limits"]


def test_watch_phrases_are_augmented_from_story_repetition():
    story = StoryState(
        story_id="s-watch-phrases",
        outline="都市故事。",
        genre="都市",
        style="克制",
        chapter_summaries=[
            ChapterSummary(chapter_number=1, summary="她把钥匙放回瓷盘。她把钥匙放回瓷盘。", facts=[]),
        ],
    )

    pack = build_craft_pack(story, 2)

    assert "她把钥匙放回瓷盘" in pack["repetition_control"]["watch_phrases"]
    assert "第一笔账还没赚到，成本已经先到了" not in pack["repetition_control"]["watch_phrases"]


def test_enrich_scene_cards_adds_dialogue_shift_only_when_scene_has_interaction():
    craft = build_craft_pack(
        StoryState(story_id="s-enrich", outline="悬疑。", genre="悬疑", style="冷峻"),
        1,
    )
    cards = [
        {"scene_id": "a", "purpose": "穿过走廊，找到旧门牌"},
        {"scene_id": "b", "purpose": "和保安对话，试探证词"},
    ]

    enriched = enrich_scene_cards_with_craft(cards, craft)

    assert "dialogue_power_shift" not in enriched[0]
    assert "dialogue_power_shift" in enriched[1]
