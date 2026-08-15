from __future__ import annotations

import json
import math
from collections.abc import Mapping
from copy import deepcopy
from itertools import islice
from typing import Any

from packages.story_core.agent_base import compact_text, parse_json_message_content
from packages.story_core.genre_plugins import (
    RULEBOOK_FIELDS,
    merge_plugin_rulebooks,
    plugin_prompt_guide,
    select_genre_plugins,
)
from packages.story_core.model_gateway import ModelRequest, RuntimeModelGateway
from packages.story_core.models import NovelProject
from packages.story_core.novel_type_catalog import (
    normalize_novel_type_ids,
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.power_system_templates import compact_power_system_template
from packages.story_core.power_systems import (
    PowerSystemValidationError,
    legacy_power_summary,
    power_system_prompt_slice,
    validate_power_system_spec,
)
from packages.story_core.runtime_config import resolve_stage_runtime
from packages.story_core.web_game_economy import appraisal_rules, exchange_rules, market_rules


class WorldEnrichmentError(RuntimeError):
    pass


_PROJECT_CONTEXT_BUDGET = 20_000
_PROJECT_CONTEXT_MAX = 24_000
_FINAL_PROMPT_MAX = 30_000
_MIN_PROJECT_CONTEXT_BUDGET = 6_000
_PROJECTION_PROFILES = (
    (240, 8, 4),
    (160, 6, 4),
    (96, 4, 3),
    (48, 2, 2),
    (24, 1, 1),
)


def _selected_novel_type_plugin(project: NovelProject, plugins=None):
    plugins = plugins if plugins is not None else select_genre_plugins(project)
    plugin_by_id = {plugin.plugin_id: plugin for plugin in plugins}
    explicit_ids = normalize_novel_type_ids(
        project.world_blueprint.get("genre_plugin_ids")
        if isinstance(project.world_blueprint, dict)
        else None
    )
    for plugin_id in explicit_ids:
        if plugin_id in plugin_by_id and plugin_id != "generic_webnovel":
            return plugin_by_id[plugin_id]
    for plugin in plugins:
        if plugin.plugin_id not in {"generic_webnovel", "eastern_fantasy"}:
            return plugin
    return plugin_by_id["generic_webnovel"]


def _requires_structured_power_system(plugin_id: str) -> bool:
    # Realistic catalog types must not gain a supernatural
    # progression system merely because they have a genre plugin.
    # Unknown/custom types keep the historical opt-in behavior so a
    # user-supplied power-system template is still honored.
    return plugin_id not in {
        "generic_webnovel",
        "urban",
        "romance",
        "suspense",
    }


def _uses_game_world_modules(plugin_id: str) -> bool:
    return plugin_id == "game_webnovel"


def _world_plugin_prompt_guide(plugins: list[Any], *, uses_game_modules: bool) -> str:
    payload = json.loads(plugin_prompt_guide(plugins))
    if not uses_game_modules:
        for plugin in payload:
            rulebook = plugin.get("rulebook") if isinstance(plugin, dict) else None
            if isinstance(rulebook, dict):
                rulebook.pop("quest_rules", None)
                rulebook.pop("panel_rules", None)
    return json.dumps(payload, ensure_ascii=False)


def _safe_compact_text(value: Any, limit: int) -> str:
    try:
        return compact_text(value, limit)
    except Exception:
        return ""


def _bounded_json_projection(
    value: Any,
    *,
    chars: int,
    items: int,
    depth: int,
) -> Any:
    if isinstance(value, str):
        return _safe_compact_text(value, chars)
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return max(-1_000_000, min(value, 1_000_000))
    if isinstance(value, float):
        return max(-1_000_000.0, min(value, 1_000_000.0)) if math.isfinite(value) else 0.0
    if depth <= 0:
        return ""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        try:
            source_items = value.items()
            for raw_key, item in islice(source_items, items):
                key = _safe_compact_text(raw_key, 80)
                if key and key not in result:
                    result[key] = _bounded_json_projection(
                        item,
                        chars=chars,
                        items=items,
                        depth=depth - 1,
                    )
        except Exception:
            return result
        return result
    if isinstance(value, (list, tuple)):
        return [
            _bounded_json_projection(
                item,
                chars=chars,
                items=items,
                depth=depth - 1,
            )
            for item in islice(value, items)
        ]
    return _safe_compact_text(value, chars)


def _bounded_world_blueprint(
    value: Any,
    *,
    chars: int,
    items: int,
    depth: int,
) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, Any] = {}
    for key in ("genre_plugin_ids", "premise"):
        try:
            if key in value:
                result[key] = _bounded_json_projection(
                    value[key], chars=chars, items=items, depth=depth
                )
        except Exception:
            continue
    try:
        if "power_system_spec" in value:
            result["power_system_spec"] = power_system_prompt_slice(
                value.get("power_system_spec")
            )
    except Exception:
        result["power_system_spec"] = {}

    try:
        source_items = value.items()
        added = 0
        for raw_key, item in source_items:
            key = _safe_compact_text(raw_key, 80)
            if not key or key in result or key == "power_system_spec":
                continue
            result[key] = _bounded_json_projection(
                item,
                chars=chars,
                items=items,
                depth=depth,
            )
            added += 1
            if added >= items:
                break
    except Exception:
        pass
    return result


def _project_payload(
    project: NovelProject,
    *,
    chars: int,
    items: int,
    depth: int,
) -> dict[str, Any]:
    return {
        "title": _safe_compact_text(project.title, min(chars, 240)),
        "source_path": _safe_compact_text(project.source_path, min(chars, 320)),
        "seed_outline": _safe_compact_text(project.seed_outline, min(chars * 8, 2600)),
        "world_summary": _safe_compact_text(project.world_summary, min(chars * 5, 1400)),
        "current_focus": _safe_compact_text(project.current_focus, min(chars * 5, 1400)),
        "author_constraints": _bounded_json_projection(
            project.author_constraints, chars=chars, items=items, depth=depth
        ),
        "world_blueprint": _bounded_world_blueprint(
            project.world_blueprint, chars=chars, items=items, depth=depth
        ),
        "character_profiles": _bounded_json_projection(
            project.character_profiles, chars=chars, items=items, depth=depth
        ),
        "relationship_graph": _bounded_json_projection(
            project.relationship_graph, chars=chars, items=items, depth=depth
        ),
        "story_core": _bounded_json_projection(
            project.story_core_context, chars=chars, items=items, depth=depth
        ),
    }


def _serialized_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        allow_nan=False,
    )


def _compact_project_payload(
    project: NovelProject,
    *,
    budget: int = _PROJECT_CONTEXT_BUDGET,
) -> dict[str, Any]:
    bounded_budget = max(6_000, min(int(budget), _PROJECT_CONTEXT_MAX))
    candidate: dict[str, Any] = {}
    for chars, items, depth in _PROJECTION_PROFILES:
        candidate = _project_payload(
            project,
            chars=chars,
            items=items,
            depth=depth,
        )
        if len(_serialized_json(candidate)) <= bounded_budget:
            return candidate
    return candidate


def _runtime_power_template(selected_plugin: Any) -> dict[str, Any]:
    try:
        record = runtime_novel_type(selected_plugin.plugin_id)
        if record is not None:
            template = novel_type_prompt_context(record).get(
                "genre_power_system_template"
            )
            if isinstance(template, Mapping):
                return deepcopy(dict(template))
    except Exception:
        pass
    return compact_power_system_template(selected_plugin.power_system_template)


def _core_power_template(template: Mapping[str, Any], budget: int) -> dict[str, Any]:
    serialized = _serialized_json(template)
    if len(serialized) <= budget:
        return deepcopy(dict(template))

    minimum_path_count = template.get("minimum_path_count", 2)
    if not isinstance(minimum_path_count, int) or isinstance(minimum_path_count, bool):
        minimum_path_count = 2
    minimum_path_count = max(1, min(minimum_path_count, 64))
    for chars, items in ((120, 8), (80, 6), (48, 4), (24, 2), (12, 1)):
        candidate = {
            "system_form": _safe_compact_text(template.get("system_form"), chars),
            "required_sections": _bounded_json_projection(
                template.get("required_sections", []),
                chars=chars,
                items=items,
                depth=2,
            ),
            "minimum_path_count": minimum_path_count,
            "fixed_milestones": _bounded_json_projection(
                template.get("fixed_milestones", []),
                chars=24,
                items=items,
                depth=2,
            ),
        }
        if len(_serialized_json(candidate)) <= budget:
            return candidate
    raise WorldEnrichmentError("world_enrichment_prompt_budget_exceeded")


