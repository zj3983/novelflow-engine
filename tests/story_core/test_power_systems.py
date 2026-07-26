from __future__ import annotations

from copy import deepcopy
import json
import math

import pytest

from packages.story_core.power_systems import (
    PowerSystemValidationError,
    legacy_power_summary,
    normalize_power_system_spec,
    power_system_prompt_slice,
    validate_power_system_spec,
)


CLASSES = ("战士", "法师", "游侠", "盗贼", "牧师", "召唤师")


def complete_spec() -> dict[str, object]:
    return {
        "name": "神域职业体系",
        "origin": ["完成觉醒任务获得职业权能"],
        "attributes": [{"name": "智力", "effect": "提高法术强度"}],
        "paths": [
            {
                "name": name,
                "role": f"{name}队伍职责",
                "core_resource": f"{name}职业资源",
                "core_attributes": [f"{name}核心属性"],
                "weapons": [f"{name}武器"],
                "armor": [f"{name}护甲"],
                "combat_loop": f"{name}战斗循环",
                "strengths": [f"{name}强项"],
                "weaknesses": [f"{name}弱项"],
                "skill_categories": [f"{name}主动技能", f"{name}被动技能"],
                "branches": [f"{name}分支甲", f"{name}分支乙"],
                "transfer_task": f"完成{name}转职任务",
                "advancement": [f"{name}进阶任务"],
            }
            for name in CLASSES
        ],
        "stages": [
            {
                "name": name,
                "level": level,
                "entry": entry,
                "change": change,
                "failure": failure,
            }
            for name, level, entry, change, failure in (
                ("见习者", 1, "创建角色", "获得通用技能", "角色重建"),
                ("正式职业", 10, "Lv.10转职任务", "获得职业资源", "任务冷却"),
                ("专精", 20, "Lv.20专精试炼", "强化战斗方向", "专精材料损失"),
                ("进阶职业", 30, "Lv.30分支任务", "获得分支技能", "转职延期"),
                ("传承", 60, "Lv.60传承试炼", "获得职业权柄", "传承反噬"),
            )
        ],
        "skills": ["职业技能由导师、技能书和试炼获得"],
        "equipment": ["职业熟练度限制武器与护甲"],
        "resources": ["技能消耗职业资源并通过战斗恢复"],
        "advancement": ["晋升必须满足等级、任务和材料"],
        "costs": ["透支会造成虚弱并降低恢复速度"],
        "counters": ["控制克制蓄力，突进克制远程"],
        "boundaries": ["越级只能依赖情报、环境和克制，不可无条件碾压"],
        "social_impact": ["公会按职业配置开荒队"],
        "visibility": ["只能观察已公开等级和装备"],
        "continuity_ledger": [
            "level",
            "class_path",
            "skills",
            "equipment",
            "resources",
            "conditions",
        ],
    }


def validation_error(
    spec: object, novel_type_id: str = "game_webnovel"
) -> PowerSystemValidationError:
    with pytest.raises(PowerSystemValidationError) as caught:
        validate_power_system_spec(spec, novel_type_id=novel_type_id)
    return caught.value


def test_game_spec_accepts_complete_six_class_system_without_mutating_input() -> None:
    source = complete_spec()
    before = deepcopy(source)

    result = validate_power_system_spec(source, novel_type_id="game_webnovel")

    assert result["paths"][1]["name"] == "法师"
    assert source == before
    result["paths"][0]["branches"].append("外部修改")
    assert source == before


@pytest.mark.parametrize(
    "section",
    [
        "name",
        "origin",
        "attributes",
        "paths",
        "stages",
        "skills",
        "equipment",
        "resources",
        "advancement",
        "costs",
        "counters",
        "boundaries",
        "social_impact",
        "visibility",
        "continuity_ledger",
    ],
)
def test_validation_reports_each_required_empty_section(section: str) -> None:
    spec = complete_spec()
    spec[section] = "" if section == "name" else []

    error = validation_error(spec)

    assert section in error.missing_sections
    assert error.missing_sections == tuple(sorted(error.missing_sections))
    assert error.violations == tuple(sorted(error.violations))


def test_validation_error_metadata_is_immutable_stable_and_descriptive() -> None:
    error = validation_error({})

    assert isinstance(error, ValueError)
    assert isinstance(error.missing_sections, tuple)
    assert isinstance(error.violations, tuple)
    assert "missing_sections=" in str(error)
    assert "violations=" in str(error)


