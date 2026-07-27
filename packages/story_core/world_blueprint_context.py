from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import re
from typing import Any

from packages.story_core.attribute_allocation import normalize_attribute_allocation_rule
from packages.story_core.power_systems import normalize_power_system_spec, power_system_prompt_slice


MANAGED_MARKER = "<!-- managed: world-blueprint/v1 -->"

RULE_FIELDS = (
    "world_rules",
    "power_system",
    "progression_rules",
    "economy_rules",
    "quest_rules",
    "faction_rules",
    "panel_rules",
    "reality_bridge_rules",
)

_RULE_KEYWORDS = {
    "power_system": (
        "等级",
        "技能",
        "装备",
        "武器",
        "法杖",
        "战斗",
        "怪物",
        "职业",
        "转职",
        "生命",
        "法力",
    ),
    "progression_rules": (
        "升级",
        "进阶",
        "成长",
        "突破",
        "经验",
        "熟练度",
        "属性",
    ),
    "economy_rules": (
        "铜币",
        "材料",
        "掉落",
        "交易",
        "价格",
        "背包",
        "寄售",
        "收购",
        "药水",
        "修理",
        "钱袋",
    ),
    "quest_rules": ("任务", "委托", "登记", "提交", "前置", "奖励"),
    "faction_rules": ("玩家", "公会", "阵营", "势力", "仓库", "守卫"),
    "panel_rules": ("面板", "生命", "法力", "经验", "耐久", "等级", "背包"),
    "reality_bridge_rules": (
        "现实余额",
        "现实到账",
        "人民币",
        "提现",
        "房租",
        "宽带",
        "信用卡",
        "银行卡",
        "银行账户",
        "现实工作",
    ),
}

_POWER_SPEC_KEYWORDS = (
    "power",
    "combat",
    "class",
    "advancement",
    "level",
    "skill",
    "equipment",
    "力量",
    "战斗",
    "职业",
    "转职",
    "进阶",
    "晋升",
    "等级",
    "技能",
    "装备",
)

_CJK_SEQUENCE = re.compile(r"[\u4e00-\u9fff]+")
_GENERIC_QUEST_TERMS = (
    "完成任务后",
    "完成委托后",
    "完成",
    "任务",
    "委托",
    "后续",
    "领取",
    "奖励",
    "提交",
    "登记",
    "前置",
)
_GENERIC_NPC_SHORT_NAMES = {
    "守卫",
    "村长",
    "铁匠",
    "商人",
    "店员",
    "管事",
    "掌柜",
    "导师",
    "队长",
    "老板",
    "伙计",
    "药师",
    "医师",
}


def merge_world_blueprint(current: Any, patch: Any) -> dict[str, Any]:
    merged = deepcopy(current) if isinstance(current, dict) else {}
    if isinstance(patch, dict):
        merged.update(deepcopy(patch))
    return merged


def render_world_markdown(title: Any, blueprint: Any) -> str:
    world = blueprint if isinstance(blueprint, dict) else {}
    lines = [MANAGED_MARKER, "", f"# 《{_markdown_title(title)}》世界观"]

    _append_section(lines, "世界背景", world.get("premise"))
    _append_section(lines, "世界规则", world.get("world_rules"))
    _append_section(lines, "经济体系", world.get("economy_rules"))
    _append_section(lines, "任务体系", world.get("quest_rules"))
    _append_quest_network(lines, world.get("quest_network"))
    _append_section(lines, "现实桥接", world.get("reality_bridge_rules"))
    _append_section(lines, "地点", world.get("locations"))
    _append_combined_section(
        lines,
        "阵营",
        (("阵营规则", world.get("faction_rules")), ("阵营名录", world.get("factions"))),
    )
    return "\n".join(lines).rstrip() + "\n"


