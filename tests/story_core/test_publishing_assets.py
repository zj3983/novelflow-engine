from __future__ import annotations

import json
from urllib.error import HTTPError, URLError

import pytest
from pydantic import ValidationError

from packages.story_core.publishing_assets import (
    CoverPromptGenerator,
    MAX_SYNOPSIS_TAG_CHARS,
    MAX_VISUAL_HOOK_CHARS,
    FanqieSynopsis,
    PublishingContext,
    SynopsisGenerator,
    build_publishing_context,
)
from packages.story_core.runtime_config import StageRuntimeSettings


def _publishing_runtime(*, provider: str = "openai") -> StageRuntimeSettings:
    return StageRuntimeSettings(
        provider=provider,
        model="publishing-model",
        api_key="publishing-key" if provider == "openai" else "",
        base_url="https://text.test/v1",
        codex_command="codex-publishing" if provider == "codexcli" else "",
        temperature=0.23,
    )


def _publishing_context() -> PublishingContext:
    return PublishingContext(
        title="归墟行舟",
        novel_type="玄幻",
        opening_idea="亡魂渡船",
        world_summary="归墟吞没所有失约者。",
        protagonists=[{"name": "陆沉", "role": "渡船人", "goal": "带妹妹活着靠岸"}],
        outline_summary={"overall": {"main_conflict": "渡船即将沉没"}},
    )


def _valid_synopsis() -> dict[str, object]:
    return {
        "tags": ["玄幻", "穿越", "成长", "克系"],
        "body": "陆沉醒来时，亡魂渡船已经驶入归墟，甲板上的乘客正在倒数自己的死期。" * 8,
        "pattern": "conflict",
        "visual_hook": "血月下的亡魂渡船",
    }


def test_synopsis_generator_returns_validated_synopsis_and_uses_runtime_transport() -> None:
    calls = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        calls.append((base_url, path, payload, api_key, kwargs))
        return {"choices": [{"message": {"content": json.dumps(_valid_synopsis(), ensure_ascii=False)}}]}

    result = SynopsisGenerator(post_json=fake_post).generate(
        _publishing_context(), _publishing_runtime(), guidance="  突出渡船危机  "
    )

    assert isinstance(result, FanqieSynopsis)
    assert result.pattern == "conflict"
    assert len(calls) == 1
    base_url, path, payload, api_key, kwargs = calls[0]
    assert (base_url, path, api_key) == ("https://text.test/v1", "/chat/completions", "publishing-key")
    assert payload["model"] == "publishing-model"
    assert payload["temperature"] == 0.23
    assert payload["response_format"] == {"type": "json_object"}
    assert kwargs == {"provider": "openai", "codex_command": ""}
    prompt_context = json.loads(payload["messages"][1]["content"])
    assert prompt_context["guidance"] == "突出渡船危机"
    assert prompt_context["title"] == "归墟行舟"
    system_prompt = payload["messages"][0]["content"]
    for requirement in ("tags", "body", "pattern", "visual_hook", "4-8", "200-450", "conflict", "contrast", "micro_scene"):
        assert requirement in system_prompt


def test_synopsis_generator_repairs_one_invalid_result_and_reports_the_problem() -> None:
    calls = []
    responses = iter(
        [
            {"choices": [{"message": {"content": '{"tags": ["玄幻"], "body": "太短"}'}}]},
            {"choices": [{"message": {"content": json.dumps(_valid_synopsis(), ensure_ascii=False)}}]},
        ]
    )

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    result = SynopsisGenerator(post_json=fake_post).generate(_publishing_context(), _publishing_runtime())

    assert result.visual_hook == "血月下的亡魂渡船"
    assert len(calls) == 2
    repair_context = json.loads(calls[1][0][2]["messages"][1]["content"])
    assert repair_context["invalid_payload"] == '{"tags": ["玄幻"], "body": "太短"}'
    assert repair_context["problem"]


