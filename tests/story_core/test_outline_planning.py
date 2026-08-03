from __future__ import annotations

from copy import deepcopy

import pytest

from packages.story_core.outline_planning import (
    validate_generated_continuation_plan,
    validate_generated_opening_plan,
)


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
                "theme_statement": "守住事实，比赢下一次争斗更重要。",
                "foreground_story": "林照从祖祠失火查到宗门旧案。",
                "background_story": "多年前有人借改名和封档重分宗门权力。",
                "book_objective": "公开旧案证据并改变宗门封档规则。",
                "ending_image": "旧案名册在议事堂当众展开。",
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
                    "emotional_curve": "受压查证，抓住破绽，取得主动。",
                    "key_results": ["保住现场证据", "取得旧档房资格", "锁定改名记录"],
                    "hook_plan": "旧名册缺失的一页指向宗门高层。",
                    "irreversible_change": "赵衡失去对祖祠和旧档房的独占控制。",
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


def test_opening_plan_rejects_concrete_monetary_amount(valid_payload: dict) -> None:
    valid_payload["outline"]["chapters"][0]["payoff"] = "担保交易到账1764.00元"

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:1:payoff$",
    ):
        validate_generated_opening_plan(valid_payload)


def test_opening_plan_rejects_monetary_amount_in_overall_story(
    valid_payload: dict,
) -> None:
    valid_payload["outline"]["overall"]["story"] = (
        "林照带着仅剩的46.83元进入宗门旧案。"
    )

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:overall:story$",
    ):
        validate_generated_opening_plan(valid_payload)


def test_opening_plan_rejects_monetary_amount_in_arc_narrative(
    valid_payload: dict,
) -> None:
    valid_payload["outline"]["arcs"][0]["payoff"] = "林照拿到价值300元的旧物"

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:arc:opening:payoff$",
    ):
        validate_generated_opening_plan(valid_payload)


@pytest.mark.parametrize(
    ("scope", "field_name", "location"),
    [
        *(('overall', field_name, f'overall:{field_name}') for field_name in (
            'story',
            'protagonist_goal',
            'main_conflict',
            'growth_path',
            'ending_direction',
            'ending_contract',
        )),
        *(('arc', field_name, f'arc:opening:{field_name}') for field_name in (
            'title',
            'goal',
            'obstacle',
            'payoff',
            'end_state',
            'game_line_payoff',
            'reality_line_payoff',
        )),
        ('arc_trace', 'long_term_antagonist_traces', 'arc:opening:long_term_antagonist_traces:0'),
        ('extension_gate', 'continue_route', 'arc:opening:extension_gate:continue_route'),
        ('extension_gate', 'close_route', 'arc:opening:extension_gate:close_route'),
        ('chapter', 'title', '1:title'),
    ],
)
def test_opening_plan_checks_every_outline_narrative_field(
    valid_payload: dict,
    scope: str,
    field_name: str,
    location: str,
) -> None:
    amount_text = "保留46.83元作为硬锚点"
    if scope == "overall":
        valid_payload["outline"]["overall"][field_name] = amount_text
    elif scope == "arc":
        valid_payload["outline"]["arcs"][0][field_name] = amount_text
    elif scope == "arc_trace":
        valid_payload["outline"]["arcs"][0][field_name] = [amount_text]
    elif scope == "extension_gate":
        gate = valid_payload["outline"]["arcs"][0].setdefault("extension_gate", {})
        gate[field_name] = amount_text
    else:
        valid_payload["outline"]["chapters"][0][field_name] = amount_text

    with pytest.raises(
        ValueError,
        match=f"^generated_outline_contains_monetary_amount:{location}$",
    ):
        validate_generated_opening_plan(valid_payload)


@pytest.mark.parametrize(
    "amount",
    ["40块", "2角", "5分", "100金币", "20银币", "8铜币"],
)
def test_opening_plan_rejects_supported_currency_units(
    valid_payload: dict,
    amount: str,
) -> None:
    valid_payload["outline"]["chapters"][0]["goal"] = amount

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:1:goal$",
    ):
        validate_generated_opening_plan(valid_payload)


