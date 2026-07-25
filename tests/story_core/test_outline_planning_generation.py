from __future__ import annotations

import json
import inspect

import pytest

from packages.story_core.outline_planning import (
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
    validate_generated_trope_selection,
)
from packages.story_core.outline_planning_generation import (
    LLMOutlinePlanningGenerator,
    OutlinePlanningBrief,
)
from packages.story_core.runtime_config import StageRuntimeSettings


def test_generator_constructor_does_not_accept_legacy_strategy_resolver() -> None:
    assert "strategy_resolver" not in inspect.signature(LLMOutlinePlanningGenerator).parameters


def _card(name: str, tier: str) -> dict:
    return {
        "name": name,
        "role": tier,
        "character_tier": tier,
        "first_appearance": 0 if tier == "long_term_antagonist" else 1,
        "identity_profile": {"origin": "青石镇", "current_identity": "宗门中人", "occupation": "处理宗门差事"},
        "background_profile": {},
        "current_life_profile": {},
        "story_drive": {"immediate_goal": "控制祖祠局面", "failure_stakes": "失去宗门位置"},
        "performance_profile": {},
        "dialogue_examples": ["这件事先说清楚。", "你把来龙去脉交代完整。"],
        "relationship_notes": [],
    }


def _valid_plan() -> dict:
    return {
        "outline": {
            "overall": {
                "story": "林照追查祖祠旧案。",
                "protagonist_goal": "查清旧案。",
                "main_conflict": "有人销毁证据。",
                "growth_path": "从守祠杂役成长为能调用宗门规则的人。",
                "ending_direction": "旧案公开。",
                "primary_trope_id": "low_status_reversal",
            },
            "arcs": [{
                "id": "opening",
                "title": "祖祠旧案",
                "start_chapter": 1,
                "end_chapter": 10,
                "goal": "找到换名册的人",
                "obstacle": "赵衡控制清点权",
                "payoff": "取得查档资格",
                "trope_id": "low_status_reversal",
                "end_state": "祖祠不再由赵衡独占",
                "stage_antagonist": "赵衡",
                "long_term_antagonist_traces": ["旧名册被换过"],
            }],
            "chapters": [
                {
                    "chapter_number": number,
                    "title": f"祖祠第{number}步",
                    "goal": "查清异动",
                    "obstacle": "赵衡阻拦",
                    "action": "林照留下证据",
                    "turn": "发现一处矛盾",
                    "payoff": "得到可验证线索",
                    "ending_hook": "有人提前来过",
                    "trope_beat": "低位压力" if number == 1 else None,
                    "cast": ["林照", "赵衡"],
                }
                for number in range(1, 31)
            ],
        },
        "characters": [
            _card("林照", "protagonist"),
            _card("赵衡", "stage_antagonist"),
            _card("周满", "supporting"),
            _card("顾长老", "long_term_antagonist"),
        ],
    }


def _brief() -> OutlinePlanningBrief:
    return OutlinePlanningBrief(
        novel_type_id="xuanhuan",
        title="我替宗门看守断香炉",
        opening_direction={
            "title": "断香炉",
            "hook": "祖祠断香炉提醒林照别让人挖第三块青砖。",
            "protagonist_goal": "在外门站稳并查清旧案。",
            "main_conflict": "有人要毁掉旧案证据。",
            "growth_path": "从守住现场开始掌握宗门规则。",
            "opening_promise": "每次解决具体问题都会换来一条可验证线索。",
            "primary_trope_id": "low_status_reversal",
        },
        author_constraints=["白描，对话完整自然。"],
    )


def _trope_templates() -> list[dict]:
    return [
        {"id": "trope-a", "name": "A", "beats": ["beat-a1", "beat-a2"]},
        {"id": "trope-b", "name": "B", "beats": ["beat-b1"]},
    ]


def _trope_plan() -> dict:
    plan = _valid_plan()
    plan["outline"]["overall"]["primary_trope_id"] = "trope-a"
    plan["outline"]["arcs"][0]["trope_id"] = "trope-a"
    plan["outline"]["chapters"][0]["trope_beat"] = "beat-a1"
    return plan


