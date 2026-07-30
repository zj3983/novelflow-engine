from __future__ import annotations

import pytest
from pydantic import ValidationError

from packages.story_core.publishing_assets import (
    MAX_SYNOPSIS_TAG_CHARS,
    MAX_VISUAL_HOOK_CHARS,
    FanqieSynopsis,
    PublishingContext,
    build_publishing_context,
)


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


def test_fanqie_synopsis_strips_body_before_validating_and_storing() -> None:
    body = "陆沉醒来后发现渡船已驶入归墟，甲板上每个人都在倒数自己的死期。" * 8

    synopsis = FanqieSynopsis(
        tags=["穿越", "成长", "无系统", "克系"],
        body=f"  \n{body}\t ",
        pattern="micro_scene",
    )

    assert synopsis.body == body


@pytest.mark.parametrize("body_length", [200, 450])
def test_fanqie_synopsis_accepts_exact_body_and_tag_boundaries(body_length: int) -> None:
    synopsis = FanqieSynopsis(
        tags=[f"标签{index}" for index in range(8)],
        body="文" * body_length,
        pattern="contrast",
    )

    assert len(synopsis.tags) == 8
    assert len(synopsis.body) == body_length


def test_fanqie_synopsis_strips_and_bounds_tags_and_visual_hook() -> None:
    synopsis = FanqieSynopsis(
        tags=[f" {index}{'标' * (MAX_SYNOPSIS_TAG_CHARS - 1)} " for index in range(4)],
        body="文" * 200,
        pattern="conflict",
        visual_hook=f" {'钩' * MAX_VISUAL_HOOK_CHARS} ",
    )

    assert all(len(tag) == MAX_SYNOPSIS_TAG_CHARS for tag in synopsis.tags)
    assert synopsis.visual_hook == "钩" * MAX_VISUAL_HOOK_CHARS
    with pytest.raises(ValidationError):
        FanqieSynopsis(
            tags=["超" * (MAX_SYNOPSIS_TAG_CHARS + 1), "二", "三", "四"],
            body="文" * 200,
            pattern="conflict",
        )
    with pytest.raises(ValidationError):
        FanqieSynopsis(
            tags=["一", "二", "三", "四"],
            body="文" * 200,
            pattern="conflict",
            visual_hook="钩" * (MAX_VISUAL_HOOK_CHARS + 1),
        )


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


def test_publishing_context_enforces_json_serialization_budget_after_escaping() -> None:
    escaped_text = "\\\x00" * 20_000
    context = build_publishing_context(
        project={
            "title": "归墟行舟" + escaped_text,
            "world_summary": "归墟吞没失约者。" + escaped_text,
            "character_profiles": [
                {
                    "name": f"角色{index}" + escaped_text,
                    "role": "同行者" + escaped_text,
                    "goal": "活着靠岸" + escaped_text,
                }
                for index in range(8)
            ],
        },
        state={"genre": "玄幻" + escaped_text},
        opening_brief={"idea": "亡魂渡船" + escaped_text},
        outline={
            "overall": {"main_conflict": "活着靠岸" + escaped_text},
            "arcs": [
                {
                    "name": "第一卷" + escaped_text,
                    "summary": "争夺船票" + escaped_text,
                    "main_conflict": "渡船封闭" + escaped_text,
                }
                for _ in range(5)
            ],
        },
    )

    assert context.title.startswith("归墟行舟")
    assert context.outline_summary["overall"]["main_conflict"].startswith("活着靠岸")
    assert len(context.model_dump_json()) < 12_000


def test_direct_context_rejects_unallowlisted_or_oversized_nested_content() -> None:
    with pytest.raises(ValidationError):
        PublishingContext(
            title="归墟行舟",
            protagonists=[{"name": "陆沉" * 81, "role": "主角", "goal": "靠岸", "body": "章节正文"}],
            outline_summary={"overall": {"main_conflict": "靠岸", "chapter_body": "章节正文"}},
        )


def test_direct_context_enforces_actual_escaped_json_budget() -> None:
    escaped_text = "\\\x00" * 20_000
    with pytest.raises(ValidationError):
        PublishingContext(
            title="归墟行舟",
            novel_type=escaped_text[:120],
            opening_idea=escaped_text[:1_000],
            world_summary=escaped_text[:2_000],
            protagonists=[
                {"name": escaped_text[:80], "role": escaped_text[:80], "goal": escaped_text[:240]}
                for _ in range(8)
            ],
            outline_summary={
                "overall": {"main_conflict": escaped_text[:240]},
                "arcs": [
                    {"name": escaped_text[:80], "summary": escaped_text[:260], "main_conflict": escaped_text[:160]}
                    for _ in range(5)
                ],
            },
        )


def test_revalidating_an_unchecked_context_enforces_public_invariants() -> None:
    unchecked = PublishingContext.model_construct(
        title="归墟行舟",
        protagonists=[{"name": "陆沉", "role": "主角", "goal": "靠岸", "body": "章节正文"}],
        outline_summary={},
    )

    with pytest.raises(ValidationError):
        PublishingContext.model_validate(unchecked)


def test_direct_context_accepts_exact_nested_character_and_arc_caps() -> None:
    context = PublishingContext(
        title="归墟行舟",
        protagonists=[{"name": "名" * 80, "role": "角" * 80, "goal": "志" * 240}],
        outline_summary={
            "arcs": [
                {"name": "卷" * 80, "summary": "概" * 260, "main_conflict": "突" * 160}
                for _ in range(5)
            ]
        },
    )

    assert context.protagonists[0]["name"] == "名" * 80
    assert len(context.outline_summary["arcs"]) == 5


def test_direct_context_uses_fallback_title_after_normalization() -> None:
    context = PublishingContext(title="  \n")

    assert context.title == "未命名作品"


def test_publishing_context_skips_fallback_candidates_that_are_blank_or_non_scalar() -> None:
    context = build_publishing_context(
        project={"title": {}, "genre": "  ", "seed_outline": "项目开篇", "world_summary": []},
        state={"genre": {"bad": "value"}, "world_summary": "世界摘要"},
        opening_brief={"working_title": "  备用标题 ", "idea": "  ", "novel_type_id": " 仙侠 "},
        outline={},
    )

    assert context.title == "备用标题"
    assert context.novel_type == "仙侠"
    assert context.opening_idea == "项目开篇"
    assert context.world_summary == "世界摘要"


def test_publishing_context_stops_reading_profiles_after_eighth_valid_item() -> None:
    class ProfilesProbe(list):
        def __iter__(self):
            for index, item in enumerate(super().__iter__()):
                if index >= 8:
                    raise AssertionError("profile after the eighth valid item was read")
                yield item

    context = build_publishing_context(
        project={
            "character_profiles": ProfilesProbe(
                [{"name": f"角色{index}", "role": "角色", "goal": "靠岸"} for index in range(9)]
            )
        },
        state={},
        opening_brief={},
        outline={},
    )

    assert len(context.protagonists) == 8


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