def render_power_markdown(title: Any, blueprint: Any) -> str:
    world = blueprint if isinstance(blueprint, dict) else {}
    lines = [MANAGED_MARKER, "", f"# 《{_markdown_title(title)}》力量体系"]
    structured = world.get("power_system_spec")

    if isinstance(structured, dict) and structured:
        attribute_allocation = normalize_attribute_allocation_rule(
            structured.get("attribute_allocation")
        )
        sections = (
            ("体系总览", (("体系名称", structured.get("name")),)),
            ("力量来源", (("来源", structured.get("origin")),)),
            ("属性", (("属性", structured.get("attributes")),)),
            (
                "阶段与晋升",
                (("阶段", structured.get("stages")), ("晋升规则", structured.get("advancement"))),
            ),
            ("职业与路线", (("路线", structured.get("paths")),)),
            (
                "技能与装备",
                (("技能", structured.get("skills")), ("装备", structured.get("equipment"))),
            ),
            (
                "资源与代价",
                (("资源", structured.get("resources")), ("代价", structured.get("costs"))),
            ),
            (
                "克制与边界",
                (("克制", structured.get("counters")), ("边界", structured.get("boundaries"))),
            ),
            ("社会影响", (("影响", structured.get("social_impact")),)),
            ("信息可见性", (("可见性", structured.get("visibility")),)),
            ("连续性账本", (("账本字段", structured.get("continuity_ledger")),)),
        )
        for heading, groups in sections:
            _append_structured_power_section(lines, heading, groups)
            if heading == "属性" and attribute_allocation:
                _append_structured_power_section(
                    lines,
                    "属性分配",
                    (
                        ("模式", attribute_allocation["mode"]),
                        ("每级点数", attribute_allocation["points_per_level"]),
                        ("起始等级", attribute_allocation["starting_level"]),
                        ("允许保留", "是" if attribute_allocation["allow_carry"] else "否"),
                        ("初始值", attribute_allocation["base_attributes"]),
                        ("洗点规则", attribute_allocation["respec_rule"]),
                    ),
                )
        return "\n".join(lines).rstrip() + "\n"

    _append_section(lines, "力量与职业", world.get("power_system"))
    _append_section(lines, "成长与战斗", world.get("progression_rules"))
    _append_section(lines, "面板规则", world.get("panel_rules"))
    _append_combined_section(
        lines,
        "世界硬约束",
        (("约束", world.get("constraints")), ("禁止破坏", world.get("forbidden_breaks"))),
    )
    return "\n".join(lines).rstrip() + "\n"


def _append_structured_power_section(
    lines: list[str],
    heading: str,
    groups: tuple[tuple[str, Any], ...],
) -> None:
    lines.extend(("", f"## {heading}", ""))
    populated = [(label, value) for label, value in groups if _has_content(value)]
    if len(groups) == 1:
        if populated:
            lines.extend(_structured_power_group_lines(*populated[0]))
        return
    for index, (label, value) in enumerate(populated):
        if index:
            lines.append("")
        lines.extend((f"### {label}", ""))
        lines.extend(_structured_power_group_lines(label, value))


def _structured_power_group_lines(label: str, value: Any) -> list[str]:
    field_order = {
        "阶段": ("level", "entry", "change", "failure"),
        "路线": (
            "role",
            "core_attributes",
            "core_resource",
            "weapons",
            "armor",
            "skill_categories",
            "combat_loop",
            "strengths",
            "weaknesses",
            "branches",
            "transfer_task",
            "advancement",
        ),
    }.get(label)
    if field_order is None or not isinstance(value, (list, tuple)):
        return _structured_markdown_list(value)

    lines: list[str] = []
    for item in value:
        if not isinstance(item, dict):
            lines.append(f"- {_structured_inline_markdown(item)}")
            continue
        escaped_name = _markdown_escape_line(
            item.get("name") or item.get("title") or ""
        )
        lines.append(f"- **{escaped_name}**" if escaped_name else "- （未命名）")
        for field in field_order:
            if _has_content(item.get(field)):
                lines.append(
                    f"  - **{_structured_field_label(field)}**："
                    f"{_structured_inline_markdown(item[field])}"
                )
    return lines