def test_synopsis_repair_repeats_contract_and_bounds_rich_invalid_payload() -> None:
    calls = []
    invalid_payload = "x" * 5_000
    responses = iter(
        [
            {"choices": [{"message": {"content": [{"text": invalid_payload}]}}]},
            {"choices": [{"message": {"content": json.dumps(_valid_synopsis(), ensure_ascii=False)}}]},
        ]
    )

    def fake_post(base_url, path, payload, api_key, **kwargs):
        calls.append((base_url, path, payload, api_key, kwargs))
        return next(responses)

    result = SynopsisGenerator(post_json=fake_post).generate(
        _publishing_context(), _publishing_runtime(provider="codexcli")
    )

    assert result.pattern == "conflict"
    assert len(calls) == 2
    _, path, repair_payload, api_key, kwargs = calls[1]
    assert path == "/chat/completions"
    assert api_key == ""
    assert kwargs == {"provider": "codexcli", "codex_command": "codex-publishing"}
    repair_system = repair_payload["messages"][0]["content"]
    for requirement in ("tags", "body", "visual_hook", "4-8", "200-450", "conflict", "contrast", "micro_scene"):
        assert requirement in repair_system
    repair_context = json.loads(repair_payload["messages"][1]["content"])
    assert repair_context["problem"] == "invalid_json"
    assert repair_context["invalid_payload"] == invalid_payload[:4_000]


def test_synopsis_generator_repairs_an_unexpected_root_field() -> None:
    calls = []
    invalid = _valid_synopsis() | {"unexpected": "must not be ignored"}
    responses = iter(
        [
            {"choices": [{"message": {"content": json.dumps(invalid, ensure_ascii=False)}}]},
            {"choices": [{"message": {"content": json.dumps(_valid_synopsis(), ensure_ascii=False)}}]},
        ]
    )

    result = SynopsisGenerator(post_json=lambda *args, **kwargs: calls.append(args) or next(responses)).generate(
        _publishing_context(), _publishing_runtime()
    )

    assert result.pattern == "conflict"
    assert len(calls) == 2


def test_synopsis_generator_repairs_null_content_with_an_empty_invalid_payload() -> None:
    calls = []
    responses = iter(
        [
            {"choices": [{"message": {"content": None}}]},
            {"choices": [{"message": {"content": json.dumps(_valid_synopsis(), ensure_ascii=False)}}]},
        ]
    )

    result = SynopsisGenerator(post_json=lambda *args, **kwargs: calls.append(args) or next(responses)).generate(
        _publishing_context(), _publishing_runtime()
    )

    assert result.pattern == "conflict"
    assert len(calls) == 2
    repair_context = json.loads(calls[1][2]["messages"][1]["content"])
    assert repair_context["invalid_payload"] == ""


def test_synopsis_generator_fails_stably_after_exactly_one_repair_for_invalid_or_malformed_results() -> None:
    calls = []
    responses = iter([{"choices": []}, {"choices": [{"message": {"content": "not json"}}]}])

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        return next(responses)

    with pytest.raises(ValueError, match="^synopsis_generation_invalid$"):
        SynopsisGenerator(post_json=fake_post).generate(_publishing_context(), _publishing_runtime())

    assert len(calls) == 2


@pytest.mark.parametrize("error", [TimeoutError("timed out"), URLError("offline")])
def test_synopsis_generator_propagates_transport_failures_without_a_repair_call(error: Exception) -> None:
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        raise error

    with pytest.raises(type(error)) as exc_info:
        SynopsisGenerator(post_json=fake_post).generate(_publishing_context(), _publishing_runtime())

    assert exc_info.value is error
    assert len(calls) == 1


def test_synopsis_generator_bounds_guidance_and_only_serializes_publishing_context() -> None:
    captured = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        return {"choices": [{"message": {"content": json.dumps(_valid_synopsis(), ensure_ascii=False)}}]}

    SynopsisGenerator(post_json=fake_post).generate(
        _publishing_context(), _publishing_runtime(), guidance="  ONCE_ONLY  "
    )

    prompt = captured["payload"]["messages"][1]["content"]
    assert json.loads(prompt)["guidance"] == "ONCE_ONLY"
    assert "chapter_body" not in prompt
    assert "history" not in prompt
    with pytest.raises(ValueError, match="^regeneration_guidance_too_long$"):
        SynopsisGenerator(post_json=fake_post).generate(
            _publishing_context(), _publishing_runtime(), guidance=" x" * 501
        )


def test_cover_prompt_generator_preserves_concept_and_adds_missing_fixed_constraints() -> None:
    result = CoverPromptGenerator(
        post_json=lambda *args, **kwargs: {"choices": [{"message": {"content": "  血月下，少年站在亡魂渡船船头，巨浪翻涌  "}}]}
    ).generate(_publishing_context(), _publishing_runtime(), visual_hook="亡魂渡船")

    assert result.startswith("血月下，少年站在亡魂渡船船头，巨浪翻涌")
    for requirement in ("适合3:4小说封面", "留白", "无文字", "无字母", "无标志", "无水印"):
        assert requirement in result