def _build_prompt(project: NovelProject, *, rules_only: bool = False) -> str:
    payload = _compact_project_payload(project)
    prompt_project = project.model_copy(
        update={
            "title": payload["title"],
            "source_path": payload["source_path"],
            "seed_outline": payload["seed_outline"],
            "world_summary": payload["world_summary"],
            "current_focus": payload["current_focus"],
            "author_constraints": payload["author_constraints"],
            "world_blueprint": payload["world_blueprint"],
            "character_profiles": payload["character_profiles"],
            "relationship_graph": payload["relationship_graph"],
        }
    )
    plugins = select_genre_plugins(prompt_project)
    selected_plugin = _selected_novel_type_plugin(prompt_project, plugins)
    power_template = _runtime_power_template(selected_plugin)
    requires_power_system = _requires_structured_power_system(selected_plugin.plugin_id)
    uses_game_modules = _uses_game_world_modules(selected_plugin.plugin_id)
    world_fields = [
        "premise", "world_rules", "locations", "factions",
        "current_arc", "constraints", "relationship_graph", "progression_rules",
        "economy_rules", "faction_rules",
        "chapter_formula", "forbidden_breaks", "opening_arc", "volume_plan",
        "longform_framework", "world_systems", "living_world",
    ]
    if requires_power_system:
        world_fields.extend(("power_system", "power_system_spec"))
    if uses_game_modules:
        world_fields.extend(("quest_rules", "panel_rules", "npc_system", "quest_network", "server_runtime", "map_ecology"))
    path_schema = (
        "paths: [{name, role, core_resource, core_attributes, weapons, armor, combat_loop, strengths, weaknesses, skill_categories, branches, transfer_task, advancement}]，"
        "逐职业写明定位、核心资源、属性、武器护甲、战斗循环、强弱项、技能类别、至少两个分支、转职任务和晋升；"
        if uses_game_modules
        else "paths: [{name, role, core_resource, core_attributes, strengths, weaknesses, skill_categories, branches, advancement}]，"
        "逐成长路线写明路线定位、力量来源、关键条件、强弱项、能力类别、至少两个分支和晋升条件；只使用上述字段；"
    )
    mode_line = (
        "请在不重写已有剧情的前提下，补强中文长篇网文项目的世界规则手册，只返回 JSON。"
        if rules_only
        else "请基于导入材料，为中文长篇网文生成第一章前可用的结构化世界档案增强版，只返回 JSON。"
    )
    lines = [
            mode_line,
            "不要写小说正文，不要推进章节剧情；只整理世界观、角色档案、关系网、类型规则和后续写作约束。",
            "必须沿用输入里的既有设定，不要随意改名；规则要能支撑连续几十章的成长、资源、势力冲突和爽点循环。",
            "输出 JSON 字段：",
            f"world_blueprint: {{{', '.join(world_fields)}}}",
            "power_system_spec 必须是完整具体的结构化力量体系，禁止使用待定、略、同上或其他模糊占位符。规范字段：",
            "name: 体系名称字符串；origin: 力量来源与获得方式字符串数组；attributes: [{name, effect}] 属性名与具体效果；",
            path_schema,
            "stages: [{name, level, entry, change, failure}]，按顺序写明阶段名、等级里程碑、进入条件、能力变化和失败后果；",
            "skills: 技能获得与使用规则；equipment: 装备类别与限制；resources: 资源产出、转化与消耗；advancement: 晋升条件与流程；",
            "costs: 使用和突破代价；counters: 路线或机制克制；boundaries: 越级与能力硬边界；social_impact: 对组织、职业和秩序的影响；visibility: 角色可观察到的信息；continuity_ledger: 后续逐章必须追踪的状态字段。以上字段除 name 外均使用数组，paths/stages/attributes 使用前述对象数组。",
            f"selected_novel_type: {selected_plugin.plugin_id}",
            (
                "game_class_advancement_rule: 所有基础职业共用三个转职节点："
                "Lv.10正式转职、Lv.30选择职业分支、Lv.60晋升传承职业。"
                "power_system_spec.class_advancement_tiers: "
                "[{level,name,purpose,common_requirements,failure_rule}]，必须完整列出三个节点；"
                "每个 paths 条目必须包含 advancement_tree: [{level,tier_name,options}]；"
                "两处 level 生成时请输出 JSON 整数 10/30/60。"
                "options 中 name、transfer_task、ability_changes 是校验必填；"
                "requirements、new_resources、equipment_permissions、failure_consequence、"
                "next_options 建议完整输出。"
                "隐藏职业只能作为相同等级节点内的特殊选项，不得改变转职等级。"
                if selected_plugin.plugin_id == "game_webnovel"
                else "game_class_advancement_rule: not_applicable"
            ),
            f"genre_power_system_template: {_serialized_json(power_template)}",
            "character_profiles: [{name, role, motivation, current_state, personality, speech_style, goals, secrets, conflict_hooks}]",
            "world_summary: 120字以内的世界摘要",
            "current_focus: 下一章/下一阶段执行焦点，必须包含主角短期目标、外部压力、规则展示点",
            "relationship_graph: [{source, target, bond, tension, trust}]",
            "locations/factions 每项格式为 {name, description}。",
            "progression_rules/economy_rules/quest_rules/faction_rules/panel_rules/chapter_formula/forbidden_breaks 必须是字符串数组，每组 3 到 6 条。",
            "world_systems 必须包含：material_base, institutions, social_order, conflict_engines, causal_loops。",
            "world_systems 要回答：资源从哪里来，谁负责分配，普通人如何上升，秩序如何维持，矛盾如何自动发生，一个动作会留下什么可追踪痕迹。",
            "longform_framework 必须包含：target_words, series_premise, volume_ladder, progression_ladder, faction_ladder, economy_ladder, mystery_ladder, map_ladder, npc_evolution_ladder, simulation_rules；只有存在现实/虚拟双线时才添加 reality_ladder。",
            "longform_framework 不写死每章剧情，只规定百万字长篇的解锁顺序、压力上限、真相揭露节奏、势力升级路径和每卷推演边界。",
            "opening_arc 必须包含 golden_three_chapters，分别规划第1章、第2章、第3章的 purpose、must_include、exposition_beats、background_budget、ending_hook。",
            "黄金三章要回答：第1章如何立世界/立主角/立金手指/立风险，第2章如何扩大收益并让压力逼近，第3章如何形成第一个小高潮并确立长期路线。",
            "background_budget 必须包含 required_layers、allowed_layers、forbidden_layers，用于限制每章能展开多少世界背景，防止第一章堆设定。",
            "living_world 必须包含：daily_routines, economy, power_structure, information_network, player_ecology, information_visibility_rules, world_reaction_ladder, location_functions, timeline, reaction_rules。",
            "living_world 要回答：普通人每天在做什么，资源如何流动，谁控制秩序，消息如何传播，地点有什么功能，时间如何推进，主角行动会造成什么连锁反应。",
            "如果是网游/游戏经济题材，必须明确币制和低级物价尺度，并严格复用题材插件提供的交易行与官方兑换统一边界。",
            f"已识别题材插件：{_world_plugin_prompt_guide(plugins, uses_game_modules=uses_game_modules)}",
            "请根据题材插件补齐可泛化的类型规则；若是复合题材，主题材负责主线逻辑，副题材提供钩子、规则或爽点。",
        ]
    if not requires_power_system:
        power_only_prefixes = (
            "power_system_spec ",
            "name:",
            "paths:",
            "stages:",
            "skills:",
            "costs:",
            "game_class_advancement_rule:",
            "genre_power_system_template:",
        )
        lines = [line for line in lines if not line.startswith(power_only_prefixes)]
    if not uses_game_modules:
        lines = [
            line.replace(", player_ecology", "")
            .replace("quest_rules/", "")
            .replace("panel_rules/", "")
            for line in lines
        ]
    context_prefix = "当前项目数据："
    template_prefix = "genre_power_system_template: "
    lines_without_template = list(lines)
    template_index = next(
        (index for index, line in enumerate(lines) if line.startswith(template_prefix)),
        None,
    )
    if template_index is not None:
        lines_without_template[template_index] = template_prefix
    fixed_without_template = len(
        "\n".join([*lines_without_template, context_prefix])
    )
    if fixed_without_template >= _FINAL_PROMPT_MAX:
        raise WorldEnrichmentError(
            "world_enrichment_prompt_fixed_instructions_exceed_budget"
        )

    if template_index is not None:
        template_budget = min(
            6_000,
            _FINAL_PROMPT_MAX
            - fixed_without_template
            - _MIN_PROJECT_CONTEXT_BUDGET,
        )
        if template_budget <= 0:
            raise WorldEnrichmentError("world_enrichment_prompt_budget_exceeded")
        power_template = _core_power_template(power_template, template_budget)
        lines[template_index] = f"{template_prefix}{_serialized_json(power_template)}"

    fixed_length = len("\n".join([*lines, context_prefix]))
    context_budget = min(
        _PROJECT_CONTEXT_MAX,
        _FINAL_PROMPT_MAX - fixed_length,
    )
    if context_budget < _MIN_PROJECT_CONTEXT_BUDGET:
        raise WorldEnrichmentError("world_enrichment_prompt_budget_exceeded")
    payload = _compact_project_payload(project, budget=context_budget)
    prompt = "\n".join([*lines, f"{context_prefix}{_serialized_json(payload)}"])
    if len(prompt) > _FINAL_PROMPT_MAX:
        raise WorldEnrichmentError("world_enrichment_prompt_budget_exceeded")
    return prompt


