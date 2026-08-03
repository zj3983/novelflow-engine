from packages.story_core.pipeline.planning_stage import resolve_chapter_plan


def test_planning_stage_uses_existing_outline_without_model_call():
    calls = []
    outline_plan = {"chapter_intent": {"chapter_title": "旧城来信"}, "character_moves": []}

    result = resolve_chapter_plan(
        outline_plan=outline_plan,
        build_prompt=lambda: "unused",
        call_model=lambda prompt, stage: calls.append((prompt, stage)) or ("", ""),
        review_plan=lambda plan: [],
        build_revision_prompt=lambda prompt, plan, issues: "revision",
    )

    assert result.ok is True
    assert result.planning_source == "outline"
    assert result.plan == outline_plan
    assert calls == []


def test_planning_stage_retries_invalid_json_response_once():
    responses = iter(
        [
            ("", "未返回有效 JSON"),
            ('{"chapter_intent":{"chapter_title":"第二次"}}', ""),
        ]
    )
    calls = []
    events = []

    result = resolve_chapter_plan(
        outline_plan=None,
        build_prompt=lambda: "base prompt",
        call_model=lambda prompt, stage: calls.append((prompt, stage)) or next(responses),
        review_plan=lambda plan: [],
        build_revision_prompt=lambda prompt, plan, issues: "revision",
        on_event=lambda name, payload: events.append((name, payload)),
    )

    assert result.ok is True
    assert result.planning_source == "model_fallback"
    assert result.plan["chapter_intent"]["chapter_title"] == "第二次"
    assert [stage for _, stage in calls] == ["剧情计划生成", "剧情计划格式重试"]
    assert events[0][0] == "format_retry"


def test_planning_stage_allows_only_one_quality_revision():
    calls = []
    reviews = iter([["缺少关键行动"], ["仍然缺少关键行动"]])

    result = resolve_chapter_plan(
        outline_plan=None,
        build_prompt=lambda: "base prompt",
        call_model=lambda prompt, stage: calls.append(stage) or ('{"chapter_intent":{}}', ""),
        review_plan=lambda plan: next(reviews),
        build_revision_prompt=lambda prompt, plan, issues: "revision prompt",
    )

    assert result.ok is False
    assert result.error.startswith("director_plan_quality_failed:")
    assert calls == ["剧情计划生成", "剧情计划重做"]