def test_validation_rejects_stage_count_fields_order_and_game_milestones() -> None:
    spec = complete_spec()
    spec["stages"] = [
        {"name": "一", "level": 10, "entry": "进入", "change": "变化", "failure": "失败"},
        {"name": "二", "level": 10, "entry": "进入", "change": "", "failure": "失败"},
    ]

    error = validation_error(spec)

    assert {
        "stages.minimum_count",
        "stages.missing_change",
        "stages.levels_not_increasing",
        "game.missing_milestones",
    } <= set(error.violations)


def test_validation_rejects_path_count_names_branches_and_game_details() -> None:
    spec = complete_spec()
    spec["paths"] = [
        {
            "name": "战士",
            "role": "坦克",
            "core_resource": "怒气",
            "weapons": [],
            "armor": ["重甲"],
            "combat_loop": "承伤反击",
            "strengths": ["承伤"],
            "weaknesses": [],
            "branches": ["盾战", "盾战"],
        }
    ]

    error = validation_error(spec)

    assert {
        "paths.minimum_count",
        "paths.distinct_branches",
        "game.missing_classes",
        "game.path_missing_weapon_affinity",
        "game.path_missing_weaknesses",
        "game.path_missing_core_attributes",
        "game.path_missing_skill_categories",
        "game.path_missing_transfer_task",
        "game.path_missing_advancement",
    } <= set(error.violations)


def test_validation_does_not_hide_empty_stage_or_path_records_during_normalization() -> None:
    spec = complete_spec()
    spec["stages"].append({})
    spec["paths"].append({})

    error = validation_error(spec)

    assert "stages.missing_name" in error.violations
    assert "paths.missing_name" in error.violations


def test_validation_rejects_blank_path_name_and_generic_path_details() -> None:
    spec = complete_spec()
    spec["paths"] = [{"name": "\x00 ", "branches": ["甲", "乙"]}, spec["paths"][1]]

    error = validation_error(spec, novel_type_id="unknown-type")

    assert "paths.missing_name" in error.violations


def test_validation_rejects_duplicate_path_names_case_insensitively() -> None:
    spec = complete_spec()
    spec["paths"][1]["name"] = " 战士 "

    assert "paths.duplicate_names" in validation_error(spec).violations


@pytest.mark.parametrize(
    ("ledger", "code"),
    [
        (
            ["progression", "skills", "resources", "conditions"],
            "continuity_ledger.missing_equipment",
        ),
        (["level", "abilities", "materials", "equipment"], "continuity_ledger.missing_conditions"),
    ],
)
def test_validation_requires_normalized_english_ledger_concepts(
    ledger: list[str], code: str
) -> None:
    spec = complete_spec()
    spec["continuity_ledger"] = ledger

    error = validation_error(spec)

    assert code in error.violations


def test_validation_accepts_normalized_english_ledger_aliases() -> None:
    spec = complete_spec()
    spec["continuity_ledger"] = [
        "current-level",
        "abilities",
        "gear",
        "materials",
        "status_effects",
    ]

    assert validate_power_system_spec(spec, novel_type_id="game_webnovel")["name"] == "神域职业体系"


def test_validation_accepts_chinese_ledger_aliases() -> None:
    spec = complete_spec()
    spec["continuity_ledger"] = ["当前等级", "技能", "装备", "资源", "负面状态"]

    assert validate_power_system_spec(spec, novel_type_id="game_webnovel")["name"] == "神域职业体系"


@pytest.mark.parametrize(
    "phrase",
    [
        "Lv20第二次转职",
        "Lv.20 second transfer",
        "20级二次转职",
        "Lv20再次转职",
        "Lv.20二转",
        "20级第二职业晋升",
    ],
)
def test_game_validation_rejects_level_twenty_as_second_transfer(phrase: str) -> None:
    spec = complete_spec()
    spec["stages"][2]["entry"] = phrase

    assert "game.level20_second_transfer" in validation_error(spec).violations


def test_game_validation_allows_second_transfer_outside_level_twenty() -> None:
    spec = complete_spec()
    spec["stages"][3]["entry"] = "Lv.30第二次转职"

    assert validate_power_system_spec(spec, novel_type_id="game_webnovel")["name"] == "神域职业体系"


def test_custom_template_and_generic_fallback_are_used() -> None:
    spec = complete_spec()
    spec["paths"] = spec["paths"][:2]
    custom = {"required_sections": ["origin", "visibility"], "minimum_path_count": 3}

    custom_error = validation_error_with_template(spec, "custom", custom)
    fallback = validate_power_system_spec(spec, novel_type_id="missing-template")

    assert "paths.minimum_count" in custom_error.violations
    assert fallback["name"] == "神域职业体系"


