from packages.story_core.pipeline.writing_stage import generate_chapter_body


def _no_expand(body, plan):
    return False


def test_writing_stage_retries_empty_body_once_and_postprocesses_result():
    responses = iter([("", "正文返回为空"), (" 原始正文 ", "")])
    calls = []
    events = []

    result = generate_chapter_body(
        body_prompt="写第一章",
        chapter_number=1,
        writer_plan={},
        call_model=lambda prompt, stage, timeout: calls.append((prompt, stage, timeout)) or next(responses),
        postprocess=lambda body: body.strip(),
        should_expand=_no_expand,
        build_expansion_prompt=lambda body: "扩写",
        expansion_is_acceptable=lambda before, after: True,
        expansion_timeout_seconds=90,
        on_event=lambda name, payload: events.append((name, payload)),
    )

    assert result.ok is True
    assert result.body == "原始正文"
    assert [stage for _, stage, _ in calls] == ["整章写作 第1章", "整章写作重试 第1章"]
    assert events[0][0] == "empty_retry"


def test_writing_stage_accepts_expansion_only_after_postprocessing():
    calls = iter([("短正文", ""), ("扩写后的完整正文", "")])

    result = generate_chapter_body(
        body_prompt="写第二章",
        chapter_number=2,
        writer_plan={"target": 4000},
        call_model=lambda prompt, stage, timeout: next(calls),
        postprocess=lambda body: f"处理:{body}",
        should_expand=lambda body, plan: body == "处理:短正文",
        build_expansion_prompt=lambda body: f"扩写:{body}",
        expansion_is_acceptable=lambda before, after: len(after) > len(before),
        expansion_timeout_seconds=120,
    )

    assert result.ok is True
    assert result.expanded is True
    assert result.body == "处理:扩写后的完整正文"


def test_writing_stage_returns_clear_expansion_failure():
    calls = iter([("短正文", ""), ("", "timeout")])

    result = generate_chapter_body(
        body_prompt="写第三章",
        chapter_number=3,
        writer_plan={},
        call_model=lambda prompt, stage, timeout: next(calls),
        postprocess=lambda body: body,
        should_expand=lambda body, plan: True,
        build_expansion_prompt=lambda body: "扩写",
        expansion_is_acceptable=lambda before, after: True,
        expansion_timeout_seconds=60,
    )

    assert result.ok is False
    assert result.error == "章节扩写失败：timeout"