def _markdown_escape_line(value: Any) -> str:
    try:
        text = str(value or "")
    except Exception:
        return ""
    one_line = " ".join(
        "".join(character if character.isprintable() else " " for character in text).split()
    )
    escaped: list[str] = []
    for character in one_line:
        if character in "\\`*_[]<>#":
            escaped.append("\\")
        escaped.append(character)
    return "".join(escaped)


def _structured_markdown_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [f"- {_structured_inline_markdown(item)}" for item in value]
    if isinstance(value, dict):
        if any(key in value for key in ("name", "title")):
            return [f"- {_structured_inline_markdown(value)}"]
        return [
            f"- **{_structured_field_label(key)}**："
            f"{_structured_inline_markdown(value[key])}"
            for key in sorted(value, key=str)
        ]
    return [f"- {_structured_inline_markdown(value)}"]


def _structured_inline_markdown(value: Any) -> str:
    if isinstance(value, dict):
        name = _markdown_escape_line(value.get("name") or value.get("title") or "")
        details = [
            f"{_structured_field_label(key)}：{_structured_inline_markdown(value[key])}"
            for key in sorted(value, key=str)
            if key not in {"name", "title"} and _has_content(value[key])
        ]
        if name and details:
            return f"**{name}**：" + "；".join(details)
        if name:
            return f"**{name}**"
        return "；".join(details) or "（空）"
    if isinstance(value, (list, tuple)):
        return "；".join(_structured_inline_markdown(item) for item in value)
    if value is None:
        return "（空）"
    return _markdown_escape_line(value)


def _structured_field_label(key: Any) -> str:
    return _markdown_escape_line(_field_label(key))


def sync_world_markdown(
    root: str | Path,
    title: Any,
    blueprint: Any,
    force: bool = False,
) -> dict[str, dict[str, Any]]:
    settings_dir = Path(root) / "设定集"
    settings_dir.mkdir(parents=True, exist_ok=True)
    documents = {
        "world": (settings_dir / "世界观.md", render_world_markdown(title, blueprint)),
        "power": (settings_dir / "力量体系.md", render_power_markdown(title, blueprint)),
    }

    results: dict[str, dict[str, Any]] = {}
    for key, (path, content) in documents.items():
        existed = path.exists()
        managed = False if force else existed and _has_managed_marker(path)
        written = force or not existed or managed
        if written:
            path.write_text(content, encoding="utf-8")
        results[key] = {
            "path": str(path),
            "written": written,
            "reason": (
                "forced"
                if force and existed and not managed
                else "refreshed"
                if managed
                else "created"
                if not existed
                else "unmanaged"
            ),
        }
    return results


def _markdown_title(title: Any) -> str:
    value = str(title or "").strip()
    return value or "未命名作品"


def _has_content(value: Any) -> bool:
    return value not in (None, "", [], {})


def _append_section(lines: list[str], heading: str, value: Any) -> None:
    if not _has_content(value):
        return
    lines.extend(("", f"## {heading}", ""))
    lines.extend(_markdown_list(value))


def _append_combined_section(
    lines: list[str],
    heading: str,
    groups: tuple[tuple[str, Any], ...],
) -> None:
    populated = [(label, value) for label, value in groups if _has_content(value)]
    if not populated:
        return
    lines.extend(("", f"## {heading}", ""))
    if len(populated) == 1:
        lines.extend(_markdown_list(populated[0][1]))
        return
    for index, (label, value) in enumerate(populated):
        if index:
            lines.append("")
        lines.extend((f"### {label}", ""))
        lines.extend(_markdown_list(value))


