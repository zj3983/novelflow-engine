from __future__ import annotations

from copy import deepcopy
import json
import math

import pytest

from packages.story_core import power_system_prompt, power_system_spec
from packages.story_core import power_systems as power_system_facade
from packages.story_core.power_systems import (
    PowerSystemValidationError,
    legacy_power_summary,
    normalize_power_system_spec,
    power_system_prompt_slice,
    validate_power_system_spec,
)


CLASSES = ("战士", "法师", "游侠", "盗贼", "牧师", "召唤师")


def test_public_facade_reexports_specification_api() -> None:
    assert power_system_facade.PowerSystemValidationError is power_system_spec.PowerSystemValidationError
    assert power_system_facade.normalize_power_system_spec is power_system_spec.normalize_power_system_spec
    assert power_system_facade.validate_power_system_spec is power_system_spec.validate_power_system_spec


def test_public_facade_reexports_prompt_api() -> None:
    assert power_system_facade.legacy_power_summary is power_system_prompt.legacy_power_summary
    assert power_system_facade.power_system_prompt_slice is power_system_prompt.power_system_prompt_slice


def test_public_facade_declares_exact_exports() -> None:
    assert power_system_facade.__all__ == (
        "PowerSystemValidationError",
        "legacy_power_summary",
        "normalize_power_system_spec",
        "power_system_prompt_slice",
        "validate_power_system_spec",
    )


def test_non_game_power_system_uses_genre_ledger_without_game_inventory_fields() -> None:
    spec = complete_spec()
    spec["paths"] = spec["paths"][:2]
    spec["continuity_ledger"] = [
        "awakening_rank",
        "ability",
        "real_identity",
        "organization_relation",
        "exposure",
        "physical_burden",
    ]

    validated = validate_power_system_spec(spec, novel_type_id="urban")

    assert validated["continuity_ledger"] == spec["continuity_ledger"]


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


def test_game_spec_accepts_six_custom_named_classes_with_complete_details() -> None:
    spec = complete_spec()
    custom_names = (
        "\u5251\u58eb",
        "\u672f\u58eb",
        "\u730e\u4eba",
        "\u523a\u5ba2",
        "\u836f\u5e08",
        "\u9a6d\u517d\u5e08",
    )
    for path, name in zip(spec["paths"], custom_names):
        path["name"] = name

    result = validate_power_system_spec(spec, novel_type_id="game_webnovel")

    assert tuple(path["name"] for path in result["paths"]) == custom_names


def test_game_spec_accepts_more_than_six_complete_classes() -> None:
    spec = complete_spec()
    extra_path = deepcopy(spec["paths"][0])
    extra_path["name"] = "机关师"
    extra_path["branches"] = ["傀儡师", "火器师"]
    spec["paths"].append(extra_path)

    result = validate_power_system_spec(spec, novel_type_id="game_webnovel")

    assert len(result["paths"]) == 7
    assert result["paths"][-1]["name"] == "机关师"


@pytest.mark.parametrize(
    ("location", "placeholder"),
    [
        (("origin", 0), "\u5f85\u5b9a"),
        (("stages", 0, "entry"), "\u7565"),
        (("paths", 0, "combat_loop"), "\u540c\u4e0a"),
        (("paths", 0, "advancement", 0), "\u7efc\u5408\u5b9e\u529b\u63d0\u5347"),
        (("origin", 0), "待完善"),
        (("stages", 0, "entry"), "后续补充"),
        (("paths", 0, "combat_loop"), "TODO"),
    ],
)
def test_validation_rejects_placeholder_or_low_information_descriptions(
    location: tuple[object, ...], placeholder: str
) -> None:
    spec = complete_spec()
    target: object = spec
    for key in location[:-1]:
        target = target[key]  # type: ignore[index]
    target[location[-1]] = placeholder  # type: ignore[index]

    error = validation_error(spec)

    assert "content.placeholder_or_low_information" in error.violations


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


def test_validation_rejects_duplicate_branches_casefolded_after_whitespace_normalization() -> None:
    spec = complete_spec()
    spec["paths"][0]["branches"] = ["Fire Mage", " fire   mage "]

    assert "paths.distinct_branches" in validation_error(spec).violations


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
    spec["stages"][3]["name"] = "Lv.30专精进阶"
    spec["stages"][3]["entry"] = "第二次转职"

    assert validate_power_system_spec(spec, novel_type_id="game_webnovel")["name"] == "神域职业体系"