@pytest.mark.parametrize("section", ["costs", "counters", "boundaries"])
def test_cost_counter_and_boundary_rules_remain_required_with_custom_template(section: str) -> None:
    spec = complete_spec()
    spec[section] = []

    error = validation_error_with_template(
        spec,
        "custom",
        {"required_sections": [], "minimum_path_count": 2},
    )

    assert section in error.missing_sections


def test_game_milestones_may_be_expressed_in_stage_text() -> None:
    spec = complete_spec()
    for stage, level in zip(spec["stages"], (1, 10, 20, 30, 60)):
        stage.pop("level")
        stage["name"] = f"Lv.{level} {stage['name']}"

    assert validate_power_system_spec(spec, novel_type_id="game_webnovel")["name"] == "神域职业体系"


def test_inferred_stage_levels_must_strictly_increase() -> None:
    spec = complete_spec()
    for stage in spec["stages"]:
        stage.pop("level")
    for stage, token in zip(spec["stages"], ("LV1", "Lv.20", "10级", "LV30", "Lv60")):
        stage["name"] = token

    error = validation_error(spec)

    assert "stages.levels_not_increasing" in error.violations
    assert "game.invalid_milestones" in error.violations


def test_stage_level_inference_ignores_arbitrary_prose_numbers() -> None:
    spec = complete_spec()
    spec["stages"][1].pop("level")
    spec["stages"][1]["name"] = "材料试炼"
    spec["stages"][1]["entry"] = "收集100个材料后进入"

    assert validate_power_system_spec(spec, novel_type_id="missing-template")["name"] == "神域职业体系"


def test_game_milestones_reject_float_levels_even_when_integral() -> None:
    spec = complete_spec()
    spec["stages"][1]["level"] = 10.0

    assert "game.invalid_milestones" in validation_error(spec).violations


def test_game_milestones_require_exact_sequence() -> None:
    spec = complete_spec()
    spec["stages"][1], spec["stages"][2] = spec["stages"][2], spec["stages"][1]

    assert "game.invalid_milestones" in validation_error(spec).violations


def validation_error_with_template(
    spec: object, novel_type_id: str, template: dict[str, object]
) -> PowerSystemValidationError:
    with pytest.raises(PowerSystemValidationError) as caught:
        validate_power_system_spec(spec, novel_type_id=novel_type_id, template=template)
    return caught.value


def test_normalization_is_canonical_json_safe_bounded_and_deep_independent() -> None:
    class Hostile:
        def __str__(self) -> str:
            raise RuntimeError("no string for you")

    source = complete_spec()
    source.update(
        {
            "name": "  神\x00域\n  职业   体系  " + "长" * 1000,
            "unknown": Hostile(),
            "attributes": [{"name": "智力", "effect": "强度", "extra": object()}] * 100,
            "stages": source["stages"] + [{"name": "无限", "level": math.inf}] * 100,
            "paths": source["paths"] + [{"name": "额外", "branches": [Hostile()]}] * 100,
        }
    )

    result = normalize_power_system_spec(source)

    assert set(result) <= {
        "name", "origin", "attributes", "paths", "stages", "skills", "equipment",
        "resources", "advancement", "costs", "counters", "boundaries", "social_impact",
        "visibility", "continuity_ledger",
    }
    assert result["name"].startswith("神域 职业 体系")
    assert len(result["name"]) <= 240
    assert len(result["attributes"]) <= 64
    assert len(result["stages"]) <= 64
    assert len(result["paths"]) <= 64
    assert json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False)) == result
    result["origin"].append("修改")
    assert "修改" not in source["origin"]


def test_normalization_preserves_bounded_extended_path_schema() -> None:
    spec = complete_spec()
    path = spec["paths"][0]
    path["core_attributes"] = ["力量" * 300] * 100
    path["skill_categories"] = ["主动", "被动"]
    path["transfer_task"] = " 完成\x00 转职试炼 "

    normalized = normalize_power_system_spec(spec)["paths"][0]

    assert set(normalized) == {
        "name", "role", "core_resource", "core_attributes", "weapons", "armor",
        "combat_loop", "strengths", "weaknesses", "skill_categories", "branches",
        "transfer_task", "advancement",
    }
    assert len(normalized["core_attributes"]) == 64
    assert len(normalized["core_attributes"][0]) == 240
    assert normalized["transfer_task"] == "完成 转职试炼"


def test_normalization_bounds_large_mapping_iteration() -> None:
    class CountingMapping(dict):
        yielded = 0

        def items(self):
            for item in super().items():
                self.yielded += 1
                yield item

    source = CountingMapping({f"noise_{index}": index for index in range(20_000)})
    source["name"] = "有限体系"

    assert normalize_power_system_spec(source)["name"] == "有限体系"
    assert source.yielded <= 128


