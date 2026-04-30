from packages.story_core.memory import build_arc_recap, maybe_update_arc_recap
from packages.story_core.models import ChapterSummary, MemoryIndexEntry, StoryState
from packages.story_core.orchestrator import _story_snapshot


def make_summary(chapter: int) -> ChapterSummary:
    return ChapterSummary(
        chapter_number=chapter,
        chapter_title=f"第{chapter}章",
        summary=f"苏叶在第{chapter}章继续围绕灰烬村、交易行和白袍公会压力推进。",
        facts=[f"第{chapter}章确认交易行异常继续积累。"],
        unresolved_threads=[f"第{chapter}章后白袍公会是否继续追查？"],
        next_focus="继续推进元素回廊前置。",
    )


def test_build_arc_recap_compresses_ten_chapters():
    story = StoryState(
        story_id="s-arc-recap",
        outline="网游开服，苏叶低调发育。",
        genre="网游",
        style="升级流",
        chapter_summaries=[make_summary(i) for i in range(1, 11)],
        memory_index=[
            MemoryIndexEntry(
                chapter_number=i,
                chapter_title=f"第{i}章",
                summary=f"苏叶在交易行与白袍公会压力中推进第{i}章。",
                tags=["交易行", "公会"],
                characters=["苏叶"],
                factions=["白袍公会"],
                locations=["灰烬村"],
            )
            for i in range(1, 11)
        ],
        progression_ledger={
            "protagonist": {"level": 5, "exp": "120/500", "class_path": "法师学徒"},
            "economy": {"currency": "0金币8银币20铜币", "market_anomaly": 4},
            "pressure": {"guild_attention": 3, "goldfinger_exposure": 2},
        },
    )

    recap = build_arc_recap(story, 1, 10)

    assert recap.start_chapter == 1
    assert recap.end_chapter == 10
    assert "灰烬村" in recap.recap
    assert any("交易行" in item for item in recap.key_threads)
    assert any("白袍公会" in item for item in recap.open_threads)
    assert recap.ledger_snapshot["protagonist"]["level"] == 5


def test_maybe_update_arc_recap_runs_on_tenth_chapter_only():
    story = StoryState(
        story_id="s-arc-auto",
        outline="网游开服，苏叶低调发育。",
        genre="网游",
        style="升级流",
        chapter_summaries=[make_summary(i) for i in range(1, 10)],
    )

    maybe_update_arc_recap(story, 9)
    assert story.arc_recaps == []

    story.chapter_summaries.append(make_summary(10))
    maybe_update_arc_recap(story, 10)

    assert len(story.arc_recaps) == 1
    assert story.arc_recaps[0].start_chapter == 1
    assert story.arc_recaps[0].end_chapter == 10


def test_story_snapshot_includes_latest_arc_recap():
    story = StoryState(
        story_id="s-arc-snapshot",
        outline="网游开服，苏叶低调发育。",
        genre="网游",
        style="升级流",
        chapter_summaries=[make_summary(i) for i in range(1, 11)],
    )
    maybe_update_arc_recap(story, 10)

    snapshot = _story_snapshot(story)

    assert snapshot["arc_recaps"]
    assert snapshot["arc_recaps"][0]["range"] == "1-10"
