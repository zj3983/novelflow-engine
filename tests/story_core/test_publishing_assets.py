from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.story_core.publishing_assets import FanqieSynopsis, build_publishing_context


def test_fanqie_synopsis_normalizes_unique_tags_and_preserves_visual_hook() -> None:
    body = "陆沉醒来后发现渡船已驶入归墟，甲板上每个人都在倒数自己的死期。" * 8

    synopsis = FanqieSynopsis(
        tags=[" 穿越 ", "成长", "穿越", "无系统", "克系"],
        body=body,
        pattern="conflict",
        visual_hook="血月下的渡船",
    )

    assert synopsis.tags == ["穿越", "成长", "无系统", "克系"]
    assert 200 <= len(synopsis.body) <= 450
    assert synopsis.visual_hook == "血月下的渡船"


@pytest.mark.parametrize(
    ("kwargs", "error_field"),
    [
        ({"tags": ["一", "二", "三"]}, "tags"),
        ({"tags": [str(index) for index in range(9)]}, "tags"),
        ({"body": "太短"}, "body"),
        ({"body": "长" * 451}, "body"),
        ({"pattern": "other"}, "pattern"),
    ],
)
def test_fanqie_synopsis_rejects_invalid_platform_constraints(
    kwargs: dict[str, object], error_field: str
) -> None:
    valid = {
        "tags": ["穿越", "成长", "无系统", "克系"],
        "body": "陆沉醒来后发现渡船已驶入归墟，甲板上每个人都在倒数自己的死期。" * 8,
        "pattern": "contrast",
    }

    with pytest.raises(ValidationError) as exc_info:
        FanqieSynopsis(**(valid | kwargs))

    assert error_field in str(exc_info.value)


def test_publishing_context_keeps_only_bounded_metadata() -> None:
    chapter_body = "不应进入提示词" * 2_000
    context = build_publishing_context(
        project={
            "title": "归墟行舟",
            "world_summary": "归墟吞没所有失约者。",
            "character_profiles": [
                {"name": "陆沉", "role": "protagonist", "goal": "带妹妹活着靠岸", "secret": {"body": chapter_body}},
                {"name": "阿七", "role": "船医", "motivation": "寻找失踪的姐姐"},
            ],
        },
        state={
            "genre": "玄幻",
            "outline": "寻找靠岸的方法",
            "history": [{"body": chapter_body}],
            "chapters": [{"body": chapter_body}],
        },
        opening_brief={"idea": "亡魂渡船"},
        outline={
            "overall": {"main_conflict": "活着靠岸", "story": "渡船穿越归墟"},
            "arcs": [{"name": "第一卷", "summary": "争夺船票", "chapter_body": chapter_body}],
            "chapters": [{"body": chapter_body}],
        },
    )

    serialized = context.model_dump_json()
    assert context.title == "归墟行舟"
    assert context.novel_type == "玄幻"
    assert context.opening_idea == "亡魂渡船"
    assert context.world_summary == "归墟吞没所有失约者。"
    assert context.protagonists == [
        {"name": "陆沉", "role": "protagonist", "goal": "带妹妹活着靠岸"},
        {"name": "阿七", "role": "船医", "goal": "寻找失踪的姐姐"},
    ]
    assert context.outline_summary["overall"]["main_conflict"] == "活着靠岸"
    assert "不应进入提示词" not in serialized
    assert len(serialized) < 12_000


def test_publishing_context_applies_deterministic_caps_to_oversized_inputs() -> None:
    oversized = "x" * 20_000
    context = build_publishing_context(
        project={
            "title": " 标题 " + oversized,
            "world_summary": oversized,
            "character_profiles": [
                {"name": f"角色{index}" + oversized, "role": oversized, "goal": oversized}
                for index in range(12)
            ],
        },
        state={"genre": oversized},
        opening_brief={"idea": oversized},
        outline={
            "overall": {"main_conflict": oversized, "story": oversized},
            "arcs": [{"name": oversized, "summary": oversized} for _ in range(20)],
        },
    )

    serialized = context.model_dump_json()
    assert len(context.title) == 120
    assert len(context.novel_type) == 120
    assert len(context.opening_idea) == 1_000
    assert len(context.world_summary) == 2_000
    assert len(context.protagonists) == 8
    assert all(len(character["name"]) <= 80 for character in context.protagonists)
    assert all(len(character["role"]) <= 80 for character in context.protagonists)
    assert all(len(character["goal"]) <= 240 for character in context.protagonists)
    assert len(context.outline_summary["arcs"]) <= 6
    assert len(serialized) < 12_000


def test_publishing_context_uses_fallback_title() -> None:
    context = build_publishing_context(project={}, state={}, opening_brief={}, outline={})

    assert context.title == "未命名作品"


def test_publishing_context_combines_top_level_and_overall_outline_metadata() -> None:
    context = build_publishing_context(
        project={},
        state={},
        opening_brief={},
        outline={"main_conflict": "冲出归墟", "overall": {"story": "渡船求生"}},
    )

    assert context.outline_summary["overall"] == {"story": "渡船求生", "main_conflict": "冲出归墟"}