@pytest.mark.parametrize("value", [None, [], "bad", 3, float("nan")])
def test_normalization_returns_empty_mapping_for_invalid_top_level(value: object) -> None:
    assert normalize_power_system_spec(value) == {}


def test_normalization_sanitizes_large_and_non_finite_numbers() -> None:
    spec = {"stages": [{"name": "一", "level": 10**100}, {"name": "二", "level": float("nan")}]}

    result = normalize_power_system_spec(spec)

    assert result["stages"][0]["level"] == 1_000_000
    assert result["stages"][1]["level"] == 0


def test_legacy_summary_is_deterministic_bounded_and_redacts_exact_money() -> None:
    spec = complete_spec()
    spec["origin"].append("注册费100金币，手续费3.5%，Lv.20开放专精")

    first = legacy_power_summary(spec)
    second = legacy_power_summary(spec)

    assert first == second
    assert first[0] == "力量体系：神域职业体系。"
    assert len(first) <= 16
    joined = "\n".join(first)
    assert "100金币" not in joined
    assert "3.5%" not in joined
    assert "Lv.20" in joined
    labels = ("力量体系", "来源", "阶段", "路线", "资源", "代价", "边界")
    assert all(any(label in line for label in labels) for line in first)


def test_legacy_summary_redacts_formatted_currency_magnitudes_and_fees() -> None:
    spec = complete_spec()
    spec["origin"] = [
        "Lv.20需RMB 1,234.50或￥2,000，奖励100万金币、88.5银币、7铜币，手续费12.5%"
    ]

    joined = "\n".join(legacy_power_summary(spec))

    assert "Lv.20" in joined
    for exact in ("1,234.50", "2,000", "100万", "88.5", "7铜币", "12.5%"):
        assert exact not in joined


def test_legacy_summary_never_invents_absent_sections_and_handles_hostile_input() -> None:
    assert legacy_power_summary({"name": "孤立体系"}) == ["力量体系：孤立体系。"]
    assert legacy_power_summary(object()) == []


def test_prompt_slice_selects_numeric_current_and_next_stage() -> None:
    result = power_system_prompt_slice(complete_spec(), stage_hint=22)

    assert [stage["level"] for stage in result["stages"]] == [20, 30]


def test_prompt_slice_numeric_hint_uses_greatest_level_even_when_unordered() -> None:
    spec = complete_spec()
    spec["stages"] = [
        spec["stages"][3],
        spec["stages"][0],
        spec["stages"][2],
        spec["stages"][1],
        spec["stages"][4],
    ]

    result = power_system_prompt_slice(spec, stage_hint=22)

    assert [stage["level"] for stage in result["stages"]] == [20, 30]


def test_prompt_slice_selects_named_stage_and_next_stage() -> None:
    result = power_system_prompt_slice(complete_spec(), stage_hint="正式职业")

    assert [stage["name"] for stage in result["stages"]] == ["正式职业", "专精"]


def test_prompt_slice_defaults_to_first_three_stages() -> None:
    result = power_system_prompt_slice(complete_spec())

    assert [stage["level"] for stage in result["stages"]] == [1, 10, 20]
    assert all(set(path) == {"name", "branches"} for path in result["paths"])


@pytest.mark.parametrize("hint", ["法师", "FIRE MAGE", "fire mage"])
def test_prompt_slice_matches_path_or_branch_case_insensitively(hint: str) -> None:
    spec = complete_spec()
    spec["paths"][1]["branches"] = ["Fire Mage", "冰霜法师"]

    result = power_system_prompt_slice(spec, path_hint=hint)

    assert result["paths"] == [normalize_power_system_spec(spec)["paths"][1]]


def test_prompt_slice_keeps_core_context_and_is_deep_independent_under_limit() -> None:
    source = complete_spec()
    result = power_system_prompt_slice(source, stage_hint=10, path_hint="战士")

    assert {
        "name", "origin", "boundaries", "costs", "counters", "continuity_ledger",
        "skills", "resources", "equipment", "advancement",
    } <= set(result)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    assert len(encoded) <= 5000
    result["paths"][0]["branches"].append("修改")
    assert "修改" not in source["paths"][0]["branches"]


def test_prompt_slice_handles_hostile_values_and_enforces_strict_json_budget() -> None:
    class HostileMapping(dict):
        def items(self):
            raise RuntimeError("hostile items")

    huge = "界" * 100_000
    hostile = {field: [huge] * 100 for field in complete_spec()}
    hostile["name"] = huge
    hostile["paths"] = HostileMapping()

    result = power_system_prompt_slice(hostile, stage_hint=object(), path_hint=object())
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    assert len(encoded) <= 5000