def test_trope_validator_rejects_invalid_primary_arc_and_beat() -> None:
    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = "missing"
    with pytest.raises(ValueError, match="^invalid_primary_trope_id$"):
        validate_generated_trope_selection(plan, _trope_templates())

    plan = _trope_plan()
    plan["outline"]["arcs"][0]["trope_id"] = "missing"
    with pytest.raises(ValueError, match="^invalid_arc_trope_id:opening$"):
        validate_generated_trope_selection(plan, _trope_templates())

    plan = _trope_plan()
    plan["outline"]["chapters"][0]["trope_beat"] = "wrong beat"
    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:1$"):
        validate_generated_trope_selection(plan, _trope_templates())


def test_trope_validator_uses_active_arc_precedence_for_overlapping_arcs() -> None:
    plan = _trope_plan()
    plan["outline"]["arcs"] = [
        {**plan["outline"]["arcs"][0], "id": "outer", "start_chapter": 1, "end_chapter": 10, "trope_id": "trope-a"},
        {**plan["outline"]["arcs"][0], "id": "inner", "start_chapter": 5, "end_chapter": 6, "trope_id": "trope-b"},
    ]
    plan["outline"]["chapters"][4]["trope_beat"] = "beat-b1"

    validate_generated_trope_selection(plan, _trope_templates())

    plan["outline"]["chapters"][4]["trope_beat"] = "beat-a1"
    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:5$"):
        validate_generated_trope_selection(plan, _trope_templates())


def test_trope_validator_allows_missing_chapter_beats() -> None:
    plan = _trope_plan()
    for chapter in plan["outline"]["chapters"]:
        chapter["trope_beat"] = None

    validate_generated_trope_selection(plan, _trope_templates())


def test_trope_validator_requires_all_nulls_when_no_candidates() -> None:
    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = None
    plan["outline"]["arcs"][0]["trope_id"] = None
    for chapter in plan["outline"]["chapters"]:
        chapter["trope_beat"] = None

    validate_generated_trope_selection(plan, [])

    plan["outline"]["chapters"][0]["trope_beat"] = "beat-a1"
    with pytest.raises(ValueError, match="^unexpected_chapter_trope_beat:1$"):
        validate_generated_trope_selection(plan, [])


def test_opening_and_continuation_validators_call_shared_trope_validator() -> None:
    plan = _trope_plan()
    plan["outline"]["overall"]["primary_trope_id"] = "trope-b"

    with pytest.raises(ValueError, match="^unexpected_primary_trope_id$"):
        validate_generated_opening_plan(
            plan,
            expected_chapter_numbers=list(range(1, 31)),
            trope_templates=_trope_templates(),
            expected_primary_trope_id="trope-a",
        )

    continuation = _trope_plan()
    continuation["outline"]["chapters"] = [
        {**continuation["outline"]["chapters"][0], "chapter_number": 31, "cast": ["Existing", "New"]}
    ]
    continuation["characters"] = [_card("New", "supporting")]
    continuation["outline"]["arcs"][0]["trope_id"] = "trope-b"
    with pytest.raises(ValueError, match="^invalid_chapter_trope_beat:31$"):
        validate_generated_continuation_plan(
            continuation,
            expected_chapter_numbers=[31],
            existing_character_names={"Existing"},
            trope_templates=_trope_templates(),
            expected_primary_trope_id="trope-a",
        )


