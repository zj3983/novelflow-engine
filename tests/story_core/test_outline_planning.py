from __future__ import annotations

from copy import deepcopy

import pytest

from packages.story_core.outline_planning import validate_generated_opening_plan


def _character(name: str, tier: str, first_appearance: int = 1) -> dict:
    return {
        "name": name,
        "role": tier,
        "character_tier": tier,
        "first_appearance": first_appearance,
        "identity_profile": {
            "age": 19 if tier == "protagonist" else 35,
            "origin": "青石镇",
            "current_identity": "外门弟子" if tier == "protagonist" else "外门执事",
            "occupation": "看守祖祠" if tier == "protagonist" else "清点旧产",
        },
        "background_profile": {
            "family": "家人在外地",
            "upbringing": "在宗门规矩里长大",
            "education_or_training": "受过外门训练",
            "formative_events": ["见过一次宗门清查"],
            "arrival_reason": "因差事来到祖祠",
        },
        "current_life_profile": {
            "residence": "外门西院",
            "livelihood": "领取宗门份例",
            "economic_state": "手头不宽裕",
            "resources_and_ability": "会基础吐纳",
            "authority_scope": "只能处理外门差事",
            "immediate_problem": "处理祖祠异动",
        },
        "story_drive": {
            "long_term_goal": "在宗门站稳",
            "immediate_goal": "控制第三块青砖",
            "motivation": "不想失去现在的位置",
            "failure_stakes": "被逐出外门",
            "hidden_matters": ["知道旧名册被换过"],
            "main_conflict_reason": "与林照争夺青砖处置权",
        },
        "performance_profile": {
            "speech_style": "把条件和责任说完整",
            "action_style": "先封住现场再找人背书",
            "risk_posture": "不亲自承担可追查的风险",
            "emotional_triggers": ["被人提到旧名册"],
            "decision_rules": ["先保住身份"],
            "reveal_limits": ["不主动说出幕后长老"],
            "voice": {},
        },
        "dialogue_examples": ["这件事先按规矩登记，谁也别碰青砖。", "你要查可以，先把责任签下来。"],
        "relationship_notes": [],
    }


@pytest.fixture
def valid_payload() -> dict:
    characters = [
        _character("林照", "protagonist"),
        _character("赵衡", "stage_antagonist"),
        _character("周满", "supporting"),
        _character("顾长老", "long_term_antagonist", 0),
    ]
    chapters = []
    for number in range(1, 31):
        chapters.append(
            {
                "chapter_number": number,
                "title": f"第{number}步",
                "goal": "查清祖祠异动",
                "obstacle": "赵衡控制现场",
                "action": "林照留下可核对的证据",
                "turn": "旧名册出现矛盾",
                "payoff": "主角得到一条可验证线索",
                "ending_hook": "有人提前找过青砖",
                "cast": ["林照", "赵衡"] if number < 3 else ["林照", "周满"],
            }
        )
    return {
        "outline": {
            "overall": {
                "story": "林照借断香炉留下的零碎提醒追查宗门旧案。",
                "protagonist_goal": "在宗门站稳并查清旧案。",
                "main_conflict": "掌管旧产的人持续销毁证据。",
                "growth_path": "从只能守住现场成长为能调动宗门规则。",
                "ending_direction": "旧案公开，宗门权力重新洗牌。",
            },
            "arcs": [
                {
                    "id": "opening",
                    "title": "祖祠旧案",
                    "start_chapter": 1,
                    "end_chapter": 10,
                    "goal": "确认谁在寻找第三块青砖",
                    "obstacle": "赵衡掌握清点和封存权",
                    "payoff": "林照拿到进入旧档房的机会",
                    "end_state": "赵衡失去对祖祠的独占控制",
                    "stage_antagonist": "赵衡",
                    "long_term_antagonist_traces": ["旧名册有一页被换过"],
                }
            ],
            "chapters": chapters,
        },
        "characters": characters,
    }


def test_valid_opening_plan_has_concrete_cast_and_two_layer_opposition(valid_payload) -> None:
    plan = validate_generated_opening_plan(valid_payload)

    assert [chapter.chapter_number for chapter in plan.outline.chapters] == list(range(1, 31))
    assert plan.outline.arcs[0].stage_antagonist == "赵衡"
    assert {card.character_tier for card in plan.characters} >= {
        "protagonist",
        "stage_antagonist",
        "long_term_antagonist",
    }


@pytest.mark.parametrize(
    "mutation,error",
    [
        (lambda payload: payload["outline"]["overall"].update({"main_conflict": ""}), "missing_overall_field:main_conflict"),
        (lambda payload: payload["characters"].__setitem__(0, _character("孙石", "supporting")), "missing_character_tier:protagonist"),
        (lambda payload: payload["characters"].__setitem__(1, _character("孙石", "supporting")), "missing_character_tier:stage_antagonist"),
        (
            lambda payload: payload["characters"].extend(
                [_character("孙石", "supporting"), _character("钱六", "supporting"), _character("陈七", "supporting")]
            ),
            "character_count_out_of_range",
        ),
        (lambda payload: payload["outline"]["chapters"].pop(2), "generated_chapters_do_not_match_target_window"),
        (lambda payload: payload["outline"]["arcs"][0].update({"stage_antagonist": "其他人"}), "stage_antagonist_card_mismatch"),
        (lambda payload: payload["outline"]["arcs"][0].update({"long_term_antagonist_traces": []}), "long_term_antagonist_trace_required"),
    ],
)
def test_opening_plan_reports_specific_structural_error(valid_payload, mutation, error) -> None:
    payload = deepcopy(valid_payload)
    mutation(payload)

    with pytest.raises(ValueError, match=error):
        validate_generated_opening_plan(payload)


def test_opening_plan_rejects_cast_without_character_card(valid_payload) -> None:
    valid_payload["outline"]["chapters"][0]["cast"].append("无卡人物")

    with pytest.raises(ValueError, match="missing_character_card:无卡人物"):
        validate_generated_opening_plan(valid_payload)


def test_initial_plan_requires_thirty_detailed_chapters(valid_payload: dict) -> None:
    valid_payload["outline"]["chapters"] = [
        {**valid_payload["outline"]["chapters"][0], "chapter_number": number}
        for number in range(1, 31)
    ]

    plan = validate_generated_opening_plan(valid_payload)

    assert [item.chapter_number for item in plan.outline.chapters] == list(range(1, 31))


def test_plan_requires_explicit_target_sequence(valid_payload: dict) -> None:
    targets = [21, 23, *range(31, 51)]
    valid_payload["outline"]["chapters"] = [
        {**valid_payload["outline"]["chapters"][0], "chapter_number": number}
        for number in targets
    ]

    plan = validate_generated_opening_plan(
        valid_payload,
        expected_chapter_numbers=targets,
    )

    assert [item.chapter_number for item in plan.outline.chapters] == targets


def test_plan_accepts_explicit_empty_target_sequence(valid_payload: dict) -> None:
    valid_payload["outline"]["chapters"] = []

    plan = validate_generated_opening_plan(
        valid_payload,
        expected_chapter_numbers=[],
    )

    assert plan.outline.chapters == []