def _append_quest_network(lines: list[str], value: Any) -> None:
    if not _has_content(value):
        return
    if not isinstance(value, dict):
        _append_section(lines, "任务网络", value)
        return

    lines.extend(("", "## 任务网络", ""))
    active_chains = value.get("active_chains")
    if isinstance(active_chains, list):
        for chain in active_chains:
            if not isinstance(chain, dict):
                lines.append(f"- {_inline_markdown(chain)}")
                continue
            name = str(chain.get("name") or chain.get("title") or "未命名任务链").strip()
            description = str(chain.get("description") or chain.get("summary") or "").strip()
            chain_line = f"- **{name}**"
            if description:
                chain_line += f"：{description}"
            lines.append(chain_line)
            stages = chain.get("stages")
            if isinstance(stages, list):
                for index, stage in enumerate(stages, start=1):
                    lines.append(f"  - 阶段 {index}：{_inline_markdown(stage)}")
            elif _has_content(stages):
                lines.append(f"  - **阶段**：{_inline_markdown(stages)}")
            for key in sorted(chain, key=str):
                if key in {"name", "title", "description", "summary", "stages"}:
                    continue
                lines.append(f"  - **{_field_label(key)}**：{_inline_markdown(chain[key])}")
    elif _has_content(active_chains):
        lines.append(
            f"- **{_field_label('active_chains')}**：{_inline_markdown(active_chains)}"
        )

    for key in sorted(value, key=str):
        if key == "active_chains":
            continue
        lines.append(f"- **{_field_label(key)}**：{_inline_markdown(value[key])}")


def _markdown_list(value: Any) -> list[str]:
    if isinstance(value, (list, tuple)):
        return [f"- {_inline_markdown(item)}" for item in value]
    if isinstance(value, dict):
        if any(key in value for key in ("name", "title")):
            return [f"- {_inline_markdown(value)}"]
        return [
            f"- **{_field_label(key)}**：{_inline_markdown(value[key])}"
            for key in sorted(value, key=str)
        ]
    return [f"- {_inline_markdown(value)}"]


def _inline_markdown(value: Any) -> str:
    if isinstance(value, dict):
        name = str(value.get("name") or value.get("title") or "").strip()
        details = [
            f"{_field_label(key)}：{_inline_markdown(value[key])}"
            for key in sorted(value, key=str)
            if key not in {"name", "title"} and _has_content(value[key])
        ]
        if name and details:
            return f"**{name}**；" + "；".join(details)
        if name:
            return f"**{name}**"
        return "；".join(details) or "（空）"
    if isinstance(value, (list, tuple)):
        return "；".join(_inline_markdown(item) for item in value)
    if value is None:
        return "（空）"
    return str(value).strip()


def _field_label(key: Any) -> str:
    labels = {
        "active_chains": "进行中的任务链",
        "description": "描述",
        "goal": "目标",
        "npc_links": "关联人物",
        "reward_rules": "奖励规则",
        "stages": "阶段",
        "summary": "摘要",
        "advancement": "晋升",
        "armor": "护甲",
        "branches": "分支",
        "change": "能力变化",
        "combat_loop": "战斗循环",
        "core_attributes": "核心属性",
        "core_resource": "核心资源",
        "effect": "效果",
        "entry": "进入条件",
        "failure": "失败后果",
        "level": "等级",
        "role": "职责",
        "skill_categories": "技能类别",
        "strengths": "强项",
        "transfer_task": "转职任务",
        "weaknesses": "弱项",
        "weapons": "武器",
    }
    return labels.get(str(key), str(key).replace("_", " "))