class RecordingRuntime:
    def __init__(self) -> None:
        self.calls = []
        self.runtime_calls = []
        self.prompt_context = {}

    def post(self, base_url, path, payload, api_key, **kwargs):
        self.calls.append({"base_url": base_url, "path": path, "payload": payload, "api_key": api_key, "kwargs": kwargs})
        self.prompt_context = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        targets = self.prompt_context.get("target_chapter_numbers", list(range(1, 31)))
        template = plan["outline"]["chapters"][0]
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": template["trope_beat"] if number == 1 else None,
            }
            for number in targets
        ]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    def resolve(self, stage):
        self.runtime_calls.append(stage)
        return StageRuntimeSettings(
            provider="codexcli",
            model="planning-test-model",
            base_url="http://runtime.test",
            codex_command="codex-test",
            temperature=0.29,
        )

    def generator(self) -> LLMOutlinePlanningGenerator:
        return LLMOutlinePlanningGenerator(
            post_json=self.post,
            runtime_resolver=self.resolve,
        )

    def brief(self, *, current_chapter: int, existing_chapters: list[int]) -> OutlinePlanningBrief:
        payload = _brief().model_dump(mode="json")
        outline = _valid_plan()["outline"]
        template = outline["chapters"][0]
        outline["overall"].update(
            {
                "core_ending_chapter": 150,
                "extension_ceiling_chapter": 500,
                "current_strategy": "expand",
                "ending_contract": "Close both story lines.",
            }
        )
        outline["arcs"][0].update(
            {
                "end_chapter": 150,
                "game_line_payoff": "Win the active game arc.",
                "reality_line_payoff": "Resolve the active reality pressure.",
                "extension_gate": {
                    "continue_route": "Enter the next city.",
                    "close_route": "Close through the verifier ending.",
                },
            }
        )
        outline["chapters"] = [
            {**template, "chapter_number": number}
            for number in existing_chapters
        ]
        payload.update(
            existing_outline=outline,
            current_chapter=current_chapter,
        )
        return OutlinePlanningBrief.model_validate(payload)


@pytest.fixture
def generator_fixture() -> RecordingRuntime:
    return RecordingRuntime()


def test_generator_requests_one_compact_structured_plan() -> None:
    recording = RecordingRuntime()
    generator = recording.generator()

    result = generator.generate(_brief(), mode="initial", guidance="  反派要有现实利益  ")

    assert len(recording.calls) == 1
    assert recording.runtime_calls == ["planner"]
    assert result.outline.chapters[0].chapter_number == 1
    request = recording.calls[0]
    assert request["path"] == "/chat/completions"
    assert request["payload"]["model"] == "planning-test-model"
    assert request["payload"]["temperature"] == 0.29
    assert request["payload"]["response_format"] == {"type": "json_object"}
    prompt = json.loads(request["payload"]["messages"][1]["content"])
    assert set(prompt) == {
        "mode",
        "genre_label",
        "genre_description",
        "genre_core_promises",
        "genre_rulebook",
        "genre_quality_checks",
        "genre_trope_templates",
        "title",
        "opening_direction",
        "author_constraints",
        "existing_outline",
        "existing_characters",
        "existing_character_names",
        "current_chapter",
        "recent_chapter_summaries",
        "one_time_guidance",
        "output_schema",
        "validation_rules",
        "target_chapter_numbers",
        "current_strategy",
    }
    assert prompt["one_time_guidance"] == "反派要有现实利益"
    assert prompt["opening_direction"]["primary_trope_id"] == "low_status_reversal"
    assert prompt["genre_trope_templates"]
    assert "genre_trope_templates" in request["payload"]["messages"][1]["content"]
    schema_text = json.dumps(prompt["output_schema"], ensure_ascii=False)
    assert '"start_chapter"' in schema_text
    assert '"long_term_antagonist_traces"' in schema_text
    assert '"stage_antagonist"' in schema_text
    assert '"additionalProperties": false' in schema_text
    assert all(tier in schema_text for tier in (
        "protagonist",
        "stage_antagonist",
        "long_term_antagonist",
        "supporting",
    ))
    rules_text = "\n".join(prompt["validation_rules"])
    assert "stage_antagonist" in rules_text
    assert "exactly equal" in rules_text
    assert "target_chapter_numbers" in rules_text
    assert "cast" in rules_text
    assert "overall.primary_trope_id" in rules_text
    assert "arc.trope_id" in rules_text
    assert "trope_beat only on milestone chapters" in rules_text
    assert "must exactly equal a beat" in rules_text
    system_text = request["payload"]["messages"][0]["content"]
    assert "Choose one overall.primary_trope_id from prompt_context.genre_trope_templates" in system_text
    assert "Use null for overall.primary_trope_id, arc.trope_id, and chapter.trope_beat when prompt_context.genre_trope_templates is empty" in system_text
    assert "Do not assign trope_beat to every chapter" in system_text
    assert "Do not change trope_id inside an arc" in system_text
    assert "chapter body" not in json.dumps(prompt, ensure_ascii=False).lower()
    assert "五章" not in request["payload"]["messages"][0]["content"]