def test_game_validation_does_not_use_specialization_fallback_when_any_level_is_known() -> None:
    spec = complete_spec()
    spec["stages"][2].pop("level")
    spec["stages"][2]["name"] = "专精"
    spec["stages"][2]["entry"] = "第二次转职"

    error = validation_error(spec)

    assert "game.invalid_milestones" in error.violations
    assert "game.level20_second_transfer" not in error.violations


def test_game_validation_uses_canonical_specialization_fallback_when_no_levels_are_known() -> None:
    spec = complete_spec()
    for index, stage in enumerate(spec["stages"]):
        stage.pop("level")
        stage["name"] = "专精" if index == 2 else f"阶段{chr(65 + index)}"
        stage["entry"] = "第二次转职" if index == 2 else "完成试炼"

    assert "game.level20_second_transfer" in validation_error(spec).violations


def test_game_validation_rejects_duplicate_class_paths() -> None:
    spec = complete_spec()
    extra = deepcopy(spec["paths"][0])
    extra["name"] = "战士"
    spec["paths"].append(extra)

    assert "game.invalid_classes" in validation_error(spec).violations


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
        "visibility", "continuity_ledger", "attribute_allocation",
    }
    assert result["name"].startswith("神域 职业 体系")
    assert len(result["name"]) <= 240
    assert len(result["attributes"]) <= 64
    assert len(result["stages"]) <= 64
    assert len(result["paths"]) <= 64
    assert json.loads(json.dumps(result, ensure_ascii=False, allow_nan=False)) == result
    result["origin"].append("修改")
    assert "修改" not in source["origin"]


def test_normalization_and_prompt_slice_preserve_enabled_attribute_allocation() -> None:
    source = complete_spec()
    source["attribute_allocation"] = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"力量": 5, "敏捷": 5, "体质": 5, "智力": 5, "精神": 5, "幸运": 5},
        "allow_carry": True,
        "respec_rule": "每周可在主城重置一次，消耗洗点券。",
    }

    normalized = normalize_power_system_spec(source)
    prompt = power_system_prompt_slice(source)

    assert normalized["attribute_allocation"] == source["attribute_allocation"]
    assert prompt["attribute_allocation"] == source["attribute_allocation"]
    normalized["attribute_allocation"]["base_attributes"]["力量"] = 99
    assert source["attribute_allocation"]["base_attributes"]["力量"] == 5


def test_normalization_does_not_add_attribute_allocation_without_an_enabled_rule() -> None:
    assert "attribute_allocation" not in normalize_power_system_spec(complete_spec())


def test_prompt_slice_ignores_extreme_attribute_starting_level_within_budget() -> None:
    source = complete_spec()
    source["attribute_allocation"] = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 10**100_000,
        "base_attributes": {"力量": 5},
        "allow_carry": True,
        "respec_rule": "每周可在主城重置一次，消耗洗点券。",
    }

    result = power_system_prompt_slice(source)
    encoded = json.dumps(result, ensure_ascii=False, separators=(",", ":"), allow_nan=False)

    assert "attribute_allocation" not in result
    assert len(encoded) <= 5_000


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


def test_normalization_is_idempotent_at_truncated_whitespace_boundaries() -> None:
    boundary = "界" * 239 + " \t" + "尾部"
    spec = {
        "name": boundary,
        **{
            field: [boundary]
            for field in (
                "origin", "skills", "equipment", "resources", "advancement",
                "costs", "counters", "boundaries", "social_impact", "visibility",
                "continuity_ledger",
            )
        },
        "attributes": [{"name": boundary, "effect": boundary}],
        "paths": [
            {
                field: [boundary]
                if field in {
                    "core_attributes", "weapons", "armor", "strengths", "weaknesses",
                    "skill_categories", "branches", "advancement",
                }
                else boundary
                for field in (
                    "name", "role", "core_resource", "core_attributes", "weapons", "armor",
                    "combat_loop", "strengths", "weaknesses", "skill_categories", "branches",
                    "transfer_task", "advancement",
                )
            }
        ],
        "stages": [
            {field: boundary for field in ("name", "entry", "change", "failure")}
        ],
    }

    first = normalize_power_system_spec(spec)
    second = normalize_power_system_spec(first)

    assert second == first
    assert not first["name"].endswith(" ")