def _has_managed_marker(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            first_line = handle.readline()
    except UnicodeDecodeError:
        return False
    return first_line.rstrip("\r\n") == MANAGED_MARKER


def select_world_context(
    blueprint: Any,
    relevance_text: Any,
    max_rules: int = 8,
) -> dict[str, Any]:
    if isinstance(max_rules, bool) or not isinstance(max_rules, int) or max_rules < 0:
        raise ValueError("max_rules must be a non-negative integer")
    if not isinstance(blueprint, dict):
        return {}

    selected: dict[str, Any] = {}
    premise = blueprint.get("premise")
    if premise not in (None, "", [], {}):
        selected["premise"] = deepcopy(premise)

    rule_budget = max_rules
    world_rules = _rule_values(blueprint, "world_rules")[: min(2, rule_budget)]
    if world_rules:
        selected["world_rules"] = deepcopy(world_rules)
        rule_budget -= len(world_rules)
    seen_rules = set(world_rules)

    relevance = str(relevance_text or "").casefold()
    if _matches_power_spec(relevance):
        power_context = outline_power_system_context(blueprint.get("power_system_spec"))
        if power_context:
            selected["power_system_spec"] = power_context
    matched_modules = [
        (field, _rule_values(blueprint, field))
        for field in RULE_FIELDS[1:]
        if _matches_module(field, relevance) and _rule_values(blueprint, field)
    ]
    positions = {field: 0 for field, _ in matched_modules}

    while rule_budget and matched_modules:
        added = False
        for field, values in matched_modules:
            position = positions[field]
            while position < len(values) and values[position] in seen_rules:
                position += 1
            positions[field] = position
            if position >= len(values):
                continue
            rule = values[position]
            selected.setdefault(field, []).append(deepcopy(rule))
            seen_rules.add(rule)
            positions[field] += 1
            rule_budget -= 1
            added = True
            if not rule_budget:
                break
        if not added:
            break

    matching_chains = _matching_quest_chains(blueprint.get("quest_network"), relevance)
    if matching_chains:
        selected["quest_network"] = {"active_chains": matching_chains}

    for field in ("locations", "factions"):
        matching_entities = _matching_entities(blueprint.get(field), relevance)
        if matching_entities:
            selected[field] = matching_entities

    return selected


def outline_power_system_context(spec: Any) -> dict[str, Any]:
    """Build the compact all-stage contract needed by outline planning."""

    base = power_system_prompt_slice(spec)
    if not base:
        return {}
    normalized = normalize_power_system_spec(spec)
    stages = deepcopy(normalized.get("stages", []))

    paths: list[dict[str, Any]] = []
    for path in normalized.get("paths", []):
        if not isinstance(path, dict):
            continue
        compact_path = {
            key: deepcopy(path[key])
            for key in ("name", "branches", "advancement")
            if path.get(key) not in (None, "", [], {})
        }
        if compact_path:
            paths.append(compact_path)

    result = {
        key: deepcopy(normalized[key])
        for key in (
            "name",
            "origin",
            "advancement",
            "costs",
            "counters",
            "boundaries",
            "continuity_ledger",
        )
        if base.get(key) not in (None, "", [], {})
    }
    if stages:
        result["stages"] = stages
    if paths:
        result["paths"] = paths
    return _fit_outline_power_budget(result)


def _matches_power_spec(relevance: str) -> bool:
    for keyword in _POWER_SPEC_KEYWORDS:
        folded = keyword.casefold()
        if keyword.isascii():
            if re.search(
                rf"(?<![A-Za-z0-9_]){re.escape(folded)}(?![A-Za-z0-9_])",
                relevance,
            ):
                return True
        elif folded in relevance:
            return True
    return False


def _outline_json_length(value: dict[str, Any]) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False))


def _outline_text(value: Any, limit: int) -> str:
    return str(value or "")[:limit]


def _major_outline_stages(stages: Any) -> list[dict[str, Any]]:
    values = [stage for stage in stages if isinstance(stage, dict)] if isinstance(stages, list) else []
    major_levels = {1, 10, 20, 30, 60}
    selected = [
        stage
        for index, stage in enumerate(values)
        if index == 0 or stage.get("level") in major_levels
    ]
    return selected or values[:1]


