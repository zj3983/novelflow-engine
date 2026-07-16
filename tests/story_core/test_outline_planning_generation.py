from __future__ import annotations

import json

import pytest

from packages.story_core.outline_planning_generation import (
    LLMOutlinePlanningGenerator,
    OutlinePlanningBrief,
)
from packages.story_core.runtime_config import StageRuntimeSettings


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
            },
            "arcs": [{
                "id": "opening",
                "title": "祖祠旧案",
                "start_chapter": 1,
                "end_chapter": 10,
                "goal": "找到换名册的人",
                "obstacle": "赵衡控制清点权",
                "payoff": "取得查档资格",
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
                    "cast": ["林照", "赵衡"],
                }
                for number in range(1, 6)
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
        },
        author_constraints=["白描，对话完整自然。"],
    )


def test_generator_requests_one_compact_structured_plan() -> None:
    calls = []
    runtime_calls = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        calls.append({"base_url": base_url, "path": path, "payload": payload, "api_key": api_key, "kwargs": kwargs})
        return {"choices": [{"message": {"content": json.dumps(_valid_plan(), ensure_ascii=False)}}]}

    generator = LLMOutlinePlanningGenerator(
        post_json=fake_post,
        runtime_resolver=lambda stage: runtime_calls.append(stage) or StageRuntimeSettings(
            provider="codexcli",
            model="planning-test-model",
            base_url="http://runtime.test",
            codex_command="codex-test",
            temperature=0.29,
        ),
    )

    result = generator.generate(_brief(), mode="initial", guidance="  反派要有现实利益  ")

    assert len(calls) == 1
    assert runtime_calls == ["planner"]
    assert result.outline.chapters[0].chapter_number == 1
    request = calls[0]
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
        "title",
        "opening_direction",
        "author_constraints",
        "existing_outline",
        "existing_characters",
        "current_chapter",
        "recent_chapter_summaries",
        "one_time_guidance",
    }
    assert prompt["one_time_guidance"] == "反派要有现实利益"
    assert "chapter body" not in json.dumps(prompt, ensure_ascii=False).lower()


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