def test_cover_prompt_generator_strips_caps_and_passes_codex_runtime_settings() -> None:
    calls = []
    concept = "幽蓝巨船穿过归墟" * 400

    def fake_post(base_url, path, payload, api_key, **kwargs):
        calls.append((base_url, path, payload, api_key, kwargs))
        return {"choices": [{"message": {"content": f"  {concept}  "}}]}

    result = CoverPromptGenerator(post_json=fake_post).generate(
        _publishing_context(), _publishing_runtime(provider="codexcli"), visual_hook="亡魂渡船", guidance="  更冷峻  "
    )

    assert result.startswith("幽蓝巨船穿过归墟")
    assert len(result) <= 2_000
    assert calls[0][1] == "/chat/completions"
    assert calls[0][4] == {"provider": "codexcli", "codex_command": "codex-publishing"}
    prompt_context = json.loads(calls[0][2]["messages"][1]["content"])
    assert prompt_context["visual_hook"] == "亡魂渡船"
    assert prompt_context["guidance"] == "更冷峻"


def test_cover_prompt_generator_keeps_all_guarantees_when_model_clauses_are_beyond_the_cap() -> None:
    concept = "无文字，幽蓝巨船穿过归墟" + ("巨浪翻涌" * 700)
    delayed_constraints = "，适合3:4小说封面，低细节标题安全留白，无字母，无标志，无水印"

    result = CoverPromptGenerator(
        post_json=lambda *args, **kwargs: {"choices": [{"message": {"content": concept + delayed_constraints}}]}
    ).generate(_publishing_context(), _publishing_runtime())

    assert len(result) <= 2_000
    for requirement in ("适合3:4小说封面", "留白", "无文字", "无字母", "无标志", "无水印"):
        assert requirement in result
    assert result.count("无文字") == 1


@pytest.mark.parametrize(
    "error",
    [
        TimeoutError("timed out"),
        URLError("offline"),
        HTTPError("https://text.test/v1/chat/completions", 503, "unavailable", None, None),
    ],
)
def test_cover_prompt_generator_propagates_transport_failures_without_retrying(error: Exception) -> None:
    calls = []

    def fake_post(*args, **kwargs):
        calls.append((args, kwargs))
        raise error

    with pytest.raises(type(error)) as exc_info:
        CoverPromptGenerator(post_json=fake_post).generate(_publishing_context(), _publishing_runtime())

    assert exc_info.value is error
    assert len(calls) == 1


def test_cover_prompt_generator_normalizes_rich_message_content() -> None:
    result = CoverPromptGenerator(
        post_json=lambda *args, **kwargs: {
            "choices": [{"message": {"content": [{"text": "  血月下的亡魂"}, "渡船  "]}}]
        }
    ).generate(_publishing_context(), _publishing_runtime())

    assert result.startswith("血月下的亡魂，渡船")


def test_cover_prompt_generator_appends_positive_canonical_segments_after_adversarial_substrings() -> None:
    adversarial_concept = "不适合3:4小说封面，不要无文字，不要无字母，不用无标志，无水印"
    result = CoverPromptGenerator(
        post_json=lambda *args, **kwargs: {"choices": [{"message": {"content": adversarial_concept}}]}
    ).generate(_publishing_context(), _publishing_runtime())

    segments = [segment.strip() for segment in result.split("，")]
    for clause in ("适合3:4小说封面", "低细节标题安全留白", "无文字", "无字母", "无标志", "无水印"):
        assert segments.count(clause) == 1
    assert len(result) <= 2_000


def test_cover_prompt_generator_recognizes_exclamation_delimited_canonical_segments() -> None:
    result = CoverPromptGenerator(
        post_json=lambda *args, **kwargs: {"choices": [{"message": {"content": "无文字！无水印"}}]}
    ).generate(_publishing_context(), _publishing_runtime())

    assert result.count("无文字") == 1
    assert result.count("无水印") == 1