def _compact_outline_contract(
    value: dict[str, Any],
    *,
    stages: list[dict[str, Any]],
    paths: list[dict[str, Any]],
    text_limit: int,
    list_limit: int,
) -> dict[str, Any]:
    candidate: dict[str, Any] = {"name": _outline_text(value.get("name"), text_limit)}
    if stages:
        candidate["stages"] = [
            {
                key: stage[key] if key == "level" else _outline_text(stage[key], text_limit)
                for key in ("name", "level", "entry", "change", "failure")
                if stage.get(key) not in (None, "", [], {})
            }
            for stage in stages
        ]

    compact_paths: list[dict[str, Any]] = []
    for path in paths:
        branches = [
            _outline_text(branch, text_limit)
            for branch in path.get("branches", [])[:2]
        ]
        if not path.get("name") or not branches:
            continue
        compact_path = {
            "name": _outline_text(path["name"], text_limit),
            "branches": branches,
        }
        advancement = [
            _outline_text(item, text_limit)
            for item in path.get("advancement", [])[:list_limit]
        ]
        if advancement:
            compact_path["advancement"] = advancement
        compact_paths.append(compact_path)
    if compact_paths:
        candidate["paths"] = compact_paths

    for field in (
        "origin",
        "advancement",
        "costs",
        "counters",
        "boundaries",
        "continuity_ledger",
    ):
        items = value.get(field) if isinstance(value.get(field), list) else []
        if items:
            candidate[field] = [
                _outline_text(item, text_limit) for item in items[:list_limit]
            ]
    return candidate


def _fit_outline_power_budget(value: dict[str, Any]) -> dict[str, Any]:
    if _outline_json_length(value) <= 5000:
        return deepcopy(value)

    stages = _major_outline_stages(value.get("stages"))
    paths = [
        path
        for path in (value.get("paths") if isinstance(value.get("paths"), list) else [])
        if isinstance(path, dict) and path.get("name") and path.get("branches")
    ]
    for text_limit, list_limit in ((120, 4), (80, 2), (48, 1), (24, 1), (12, 1)):
        candidate = _compact_outline_contract(
            value,
            stages=stages,
            paths=paths,
            text_limit=text_limit,
            list_limit=list_limit,
        )
        if _outline_json_length(candidate) <= 5000:
            return candidate

    retained_stages = list(stages)
    retained_paths = list(paths)
    while _outline_json_length(candidate) > 5000:
        can_trim_stage = len(retained_stages) > 3
        can_trim_path = len(retained_paths) > 1
        if not can_trim_stage and not can_trim_path:
            break
        if can_trim_path and (not can_trim_stage or len(retained_paths) > len(retained_stages)):
            retained_paths.pop()
        else:
            retained_stages.pop()
        candidate = _compact_outline_contract(
            value,
            stages=retained_stages,
            paths=retained_paths,
            text_limit=12,
            list_limit=1,
        )

    for text_limit in (8, 4, 2, 1):
        if _outline_json_length(candidate) <= 5000:
            return candidate
        candidate = _compact_outline_contract(
            value,
            stages=retained_stages,
            paths=retained_paths,
            text_limit=text_limit,
            list_limit=1,
        )

    if _outline_json_length(candidate) <= 5000:
        return candidate
    return _compact_outline_contract(
        value,
        stages=stages[:3],
        paths=paths[:1],
        text_limit=1,
        list_limit=1,
    )


def flatten_selected_rules(selected: Any) -> list[Any]:
    if not isinstance(selected, dict):
        return []

    flattened: list[Any] = []
    for field in RULE_FIELDS:
        values = selected.get(field)
        if isinstance(values, list):
            flattened.extend(deepcopy(values))
    return flattened


def _rule_values(blueprint: dict[str, Any], field: str) -> list[Any]:
    values = blueprint.get(field)
    if not isinstance(values, list):
        return []

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str):
            continue
        rule = value.strip()
        if not rule or rule in seen:
            continue
        seen.add(rule)
        normalized.append(rule)
    return normalized


def _matches_module(field: str, relevance: str) -> bool:
    return any(keyword.casefold() in relevance for keyword in _RULE_KEYWORDS[field])


def _matching_entities(entities: Any, relevance: str) -> list[dict[str, Any]]:
    if not isinstance(entities, list):
        return []

    matches: list[tuple[dict[str, Any], str]] = []
    for entity in entities:
        if not isinstance(entity, dict):
            continue
        identifiers = [
            str(entity.get(field) or "").strip().casefold()
            for field in ("name", "title")
        ]
        matched_identifiers = [
            identifier
            for identifier in identifiers
            if len(identifier) >= 2 and identifier in relevance
        ]
        if matched_identifiers:
            matches.append((entity, max(matched_identifiers, key=len)))

    return [
        deepcopy(entity)
        for entity, identifier in matches
        if not any(
            identifier != other and identifier in other
            for _, other in matches
        )
    ][:3]