def test_opening_plan_rejects_currency_unit_before_amount(valid_payload: dict) -> None:
    valid_payload["outline"]["chapters"][0]["payoff"] = "奖励金币100"

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:1:payoff$",
    ):
        validate_generated_opening_plan(valid_payload)


@pytest.mark.parametrize(
    "financial_percentage",
    [
        "手续费5%",
        "费率为5%",
        "手续费将按照本次平台担保交易的最终实际成交金额收取5%",
        "按5%收取手续费",
        "手续费比例为5%",
        "手续费高达5%",
        "以5%的比例收取手续费",
        "手续费不得超过5%",
        "手续费占成交额的5%",
        "费率调整为5%",
        "手续费按成交额的5%收取",
        "手续费按成交额百分之五收取",
        "平台服务费为5%",
        "平台服务费收取5%",
        "成交额的5%作为服务费",
        "手续费为成交额的5%",
        "服务费是成交金额的百分之五",
        "手续费按5%计收",
        "手续费按成交额5%计提",
    ],
)
def test_continuation_plan_rejects_financial_fee_percentage_without_amount(
    valid_payload: dict,
    financial_percentage: str,
) -> None:
    valid_payload["outline"]["arcs"] = []
    valid_payload["outline"]["chapters"] = [
        {
            **valid_payload["outline"]["chapters"][0],
            "chapter_number": 31,
            "turn": financial_percentage,
            "cast": ["林照"],
        }
    ]
    valid_payload["characters"] = []

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:31:turn$",
    ):
        validate_generated_continuation_plan(
            valid_payload,
            expected_chapter_numbers=[31],
            existing_character_names={"林照"},
        )


def test_generated_plan_allows_nonfinancial_quantities_and_qualitative_money_outcome(
    valid_payload: dict,
) -> None:
    valid_payload["outline"]["chapters"][0]["action"] = (
        "击杀5只灰狼，升到2级，扣除手续费后款项到账"
    )

    plan = validate_generated_opening_plan(valid_payload)

    assert plan.outline.chapters[0].action == "击杀5只灰狼，升到2级，扣除手续费后款项到账"


def test_amount_sanitizer_never_emits_prompt_instruction_as_story_event() -> None:
    from packages.story_core.outline_planning import _sanitize_generated_narrative_value

    sanitized = _sanitize_generated_narrative_value("平台扣除5%手续费后，到账1764.00元。")

    assert "不在大纲中" not in sanitized
    assert "写明具体数额" not in sanitized
    assert "1764" not in sanitized
    assert "5%" not in sanitized


def test_generated_plan_allows_time_and_unrelated_percentage(valid_payload: dict) -> None:
    valid_payload["outline"]["chapters"][0]["obstacle"] = (
        "等待5分钟，技能命中率只有20%"
    )

    plan = validate_generated_opening_plan(valid_payload)

    assert plan.outline.chapters[0].obstacle == "等待5分钟，技能命中率只有20%"


@pytest.mark.parametrize(
    "unrelated_percentage",
    [
        "扣除手续费后技能命中率20%",
        "手续费不变且成功率提升5%",
        "手续费不变且技能命中率为20%",
        "手续费取消后生命值恢复20%",
        "手续费不变且经验值提升20%",
        "手续费不变且按命中率20%释放技能",
        "手续费不变但有5%概率触发暴击",
        "扣除手续费后有20%概率掉落装备",
    ],
)
def test_generated_plan_allows_unrelated_percentage_near_fee_terms(
    valid_payload: dict,
    unrelated_percentage: str,
) -> None:
    valid_payload["outline"]["chapters"][0]["turn"] = unrelated_percentage

    plan = validate_generated_opening_plan(valid_payload)

    assert plan.outline.chapters[0].turn == unrelated_percentage


