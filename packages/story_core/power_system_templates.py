from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
import math
from types import MappingProxyType
from typing import Any, cast


REQUIRED_SECTIONS = (
    "origin",
    "stages",
    "paths",
    "skills",
    "resources",
    "costs",
    "counters",
    "boundaries",
    "continuity_ledger",
)


def _stages(*names: str) -> list[dict[str, str]]:
    return [
        {
            "name": name,
            "description": "说明进入条件、能力变化、资源消耗和失败代价。",
        }
        for name in names
    ]


def _template(
    *,
    system_form: str,
    stages: list[dict[str, str]],
    minimum_path_count: int,
    branching_rules: list[str],
    resource_rules: list[str],
    cost_rules: list[str],
    conflict_rules: list[str],
    ledger_fields: list[str],
    quality_checks: list[str],
    fixed_milestones: list[int] | None = None,
) -> dict[str, object]:
    template: dict[str, object] = {
        "system_form": system_form,
        "required_sections": list(REQUIRED_SECTIONS),
        "progression_shape": {"stages": stages},
        "branching_rules": branching_rules,
        "resource_rules": resource_rules,
        "cost_rules": cost_rules,
        "conflict_rules": conflict_rules,
        "ledger_fields": ledger_fields,
        "quality_checks": quality_checks,
        "minimum_path_count": minimum_path_count,
    }
    if fixed_milestones is not None:
        template["fixed_milestones"] = fixed_milestones
    return template


def _freeze(value: object) -> object:
    if isinstance(value, dict):
        return MappingProxyType({key: _freeze(item) for key, item in value.items()})
    if isinstance(value, (list, tuple)):
        return tuple(_freeze(item) for item in value)
    return value