def test_generator_rejects_selected_primary_trope_drift() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        plan = _valid_plan()
        plan["outline"]["overall"]["primary_trope_id"] = "golden_finger_first_test"
        plan["outline"]["arcs"][0]["trope_id"] = "golden_finger_first_test"
        plan["outline"]["chapters"][0]["trope_beat"] = "异常出现"
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    with pytest.raises(ValueError, match="^outline_planning_generation_failed$") as exc_info:
        generator.generate(_brief(), mode="initial")

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "unexpected_primary_trope_id"


def test_extend_rejects_existing_primary_trope_drift() -> None:
    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["overall"]["primary_trope_id"] = "golden_finger_first_test"
        plan["outline"]["arcs"][0]["trope_id"] = "golden_finger_first_test"
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": "异常出现" if number == prompt["target_chapter_numbers"][0] else None,
                "cast": ["林照", "New"],
            }
            for number in prompt["target_chapter_numbers"]
        ]
        plan["characters"] = [_card("New", "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=20, existing_chapters=list(range(1, 31)))
    payload = brief.model_dump(mode="json")
    payload["existing_character_names"] = ["林照"]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    with pytest.raises(ValueError, match="^outline_planning_generation_failed$") as exc_info:
        generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == "unexpected_primary_trope_id"


def test_extend_prompt_requests_only_missing_window_chapters(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=20,
        existing_chapters=list(range(1, 31)),
    )

    generator_fixture.generator().generate(brief, mode="extend")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(31, 51))
    assert generator_fixture.prompt_context["current_strategy"] == "expand"


def test_regenerate_requests_thirty_future_chapters(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=20,
        existing_chapters=list(range(1, 51)),
    )

    generator_fixture.generator().generate(brief, mode="regenerate")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(21, 51))


def test_initial_requires_unstarted_project(generator_fixture) -> None:
    brief = generator_fixture.brief(current_chapter=1, existing_chapters=list(range(1, 31)))

    with pytest.raises(ValueError, match="^initial_outline_requires_unstarted_project$"):
        generator_fixture.generator().generate(brief, mode="initial")


def test_extend_rejects_full_window(generator_fixture) -> None:
    brief = generator_fixture.brief(current_chapter=20, existing_chapters=list(range(1, 51)))

    with pytest.raises(ValueError, match="^outline_window_already_full$"):
        generator_fixture.generator().generate(brief, mode="extend")


def test_extend_prompt_includes_sparse_window_holes(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=20,
        existing_chapters=[*range(1, 21), 30],
    )

    generator_fixture.generator().generate(brief, mode="extend")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == [
        *range(21, 30),
        *range(31, 51),
    ]


def test_regenerate_stops_at_extension_ceiling(generator_fixture) -> None:
    brief = generator_fixture.brief(current_chapter=490, existing_chapters=list(range(1, 491)))
    payload = brief.model_dump(mode="json")
    payload["existing_outline"]["overall"]["extension_ceiling_chapter"] = 500
    brief = OutlinePlanningBrief.model_validate(payload)

    generator_fixture.generator().generate(brief, mode="regenerate")

    assert generator_fixture.prompt_context["target_chapter_numbers"] == list(range(491, 501))


def test_regenerate_at_extension_ceiling_rejects_before_model_call(generator_fixture) -> None:
    brief = generator_fixture.brief(
        current_chapter=500,
        existing_chapters=list(range(1, 501)),
    )

    with pytest.raises(ValueError, match="^outline_window_already_full$"):
        generator_fixture.generator().generate(brief, mode="regenerate")

    assert generator_fixture.calls == []
    assert generator_fixture.runtime_calls == []