def test_normalization_bounds_raw_string_examination() -> None:
    class CountingString(str):
        examined = 0

        def __iter__(self):
            for character in super().__iter__():
                self.examined += 1
                yield character

    hostile = CountingString(" " * 5_000 + "x" * 10_000_000)

    assert normalize_power_system_spec({"name": hostile}) == {}
    assert 0 < hostile.examined <= 4_096


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


def test_legacy_summary_redacts_currency_units_before_amounts() -> None:
    spec = complete_spec()
    spec["origin"] = [
        "Lv.30奖励金币100、银币50、铜币1,000，费用元100、人民币100"
    ]

    joined = "\n".join(legacy_power_summary(spec))

    assert "Lv.30" in joined
    for exact in ("金币100", "银币50", "铜币1,000", "元100", "人民币100"):
        assert exact not in joined


def test_legacy_summary_preserves_lexical_yuan_and_mechanics_percentages() -> None:
    spec = complete_spec()
    spec["origin"] = ["元婴境消耗100元婴丹，暴击率提高20%，抗性20%，支付100元。"]

    joined = "\n".join(legacy_power_summary(spec))

    assert "元婴境" in joined
    assert "100元婴丹" in joined
    assert "暴击率提高20%" in joined
    assert "抗性20%" in joined
    assert "支付100元" not in joined


@pytest.mark.parametrize(
    "compound",
    ["元核", "元魂", "元丹", "元婴", "元素", "元神", "元气", "元灵", "元力", "元初", "元始"],
)
def test_legacy_summary_preserves_nonfinancial_yuan_power_compounds(compound: str) -> None:
    spec = complete_spec()
    spec["origin"] = [f"保留100{compound}设定，100元购买药品，支付100元购买"]

    joined = "\n".join(legacy_power_summary(spec))

    assert f"100{compound}" in joined
    assert "100元购买药品" not in joined
    assert "支付100元购买" not in joined


@pytest.mark.parametrize(
    "context",
    [
        "支付", "购买", "价格", "售价", "费用", "手续费", "到账", "提现",
        "交易", "收入", "成本", "租金", "余额", "人民币", "RMB",
    ],
)
def test_legacy_summary_redacts_yuan_only_with_local_financial_semantics(context: str) -> None:
    spec = complete_spec()
    spec["origin"] = [f"{context}调整为100元。"]

    joined = "\n".join(legacy_power_summary(spec))

    assert "100元" not in joined


@pytest.mark.parametrize(
    ("sentence", "preserved"),
    [
        ("购买道具后获得100元核", "100元核"),
        ("支付代价后恢复100元力", "100元力"),
        ("支付100元购买", None),
        ("门票100元才能进入", None),
        ("需100元才能进入", None),
        ("花100元解锁", None),
        ("记录为100元。", None),
    ],
)
def test_legacy_summary_binds_yuan_to_nearest_preceding_governing_cue(
    sentence: str,
    preserved: str | None,
) -> None:
    spec = complete_spec()
    spec["origin"] = [sentence]

    joined = "\n".join(legacy_power_summary(spec))

    if preserved is None:
        assert "100元" not in joined
    else:
        assert preserved in joined


def test_legacy_summary_redacts_unknown_yuan_suffix_by_default() -> None:
    spec = complete_spec()
    spec["origin"] = ["记录显示100元很贵"]

    assert "100元" not in "\n".join(legacy_power_summary(spec))


def test_legacy_summary_power_suffix_is_positive_evidence_despite_financial_cue() -> None:
    spec = complete_spec()
    spec["origin"] = ["支付100元魂"]

    assert "100元魂" in "\n".join(legacy_power_summary(spec))


def test_legacy_summary_preserves_yuan_power_stage_and_path_text() -> None:
    spec = complete_spec()
    spec["stages"][0]["name"] = "3级元婴"
    spec["paths"][0]["name"] = "元素法师"

    joined = "\n".join(legacy_power_summary(spec))

    assert "3级元婴" in joined
    assert "元素法师" in joined