def _as_string_list(value: Any, limit: int, *, item_limit: int = 240) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, dict):
            text = compact_text(str(item.get("description") or item.get("name") or ""), item_limit)
        else:
            text = compact_text(str(item), item_limit)
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _merge_string_lists(*values: Any, limit: int, item_limit: int = 240) -> list[str]:
    merged: list[str] = []
    for value in values:
        for item in _as_string_list(value, limit, item_limit=item_limit):
            if item not in merged:
                merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_entry_list(value: Any, limit: int) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            name = compact_text(str(item.get("name", "")), 80)
            description = compact_text(str(item.get("description", "")), 260)
        else:
            name = compact_text(str(item), 80)
            description = name
        if name and name not in seen:
            result.append({"name": name, "description": description})
            seen.add(name)
        if len(result) >= limit:
            break
    return result


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _default_living_world(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    plugin_ids = {str(plugin.get("id", "")) for plugin in genre_plugins}
    if "game_webnovel" in plugin_ids:
        return {
            "daily_routines": [
                "普通玩家在起始区域抢怪、组队、捡材料，靠基础任务积累第一阶段装备与资源。",
                "商人玩家盯交易行价差，低级材料只能记录价格、数量和时间戳，不能直接知道卖家身份或刷怪坐标。",
                "公会外围成员巡逻资源点、拉拢新人、驱赶散人玩家。",
            ],
            "economy": {
                "resource_flow": [
                    *market_rules(),
                    *exchange_rules(),
                    "低级材料从刷怪点流入交易行，再被生活职业玩家、公会仓库和倒卖商吸收。",
                    "大量低价材料会压低短期价格并形成弱线索，但不会单次暴露卖家身份、现实身份或精确刷怪点。",
                ],
                "pressure_points": ["匿名寄售轨迹", "材料价格波动", "兑换价波动", "公会集中收购", "散人跟风刷点"],
            },
            "power_structure": {
                "dominant_groups": ["区域玩家组织", "交易市场商人", "成长导师与任务NPC"],
                "control_methods": ["包场资源点", "压价收购", "新人招募", "攻略信息垄断"],
            },
            "information_network": {
                "channels": ["交易行价格榜", "玩家闲聊", "公会频道", "攻略贩子", "职业大厅传闻"],
                "rumors": ["有人掌握高效资源路线", "首次阶段晋升需要额外条件"],
            },
            "player_ecology": [
                "散人玩家靠组队、蹭任务和低级材料维持发育，最怕被公会清场或商人压价。",
                "搬砖党关注稳定产出和出货安全，不追求首杀，但会放大材料价格波动。",
                "攻略贩子、商人玩家和公会外围共享部分公开信息，却各自隐瞒货源、路线和名单。",
                "生活职业玩家需要稳定材料供应，会让药剂、修理、仓储和制造需求持续反推市场。",
            ],
            "information_visibility_rules": [
                "交易行默认只公开物品、价格、数量、批次、手续费和时间戳，不公开卖家坐标、现实身份或隐藏天赋。",
                "论坛和玩家频道只能传播截图、传闻和推测；没有连续证据前，不能直接得出主角拥有未公开机制。",
                "公会内部可以记录资源点目击、价格曲线和成员汇报，但需要多源交叉后才会形成观察名单。",
                "NPC只能根据自身服务数据判断异常，例如库存、任务反馈、寄售流水、装备耐久和声望变化。",
            ],
            "world_reaction_ladder": [
                "第1层：价格、库存、玩家闲聊或系统记录出现轻微异常。",
                "第2层：商人玩家和搬砖党记录时间戳、批次和资源点传闻。",
                "第3层：公会外围或NPC服务节点提出试探、压价、任务门槛或路线限制。",
                "第4层：多源线索反复出现后，主角才进入观察名单或被设计拉拢。",
            ],
            "location_functions": [
                {"name": "起始区域公共区", "function": "早期交易、招募、冲突和消息扩散中心"},
                {"name": "交易行", "function": "资源变现与市场弱线索来源，低级材料只暴露价格/数量/时间戳，不能直接暴露坐标"},
                {"name": "近郊资源区", "function": "初期材料产地和散人争夺区"},
                {"name": "职业大厅", "function": "10级职业试炼线索入口"},
            ],
            "timeline": [
                "开服初期：玩家摸索基础玩法，材料价格尚不稳定。",
                "第一批异常收益出现后：主角先在任务、装备和路线进度上领先；外部关注要等稀有物、榜单或多源记录后才升级。",
                "10级临近前：职业试炼攻略和资源垄断会成为新冲突。",
            ],
            "reaction_rules": [
                "主角大量出售低级材料只会引发价格波动、商人脚本注意和时间戳弱线索，不会单次暴露身份或精确坐标。",
                "主角越低调处理收益，越需要付出时间、手续费、拆单或绕路成本。",
                "公会不会立刻知道真相；只有重复出货模式、稀有物品、榜单公告、资源点目击、NPC任务异常或多处线索汇总后，才会逐步缩小范围。",
                "任何罕见收益都必须产生至少一个外部反应：商人注意、散人跟风、公会试探或NPC线索变化。",
            ],
        }
    return {
        "daily_routines": [
            "普通角色有自己的工作、欲望、恐惧和信息来源，不应只在主角需要时出现。",
            "配角和势力会围绕资源、关系、名声或安全感做出日常选择。",
        ],
        "economy": {
            "resource_flow": ["资源从产出者流向中间人、组织和最终使用者，价格会随稀缺度和风险变化。"],
            "pressure_points": ["资源短缺", "信息差", "身份风险", "组织垄断"],
        },
        "power_structure": {
            "dominant_groups": ["地方强势者", "资源控制者", "信息中介"],
            "control_methods": ["规则制定", "资源分配", "舆论影响", "暴力或关系压迫"],
        },
            "information_network": {
                "channels": ["公开传闻", "私下交易", "组织内部消息", "现场目击"],
                "rumors": [],
            },
            "player_ecology": [],
            "information_visibility_rules": [
                "公开渠道只能传播可观察痕迹，不能替角色全知全能地揭露秘密。",
                "组织内部消息需要来源、延迟和误判空间。",
            ],
            "world_reaction_ladder": [
                "轻微异常先变成传闻或价格波动，再升级为试探、压迫和正面冲突。",
            ],
            "location_functions": [],
            "timeline": ["世界在主角行动之外持续推进，势力和普通人会对变化做出延迟反应。"],
            "reaction_rules": [
            "主角的收益、冲突或异常行为必须引起世界中至少一个群体的后续反应。",
            "世界反应不应全知全能，要通过可观察痕迹逐步逼近真相。",
        ],
    }


def _merge_living_world(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("living_world"))
    current = _as_dict(current_world.get("living_world"))
    defaults = _default_living_world(project, genre_plugins)
    incoming_resource_flow = _as_dict(incoming.get("economy")).get("resource_flow")
    current_resource_flow = _as_dict(current.get("economy")).get("resource_flow")
    default_resource_flow = _as_dict(defaults.get("economy")).get("resource_flow")
    plugin_ids = {str(plugin.get("id", "")) for plugin in genre_plugins}
    resource_flow_sources = (
        ([*market_rules(), *exchange_rules()], current_resource_flow, incoming_resource_flow, default_resource_flow)
        if "game_webnovel" in plugin_ids
        else (incoming_resource_flow, current_resource_flow, default_resource_flow)
    )
    return {
        "daily_routines": _merge_string_lists(
            incoming.get("daily_routines"),
            current.get("daily_routines"),
            defaults.get("daily_routines"),
            limit=12,
            item_limit=220,
        ),
        "economy": {
            "resource_flow": _merge_string_lists(
                *resource_flow_sources,
                limit=10,
                item_limit=240,
            ),
            "pressure_points": _merge_string_lists(
                _as_dict(incoming.get("economy")).get("pressure_points"),
                _as_dict(current.get("economy")).get("pressure_points"),
                _as_dict(defaults.get("economy")).get("pressure_points"),
                limit=10,
                item_limit=160,
            ),
        },
        "power_structure": {
            "dominant_groups": _merge_string_lists(
                _as_dict(incoming.get("power_structure")).get("dominant_groups"),
                _as_dict(current.get("power_structure")).get("dominant_groups"),
                _as_dict(defaults.get("power_structure")).get("dominant_groups"),
                limit=10,
                item_limit=120,
            ),
            "control_methods": _merge_string_lists(
                _as_dict(incoming.get("power_structure")).get("control_methods"),
                _as_dict(current.get("power_structure")).get("control_methods"),
                _as_dict(defaults.get("power_structure")).get("control_methods"),
                limit=10,
                item_limit=180,
            ),
        },
        "information_network": {
            "channels": _merge_string_lists(
                _as_dict(incoming.get("information_network")).get("channels"),
                _as_dict(current.get("information_network")).get("channels"),
                _as_dict(defaults.get("information_network")).get("channels"),
                limit=10,
                item_limit=120,
            ),
            "rumors": _merge_string_lists(
                _as_dict(incoming.get("information_network")).get("rumors"),
                _as_dict(current.get("information_network")).get("rumors"),
                _as_dict(defaults.get("information_network")).get("rumors"),
                limit=10,
                item_limit=220,
            ),
        },
        "player_ecology": _merge_string_lists(
            incoming.get("player_ecology"),
            current.get("player_ecology"),
            defaults.get("player_ecology"),
            limit=12,
            item_limit=220,
        ),
        "information_visibility_rules": _merge_string_lists(
            incoming.get("information_visibility_rules"),
            current.get("information_visibility_rules"),
            defaults.get("information_visibility_rules"),
            limit=12,
            item_limit=240,
        ),
        "world_reaction_ladder": _merge_string_lists(
            incoming.get("world_reaction_ladder"),
            current.get("world_reaction_ladder"),
            defaults.get("world_reaction_ladder"),
            limit=10,
            item_limit=220,
        ),
        "location_functions": _as_entry_list(
            incoming.get("location_functions") or current.get("location_functions") or defaults.get("location_functions"),
            16,
        ),
        "timeline": _merge_string_lists(incoming.get("timeline"), current.get("timeline"), defaults.get("timeline"), limit=12, item_limit=240),
        "reaction_rules": _merge_string_lists(
            incoming.get("reaction_rules"),
            current.get("reaction_rules"),
            defaults.get("reaction_rules"),
            limit=12,
            item_limit=240,
        ),
    }


def _default_world_systems(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    plugin_ids = {str(plugin.get("id", "")) for plugin in genre_plugins}
    if "game_webnovel" in plugin_ids:
        return {
            "material_base": [
                "起始区域经济依赖基础产出、任务奖励、生活职业消耗和交易手续费形成闭环。",
                "基础资源按项目设定的币制和稀缺度计价，低阶产出不能直接等同于高阶财富。",
                "开服初期信息差比等级更值钱，攻略、刷新点、隐藏触发条件都会被商人和公会快速定价。",
                "稀有掉落可以制造暴利，但大规模流入市场会留下价格、数量和上架时间的异常痕迹。",
            ],
            "institutions": [
                {"name": "交易行", "description": "负责资源变现和价格发现；低级材料交易只提供价格、数量、时间戳等弱线索，商人可盯盘但不能直接定位玩家坐标或现实身份。"},
                {"name": "区域玩家组织", "description": "通过资源点管理、新人招募和集中收购建立影响力，并对异常收益保持有限关注。"},
                {"name": "成长服务机构", "description": "掌握阶段晋升入口，导师、公告板和玩家闲聊会提前释放门槛线索。"},
            ],
            "social_order": [
                "普通玩家靠组队抢怪和任务奖励缓慢上升，散人想出头必须依赖信息差或稀缺资源。",
                "商人玩家不直接战斗，却通过账本、价格曲线和寄售记录影响资源分配。",
                "公会外围不一定知道真相，但会根据资源异常、传闻和利益变化逐步缩小怀疑范围。",
            ],
            "conflict_engines": [
                "项目已设定的核心优势可以带来成长节奏领先，但必须同时产生资源、行动或暴露成本。",
                "主角越想保持领先，就越需要处理补给、耐久、背包、路线选择和玩家目击带来的行动成本。",
                "现实兑换渠道尚未稳定时，主角的收益先体现为游戏内进度、任务奖励、装备储备和路线权限，而不是立刻折算成现实暴富。",
                "10级职业试炼临近后，攻略垄断、材料囤积和队伍名额会自然升级为阶段冲突。",
            ],
            "causal_loops": [
                {"name": "领先滚雪球", "description": "主角提高行动效率 -> 更快完成任务或达到成长门槛 -> 多章累积后才形成可观察的进度差。"},
                {"name": "路线分化", "description": "项目既定机制改变成长选择 -> 系统反馈出现差异 -> 阶段门槛被重新解释 -> 新风险随之出现。"},
                {"name": "散人跟风", "description": "某个刷怪点收益变高的传闻扩散 -> 普通玩家涌入 -> 公会清场 -> 主角必须更换行动路径。"},
            ],
        }
    return {
        "material_base": [
            "世界必须有可追踪的资源来源、分配方式和消耗出口，不能只有抽象设定。",
            "稀缺资源、信息差和身份风险共同决定角色选择，而不是所有人围着主角静止等待。",
        ],
        "institutions": [
            {"name": "秩序维护者", "description": "通过规则、资源或暴力维持现有秩序。"},
            {"name": "资源中介", "description": "连接生产者、使用者和消息渠道，从流通中获利。"},
            {"name": "边缘群体", "description": "在制度缝隙中寻找上升机会，也最容易被主角行动影响。"},
        ],
        "social_order": [
            "普通人有日常目标、恐惧和上升路径，配角的行动应能从身份与利益中解释。",
            "权力结构会通过奖惩、舆论、资源分配或准入门槛对异常者产生反应。",
        ],
        "conflict_engines": [
            "主角获得收益会改变既有利益分配，并引发至少一个群体的后续反应。",
            "每个阶段冲突应同时包含外部压力、内部代价和下一步门槛。",
        ],
        "causal_loops": [
            {"name": "收益反应", "description": "主角获得资源 -> 既有秩序感到异常 -> 信息通过可观察痕迹传播 -> 新压力逼近。"},
            {"name": "身份风险", "description": "主角隐藏优势 -> 行动选择变窄 -> 成本上升 -> 必须在收益和暴露之间做取舍。"},
        ],
    }


def _merge_world_systems(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("world_systems"))
    current = _as_dict(current_world.get("world_systems"))
    defaults = _default_world_systems(project, genre_plugins)
    return {
        "material_base": _merge_string_lists(
            incoming.get("material_base"),
            current.get("material_base"),
            defaults.get("material_base"),
            limit=10,
            item_limit=240,
        ),
        "institutions": _as_entry_list(
            incoming.get("institutions") or current.get("institutions") or defaults.get("institutions"),
            12,
        ),
        "social_order": _merge_string_lists(
            incoming.get("social_order"),
            current.get("social_order"),
            defaults.get("social_order"),
            limit=10,
            item_limit=240,
        ),
        "conflict_engines": _merge_string_lists(
            incoming.get("conflict_engines"),
            current.get("conflict_engines"),
            defaults.get("conflict_engines"),
            limit=10,
            item_limit=260,
        ),
        "causal_loops": _as_entry_list(
            incoming.get("causal_loops") or current.get("causal_loops") or defaults.get("causal_loops"),
            12,
        ),
    }


def _has_game_plugin(genre_plugins: list[dict[str, Any]]) -> bool:
    return any(str(plugin.get("id", "")) == "game_webnovel" for plugin in genre_plugins)


def _as_rich_entry_list(value: Any, limit: int, *, allowed_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in value:
        if isinstance(item, dict):
            name = compact_text(str(item.get("name", "")).strip(), 80)
            if not name:
                continue
            entry: dict[str, Any] = {"name": name}
            for key in allowed_keys:
                raw = item.get(key)
                if isinstance(raw, list):
                    entry[key] = _as_string_list(raw, 8, item_limit=180)
                elif isinstance(raw, dict):
                    entry[key] = raw
                elif raw is not None:
                    entry[key] = compact_text(str(raw).strip(), 220)
            if name not in seen:
                result.append(entry)
                seen.add(name)
        else:
            name = compact_text(str(item).strip(), 80)
            if name and name not in seen:
                result.append({"name": name, "description": name})
                seen.add(name)
        if len(result) >= limit:
            break
    return result


def _merge_rich_entry_lists(*values: Any, limit: int, allowed_keys: tuple[str, ...]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    for value in values:
        for entry in _as_rich_entry_list(value, limit, allowed_keys=allowed_keys):
            name = str(entry.get("name", "")).strip()
            if name and name not in seen:
                merged.append(entry)
                seen.add(name)
            if len(merged) >= limit:
                return merged
    return merged


def _default_npc_system(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if not _has_game_plugin(genre_plugins):
        return {
            "npcs": [],
            "rules": ["NPC 不是背景板：每个关键 NPC 都有服务、信息边界、利益倾向和能改变任务链的反馈。"],
        }
    return {
        "npcs": [
            {
                "name": "任务管理员",
                "role": "起始区域任务与声望服务节点",
                "location": "起始区域公共服务点",
                "services": ["基础任务", "声望任务", "区域异常登记"],
                "agenda": "维持区域任务秩序，把玩家引向符合当前阶段的目标。",
                "knowledge_limit": "只知道区域异常和任务反馈，不知道玩家未公开状态。",
                "quest_hooks": ["区域清理", "公共设施维护"],
                "voice": "官腔、谨慎、习惯用系统规章压住玩家争执。",
            },
            {
                "name": "补给商",
                "role": "消耗品与材料回收 NPC",
                "location": "补给点",
                "services": ["出售基础补给", "回收常见材料", "发布补给支线"],
                "agenda": "稳定基础补给供应，并用价格策略保护自己的利润。",
                "knowledge_limit": "能从库存和需求缺口察觉区域异常，但看不到玩家私有状态。",
                "quest_hooks": ["收集补给材料", "库存断供预警"],
                "voice": "絮叨、会压价，但对守规矩的玩家留一点情面。",
            },
            {
                "name": "成长导师",
                "role": "成长导师与阶段门槛守门人",
                "location": "成长服务机构",
                "services": ["技能学习", "阶段晋升登记", "成长路线线索"],
                "agenda": "筛选满足条件的玩家，维护成长体系的门槛权威。",
                "knowledge_limit": "能看出公开状态波动异常，但不能确认未公开机制。",
                "quest_hooks": ["基础能力考核", "晋升材料前置", "首次阶段试炼"],
                "voice": "冷淡、重规则，讲话像在宣读试炼条款。",
            },
            {
                "name": "仓储管理员",
                "role": "仓库、邮件与流水记录节点",
                "location": "仓库",
                "services": ["仓库格扩展", "邮件转寄", "寄售流水查询"],
                "agenda": "按系统规章记录异常存取，避免仓库成为洗货点。",
                "knowledge_limit": "只看见物流和寄存频率，不知道玩家战斗过程。",
                "quest_hooks": ["遗失包裹", "异常寄存记录", "匿名寄售追踪"],
                "voice": "机械、守规、每句话都像盖章。",
            },
            {
                "name": "装备修理师",
                "role": "装备耐久与金币消耗点",
                "location": "铁匠铺",
                "services": ["修理装备", "低级装备制作", "矿石和兽皮回收"],
                "agenda": "低价收购矿石和兽皮，同时从修理频率判断谁在高强度刷怪。",
                "knowledge_limit": "能判断装备磨损和战斗强度，不能知道隐藏爆率来源。",
                "quest_hooks": ["损坏法杖修复", "铁矿短缺", "耐久异常报告"],
                "voice": "粗粝、务实，只认材料和手艺。",
            },
        ],
        "rules": [
            "NPC 必须有服务窗口、价格或门槛，主角每次利用 NPC 都会留下交易、任务或声望痕迹。",
            "NPC 不全知：他们只能根据任务反馈、库存、寄售流水、装备磨损和玩家传闻逐步逼近真相。",
            "NPC 线索要能推动任务链、职业试炼、地图开放或市场风险，而不是只负责讲设定。",
        ],
    }


def _merge_npc_system(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("npc_system"))
    current = _as_dict(current_world.get("npc_system"))
    defaults = _default_npc_system(project, genre_plugins)
    return {
        "npcs": _merge_rich_entry_lists(
            incoming.get("npcs"),
            current.get("npcs"),
            defaults.get("npcs"),
            limit=16,
            allowed_keys=("role", "location", "services", "agenda", "knowledge_limit", "quest_hooks", "voice", "description"),
        ),
        "rules": _merge_string_lists(incoming.get("rules"), current.get("rules"), defaults.get("rules"), limit=10, item_limit=220),
    }


def _default_quest_network(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if not _has_game_plugin(genre_plugins):
        return {"quest_types": [], "active_chains": [], "reward_rules": [], "failure_costs": []}
    return {
        "quest_types": ["击杀任务", "采集任务", "跑腿任务", "职业试炼", "隐藏触发", "日常委托", "声望任务"],
        "active_chains": [
            {
                "name": "阶段晋升前置",
                "description": "从基础任务、导师登记和材料准备逐步接入项目设定的首次晋升考核。",
                "stages": ["满足基础条件", "提交所需资源", "完成阶段考核"],
                "npc_links": ["成长导师", "任务管理员"],
            },
            {
                "name": "区域资源链",
                "description": "补给需求联动服务点、交易市场和玩家行动路线，并让异常资源流入留下有限痕迹。",
                "stages": ["发现供需缺口", "收集或护送资源", "处理区域异常"],
                "npc_links": ["补给商", "仓储管理员"],
            },
        ],
        "reward_rules": [
            "新手任务奖励以经验、铜币、低级消耗品和声望为主，稀有装备必须有明确门槛或代价。",
            "隐藏任务可以给出路线优势，但不能直接跳过等级、职业试炼或市场风险。",
        ],
        "failure_costs": ["任务超时会降低 NPC 信任或声望。", "异常刷取会提升公会、商人和 NPC 记录节点的关注。"],
    }


def _merge_quest_network(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("quest_network"))
    current = _as_dict(current_world.get("quest_network"))
    defaults = _default_quest_network(project, genre_plugins)
    return {
        "quest_types": _merge_string_lists(incoming.get("quest_types"), current.get("quest_types"), defaults.get("quest_types"), limit=12, item_limit=80),
        "active_chains": _merge_rich_entry_lists(
            incoming.get("active_chains"),
            current.get("active_chains"),
            defaults.get("active_chains"),
            limit=12,
            allowed_keys=("description", "stages", "npc_links", "risk", "reward"),
        ),
        "reward_rules": _merge_string_lists(incoming.get("reward_rules"), current.get("reward_rules"), defaults.get("reward_rules"), limit=10, item_limit=220),
        "failure_costs": _merge_string_lists(incoming.get("failure_costs"), current.get("failure_costs"), defaults.get("failure_costs"), limit=8, item_limit=180),
    }


def _default_server_runtime(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if not _has_game_plugin(genre_plugins):
        return {"phase": "", "channels": [], "announcement_rules": [], "gm_rules": [], "anti_cheat_rules": [], "instance_rules": []}
    return {
        "phase": "开服或新阶段初期，起始区域玩家密集，价格体系尚未稳定，玩家仍在摸索成长路线。",
        "channels": ["系统公告", "世界频道", "区域频道", "公会频道", "交易行寄售记录", "论坛热帖"],
        "announcement_rules": [
            "首杀、首通、隐藏区域开启和大型市场异常会形成公告或论坛热帖。",
            "普通玩家不知道完整真相，只能根据公告、掉落、价格和传闻拼图。",
        ],
        "gm_rules": [
            "系统不会主动解释隐藏天赋，只会用任务、面板、异常提示和限制条件反馈。",
            "GM 或系统监管只处理明显破坏平衡的异常，不会替主角解决叙事压力。",
        ],
        "anti_cheat_rules": [
            "连续异常掉落、异常寄售和不合理升级速度会提高系统记录异常或玩家举报概率。",
            "低级材料的单次匿名寄售不会暴露坐标；只有连续重复、稀有物、首杀公告、任务异常或举报汇总才会升级为系统/公会级追踪。",
            "主角必须通过拆单、绕路、控制节奏和使用 NPC 服务来降低暴露。",
        ],
        "instance_rules": ["副本、职业试炼和隐藏地图需要等级、物品、声望或 NPC 信任作为门槛。"],
    }


def _merge_server_runtime(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("server_runtime"))
    current = _as_dict(current_world.get("server_runtime"))
    defaults = _default_server_runtime(project, genre_plugins)
    return {
        "phase": compact_text(str(incoming.get("phase") or current.get("phase") or defaults.get("phase") or ""), 220),
        "channels": _merge_string_lists(incoming.get("channels"), current.get("channels"), defaults.get("channels"), limit=12, item_limit=80),
        "announcement_rules": _merge_string_lists(incoming.get("announcement_rules"), current.get("announcement_rules"), defaults.get("announcement_rules"), limit=8, item_limit=200),
        "gm_rules": _merge_string_lists(incoming.get("gm_rules"), current.get("gm_rules"), defaults.get("gm_rules"), limit=8, item_limit=200),
        "anti_cheat_rules": _merge_string_lists(incoming.get("anti_cheat_rules"), current.get("anti_cheat_rules"), defaults.get("anti_cheat_rules"), limit=8, item_limit=200),
        "instance_rules": _merge_string_lists(incoming.get("instance_rules"), current.get("instance_rules"), defaults.get("instance_rules"), limit=8, item_limit=200),
    }


def _default_map_ecology(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if not _has_game_plugin(genre_plugins):
        return {"zones": [], "rules": []}
    return {
        "zones": [
            {
                "name": "起始区域",
                "description": "玩家早期活动的相对安全区，承担任务发布、补给、交易、成长登记和社交。",
                "resources": ["基础任务", "基础补给", "交易入口", "成长服务"],
                "npcs": ["任务管理员", "仓储管理员", "成长导师", "补给商", "装备修理师"],
                "player_density": "高",
                "risk": "信息暴露、价格波动、被公会外围盯上。",
                "outputs": ["任务链", "交易流水", "声望变化", "论坛传闻"],
            },
            {
                "name": "近郊资源区",
                "description": "提供基础战斗、采集和任务产出，也是散人与组织成员发生摩擦的早期区域。",
                "resources": ["常见材料", "基础经验", "初级装备或制作资源"],
                "npcs": [],
                "player_density": "中高",
                "risk": "刷怪路线被观察、资源点被清场。",
                "outputs": ["低级材料", "战斗磨损", "玩家传闻"],
            },
            {
                "name": "进阶探索区",
                "description": "风险和收益高于近郊，连接补给需求、区域事件和后续任务链。",
                "resources": ["进阶材料", "任务物品", "区域情报"],
                "npcs": ["补给商"],
                "player_density": "中",
                "risk": "环境伤害、补给消耗、材料异常引发服务节点关注。",
                "outputs": ["区域支线", "材料价格波动", "寄售记录"],
            },
            {
                "name": "阶段考核区",
                "description": "连接晋升材料和阶段考核前置的危险地点，不是安全教学区。",
                "resources": ["晋升材料", "能力痕迹", "条件触发点"],
                "npcs": ["成长导师"],
                "player_density": "低",
                "risk": "试炼门槛、隐藏路线暴露、怪物强度跳变。",
                "outputs": ["阶段晋升线索", "试炼资格", "组织试探"],
            },
        ],
        "rules": [
            "地图不是背景：每个地点都要提供资源、风险、玩家密度、NPC 服务或信息痕迹。",
            "主角移动路线要改变成本：补给、耐久、时间、被观察概率和任务窗口都会变化。",
        ],
    }


def _merge_map_ecology(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("map_ecology"))
    current = _as_dict(current_world.get("map_ecology"))
    defaults = _default_map_ecology(project, genre_plugins)
    return {
        "zones": _merge_rich_entry_lists(
            incoming.get("zones"),
            current.get("zones"),
            defaults.get("zones"),
            limit=16,
            allowed_keys=("description", "resources", "npcs", "player_density", "risk", "outputs"),
        ),
        "rules": _merge_string_lists(incoming.get("rules"), current.get("rules"), defaults.get("rules"), limit=8, item_limit=220),
    }


def _default_opening_arc(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    plugin_ids = {str(plugin.get("id", "")) for plugin in genre_plugins}
    if "game_webnovel" in plugin_ids:
        return {
            "golden_three_chapters": {
                "chapter_1": {
                    "purpose": "立世界、立主角、立项目既定核心机制、立风险，并完成第一次有效行动。",
                    "conflict_modes": [
                        "动机压力：从当前角色卡、大纲或开书方向提取主角必须行动的直接原因。",
                        "规则压力：只验证当前项目已经设定的机制、能力或策略优势，不得另造触发器。",
                        "进度压力：低级材料只是新手噪音，真正的爽点是主角更快完成任务、凑齐装备/技能门槛。",
                        "NPC压力：村长、导师、药剂师、仓库或修理节点通过任务门槛、服务费用、声望记录留下痕迹。",
                    ],
                    "forbidden_conflicts": [
                        "禁止第一章让公会或商人精准锁定主角坐标、现实身份或刷怪点。",
                        "禁止第一章写成商人玩家或区域组织与主角正面争夺核心资源、围杀或杀人夺宝。",
                        "禁止第一章直接进入高阶副本、世界BOSS、主城大战或卷级大决战。",
                    ],
                    "must_include": [
                        "使用项目设定的游戏名与运行形态，交代当前阶段、玩家生态和主角进入游戏的原因。",
                        "从当前项目角色卡与大纲交代主角的现实处境、技能来源和进入游戏的直接目标，不得另行编造固定背景。",
                        "角色创建或登录阶段应按当前项目设定交代游戏ID、初始身份与基础能力选择。",
                        "第一章必须出现一次简短角色面板，写清游戏ID、等级、职业/路线、经验、主武器或基础技能、货币/背包关键项。",
                        "只有项目明确设定特殊能力时才铺垫其既有触发条件；未设定时以操作、情报或策略形成优势。",
                        "当前项目已设定核心机制的首次验证，必须同时展示收益和具体代价；项目未设定时不得凭空添加外挂。",
                        "第一章是否完成实际交易必须服从项目大纲；未授权时，交易行只作为背景入口、价牌或后续处理材料的弱钩子。",
                        "大型服务器尺度与公会生态：低级材料不会引发关注，公会只以公告、队伍秩序、资源点传闻或玩家闲聊露出存在感，不正面追查主角。",
                        "公会生态应按当前项目已命名势力展开；没有已命名势力时只露出区域组织、商会或散人群体。",
                    ],
                    "exposition_beats": [
                        "通过登录界面、系统公告或玩家频道交代项目设定的游戏名、运行形态和当前阶段。",
                        "通过角色创建或登录界面写出当前项目已设定的初始身份、装备与基础能力选择。",
                        "通过角色面板把项目已有的职业或路线、等级、经验、装备、技能和资源写进可追踪账本。",
                        "通过与当前项目一致的现实细节交代主角动机，不得固定为缺钱、停职或特定职业经历。",
                        "只有当前项目明确设定特殊机制时，才通过既有触发条件铺垫其首次生效。",
                        "通过论坛热帖或玩家闲聊展示当前项目已有势力，或以未命名区域组织表现资源竞争。",
                        "通过交易行界面自然说明匿名寄售、手续费、流水记录和寄售限制。",
                    ],
                    "background_budget": {
                        "required_layers": [
                            "现实入口：现实职业/账单压力必须在可感细节中出现。",
                            "游戏入口：游戏名、开服状态、游戏ID、登录/建号界面和初始身份必须清楚。",
                            "角色入口：第一章应有一次短角色面板，只写当前项目已经设定的身份、装备和基础能力。",
                            "规则入口：只展开当前项目核心机制的首次验证和下一步成长目标。",
                        ],
                        "allowed_layers": [
                            "一个命名NPC服务节点完整出场，其余NPC只作窗口、队列或公告板一笔带过。",
                            "公会、商会、散人和搬砖党只通过论坛热帖、玩家闲聊或资源点秩序露出存在感。",
                            "章末只留下任务、装备、技能或地图路线上的下一步领先目标。",
                        ],
                        "forbidden_layers": [
                            "禁止多个命名NPC、多个服务地点和多个公会视角连续完整展开。",
                            "禁止第一章写完整公会追查、商人正面谈判、职业试炼全规则或主城级世界观。",
                            "禁止把游戏背景、经济体系、NPC制度和势力历史写成百科说明段落。",
                        ],
                    },
                    "ending_hook": "商人从低价批次和时间戳察觉可疑货源，但公会只能收到模糊市场波动或玩家传闻，主角的低调路线第一次出现间接风险。",
                },
                "chapter_2": {
                    "purpose": "扩大收益，验证规则，让市场、商人和公会压力明显逼近。",
                    "conflict_modes": [
                        "资源路线压力：刷怪点拥挤、补给消耗、装备耐久、背包容量和路上来回限制主角效率。",
                        "任务链压力：NPC发布前置任务、材料需求、声望门槛或职业试炼线索，让收益和风险绑定。",
                        "市场批次压力：重复出货、价格波动、商人账本和寄售时间戳让可疑货源画像逐步成形。",
                        "公会外围压力：公会只能通过清场、拉拢、压价、论坛传闻或外围盯点间接试探。",
                    ],
                    "forbidden_conflicts": [
                        "禁止第二章让公会直接发现主角未公开机制或隐藏能力的真相。",
                        "禁止单次交易、单次掉落或一句传闻就让敌人精准定位主角。",
                        "禁止公会会长亲自围杀新手村散人，压力应来自外围秩序和资源控制。",
                    ],
                    "must_include": [
                        "更高效率的刷怪或任务选择，但必须付出时间、路线或身份成本。",
                        "交易行价格波动与商人玩家追踪线索进一步成形，但必须遵守弱线索递进，不能单次精准定位。",
                        "公会外围开始试探、清场或拉拢，主角主动规避而不是正面莽撞。",
                        "自然铺垫当前项目首次阶段晋升的材料、情报或入场条件。",
                    ],
                    "exposition_beats": [
                        "用交易记录和倒卖商反应展示市场如何发现异常。",
                        "用公会频道、巡逻队或玩家投诉展示资源点秩序。",
                        "用攻略帖、导师提示或任务公告露出阶段晋升门槛。",
                    ],
                    "background_budget": {
                        "required_layers": ["补给/耐久/背包成本", "NPC任务前置", "交易批次异常"],
                        "allowed_layers": ["商人正面试探", "公会外围清场或拉拢", "一个职业试炼线索"],
                        "forbidden_layers": ["公会直接知道隐藏天赋", "服务器级通缉", "完整主城势力史"],
                    },
                    "ending_hook": "主角被某个商人或区域组织列入观察名单，或触发阶段晋升的前置线索。",
                },
                "chapter_3": {
                    "purpose": "形成第一个小高潮，明确敌对压力和长期成长路线。",
                    "conflict_modes": [
                        "具体试探：商人、外围公会或NPC记录节点拿到不完整证据，尝试压价、拉拢或设局。",
                        "成长门槛：等级、队伍资格、材料提交、导师评估或副本前置形成阶段目标。",
                        "低调反制：主角用拆单、绕路、借NPC服务、借论坛噪音或换资源点化解压力。",
                        "长期路线：安全升到10级、完成职业试炼、建立隐蔽供货渠道，而不是马上称霸服务器。",
                    ],
                    "forbidden_conflicts": [
                        "禁止第三章提前写成服务器级大决战或公会全面战争。",
                        "禁止NPC无理由送神装、跳过职业试炼或替主角解释全部隐藏机制。",
                        "禁止反派突然降智，只因主角需要爽点就暴露破绽。",
                    ],
                    "must_include": [
                        "公会、商人或NPC势力对主角形成一次具体试探。",
                        "主角用低调策略反制，证明核心性格和生存路线。",
                        "当前项目已设定的核心机制与常规成长路线出现明确差异；若未设定特殊机制，则突出策略或资源差异。",
                        "确立第一卷阶段目标：达到首次晋升门槛、完成阶段考核并建立稳定资源渠道。",
                    ],
                    "exposition_beats": [
                        "用一次冲突展示公会规则和散人处境。",
                        "用技能/面板异常展示隐藏路线的长期悬念。",
                        "用章末新线索把短期收益推向职业试炼主线。",
                    ],
                    "background_budget": {
                        "required_layers": ["一次具体试探", "一次低调反制", "第一卷长期路线"],
                        "allowed_layers": ["职业试炼门槛", "商人压价", "公会外围设局"],
                        "forbidden_layers": ["服务器级大战", "NPC无理由送神装", "隐藏机制全解释"],
                    },
                    "ending_hook": "阶段考核或成长分支露出真正门槛，主角必须在暴露风险和成长速度之间选择。",
                },
            }
        }
    return {
        "golden_three_chapters": {
            "chapter_1": {
                "purpose": "立世界、立主角、立核心优势、立风险，并给读者一个可感知的第一爽点。",
                "conflict_modes": ["当下困境", "核心机制初次验证", "行动后果向外扩散"],
                "forbidden_conflicts": ["禁止无铺垫正面对决", "禁止核心秘密立刻暴露"],
                "must_include": ["具体场景入口", "主角当前处境与眼前目标", "核心能力首次验证", "首次收益与代价", "外部压力钩子"],
                "exposition_beats": ["用行动及结果交代世界规则", "用具体细节交代主角动机", "用对话或传闻交代外部势力"],
                "background_budget": {
                    "required_layers": ["主角处境", "世界入口", "核心能力首次验证"],
                    "allowed_layers": ["一个外部势力弱反应", "一个有明确用途的地点"],
                    "forbidden_layers": ["连续堆设定", "多势力完整视角"],
                },
                "ending_hook": "外部世界开始注意到主角造成的异常。",
            },
            "chapter_2": {
                "purpose": "扩大收益，验证规则，让外部压力逼近。",
                "conflict_modes": ["资源选择", "行动条件", "外部观察"],
                "forbidden_conflicts": ["禁止敌人一步到位知道真相"],
                "must_include": ["能力第二次验证", "资源或关系收益", "外部势力反应", "下一阶段门槛"],
                "exposition_beats": ["用交换、差事或冲突补充制度", "用配角反应展示世界不是静止背景"],
                "background_budget": {
                    "required_layers": ["规则代价", "外部反应"],
                    "allowed_layers": ["一个新地点或新关系"],
                    "forbidden_layers": ["敌人一步到位知道真相"],
                },
                "ending_hook": "主角进入观察名单或触发下一阶段线索。",
            },
            "chapter_3": {
                "purpose": "形成第一个小高潮，明确长期路线。",
                "conflict_modes": ["具体试探", "策略反制", "长期路线"],
                "forbidden_conflicts": ["禁止提前卷级决战"],
                "must_include": ["具体对抗", "主角策略反制", "长期目标", "卷级压力"],
                "exposition_beats": ["用冲突展示势力规则", "用选择展示主角路线"],
                "background_budget": {
                    "required_layers": ["具体试探", "长期路线"],
                    "allowed_layers": ["阶段小高潮"],
                    "forbidden_layers": ["提前卷级决战"],
                },
                "ending_hook": "更高层级的门槛或敌人露头。",
            },
        }
    }


def _as_opening_chapter(value: Any) -> dict[str, Any]:
    raw = _as_dict(value)
    return {
        "purpose": compact_text(str(raw.get("purpose", "")), 220),
        "conflict_modes": _as_string_list(raw.get("conflict_modes"), 8, item_limit=220),
        "forbidden_conflicts": _as_string_list(raw.get("forbidden_conflicts"), 8, item_limit=220),
        "must_include": _as_string_list(raw.get("must_include"), 8, item_limit=220),
        "exposition_beats": _as_string_list(raw.get("exposition_beats"), 8, item_limit=220),
        "background_budget": _as_background_budget(raw.get("background_budget")),
        "ending_hook": compact_text(str(raw.get("ending_hook", "")), 220),
    }


def _as_background_budget(value: Any) -> dict[str, list[str]]:
    raw = _as_dict(value)
    return {
        "required_layers": _as_string_list(raw.get("required_layers"), 6, item_limit=180),
        "allowed_layers": _as_string_list(raw.get("allowed_layers"), 6, item_limit=180),
        "forbidden_layers": _as_string_list(raw.get("forbidden_layers"), 6, item_limit=180),
    }


def _merge_opening_arc(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("opening_arc"))
    current = _as_dict(current_world.get("opening_arc"))
    plugin_ids = {str(plugin.get("id", "")) for plugin in genre_plugins}
    if not _has_game_plugin(genre_plugins) and plugin_ids.intersection(
        {"xuanhuan", "xianxia", "eastern_fantasy"}
    ):
        replacements = {
            "现实缺口": "当下困境",
            "规则验证": "核心机制初次验证",
            "弱线索外溢": "行动后果向外扩散",
            "资源路线": "资源选择",
            "任务门槛": "行动条件",
            "主角现实处境或核心缺口": "主角当前处境与眼前目标",
            "用动作或界面交代世界规则": "用行动及结果交代世界规则",
            "一个服务节点": "一个有明确用途的地点",
            "一个新地点或新服务": "一个新地点或新关系",
        }

        def migrate(value: Any) -> Any:
            if isinstance(value, str):
                return replacements.get(value, value)
            if isinstance(value, list):
                return [migrate(item) for item in value]
            if isinstance(value, dict):
                return {key: migrate(item) for key, item in value.items()}
            return value

        incoming = migrate(incoming)
        current = migrate(current)
    defaults = _default_opening_arc(project, genre_plugins)
    incoming_golden = _as_dict(incoming.get("golden_three_chapters"))
    current_golden = _as_dict(current.get("golden_three_chapters"))
    default_golden = _as_dict(defaults.get("golden_three_chapters"))

    golden_three: dict[str, Any] = {}
    for key in ("chapter_1", "chapter_2", "chapter_3"):
        merged = _as_opening_chapter(incoming_golden.get(key) or current_golden.get(key) or default_golden.get(key))
        fallback = _as_opening_chapter(default_golden.get(key))
        golden_three[key] = {
            "purpose": merged["purpose"] or fallback["purpose"],
            "conflict_modes": merged["conflict_modes"] or fallback["conflict_modes"],
            "forbidden_conflicts": merged["forbidden_conflicts"] or fallback["forbidden_conflicts"],
            "must_include": merged["must_include"] or fallback["must_include"],
            "exposition_beats": merged["exposition_beats"] or fallback["exposition_beats"],
            "background_budget": {
                "required_layers": merged["background_budget"]["required_layers"] or fallback["background_budget"]["required_layers"],
                "allowed_layers": merged["background_budget"]["allowed_layers"] or fallback["background_budget"]["allowed_layers"],
                "forbidden_layers": merged["background_budget"]["forbidden_layers"] or fallback["background_budget"]["forbidden_layers"],
            },
            "ending_hook": merged["ending_hook"] or fallback["ending_hook"],
        }
    return {"golden_three_chapters": golden_three}


def _default_volume_plan(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if _has_game_plugin(genre_plugins):
        return {
            "volume_title": "第一卷 起始区域",
            "target_chapters": 30,
            "core_goal": "主角在控制信息暴露的前提下达到首次阶段晋升门槛，并建立稳定的成长与资源渠道。",
            "phase_beats": [
                {"range": "1-3", "purpose": "立住起始区域、主角目标、项目核心机制、市场弱线索和区域组织秩序。"},
                {"range": "4-8", "purpose": "围绕近郊资源区和进阶探索区扩大收益，补足NPC任务、补给消耗、耐久和市场批次异常。"},
                {"range": "9-15", "purpose": "推进首次阶段晋升，利用导师、补给和仓储流水形成前置任务链。"},
                {"range": "16-24", "purpose": "商人和公会外围拿到不完整证据，开始压价、拉拢、清场和论坛试探。"},
                {"range": "25-30", "purpose": "完成第一卷小高潮：阶段晋升门槛兑现，主角建立稳定资源渠道并留下更高阶地图钩子。"},
            ],
            "long_threads": [
                "达到首次阶段晋升门槛并取得考核资格。",
                "控制核心机制的信息暴露，避免交易记录、NPC记录和组织观察形成多源汇总。",
                "建立低调变现渠道，从铜币/银币收益逐步过渡到稀有材料议价权。",
                "让区域组织、商人玩家、散人玩家和NPC服务节点持续反应，但不能全知全能。",
            ],
            "chapter_anchors": [
                "第1章完成首次收益闭环。",
                "第3章形成第一次具体试探。",
                "第10章前后触达职业试炼门槛。",
                "第20章前后形成公会外围和商人联合压力。",
                "第30章完成第一卷阶段目标并开启主城/高阶地图线。",
            ],
        }
    return {
        "volume_title": "第一卷 起势",
        "target_chapters": 30,
        "core_goal": "完成主角能力验证、外部压力成形和第一阶段目标兑现。",
        "phase_beats": [
            {"range": "1-3", "purpose": "立世界、立主角、立核心优势和风险。"},
            {"range": "4-10", "purpose": "扩大收益并让外部压力逐步逼近。"},
            {"range": "11-20", "purpose": "推进中段任务、关系和势力冲突。"},
            {"range": "21-30", "purpose": "兑现第一卷小高潮并打开下一卷钩子。"},
        ],
        "long_threads": ["核心能力成长线。", "外部势力压力线。", "主角长期目标线。"],
        "chapter_anchors": ["第1章首次闭环。", "第3章小钩子兑现。", "第30章卷末阶段兑现。"],
    }


def _merge_phase_beats(*values: Any, limit: int = 8) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if not isinstance(item, dict):
                continue
            range_text = compact_text(str(item.get("range", "")), 40)
            purpose = compact_text(str(item.get("purpose", "")), 220)
            key = f"{range_text}:{purpose}"
            if range_text and purpose and key not in seen:
                result.append({"range": range_text, "purpose": purpose})
                seen.add(key)
            if len(result) >= limit:
                return result
    return result


def _merge_volume_plan(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("volume_plan"))
    current = _as_dict(current_world.get("volume_plan"))
    defaults = _default_volume_plan(project, genre_plugins)
    target = _as_int(incoming.get("target_chapters") or current.get("target_chapters"), int(defaults["target_chapters"]))
    return {
        "volume_title": compact_text(str(incoming.get("volume_title") or current.get("volume_title") or defaults["volume_title"]), 80),
        "target_chapters": max(10, target),
        "core_goal": compact_text(str(incoming.get("core_goal") or current.get("core_goal") or defaults["core_goal"]), 260),
        "phase_beats": _merge_phase_beats(incoming.get("phase_beats"), current.get("phase_beats"), defaults.get("phase_beats"), limit=8),
        "long_threads": _merge_string_lists(incoming.get("long_threads"), current.get("long_threads"), defaults.get("long_threads"), limit=10, item_limit=220),
        "chapter_anchors": _merge_string_lists(incoming.get("chapter_anchors"), current.get("chapter_anchors"), defaults.get("chapter_anchors"), limit=10, item_limit=180),
    }


def _default_longform_framework(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if _has_game_plugin(genre_plugins):
        return {
            "target_words": 1000000,
            "series_premise": (
                "主角从项目设定的起始区域出发，逐步掌握游戏资源、规则和成长路线，"
                "并在多卷推进中揭开当前项目已经确立的核心谜团。"
            ),
            "volume_ladder": [
                {"range": "1-30", "title": "起步", "unlock": "基础等级、核心机制验证、第一条任务/装备/路线优势", "pressure_cap": "普通玩家误读和资源点弱目击"},
                {"range": "31-80", "title": "主城暗流", "unlock": "10-30级、主城交易行、职业大厅、商会玩家", "pressure_cap": "商会询价、公会招募、职业门槛"},
                {"range": "81-150", "title": "组织竞争", "unlock": "中期等级、区域资源点、团队副本、组织核心队伍", "pressure_cap": "区域围猎和资源封锁，但不能服务器级通缉"},
                {"range": "151-240", "title": "路线进阶", "unlock": "职业或能力进阶、阶段副本、核心机制的新表现", "pressure_cap": "成长机构和副本资格审查"},
                {"range": "241-380", "title": "服务器榜单", "unlock": "排行榜、拍卖会、区域副本首通、隐形资源节点身份", "pressure_cap": "榜单曝光和商会联盟经济战"},
                {"range": "381-560", "title": "跨服裂隙", "unlock": "跨服战场、阵营声望、世界碎片、NPC异常自主行为", "pressure_cap": "阵营战争和跨服追踪"},
                {"range": "561-760", "title": "现实资本入场", "unlock": "账号合同、黑市行情、线下身份风险、现实公司博弈", "pressure_cap": "现实资本围猎但不能直接抹除游戏规则"},
                {"range": "761-1000", "title": "终局规则", "unlock": "世界权限、项目核心真相、终局规则争夺", "pressure_cap": "世界级规则战争"},
            ],
            "progression_ladder": [
                "1-10级：只允许新手村装备、基础技能、铜币/银币收益和职业前置线索。",
                "10-30级：开放主城、进阶技能、稳定银币/少量金币收益和主城商会。",
                "30-50级：开放团队副本、区域资源点、装备套装和公会战术压迫。",
                "50-70级：开放职业或能力分支、阶段副本深层、稀有材料议价权。",
                "70-90级：开放服务器榜单、拍卖行高价资源和区域首通影响力。",
                "90级以后：开放跨服阵营、世界碎片、隐藏权限和现实资本冲突。",
            ],
            "faction_ladder": [
                "商人玩家：负责开局价格、批次、拆单和供货关系压力。",
                "区域组织外围：负责起始资源点清场、拉拢、论坛传闻和弱试探。",
                "区域组织核心：进入主城或中心区后介入区域围猎、队伍资格和副本资源封锁。",
                "商会联盟：服务器榜单前后介入拍卖、压价、合同和经济战。",
                "成长机构/导师体系：负责阶段门槛、考核资格和成长路线审查。",
                "官方运营/系统记录：现实资本卷之前只做规则记录和异常排查，不直接下场解释真相。",
                "现实资本：中后期通过账号合同、黑市和线下身份风险介入。",
                "世界权限持有者：终局阶段才揭示为真正对手。"
            ],
            "economy_ladder": [
                "第1卷：铜币/银币、低级材料、任务奖励、基础装备和路线权限；低级交易只是背景，不能现实暴富。",
                "第2卷：主城商会询价、少量金币、稳定供货关系；现实汇率仍不稳定。",
                "第3卷：区域资源点、团队副本材料、公会垄断和供货合同。",
                "第4-5卷：稀有材料、拍卖会、榜单经济、商会联盟压价。",
                "第6卷后：跨服资源、阵营货币、现实黑市和资本合约逐步出现。",
            ],
            "reality_ladder": [
                "第1卷现实线负责压力、主角技能来源和阶段性账单变化；是否解决急账服从总纲节点，长期生存压力不能一次清空。",
                "第2-3卷现实线表现为玩家论坛、外包旧同事、账号价值传闻。",
                "第4-5卷现实线出现黑市报价、合同试探和现实身份擦边风险。",
                "第6-7卷现实资本正式入场，线下压力与游戏资产绑定。",
                "第8卷现实与游戏边界反转，揭示游戏世界的真实性质。",
            ],
            "mystery_ladder": [
                "第1卷：只展示当前项目核心谜团的首个可观察现象。",
                "第2卷：核心谜团开始影响成长路线或资源选择。",
                "第3卷：系统记录到无法解释的收益结构，但没有真相。",
                "第4卷：阶段考核揭示核心谜团并非普通系统现象。",
                "第5卷：榜单与拍卖暴露世界权限碎片线索。",
                "第6卷：跨服裂隙证明NPC和世界碎片具备自主反应。",
                "第7卷：现实资本知道部分真相并争夺账号权限。",
                "第8卷：揭开当前项目已经确立的终局真相。",
            ],
            "map_ladder": [
                "起始区域/近郊资源区/进阶探索区：早期资源、NPC服务和弱市场线索。",
                "主城/职业大厅/主城交易行：职业进阶、商会、主城公会规则。",
                "区域资源带/团队副本：公会围猎、材料垄断、队伍资格。",
                "阶段考核区：职业或能力进阶副本和成长路线门槛。",
                "跨服裂隙/阵营战场：世界碎片和阵营战争。",
                "终局区域：最终规则与权限争夺。",
            ],
            "npc_evolution_ladder": [
                "第1卷NPC是服务节点：任务、价格、库存、职业提示和信息边界。",
                "第2-3卷NPC开始记录声望、异常服务流水和职业评价。",
                "第4卷职业导师体系发现主角路线异常，但只能通过规则审查施压。",
                "第6卷后部分NPC出现超出普通脚本的记忆和选择。",
                "终局NPC成为虚拟文明与世界权限真相的一部分。",
            ],
            "simulation_rules": [
                "每章只允许解锁当前卷范围内的世界层级，不能提前写服务器级、跨服级或终局规则冲突。",
                "长期真相必须分阶段揭露：先现象，再证据，再误判，再局部真相，最后总真相。",
                "势力升级必须经过弱线索、多源汇总、试探、围猎、正面冲突，不得一步全知。",
                "经济收益必须跟随阶段上限升级，不能让新手材料直接造成现实暴富或全服崩盘。",
                "现实线必须先作为压力和技能来源，再升级为黑市、合同、身份风险和资本博弈。",
            ],
        }
    return {
        "target_words": 1000000,
        "series_premise": "主角从局部困境出发，逐步进入更大世界层级，并在多卷推进中揭开核心真相。",
        "volume_ladder": [
            {"range": "1-30", "title": "起势", "unlock": "核心能力与第一阶段目标", "pressure_cap": "局部势力压力"},
            {"range": "31-100", "title": "扩张", "unlock": "更大地图与组织关系", "pressure_cap": "区域级压力"},
            {"range": "101-250", "title": "对抗", "unlock": "主要敌对结构", "pressure_cap": "组织级压力"},
            {"range": "251-500", "title": "真相", "unlock": "世界核心谜团", "pressure_cap": "世界级压力"},
            {"range": "501-1000", "title": "终局", "unlock": "最终规则与终局对手", "pressure_cap": "终局压力"},
        ],
        "progression_ladder": ["能力、资源、关系和信息必须分阶段解锁。"],
        "faction_ladder": ["敌对压力必须从局部角色升级到组织，再升级到世界级对手。"],
        "economy_ladder": ["收益规模必须随世界层级扩张，不能开局暴富解决所有问题。"],
        "reality_ladder": ["现实线先提供压力，再逐步进入核心冲突。"],
        "mystery_ladder": ["核心谜团必须分阶段揭露，不能一次解释完。"],
        "map_ladder": ["地图必须按阶段开放，每个地图承担不同冲突功能。"],
        "npc_evolution_ladder": ["配角和NPC必须随阶段获得新职责、新信息和新关系。"],
        "simulation_rules": ["章节推演必须遵守当前阶段上限，不能提前终局化。"],
    }


def _merge_ladder_entries(*values: Any, limit: int = 12) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                entry = {
                    "range": compact_text(str(item.get("range", "")), 40),
                    "title": compact_text(str(item.get("title", "")), 80),
                    "unlock": compact_text(str(item.get("unlock", "")), 220),
                    "pressure_cap": compact_text(str(item.get("pressure_cap", "")), 220),
                }
                key = "|".join(entry.values())
            else:
                text = compact_text(str(item), 220)
                entry = {"range": "", "title": text, "unlock": text, "pressure_cap": ""}
                key = text
            if key.strip() and key not in seen:
                result.append(entry)
                seen.add(key)
            if len(result) >= limit:
                return result
    return result


def _merge_longform_framework(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("longform_framework"))
    current = _as_dict(current_world.get("longform_framework"))
    defaults = _default_longform_framework(project, genre_plugins)
    target_words = _as_int(incoming.get("target_words") or current.get("target_words"), int(defaults["target_words"]))
    def preferred(field: str) -> Any:
        for source in (incoming, current, defaults):
            value = source.get(field)
            if value not in (None, "", [], {}):
                if source is not defaults and isinstance(value, list):
                    default_value = defaults.get(field)
                    if isinstance(default_value, list):
                        default_keys = {_serialized_json(item) for item in default_value}
                        specific = [
                            item for item in value
                            if _serialized_json(item) not in default_keys
                        ]
                        if specific:
                            return specific
                return value
        return []

    return {
        "target_words": max(100000, target_words),
        "series_premise": compact_text(str(incoming.get("series_premise") or current.get("series_premise") or defaults["series_premise"]), 420),
        "volume_ladder": _merge_ladder_entries(preferred("volume_ladder"), limit=12),
        "progression_ladder": _merge_string_lists(preferred("progression_ladder"), limit=12, item_limit=240),
        "faction_ladder": _merge_string_lists(preferred("faction_ladder"), limit=12, item_limit=240),
        "economy_ladder": _merge_string_lists(preferred("economy_ladder"), limit=10, item_limit=240),
        "reality_ladder": _merge_string_lists(preferred("reality_ladder"), limit=10, item_limit=240),
        "mystery_ladder": _merge_string_lists(preferred("mystery_ladder"), limit=12, item_limit=240),
        "map_ladder": _merge_string_lists(preferred("map_ladder"), limit=12, item_limit=240),
        "npc_evolution_ladder": _merge_string_lists(preferred("npc_evolution_ladder"), limit=10, item_limit=240),
        "simulation_rules": _merge_string_lists(preferred("simulation_rules"), limit=12, item_limit=240),
    }


def _default_progression_ledger(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if _has_game_plugin(genre_plugins):
        return {
            "protagonist": {"level": 1, "exp": "0/100", "class_path": "初始路线", "location": "起始区域"},
            "economy": {"currency": "0", "inventory": [], "market_anomaly": 0},
            "equipment": {"weapon": "", "armor": "", "durability": "正常"},
            "skills": {"active": [], "locked": []},
            "quests": {"active": [], "completed": []},
            "relations": {"npc": {}, "players": {}},
            "pressure": {"guild_attention": 0, "goldfinger_exposure": 0, "system_risk": 0},
        }
    return {
        "protagonist": {"stage": "起步", "location": ""},
        "economy": {"resources": [], "risk": 0},
        "quests": {"active": [], "completed": []},
        "relations": {},
        "pressure": {"external_attention": 0},
    }


def _deep_merge_dicts(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dicts(result[key], value)
        elif value not in (None, "", [], {}):
            result[key] = value
    return result


def _merge_progression_ledger(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    defaults = _default_progression_ledger(project, genre_plugins)
    current = _as_dict(current_world.get("progression_ledger"))
    incoming = _as_dict(incoming_world.get("progression_ledger"))
    return _deep_merge_dicts(_deep_merge_dicts(defaults, current), incoming)


def _relationship_score(value: Any) -> float:
    try:
        score = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(score):
        return 0.0
    return max(0.0, min(100.0, score))


def _as_relationships(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        source = compact_text(str(item.get("source", "")), 80)
        target = compact_text(str(item.get("target", "")), 80)
        if not source or not target:
            continue
        result.append(
            {
                "source": source,
                "target": target,
                "bond": compact_text(str(item.get("bond", "")), 180),
                "tension": _relationship_score(item.get("tension")),
                "trust": _relationship_score(item.get("trust")),
            }
        )
        if len(result) >= limit:
            break
    return result


def _as_character_profiles(value: Any, fallback: list[dict], limit: int = 24) -> list[dict[str, Any]]:
    raw_profiles = value if isinstance(value, list) else []
    if not raw_profiles:
        raw_profiles = fallback

    profiles: list[dict[str, Any]] = []
    for item in raw_profiles:
        if not isinstance(item, dict):
            continue
        name = compact_text(str(item.get("name", "")), 80)
        if not name:
            continue
        profiles.append(
            {
                "name": name,
                "game_id": compact_text(str(item.get("game_id", "")), 80),
                "role": compact_text(str(item.get("role", "")), 80),
                "motivation": compact_text(str(item.get("motivation", "")), 220),
                "current_state": compact_text(str(item.get("current_state", "")), 220),
                "personality": compact_text(str(item.get("personality", "")), 220),
                "speech_style": compact_text(str(item.get("speech_style", "")), 160),
                "goals": _as_string_list(item.get("goals", []), 5),
                "secrets": _as_string_list(item.get("secrets", []), 5),
                "conflict_hooks": _as_string_list(item.get("conflict_hooks", []), 5),
            }
        )
        if len(profiles) >= limit:
            break
    return profiles


def _default_character_profiles(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return []


def _derive_author_constraints(world_blueprint: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    plugin_ids = {str(item).strip() for item in world_blueprint.get("genre_plugin_ids", []) if str(item).strip()}
    if "game_webnovel" in plugin_ids:
        constraints.append(
            "网游角色必须区分现实姓名和游戏ID：游戏内行动、交易行、论坛和公会追踪优先使用游戏ID，现实身份只能在现实场景或旁白中出现。"
        )
    for field in RULEBOOK_FIELDS:
        constraints.extend(_as_string_list(world_blueprint.get(field), 2, item_limit=180))
    constraints.extend(_as_string_list(world_blueprint.get("constraints"), 6, item_limit=180))
    living_world = _as_dict(world_blueprint.get("living_world"))
    constraints.extend(_as_string_list(living_world.get("reaction_rules"), 4, item_limit=180))
    constraints.extend(_as_string_list(living_world.get("timeline"), 2, item_limit=180))
    constraints.extend(_as_string_list(_as_dict(living_world.get("economy")).get("pressure_points"), 2, item_limit=120))
    world_systems = _as_dict(world_blueprint.get("world_systems"))
    constraints.extend(_as_string_list(world_systems.get("conflict_engines"), 3, item_limit=180))
    constraints.extend(_as_string_list(world_systems.get("material_base"), 2, item_limit=180))
    npc_system = _as_dict(world_blueprint.get("npc_system"))
    constraints.extend(_as_string_list(npc_system.get("rules"), 2, item_limit=180))
    quest_network = _as_dict(world_blueprint.get("quest_network"))
    constraints.extend(_as_string_list(quest_network.get("reward_rules"), 2, item_limit=180))
    server_runtime = _as_dict(world_blueprint.get("server_runtime"))
    constraints.extend(_as_string_list(server_runtime.get("anti_cheat_rules"), 2, item_limit=180))
    map_ecology = _as_dict(world_blueprint.get("map_ecology"))
    constraints.extend(_as_string_list(map_ecology.get("rules"), 2, item_limit=180))
    longform = _as_dict(world_blueprint.get("longform_framework"))
    constraints.extend(_as_string_list(longform.get("simulation_rules"), 4, item_limit=180))
    constraints.extend(_as_string_list(longform.get("economy_ladder"), 2, item_limit=180))
    constraints.extend(_as_string_list(longform.get("mystery_ladder"), 2, item_limit=180))
    opening_arc = _as_dict(world_blueprint.get("opening_arc"))
    golden_three = _as_dict(opening_arc.get("golden_three_chapters"))
    for key in ("chapter_1", "chapter_2", "chapter_3"):
        chapter_plan = _as_dict(golden_three.get(key))
        constraints.extend(_as_string_list(chapter_plan.get("conflict_modes"), 2, item_limit=180))
        constraints.extend(_as_string_list(chapter_plan.get("forbidden_conflicts"), 2, item_limit=180))
        constraints.extend(_as_string_list(chapter_plan.get("must_include"), 2, item_limit=180))
        background_budget = _as_dict(chapter_plan.get("background_budget"))
        constraints.extend(_as_string_list(background_budget.get("required_layers"), 2, item_limit=180))
        constraints.extend(_as_string_list(background_budget.get("forbidden_layers"), 2, item_limit=180))
        if chapter_plan.get("ending_hook"):
            constraints.append(str(chapter_plan["ending_hook"]))

    deduped: list[str] = []
    for constraint in constraints:
        cleaned = compact_text(constraint, 180)
        if cleaned and cleaned not in deduped:
            deduped.append(cleaned)
        if len(deduped) >= 8:
            break
    return deduped


def _drop_irrelevant_genre_constraints(
    constraints: list[str],
    *,
    uses_game_modules: bool,
    requires_power_system: bool,
) -> list[str]:
    if uses_game_modules or requires_power_system:
        return constraints
    irrelevant_markers = (
        "金手指",
        "玄幻系统文",
        "游戏系统",
        "万能系统",
        "不写超自然",
        "爽点",
        "玩家",
        "NPC",
        "任务面板",
        "属性面板",
        "等级经验",
    )
    return [
        constraint
        for constraint in constraints
        if not any(marker in constraint for marker in irrelevant_markers)
    ]


def _plugin_metadata(project: NovelProject) -> tuple[list[dict[str, Any]], dict[str, list[str]]]:
    plugins = select_genre_plugins(project)
    rulebook = merge_plugin_rulebooks(plugins)
    metadata = [
        {
            "id": plugin.plugin_id,
            "name": plugin.name,
            "core_promises": list(plugin.core_promises),
            "ledger_fields": list(plugin.ledger_fields),
            "quality_checks": list(plugin.quality_checks),
        }
        for plugin in plugins
    ]
    return metadata, rulebook


def _power_system_validation_error(error: PowerSystemValidationError) -> ValueError:
    missing = ",".join(error.missing_sections)
    violations = ",".join(error.violations)
    return ValueError(
        "invalid_power_system_spec: "
        f"missing_sections=[{missing}]; violations=[{violations}]"
    )


_GAME_ONLY_POWER_PATH_FIELDS = frozenset(
    ("weapons", "armor", "combat_loop", "transfer_task", "advancement_tree")
)


def _power_spec_for_genre(value: Any, plugin_id: str) -> Any:
    """Remove game-class structure before validating a non-game power system."""

    if plugin_id == "game_webnovel" or not isinstance(value, dict):
        return value
    cleaned = deepcopy(value)
    cleaned.pop("class_advancement_tiers", None)
    paths = cleaned.get("paths")
    if isinstance(paths, list):
        for path in paths:
            if not isinstance(path, dict):
                continue
            for field in _GAME_ONLY_POWER_PATH_FIELDS:
                path.pop(field, None)
    return cleaned


def _validated_power_system_merge(
    project: NovelProject,
    incoming_world: dict[str, Any],
    current_world: dict[str, Any],
    *,
    rules_only: bool | None,
) -> tuple[dict[str, Any] | None, bool]:
    selected_plugin = _selected_novel_type_plugin(project)
    if not _requires_structured_power_system(selected_plugin.plugin_id):
        return None, False
    validation_args = {
        "novel_type_id": selected_plugin.plugin_id,
        "template": selected_plugin.power_system_template,
    }
    incoming_supplied = "power_system_spec" in incoming_world

    current_validated: dict[str, Any] | None = None
    if "power_system_spec" in current_world:
        try:
            current_validated = validate_power_system_spec(
                _power_spec_for_genre(
                    current_world.get("power_system_spec"), selected_plugin.plugin_id
                ),
                **validation_args,
            )
            current_validated = _power_spec_for_genre(
                current_validated, selected_plugin.plugin_id
            )
        except PowerSystemValidationError:
            current_validated = None

    if incoming_supplied:
        try:
            incoming_validated = validate_power_system_spec(
                _power_spec_for_genre(
                    incoming_world.get("power_system_spec"), selected_plugin.plugin_id
                ),
                **validation_args,
            )
            incoming_validated = _power_spec_for_genre(
                incoming_validated, selected_plugin.plugin_id
            )
        except PowerSystemValidationError as error:
            raise _power_system_validation_error(error) from error
        changed = current_validated is None or incoming_validated != current_validated
        return deepcopy(incoming_validated), changed

    if current_validated is not None:
        return deepcopy(current_validated), False
    if rules_only is not False:
        return None, False

    try:
        validate_power_system_spec(
            _power_spec_for_genre(
                current_world.get("power_system_spec"), selected_plugin.plugin_id
            ),
            **validation_args,
        )
    except PowerSystemValidationError as error:
        raise _power_system_validation_error(error) from error
    raise ValueError("invalid_power_system_spec: validation_failed")


def _merge_enrichment(
    project: NovelProject,
    parsed: dict[str, Any],
    *,
    rules_only: bool | None = None,
) -> NovelProject:
    current_world = deepcopy(project.world_blueprint or {})
    incoming_world = parsed.get("world_blueprint") if isinstance(parsed.get("world_blueprint"), dict) else {}
    power_system_spec, power_system_changed = _validated_power_system_merge(
        project,
        incoming_world,
        current_world,
        rules_only=rules_only,
    )
    next_project = project.model_copy(deep=True)
    genre_plugins, plugin_rulebook = _plugin_metadata(project)
    plugin_ids = {str(plugin.get("id", "")) for plugin in genre_plugins}
    uses_game_modules = "game_webnovel" in plugin_ids
    selected_plugin = _selected_novel_type_plugin(project)
    requires_power_system = _requires_structured_power_system(selected_plugin.plugin_id)

    relationships = _as_relationships(
        parsed.get("relationship_graph") or incoming_world.get("relationship_graph") or project.relationship_graph,
        48,
    )
    world_blueprint: dict[str, Any] = {
        "premise": compact_text(str(incoming_world.get("premise") or current_world.get("premise") or project.world_summary), 360),
        "world_rules": _merge_string_lists(incoming_world.get("world_rules"), current_world.get("world_rules"), limit=16),
        "locations": _as_entry_list(incoming_world.get("locations") or current_world.get("locations"), 16),
        "factions": _as_entry_list(incoming_world.get("factions") or current_world.get("factions"), 16),
        "current_arc": compact_text(str(incoming_world.get("current_arc") or current_world.get("current_arc") or project.current_focus), 520),
        "relationship_graph": relationships,
        "genre_plugins": genre_plugins,
    }
    if requires_power_system:
        world_blueprint["power_system"] = (
            legacy_power_summary(power_system_spec)
            if power_system_changed
            else deepcopy(current_world.get("power_system", []))
            if power_system_spec is not None
            else _merge_string_lists(
                incoming_world.get("power_system"),
                current_world.get("power_system"),
                limit=16,
            )
        )
    if power_system_spec is not None:
        world_blueprint["power_system_spec"] = deepcopy(power_system_spec)
    world_blueprint["opening_arc"] = _merge_opening_arc(project, incoming_world, current_world, genre_plugins)
    world_blueprint["volume_plan"] = _merge_volume_plan(project, incoming_world, current_world, genre_plugins)
    world_blueprint["longform_framework"] = _merge_longform_framework(project, incoming_world, current_world, genre_plugins)
    if not uses_game_modules:
        world_blueprint["longform_framework"].pop("reality_ladder", None)
    world_blueprint["progression_ledger"] = _merge_progression_ledger(project, incoming_world, current_world, genre_plugins)
    world_blueprint["world_systems"] = _merge_world_systems(project, incoming_world, current_world, genre_plugins)
    world_blueprint["living_world"] = _merge_living_world(project, incoming_world, current_world, genre_plugins)
    if not uses_game_modules:
        world_blueprint["living_world"].pop("player_ecology", None)
    else:
        world_blueprint["npc_system"] = _merge_npc_system(project, incoming_world, current_world, genre_plugins)
        world_blueprint["quest_network"] = _merge_quest_network(project, incoming_world, current_world, genre_plugins)
        world_blueprint["server_runtime"] = _merge_server_runtime(project, incoming_world, current_world, genre_plugins)
        world_blueprint["map_ecology"] = _merge_map_ecology(project, incoming_world, current_world, genre_plugins)
    if incoming_world.get("genre_plugin_ids") or current_world.get("genre_plugin_ids"):
        world_blueprint["genre_plugin_ids"] = incoming_world.get("genre_plugin_ids") or current_world.get("genre_plugin_ids")

    for field in RULEBOOK_FIELDS:
        if field in {"quest_rules", "panel_rules"} and not uses_game_modules:
            continue
        sources = (
            (
                [*market_rules(), *appraisal_rules(), *exchange_rules()],
                current_world.get(field),
                incoming_world.get(field),
                plugin_rulebook.get(field, []),
            )
            if field == "economy_rules" and "game_webnovel" in plugin_ids
            else (incoming_world.get(field), current_world.get(field), plugin_rulebook.get(field, []))
        )
        world_blueprint[field] = _merge_string_lists(
            *sources,
            limit=12,
            item_limit=260,
        )

    derived_constraints = _derive_author_constraints(world_blueprint)
    merged_constraints = _merge_string_lists(
        incoming_world.get("constraints"),
        current_world.get("constraints"),
        project.author_constraints,
        derived_constraints,
        limit=8,
        item_limit=200,
    )
    world_blueprint["constraints"] = _drop_irrelevant_genre_constraints(
        merged_constraints,
        uses_game_modules=uses_game_modules,
        requires_power_system=requires_power_system,
    )

    next_project.world_blueprint = world_blueprint
    next_project.author_constraints = _drop_irrelevant_genre_constraints(
        _merge_string_lists(
        project.author_constraints,
        world_blueprint["constraints"],
        derived_constraints,
        limit=8,
        item_limit=200,
        ),
        uses_game_modules=uses_game_modules,
        requires_power_system=requires_power_system,
    )
    next_project.character_profiles = _as_character_profiles(
        parsed.get("character_profiles"),
        project.character_profiles or _default_character_profiles(project, genre_plugins),
    )
    next_project.relationship_graph = relationships
    if parsed.get("world_summary"):
        next_project.world_summary = compact_text(str(parsed["world_summary"]), 360)
    elif world_blueprint["premise"]:
        next_project.world_summary = world_blueprint["premise"]
    if parsed.get("current_focus"):
        next_project.current_focus = compact_text(str(parsed["current_focus"]), 620)
    elif world_blueprint["current_arc"]:
        next_project.current_focus = world_blueprint["current_arc"]
    return next_project


def _call_world_enrichment_model(
    project: NovelProject,
    *,
    rules_only: bool,
    model_gateway: RuntimeModelGateway | None = None,
) -> NovelProject:
    gateway = model_gateway or RuntimeModelGateway(runtime_resolver=resolve_stage_runtime)
    response = gateway.complete_stage(
        "planner",
        ModelRequest(
            prompt=_build_prompt(project, rules_only=rules_only),
            system_prompt="You are a senior Chinese webnovel worldbuilding editor. Return JSON only.",
            provider="",
            model="",
            operation="world_rulebook_enrichment" if rules_only else "world_enrichment",
            max_tokens=6000,
            json_mode=True,
            metadata={"reasoning_effort": "low", "enable_thinking": False},
        ),
    )
    if not response.ok:
        raise WorldEnrichmentError(response.error or "model_call_failed")
    parsed = parse_json_message_content(
        {"choices": [{"message": {"content": response.text}}]}
    )
    if not parsed:
        raise WorldEnrichmentError("invalid_llm_response")
    try:
        return _merge_enrichment(project, parsed, rules_only=rules_only)
    except TypeError as error:
        if "unexpected keyword argument 'rules_only'" not in str(error):
            raise
        return _merge_enrichment(project, parsed)


def enrich_project_world(project: NovelProject) -> NovelProject:
    return _call_world_enrichment_model(project, rules_only=False)


def enrich_project_rulebook(project: NovelProject) -> NovelProject:
    return _call_world_enrichment_model(project, rules_only=True)