def _thaw(value: object) -> object:
    if isinstance(value, Mapping):
        return {key: _thaw(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


_POWER_SYSTEM_TEMPLATE_DATA = {
    "generic_webnovel": _template(
        system_form="自适应超凡体系",
        stages=_stages("起步阶段", "成型阶段", "高阶阶段"),
        minimum_path_count=2,
        branching_rules=["根据项目核心创意建立至少两条可区分路线，避免堆叠无关体系。"],
        resource_rules=["资源必须映射到路线、技能和阶段，并说明获取与转化方式。"],
        cost_rules=["每次突破和越级行动都要有消耗、风险或长期代价。"],
        conflict_rules=["定义同级胜负、路线克制、越级上限和强者受限原因。"],
        ledger_fields=["当前阶段", "路线", "技能", "装备或媒介", "资源", "负面状态"],
        quality_checks=["来源明确", "成长连续", "路线可辨", "资源闭环", "边界可执行"],
    ),
    "game_webnovel": _template(
        system_form="等级职业体系",
        stages=_stages("Lv.1见习", "Lv.10基础职业", "Lv.20专精", "Lv.30进阶职业", "Lv.60传承职业"),
        minimum_path_count=6,
        fixed_milestones=[1, 10, 20, 30, 60],
        branching_rules=["六个基础职业各自说明核心资源、武器护甲、战斗循环和至少两个进阶方向。"],
        resource_rules=["经验、技能点、装备、材料和货币必须形成可追踪的产出与消耗循环。"],
        cost_rules=["规定死亡惩罚、耐久损耗、技能冷却、转职失败和稀有资源损失。"],
        conflict_rules=["定义等级差、职业克制、队伍职责和越级战斗边界。"],
        ledger_fields=["等级", "职业与专精", "属性", "技能", "装备", "经验", "货币材料", "状态效果"],
        quality_checks=["六职业完整", "里程碑无冲突", "职业循环具体", "装备技能闭环", "克制可执行"],
    ),
    "xuanhuan": _template(
        system_form="境界血脉体系",
        stages=_stages("血脉觉醒", "境界成型", "领域法则"),
        minimum_path_count=2,
        branching_rules=["至少区分血脉、体质、武魂或异物等两条成长路线。"],
        resource_rules=["灵材、异物、传承和炼化条件必须对应具体境界与能力。"],
        cost_rules=["机缘伴随炼化风险、血脉反噬、根基损伤或法则冲突。"],
        conflict_rules=["说明同境强弱依据、跨境凭依、领域克制和不可跨越边界。"],
        ledger_fields=["境界", "血脉体质", "战技", "异物", "资源", "反噬", "法则领悟"],
        quality_checks=["境界连续", "血脉有源", "机缘有险", "跨境有据", "法则受限"],
    ),
    "xianxia": _template(
        system_form="修真因果体系",
        stages=_stages("炼气筑基", "结丹元神", "渡劫飞升"),
        minimum_path_count=2,
        branching_rules=["至少提供剑修、丹修、法宝、术法等两条道途并说明兼修限制。"],
        resource_rules=["灵气、寿元、丹材、法宝和传承稀缺性必须互相约束。"],
        cost_rules=["突破承担心魔、天劫、因果、寿元或道基受损风险。"],
        conflict_rules=["规定境界压制、法宝术法克制、因果反噬和越阶上限。"],
        ledger_fields=["境界", "灵根", "功法道途", "术法", "法宝", "寿元", "因果", "劫数"],
        quality_checks=["道途清晰", "寿元一致", "资源稀缺", "因果兑现", "渡劫有据"],
    ),
    "urban": _template(
        system_form="都市异能体系",
        stages=_stages("异常觉醒", "能力掌控", "高危权能"),
        minimum_path_count=2,
        branching_rules=["至少建立两类异能或隐秘职业，并区分现实身份与超凡职责。"],
        resource_rules=["训练、情报、组织许可、现实资产和能力媒介共同限制成长。"],
        cost_rules=["力量使用带来身体负担、身份暴露、法律追责或舆论风险。"],
        conflict_rules=["超凡冲突仍受法律、监控、组织和社会资源约束。"],
        ledger_fields=["觉醒等级", "异能", "现实身份", "组织关系", "暴露度", "身体负担", "社会后果"],
        quality_checks=["现实约束有效", "身份掩护可信", "机构会反应", "代价可见", "能力非万能"],
    ),
    "romance": _template(
        system_form="血脉契约共鸣体系",
        stages=_stages("血脉显现", "契约共鸣", "命运抉择"),
        minimum_path_count=2,
        branching_rules=["至少区分两种血脉、契约或共鸣路径，并保留角色自主选择。"],
        resource_rules=["信任、记忆、血脉媒介和契约条件影响能力，但不量化替代感情。"],
        cost_rules=["违约、误判共鸣和强行干涉关系会造成反噬、失忆或能力失控。"],
        conflict_rules=["超凡规则不能证明爱情、取消同意或替代真实关系选择。"],
        ledger_fields=["血脉状态", "契约条款", "共鸣条件", "能力", "反噬", "知情与同意", "关系变化"],
        quality_checks=["感情不数值化", "选择有自主性", "契约有边界", "共鸣会变化", "代价能兑现"],
    ),
    "suspense": _template(
        system_form="超凡调查体系",
        stages=_stages("感知异常", "解析线索", "触及真相"),
        minimum_path_count=2,
        branching_rules=["至少区分灵视、通灵、记忆读取等两类调查路线。"],
        resource_rules=["能力依赖现场、媒介、记忆完整度、精神稳定或有限使用次数。"],
        cost_rules=["使用能力可能产生误判、污染、记忆缺损、精神创伤或暴露。"],
        conflict_rules=["能力只提供可质疑线索，必须规定证据效力、不可知范围和反制方法。"],
        ledger_fields=["调查能力", "使用次数", "证据效力", "误判条件", "精神状态", "污染", "未知范围"],
        quality_checks=["推理闭环独立", "线索可验证", "误判有条件", "证据有限", "真相不直给"],
    ),
    "rules_mystery": _template(
        system_form="规则权限污染体系",
        stages=_stages("规则识别", "权限争夺", "污染临界"),
        minimum_path_count=2,
        branching_rules=["至少区分规则权限、认知抗性、异常道具等两条生存路线。"],
        resource_rules=["权限、线索、异常道具和认知稳定度必须通过行动获得和消耗。"],
        cost_rules=["违规、权限滥用和污染累积会造成明确且不可随意撤销的后果。"],
        conflict_rules=["真假规则必须可验证，不存在无条件免疫，并规定存活边界。"],
        ledger_fields=["已知规则", "验证记录", "权限", "污染阶段", "认知抗性", "异常道具", "违规后果"],
        quality_checks=["规则可验证", "权限有代价", "污染递进", "无绝对免疫", "存活条件明确"],
    ),
}


POWER_SYSTEM_TEMPLATES = cast(
    Mapping[str, Mapping[str, object]],
    _freeze(_POWER_SYSTEM_TEMPLATE_DATA),
)


def copy_power_system_template(plugin_id: str) -> dict[str, object]:
    return cast(dict[str, object], _thaw(POWER_SYSTEM_TEMPLATES[plugin_id]))


_COMPACT_TEMPLATE_FIELDS = (
    "system_form",
    "required_sections",
    "progression_shape",
    "branching_rules",
    "resource_rules",
    "cost_rules",
    "conflict_rules",
    "ledger_fields",
    "quality_checks",
    "minimum_path_count",
    "fixed_milestones",
)
_COMPACT_LIST_CAP = 12
_COMPACT_MAPPING_CAP = 20
_COMPACT_STRING_CAP = 180
_REQUIRED_SECTIONS_ITEM_CAP = 80
_FIXED_MILESTONE_CAP = 16


def _compact_string(value: str, limit: int = _COMPACT_STRING_CAP) -> str:
    return "".join(character for character in value if character.isprintable())[:limit]


def _compact_object_string(value: Any, limit: int = _COMPACT_STRING_CAP) -> str:
    try:
        return _compact_string(str(value), limit)
    except Exception:
        return ""


def _bounded_integer(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return min(max(value, minimum), maximum)


def _compact_json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {
            _compact_object_string(key): _compact_json_value(item)
            for key, item in list(value.items())[:_COMPACT_MAPPING_CAP]
        }
    if isinstance(value, (list, tuple)):
        return [_compact_json_value(item) for item in value[:_COMPACT_LIST_CAP]]
    if isinstance(value, str):
        return _compact_string(value)
    if isinstance(value, bool):
        return value
    if isinstance(value, int):
        return min(max(value, -1_000_000), 1_000_000)
    if isinstance(value, float):
        if not math.isfinite(value):
            return 0.0
        return min(max(value, -1_000_000.0), 1_000_000.0)
    if value is None:
        return value
    return _compact_object_string(value)


def compact_power_system_template(template: Mapping[str, object]) -> dict[str, object]:
    compact = {
        field: _compact_json_value(template[field])
        for field in _COMPACT_TEMPLATE_FIELDS
        if field in template
    }
    required_sections = template.get("required_sections")
    if isinstance(required_sections, (list, tuple)):
        compact["required_sections"] = [
            _compact_object_string(item, _REQUIRED_SECTIONS_ITEM_CAP)
            for item in required_sections[:_COMPACT_LIST_CAP]
        ]
    if "minimum_path_count" in template:
        compact["minimum_path_count"] = _bounded_integer(
            template["minimum_path_count"], default=2, minimum=1, maximum=64
        )
    if "fixed_milestones" in template:
        milestones = template["fixed_milestones"]
        valid_milestones = (
            [
                item
                for item in milestones
                if isinstance(item, int) and not isinstance(item, bool)
            ]
            if isinstance(milestones, (list, tuple))
            else []
        )
        compact["fixed_milestones"] = [
            _bounded_integer(item, default=0, minimum=0, maximum=1_000_000)
            for item in valid_milestones[:_FIXED_MILESTONE_CAP]
        ]
    return deepcopy(compact)