@pytest.mark.parametrize(
    "response",
    [
        {"choices": [{"message": {"content": None}}]},
        {"choices": [{"message": {"content": 0}}]},
        {"choices": [{"message": {"content": False}}]},
        {"choices": [{"message": {"content": [{"text": None}]}}]},
        {"choices": [{"message": {"content": [{"text": 0}]}}]},
        {"choices": [{"message": {"content": [{"text": 1}]}}]},
        {"choices": [{"message": {"content": [{"text": False}]}}]},
        {"choices": [{"message": {"content": [{"text": True}]}}]},
        {"choices": [{"message": {"content": [None]}}]},
        {"choices": [{"message": {"content": [0]}}]},
        {"choices": [{"message": {"content": [False]}}]},
    ],
)
def test_cover_prompt_generator_rejects_non_text_content_shapes(response: dict) -> None:
    with pytest.raises(ValueError, match="^cover_prompt_generation_invalid$"):
        CoverPromptGenerator(post_json=lambda *args, **kwargs: response).generate(
            _publishing_context(), _publishing_runtime()
        )


@pytest.mark.parametrize("response", [{"choices": []}, {"choices": [{"message": {"content": "   "}}]}])
def test_cover_prompt_generator_rejects_blank_or_malformed_response_stably(response: dict) -> None:
    with pytest.raises(ValueError, match="^cover_prompt_generation_invalid$"):
        CoverPromptGenerator(post_json=lambda *args, **kwargs: response).generate(
            _publishing_context(), _publishing_runtime()
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


def test_fanqie_synopsis_rejects_tuple_tags() -> None:
    with pytest.raises(ValidationError):
        FanqieSynopsis(
            tags=(" 穿越 ", "成长", "穿越", "无系统", "克系"),
            body="文" * 200,
            pattern="conflict",
        )


@pytest.mark.parametrize("tags", [{"穿越", "成长", "无系统", "克系"}, iter(["穿越", "成长", "无系统", "克系"])])
def test_fanqie_synopsis_rejects_non_list_tag_iterables(tags: object) -> None:
    with pytest.raises(ValidationError):
        FanqieSynopsis(tags=tags, body="文" * 200, pattern="conflict")


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


def test_context_rejects_tuple_protagonists_in_construction_and_revalidation() -> None:
    tuple_protagonists = ({"name": "陆沉" * 1_000, "role": "主角", "goal": "靠岸", "body": "章节正文"},)

    with pytest.raises(ValidationError):
        PublishingContext(title="归墟行舟", protagonists=tuple_protagonists)
    with pytest.raises(ValidationError):
        PublishingContext.model_validate({"title": "归墟行舟", "protagonists": tuple_protagonists})
    unchecked = PublishingContext.model_construct(title="归墟行舟", protagonists=tuple_protagonists, outline_summary={})
    with pytest.raises(ValidationError):
        PublishingContext.model_validate(unchecked)


def test_context_rejects_tuple_outline_summary_before_dict_coercion() -> None:
    tuple_outline = (("overall", {"main_conflict": "靠岸", "chapter_body": "章节正文"}),)

    with pytest.raises(ValidationError):
        PublishingContext(title="归墟行舟", outline_summary=tuple_outline)


def test_context_rejects_set_and_custom_iterable_containers() -> None:
    class ProfilesIterable:
        def __iter__(self):
            yield {"name": "陆沉", "role": "主角", "goal": "靠岸"}

    with pytest.raises(ValidationError):
        PublishingContext(title="归墟行舟", protagonists={"not-a-profile"})
    with pytest.raises(ValidationError):
        PublishingContext(title="归墟行舟", protagonists=ProfilesIterable())
    with pytest.raises(ValidationError):
        PublishingContext(title="归墟行舟", outline_summary={"not-a-summary"})


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


def test_publishing_context_builder_accepts_a_lazy_profile_iterable() -> None:
    class ProfilesIterable:
        def __iter__(self):
            yield {"name": "陆沉", "role": "主角", "goal": "靠岸"}

    context = build_publishing_context(
        project={"character_profiles": ProfilesIterable()}, state={}, opening_brief={}, outline={}
    )

    assert context.protagonists == [{"name": "陆沉", "role": "主角", "goal": "靠岸"}]


def test_publishing_context_uses_later_valid_character_and_outline_fallbacks() -> None:
    context = build_publishing_context(
        project={
            "character_profiles": [
                {"name": "陆沉", "role": "  ", "story_role": "主角", "goal": {"bad": True}, "motivation": "活着靠岸"}
            ]
        },
        state={},
        opening_brief={},
        outline={
            "arcs": [
                {"name": "  ", "title": "第一卷", "summary": {"bad": True}, "description": "争夺船票"}
            ]
        },
    )

    assert context.protagonists == [{"name": "陆沉", "role": "主角", "goal": "活着靠岸"}]
    assert context.outline_summary["arcs"] == [{"name": "第一卷", "summary": "争夺船票"}]


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