@pytest.mark.parametrize(
    "term",
    ["手续费", "费率", "税", "佣金", "折扣", "利息", "收益率", "提现", "到账", "交易费"],
)
def test_legacy_summary_redacts_percentages_only_in_financial_context(term: str) -> None:
    spec = complete_spec()
    spec["origin"] = [f"暴击率提高20%，{term}12.5%，抗性20%"]

    joined = "\n".join(legacy_power_summary(spec))

    assert f"{term}12.5%" not in joined
    assert "暴击率提高20%" in joined
    assert "抗性20%" in joined


@pytest.mark.parametrize(
    "sentence",
    [
        "手续费12.5%同时暴击率提高20%",
        "12.5%的手续费同时暴击率提高20%",
    ],
)
def test_legacy_summary_classifies_each_percentage_by_nearest_context(sentence: str) -> None:
    spec = complete_spec()
    spec["origin"] = [sentence]

    joined = "\n".join(legacy_power_summary(spec))

    assert "12.5%" not in joined
    assert "暴击率提高20%" in joined


def test_legacy_summary_redacts_financial_percentage_across_conjunction() -> None:
    spec = complete_spec()
    spec["origin"] = ["手续费同时调整为12.5%"]

    assert "12.5%" not in "\n".join(legacy_power_summary(spec))


def test_legacy_summary_percentages_use_nearest_preceding_governing_cue() -> None:
    spec = complete_spec()
    spec["origin"] = ["手续费同时调整为12.5%并使暴击率20%"]

    joined = "\n".join(legacy_power_summary(spec))

    assert "12.5%" not in joined
    assert "暴击率20%" in joined


def test_legacy_summary_percentage_uses_following_cue_only_without_preceding_cue() -> None:
    spec = complete_spec()
    spec["origin"] = ["20%的暴击率，12.5%的手续费"]

    joined = "\n".join(legacy_power_summary(spec))

    assert "20%的暴击率" in joined
    assert "12.5%的手续费" not in joined


@pytest.mark.parametrize(
    "gameplay_term",
    ["暴击", "抗性", "伤害", "命中", "闪避", "速度", "生命", "法力", "冷却", "加成"],
)
def test_legacy_summary_preserves_percentage_when_gameplay_semantics_are_nearer(
    gameplay_term: str,
) -> None:
    spec = complete_spec()
    spec["origin"] = [f"手续费调整后{gameplay_term}提高20%"]

    joined = "\n".join(legacy_power_summary(spec))

    assert f"{gameplay_term}提高20%" in joined


def test_legacy_summary_financial_percentage_wins_distance_ties() -> None:
    spec = complete_spec()
    spec["origin"] = ["税20%暴击"]

    assert "20%" not in "\n".join(legacy_power_summary(spec))


@pytest.mark.parametrize(
    ("sentence", "preserved"),
    [
        ("暴击状态结束后12.5%的手续费", None),
        ("暴击状态结束后12.5%作为手续费", None),
        ("暴击率20%并收取12.5%手续费", "暴击率20%"),
    ],
)
def test_legacy_summary_postfix_financial_noun_overrides_preceding_gameplay_cue(
    sentence: str,
    preserved: str | None,
) -> None:
    spec = complete_spec()
    spec["origin"] = [sentence]

    joined = "\n".join(legacy_power_summary(spec))

    assert "12.5%" not in joined
    if preserved is not None:
        assert preserved in joined


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


def test_prompt_slice_prefers_exact_path_alias_over_longer_contains_match() -> None:
    spec = complete_spec()
    spec["paths"][0]["name"] = "Mage"
    spec["paths"][0]["branches"] = ["Wizard", "Sorcerer"]
    spec["paths"][1]["name"] = "Fire Mage"
    spec["paths"][1]["branches"] = ["Flame Adept", "Ember Sage"]

    result = power_system_prompt_slice(spec, path_hint="Mage")

    assert result["paths"] == [normalize_power_system_spec(spec)["paths"][0]]


def test_prompt_slice_uses_longest_bidirectional_path_alias_for_production_class_name() -> None:
    spec = complete_spec()
    spec["paths"][0]["name"] = "元素"
    spec["paths"][0]["branches"] = ["元素战士", "符文战士"]
    spec["paths"][1]["branches"] = ["元素法师", "冰霜法师"]

    result = power_system_prompt_slice(spec, stage_hint=12, path_hint="元素法师学徒")

    assert result["paths"] == [normalize_power_system_spec(spec)["paths"][1]]
    assert result["paths"][0]["branches"][0] == "元素法师"


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