def test_extend_accepts_only_new_character_cards_and_existing_cast() -> None:
    prompt_context = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt_context.update(json.loads(payload["messages"][1]["content"]))
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["arcs"] = []
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": None,
                "cast": ["林照", "新角色"],
            }
            for number in prompt_context["target_chapter_numbers"]
        ]
        plan["characters"] = [_card("新角色", "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=20, existing_chapters=list(range(1, 31)))
    payload = brief.model_dump(mode="json")
    payload["existing_characters"] = [{"name": "林照"}]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    plan = generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert [card.name for card in plan.characters] == ["新角色"]
    rules = "\n".join(prompt_context["validation_rules"])
    assert "only newly introduced character cards" in rules
    assert "existing_character_names" in rules


def test_extend_accepts_seventh_existing_character_in_cast() -> None:
    prompt_context = {}
    detailed_names = [f"已有角色{number}" for number in range(1, 7)]
    all_names = [*detailed_names, "第七个已有角色"]

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt_context.update(json.loads(payload["messages"][1]["content"]))
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["arcs"] = []
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "trope_beat": None,
                "cast": ["第七个已有角色", "新角色"],
            }
            for number in prompt_context["target_chapter_numbers"]
        ]
        plan["characters"] = [_card("新角色", "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=20, existing_chapters=list(range(1, 31)))
    payload = brief.model_dump(mode="json")
    payload["existing_characters"] = [{"name": name} for name in detailed_names]
    payload["existing_character_names"] = all_names
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    plan = generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert [card.name for card in plan.characters] == ["新角色"]
    assert prompt_context["existing_character_names"] == all_names


@pytest.mark.parametrize(
    "returned_name,cast,error",
    [
        (
            "第七个已有角色",
            ["第七个已有角色"],
            "duplicate_existing_character_card:第七个已有角色",
        ),
        ("新角色", ["未知角色"], "missing_character_card:未知角色"),
    ],
)
def test_extend_wraps_model_contract_errors_uniformly(
    returned_name: str,
    cast: list[str],
    error: str,
) -> None:
    existing_name = "第七个已有角色"

    def fake_post(base_url, path, payload, api_key, **kwargs):
        prompt = json.loads(payload["messages"][1]["content"])
        plan = _valid_plan()
        template = plan["outline"]["chapters"][0]
        plan["outline"]["arcs"] = []
        plan["outline"]["chapters"] = [
            {
                **template,
                "chapter_number": number,
                "cast": cast,
            }
            for number in prompt["target_chapter_numbers"]
        ]
        plan["characters"] = [_card(returned_name, "supporting")]
        return {"choices": [{"message": {"content": json.dumps(plan, ensure_ascii=False)}}]}

    fixture = RecordingRuntime()
    brief = fixture.brief(current_chapter=20, existing_chapters=list(range(1, 31)))
    payload = brief.model_dump(mode="json")
    payload["existing_character_names"] = [existing_name]
    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=fixture.resolve,
    )

    with pytest.raises(ValueError, match="^outline_planning_generation_failed$") as exc_info:
        generator.generate(OutlinePlanningBrief.model_validate(payload), mode="extend")

    assert isinstance(exc_info.value.__cause__, ValueError)
    assert str(exc_info.value.__cause__) == error


def test_generator_rejects_invalid_output_and_long_guidance() -> None:
    runtime_calls = []
    generator = LLMOutlinePlanningGenerator(
        post_json=lambda *args, **kwargs: {"choices": [{"message": {"content": "{}"}}]},
        runtime_resolver=lambda name: runtime_calls.append(name) or StageRuntimeSettings(
            provider="codexcli", model="planning-test-model"
        ),
    )

    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(_brief(), mode="initial")
    with pytest.raises(ValueError, match="regeneration_guidance_too_long"):
        generator.generate(_brief(), mode="initial", guidance="x" * 1001)

    assert runtime_calls == ["planner"]
