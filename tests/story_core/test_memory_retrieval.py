from packages.story_core.memory import add_chapter_memory_index, retrieve_relevant_memories
from packages.story_core.models import CharacterState, MemoryIndexEntry, StoryState
from packages.story_core.orchestrator import _story_snapshot


def test_add_chapter_memory_index_extracts_webnovel_tags():
    story = StoryState(
        story_id="s-memory-index",
        outline="网游开服，苏叶低调发育。",
        genre="网游",
        style="升级流",
    )

    add_chapter_memory_index(
        story,
        chapter_number=1,
        chapter_title="蛰伏与首金",
        summary="苏叶在灰烬村通过交易行拆单出售狼皮，白袍公会外围只能看到价格波动。",
        facts=["苏叶激活混沌之种。", "灰烬村村长发布新手任务。"],
        unresolved_threads=["白袍公会会不会继续追查交易行异常？"],
    )

    entry = story.memory_index[0]

    assert entry.chapter_number == 1
    assert "苏叶" in entry.characters
    assert "灰烬村" in entry.locations
    assert "白袍公会" in entry.factions
    assert "交易行" in entry.tags
    assert "狼皮" in entry.items
    assert "白袍公会会不会继续追查交易行异常？" in entry.unresolved_threads


def test_retrieve_relevant_memories_prefers_query_tags_over_recency_only():
    story = StoryState(
        story_id="s-memory-retrieve",
        outline="网游开服，苏叶低调发育。",
        genre="网游",
        style="升级流",
        memory_index=[
            MemoryIndexEntry(
                chapter_number=1,
                chapter_title="首金",
                summary="苏叶在交易行拆单出售狼皮。",
                tags=["交易行", "市场异常"],
                characters=["苏叶"],
                locations=["灰烬村"],
                factions=[],
                items=["狼皮"],
            ),
            MemoryIndexEntry(
                chapter_number=2,
                chapter_title="药剂铺",
                summary="药剂师洛婶要求苏叶提交毒腺。",
                tags=["NPC", "任务链"],
                characters=["苏叶", "药剂师洛婶"],
                locations=["黑水沼泽"],
                factions=[],
                items=["毒腺"],
            ),
            MemoryIndexEntry(
                chapter_number=3,
                chapter_title="论坛暗流",
                summary="白袍公会外围在论坛追查交易行异常。",
                tags=["公会", "交易行"],
                characters=[],
                locations=[],
                factions=["白袍公会"],
                items=[],
            ),
        ],
    )

    memories = retrieve_relevant_memories(story, "白袍公会继续根据交易行时间戳追查狼皮来源", limit=2)

    assert [entry.chapter_number for entry in memories] == [3, 1]


def test_story_snapshot_includes_relevant_memories_not_full_history():
    story = StoryState(
        story_id="s-memory-snapshot",
        outline="网游开服，苏叶低调发育。",
        genre="网游",
        style="升级流",
        memory_index=[
            MemoryIndexEntry(
                chapter_number=index,
                chapter_title=f"第{index}章",
                summary=f"第{index}章普通推进。",
                tags=["日常"],
            )
            for index in range(1, 12)
        ]
        + [
            MemoryIndexEntry(
                chapter_number=12,
                chapter_title="交易暗流",
                summary="白袍公会开始追查交易行异常。",
                tags=["交易行", "公会"],
                factions=["白袍公会"],
            )
        ],
    )

    snapshot = _story_snapshot(story)

    assert len(snapshot["relevant_memories"]) <= 6
    assert any(memory["chapter_number"] == 12 for memory in snapshot["relevant_memories"])
    assert len(snapshot["relevant_memories"]) < len(story.memory_index)


def test_post_chapter_updates_write_memory_index():
    from packages.story_core.memory import apply_post_chapter_updates

    story = StoryState(
        story_id="s-memory-post",
        outline="网游开服，苏叶低调发育。",
        genre="网游",
        style="升级流",
    )

    apply_post_chapter_updates(
        story,
        "苏叶在灰烬村交易行拆单卖出狼皮，白袍公会外围只看见市场异常。",
        1,
        conflict_summary={
            "primary_conflict": {"lead": "苏叶", "opposition": "白袍公会", "collision": "交易行弱线索"},
            "secondary_conflict": {"participants": [{"name": "白袍公会", "goal": "追查狼皮来源"}]},
        },
    )

    assert len(story.memory_index) == 1
    assert story.memory_index[0].chapter_number == 1
    assert "交易行" in story.memory_index[0].tags
    assert "白袍公会" in story.memory_index[0].factions


def test_post_chapter_updates_apply_only_validated_final_memory():
    from packages.story_core.memory import apply_post_chapter_updates

    story = StoryState(
        story_id="s-memory-final-prose",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[
            CharacterState(name="林照", role="主角", current_emotion="平静", location="祖祠"),
            CharacterState(name="周执事", role="配角", current_emotion="冷淡", location="外院"),
        ],
    )
    memory = {
        "summary": "林照把断香炉搬回偏殿，并被要求明早去账房。",
        "facts": ["断香炉已搬回偏殿"],
        "unresolved_threads": ["账房为何找林照"],
        "next_focus": "明早去账房",
        "chapter_title": "搬炉",
        "character_updates": [
                {
                    "name": "林照",
                    "state_line": "reality",
                    "goal": "明早去账房",
                "location": "偏殿",
                "evidence": "林照把断香炉搬回偏殿。周执事叫他明早过去，林照答应明早去账房。",
            }
        ],
        "ledger_updates": {},
        "rejected_updates": [],
    }

    apply_post_chapter_updates(
        story,
        "林照把断香炉搬回偏殿。周执事叫他明早过去，林照答应明早去账房。",
        1,
        post_draft_memory=memory,
        conflict_summary={
            "primary_conflict": {"lead": "林照", "opposition": "周执事", "collision": "断香炉"}
        },
    )

    summary = story.chapter_summaries[-1]
    assert summary.summary == memory["summary"]
    assert summary.facts == memory["facts"]
    assert summary.unresolved_threads == memory["unresolved_threads"]
    assert summary.next_focus == memory["next_focus"]
    assert story.characters[0].location == "偏殿"
    assert story.characters[0].goals[0] == "明早去账房"
    assert story.characters[0].current_emotion == "平静"
    assert story.characters[1].current_emotion == "冷淡"
    assert story.characters[1].location == "外院"
    dumped = story.model_dump_json()
    assert "调查仍在继续推进" not in dumped
    assert "迷局深处" not in dumped
    assert '"alert"' not in dumped
    assert '"wary"' not in dumped
