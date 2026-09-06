import json
from copy import deepcopy
from typing import Any

import pytest
from pydantic import BaseModel

from packages.story_core.model_gateway import ModelResponse, RuntimeModelGateway
from packages.story_core.outline_planning_generation import (
    GeneratedChapterWindow,
    LLMOutlinePlanningGenerator,
    OutlinePlanningBrief,
)
from packages.story_core.title_strategy import (
    normalize_title_text,
    select_all_existing_chapter_titles,
    validate_chapter_title_window,
)


def test_normalize_title_text_removes_prefixes_and_wrappers():
    assert normalize_title_text("第198章 玄渊降临") == "玄渊降临"
    assert normalize_title_text("第 二百零九 章：玄渊降临！") == "玄渊降临！"
    assert normalize_title_text("《玄渊降临》") == "玄渊降临"
    assert normalize_title_text("“玄渊真身”") == "玄渊真身"
    assert normalize_title_text("【破阵斩核】") == "破阵斩核"


def test_validate_chapter_title_window_detects_all_duplicate_variants():
    known = [
        {"chapter_number": 198, "title": "第198章 玄渊降临"},
        {"chapter_number": 216, "title": "化神之劫"},
    ]
    generated = [
        {"chapter_number": 209, "title": "《玄渊降临》"},
    ]

    with pytest.raises(ValueError) as exc_info:
        validate_chapter_title_window(
            generated,
            genre_id="xuanhuan",
            known_chapters=known,
            generated_chapter_numbers={209},
        )
    assert str(exc_info.value) == "duplicate_chapter_title:209:198:《玄渊降临》"


def test_generate_chapter_batch_auto_repairs_duplicate_title():
    captured_payloads = []

    class _FakeGateway:
        def complete_stage(self, stage: str, request: Any) -> ModelResponse:
            op = getattr(request, "operation", "")
            captured_payloads.append(request)

            if "repair" in op:
                return ModelResponse.success(
                    request,
                    text=json.dumps(
                        {
                            "titles": [
                                {"chapter_number": 209, "title": "玄渊虚影"}
                            ]
                        },
                        ensure_ascii=False,
                    ),
                )

            return ModelResponse.success(
                request,
                text=json.dumps(
                    {
                        "chapters": [
                            {
                                "chapter_number": 209,
                                "title": "玄渊降临",
                                "goal": "抵挡玄渊真人的虚影攻击",
                                "obstacle": "小哑巴的自我意志与玄渊的控制欲",
                                "action": "小哑巴抗争，林修协助破局",
                                "turn": "虚影败退但本体觉醒",
                                "payoff": "成功击退虚影",
                                "ending_hook": "玄渊真人的本体在远方苏醒",
                                "cast": ["林修", "小哑巴"],
                                "core_conflict": "小哑巴的自我意志与玄渊的控制欲",
                                "gain": "击退玄渊虚影",
                                "cost": "消耗神魂之力",
                                "foreshadowing": ["玄渊真身觉醒"],
                                "state_delta_summary": "击退玄渊虚影，迎来更大的危机",
                                "scene_chain": [
                                    {
                                        "location": "天机阁内殿",
                                        "action": "对峙虚影",
                                        "result": "虚影显形",
                                    },
                                    {
                                        "location": "内殿阵眼",
                                        "action": "联手反击",
                                        "result": "击退虚影",
                                    },
                                ],
                            }
                        ]
                    },
                    ensure_ascii=False,
                ),
            )

    generator = LLMOutlinePlanningGenerator(
        model_gateway=_FakeGateway(),  # type: ignore[arg-type]
        runtime_resolver=lambda role: type(
            "Runtime",
            (),
            {"provider": "antigravity", "model": "gemini-3.7-flash", "temperature": 0.3, "api_key": "dummy"},
        )(),
    )

    brief = OutlinePlanningBrief(
        novel_type_id="xuanhuan",
        title="万界修真录",
        overall_context={"story": "测试大纲"},
        opening_direction={
            "title": "方向测试",
            "hook": "开局获得线索",
            "opening_promise": "查明真相升级破局",
            "primary_trope_id": "default",
        },
        author_constraints=[],
        existing_outline={
            "chapters": [
                {"chapter_number": 198, "title": "玄渊降临"},
            ]
        },
        existing_characters=[
            {"name": "林修", "first_appearance": 1},
            {"name": "小哑巴", "first_appearance": 1},
        ],
        existing_character_names=["林修", "小哑巴"],
        current_chapter=198,
        recent_chapter_summaries=[],
        historical_chapter_summaries=[],
    )

    volume = {
        "id": "arc-191-220",
        "title": "天机阁决战",
        "start_chapter": 191,
        "end_chapter": 220,
        "story_nodes": [
            {"start_chapter": 206, "end_chapter": 220, "goal": "击退玄渊"}
        ],
    }

    result = generator.generate_chapter_batch(
        brief,
        volume=volume,
        chapter_numbers=[209],
        previous_batches=[],
        adjacent_chapters=[],
    )

    assert len(result.chapters) == 1
    assert result.chapters[0].chapter_number == 209
    assert result.chapters[0].title == "玄渊虚影"

    assert len(captured_payloads) == 2
    repair_req = json.loads(captured_payloads[1].messages[1]["content"])
    assert "玄渊降临" in repair_req["forbidden_existing_titles"]
