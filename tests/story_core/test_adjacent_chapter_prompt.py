from packages.story_core.models import ChapterSummary, StoryState
from packages.story_core.genre_stages.common_writer import _writer_continuity_lines
from packages.story_core.orchestrator import (
    _director_plan_quality_issues,
    _director_prompt_outline_context,
    _review_chapter_body,
)
from packages.story_core.simplified_review import build_simplified_review


def _story_with_interface() -> StoryState:
    return StoryState(
        story_id="story-test",
        outline="测试大纲",
        genre="玄幻",
        style="",
        current_chapter=143,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=143,
                summary="这是误存的上一章开头。",
                facts=["沈墨璃离开神殿，前往沈家与联盟传递消息。"],
                unresolved_threads=["天机阁六个光点正在合围。"],
            )
        ],
        outline_context={
            "continuity_interface": {
                "previous_chapter_number": 143,
                "previous_tail": "沈墨璃踏入西侧密道，身影消失，殿门重新合拢。",
                "previous_facts": ["沈墨璃离开神殿，前往沈家与联盟传递消息。"],
                "previous_threads": ["天机阁六个光点正在合围。"],
                "next_chapter_number": 145,
                "next_opening": "第145章旧稿仍写沈墨璃在神殿。",
                "fact_priority": ["已发生剧情", "本章计划", "静态人物设定", "后续旧稿"],
            }
        },
    )


def test_writer_fact_section_renders_adjacent_interface_before_summary_recap():
    prompt = "\n".join(_writer_continuity_lines(_story_with_interface()))

    assert "相邻章节接口" in prompt
    assert "沈墨璃踏入西侧密道" in prompt
    assert "沈墨璃离开神殿" in prompt
    assert "后续旧稿不能覆盖已发生剧情" in prompt
    assert "上一章留下：这是误存的上一章开头" not in prompt
    assert "这是误存的上一章开头" not in prompt


def test_director_prompt_keeps_compact_continuity_interface():
    rendered = _director_prompt_outline_context(_story_with_interface().outline_context)

    assert rendered["continuity_interface"]["previous_chapter_number"] == 143
    assert "沈墨璃离开神殿" in rendered["continuity_interface"]["previous_facts"][0]
    assert rendered["continuity_interface"]["next_chapter_number"] == 145


def test_director_rejects_departed_character_without_return_action():
    story = _story_with_interface()
    plan = {
        "character_moves": [
            {"name": "林修", "goal": "检查地脉", "action": "林修拆开阵心石。"},
            {"name": "沈墨璃", "goal": "协助检查", "action": "沈墨璃落在林修身侧查看阵纹。"},
        ],
        "event_plan": {
            "chapter_satisfaction": {
                "core_event": "检查地脉",
                "obstacle": "寒毒上行",
                "visible_payoff": "找出堵点",
                "cost": "本命剑受损",
                "state_change": "锁定异常回路",
                "next_hook": "玄渊现身",
            },
            "chapter_end_hook": {"content": "玄渊在殿外开口。"},
        },
    }

    issues = _director_plan_quality_issues(story, plan)

    assert any("沈墨璃" in issue and "离场" in issue for issue in issues)


def test_director_allows_departed_character_with_explicit_return_action():
    story = _story_with_interface()
    plan = {
        "character_moves": [
            {
                "name": "沈墨璃",
                "goal": "带医修返回",
                "action": "沈墨璃从沈家赶回雪山，穿过密道后进入神殿。",
            }
        ],
        "event_plan": {
            "chapter_satisfaction": {
                "core_event": "医修抵达",
                "obstacle": "密道受阻",
                "visible_payoff": "寒毒得到控制",
                "cost": "耗尽传送符",
                "state_change": "沈墨璃返回神殿",
                "next_hook": "医修认出寒毒来源",
            },
            "chapter_end_hook": {"content": "医修认出寒毒来源。"},
        },
    }

    issues = _director_plan_quality_issues(story, plan)

    assert not any("沈墨璃" in issue and "离场" in issue for issue in issues)


def test_writing_review_blocks_interface_conflict_and_chinese_fragment():
    body = (
        "沈墨璃落在林修身侧。她的意思实打实。"
        + "林修继续检查地脉回路，小乐在一旁记录阵纹变化。" * 220
    )
    interface = {
        "previous_facts": ["沈墨璃离开神殿，前往沈家。"],
        "next_chapter_number": 145,
        "next_opening": "沈墨璃一步挡在小乐与残镜之间。",
    }

    review = _review_chapter_body(
        144,
        body,
        {},
        [],
        simulation_plan={"continuity_interface": interface},
    )
    simplified = build_simplified_review({"writing_review": review})

    assert any("无过程返场" in issue for issue in review["issues"])
    assert any("中文残句" in issue for issue in review["issues"])
    assert review["downstream_rewrite_required"] is True
    assert review["downstream_chapter_number"] == 145
    assert simplified["has_hard_errors"] is True