@pytest.mark.parametrize(
    "ordinary_quantity",
    [
        "收集5块碎片",
        "评分达到5分",
        "完成三分之一进度",
        "牛排达到七分熟",
        "本局拿到5分",
        "使出三分力",
        "有七分把握",
        "当前最快记录38分02秒",
        "剩余时间1分47秒",
        "收入3名弟子",
        "收入三名成员",
    ],
)
def test_generated_plan_allows_classifier_and_score_quantities(
    valid_payload: dict,
    ordinary_quantity: str,
) -> None:
    valid_payload["outline"]["chapters"][0]["action"] = ordinary_quantity

    plan = validate_generated_opening_plan(valid_payload)

    assert plan.outline.chapters[0].action == ordinary_quantity


@pytest.mark.parametrize(
    "amount",
    ["一百元", "金币一百", "10万元", "3亿元", "１２元"],
)
def test_opening_plan_rejects_chinese_fullwidth_and_scaled_amounts(
    valid_payload: dict,
    amount: str,
) -> None:
    valid_payload["outline"]["chapters"][0]["goal"] = f"获得{amount}"

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:1:goal$",
    ):
        validate_generated_opening_plan(valid_payload)


@pytest.mark.parametrize(
    "financial_amount",
    [
        "账户余额为332.60",
        "账户余额还有332.60",
        "账户余额只剩332.60",
        "账户余额仅剩332.60",
        "账户余额约332.60",
        "账户余额：332.60",
        "账户余额: 332.60",
        "账户余额、 332.60",
        "余额降至332.60",
        "余额升至 332.60",
        "成交价人民币1764",
        "成交价约为1764",
        "房租1180",
        "房租需付1180",
        "收入3000",
        "售价￥1764",
        "售价¥1764",
    ],
)
def test_opening_plan_rejects_bare_amount_near_financial_keyword(
    valid_payload: dict,
    financial_amount: str,
) -> None:
    valid_payload["outline"]["chapters"][0]["payoff"] = financial_amount

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:1:payoff$",
    ):
        validate_generated_opening_plan(valid_payload)


def test_opening_plan_rejects_percentage_before_fee_term(valid_payload: dict) -> None:
    valid_payload["outline"]["chapters"][0]["goal"] = "收取5%的手续费"

    with pytest.raises(
        ValueError,
        match="^generated_outline_contains_monetary_amount:1:goal$",
    ):
        validate_generated_opening_plan(valid_payload)


def test_continuation_plan_accepts_existing_and_new_cast(valid_payload: dict) -> None:
    valid_payload["outline"]["arcs"] = []
    valid_payload["outline"]["chapters"] = [
        {
            **valid_payload["outline"]["chapters"][0],
            "chapter_number": 31,
            "cast": ["林照", "新角色"],
        }
    ]
    valid_payload["characters"] = [_character("新角色", "supporting")]

    plan = validate_generated_continuation_plan(
        valid_payload,
        expected_chapter_numbers=[31],
        existing_character_names={"林照"},
    )

    assert [card.name for card in plan.characters] == ["新角色"]


def test_continuation_plan_rejects_unknown_cast(valid_payload: dict) -> None:
    valid_payload["outline"]["arcs"] = []
    valid_payload["outline"]["chapters"] = [
        {
            **valid_payload["outline"]["chapters"][0],
            "chapter_number": 31,
            "cast": ["林照", "未知角色"],
        }
    ]
    valid_payload["characters"] = [_character("新角色", "supporting")]

    with pytest.raises(ValueError, match="missing_character_card:未知角色"):
        validate_generated_continuation_plan(
            valid_payload,
            expected_chapter_numbers=[31],
            existing_character_names={"林照"},
        )


def test_continuation_plan_rejects_existing_character_submitted_as_new_card(
    valid_payload: dict,
) -> None:
    valid_payload["outline"]["arcs"] = []
    valid_payload["outline"]["chapters"] = [
        {
            **valid_payload["outline"]["chapters"][0],
            "chapter_number": 31,
            "cast": ["第七个已有角色"],
        }
    ]
    valid_payload["characters"] = [_character("第七个已有角色", "supporting")]

    with pytest.raises(
        ValueError,
        match="^duplicate_existing_character_card:第七个已有角色$",
    ):
        validate_generated_continuation_plan(
            valid_payload,
            expected_chapter_numbers=[31],
            existing_character_names={"第七个已有角色"},
        )