def _matching_quest_chains(quest_network: Any, relevance: str) -> list[dict[str, Any]]:
    if not isinstance(quest_network, dict):
        return []
    active_chains = quest_network.get("active_chains")
    if not isinstance(active_chains, list):
        return []

    chains = [chain for chain in active_chains if isinstance(chain, dict)]
    exact_name_matches = [
        (chain, name)
        for chain in chains
        if (name := _chain_name(chain)) and name in relevance
    ]
    if exact_name_matches:
        matching_names = {name for _, name in exact_name_matches}
        most_specific_names = {
            name
            for name in matching_names
            if not any(name != other and name in other for other in matching_names)
        }
        return [
            deepcopy(chain)
            for chain, name in exact_name_matches
            if name in most_specific_names
        ]

    return [
        deepcopy(chain)
        for chain in chains
        if _quest_chain_matches(chain, relevance)
    ]


def _quest_chain_matches(chain: dict[str, Any], relevance: str) -> bool:
    if any(identifier in relevance for identifier in _quest_identifiers(chain)):
        return True

    relevance_bigrams = _cjk_bigrams(_remove_generic_quest_terms(relevance))
    chain_text = " ".join(_text_values(chain)).casefold()
    chain_bigrams = _cjk_bigrams(_remove_generic_quest_terms(chain_text))
    return len(relevance_bigrams & chain_bigrams) >= 2


def _quest_identifiers(chain: dict[str, Any]) -> set[str]:
    identifiers: set[str] = set()

    npc_links = chain.get("npc_links")
    if isinstance(npc_links, (list, tuple)):
        for link in npc_links:
            if isinstance(link, str):
                values = [link]
            elif isinstance(link, dict):
                values = _name_like_values(link)
            else:
                continue
            npc_identifiers = _cjk_identifiers(values) - _GENERIC_NPC_SHORT_NAMES
            identifiers.update(npc_identifiers)
            identifiers.update(
                identifier[-2:]
                for identifier in npc_identifiers
                if len(identifier) > 2
                and identifier[-2:] not in _GENERIC_NPC_SHORT_NAMES
            )

    stages = chain.get("stages")
    if isinstance(stages, (list, tuple)):
        for stage in stages:
            if isinstance(stage, dict):
                identifiers.update(_cjk_identifiers(_name_like_values(stage)))

    return identifiers


def _chain_name(chain: dict[str, Any]) -> str:
    name = chain.get("name")
    return name.strip().casefold() if isinstance(name, str) else ""


def _cjk_identifiers(values: list[str]) -> set[str]:
    return {
        sequence
        for value in values
        for sequence in _CJK_SEQUENCE.findall(value)
        if len(sequence) >= 2 and sequence not in _GENERIC_QUEST_TERMS
    }


def _name_like_values(value: dict[Any, Any]) -> list[str]:
    return [
        text
        for key, item in value.items()
        if isinstance(key, str)
        and (key.casefold() == "npc" or key.casefold().endswith("name"))
        for text in _text_values(item)
    ]


def _remove_generic_quest_terms(text: str) -> str:
    cleaned = text
    for term in _GENERIC_QUEST_TERMS:
        cleaned = cleaned.replace(term, " ")
    return cleaned


def _cjk_bigrams(text: str) -> set[str]:
    return {
        sequence[index : index + 2]
        for sequence in _CJK_SEQUENCE.findall(text)
        for index in range(len(sequence) - 1)
    }


def _text_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [text for item in value.values() for text in _text_values(item)]
    if isinstance(value, (list, tuple)):
        return [text for item in value for text in _text_values(item)]
    return []
