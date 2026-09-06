from __future__ import annotations

import json
import math
import re
from collections.abc import Callable, Mapping
from copy import deepcopy
from dataclasses import dataclass
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
from packages.story_core.power_system_spec import (
    effective_power_system_template,
    uses_traditional_game_class_advancement,
)
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


@dataclass(frozen=True)
class WorldBuildModule:
    """One bounded worldbuilding responsibility and its persisted fields."""

    module_id: str
    title: str
    fields: tuple[str, ...]
    required_fields: tuple[str, ...]
    instructions: str
    max_tokens: int


def world_build_modules(project: NovelProject) -> tuple[WorldBuildModule, ...]:
    """Select the smallest useful worldbuilding workflow for a novel type.

    The previous one-shot prompt asked one model call to invent every layer of a
    setting.  Modules keep ownership clear while still avoiding a heavyweight
    agent graph: normal projects make three calls; game novels add one runtime
    ecology call.
    """

    selected_plugin = _selected_novel_type_plugin(project)
    requires_power_system = _requires_structured_power_system(selected_plugin.plugin_id)
    core_fields = ("premise", "world_rules", "constraints", "locations", "factions")
    core_required: tuple[str, ...] = ("world_rules", "locations", "factions")
    if requires_power_system:
        core_fields += ("power_system", "power_system_spec")
        core_required = core_required + ("power_system_spec",)
    core_instructions = (
        "定义这个世界不可违背的底层规则、代价和边界。"
        "只解释本作与日常常识不同的部分，不写剧情结果或角色命运。"
    )
    if requires_power_system:
        core_instructions += (
            "同时给出可校验的力量或成长体系：来源、路径、阶段、资源、代价、克制和可见信息都必须具体。"
        )

    modules: list[WorldBuildModule] = [
        WorldBuildModule(
            module_id="core_rules",
            title="核心规则",
            fields=core_fields,
            required_fields=core_required,
            instructions=core_instructions,
            max_tokens=3200 if requires_power_system else 1800,
        ),
        WorldBuildModule(
            module_id="society_and_livelihood",
            title="社会与资源",
            fields=(
                "locations",
                "factions",
                "economy_rules",
                "faction_rules",
                "relationship_graph",
                "world_systems",
                "living_world",
            ),
            required_fields=("world_systems", "living_world"),
            instructions=(
                "建立地点、组织、资源流动和普通人的日常。必须交代谁分配资源、消息从哪里来、"
                "人为什么会相互合作或冲突；只写客观运行机制，不替章节设计剧情。"
            ),
            max_tokens=2600,
        ),
    ]
    if _uses_game_world_modules(selected_plugin.plugin_id):
        modules.append(
            WorldBuildModule(
                module_id="game_ecology",
                title="游戏运行",
                fields=(
                    "quest_rules",
                    "panel_rules",
                    "npc_system",
                    "quest_network",
                    "server_runtime",
                    "map_ecology",
                ),
                required_fields=(
                    "npc_system",
                    "quest_network",
                    "server_runtime",
                    "map_ecology",
                ),
                instructions=(
                    "只补充当前项目已明确的游戏规则：任务、交易与资源、地图生态、NPC 和服务器阶段。"
                    "不得凭空套入职业、等级、现实反馈、货币或交易行规则；缺失处保持中性。"
                ),
                max_tokens=2200,
            )
        )
    modules.append(
        WorldBuildModule(
            module_id="story_engine",
            title="长篇运行",
            fields=(
                "current_arc",
                "progression_rules",
                "chapter_formula",
                "forbidden_breaks",
                "opening_arc",
                "volume_plan",
                "longform_framework",
                "progression_ledger",
            ),
            required_fields=(
                "opening_arc",
                "volume_plan",
                "longform_framework",
            ),
            instructions=(
                "把已建立的规则转成可持续写作的运行边界：开篇风险、卷目标、成长阶梯、势力压力、"
                "资源消耗和谜团揭示节奏。不要替每一章编剧情，更不能改写已有章节事实。"
            ),
            max_tokens=2800,
        )
    )
    return tuple(modules)


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
            if not key or key in result or key in {"power_system_spec", "world_build_artifacts"}:
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
    current_power_spec = (
        project.world_blueprint.get("power_system_spec")
        if isinstance(project.world_blueprint, Mapping)
        else None
    )
    uses_traditional_game_advancement = (
        uses_game_modules
        and uses_traditional_game_class_advancement(current_power_spec)
    )
    power_template = effective_power_system_template(
        selected_plugin.plugin_id,
        power_template,
        current_power_spec,
    )
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
        if uses_traditional_game_advancement
        else "paths: [{name, role, core_resource, core_attributes, strengths, weaknesses, skill_categories, branches, advancement}]，"
        "逐成长路线写明路线定位、力量来源、关键条件、强弱项、能力类别、分支和推进条件；只使用上述字段；"
    )
    stage_schema = (
        "stages: [{name, level, entry, change, failure}]，按顺序写明阶段名、等级里程碑、进入条件、能力变化和失败后果；"
        if uses_traditional_game_advancement
        else "stages: [{name, level, entry, change, failure}]，按项目自身规则写阶段或行动里程碑；无等级项目不得虚构等级，level 可留空；"
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
            stage_schema,
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
                if uses_traditional_game_advancement
                else (
                    "game_progression_contract: 机器可读 JSON 契约："
                    "power_system_spec.class_advancement_tiers: "
                    "[{level,name,purpose,common_requirements,failure_rule}]；"
                    "paths 可包含 advancement_tree: [{level,tier_name,options}]。"
                    "仅当当前项目明确职业与等级晋升时填充这些数组，否则返回空数组；"
                    "不得自行添加项目未声明的职业路线或晋升机制。"
                    if selected_plugin.plugin_id == "game_webnovel"
                    else "game_class_advancement_rule: not_applicable"
                )
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
            "黄金三章要回答：第1章如何立世界/立主角/立项目既定规则/立风险，第2章如何扩大行动空间并让压力逼近，第3章如何形成第一个小高潮并确立长期路线。",
            "background_budget 必须包含 required_layers、allowed_layers、forbidden_layers，用于限制每章能展开多少世界背景，防止第一章堆设定。",
            "living_world 必须包含：daily_routines, economy, power_structure, information_network, player_ecology, information_visibility_rules, world_reaction_ladder, location_functions, timeline, reaction_rules。",
            "living_world 要回答：普通人每天在做什么，资源如何流动，谁控制秩序，消息如何传播，地点有什么功能，时间如何推进，主角行动会造成什么连锁反应。",
            "网游项目只能使用当前项目已经明确的等级、交换、现实关联和地图结构；缺失时保持中性，不得自行套用传统网游模板。",
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


def _merge_string_lists_with_fallback(
    current: Any,
    incoming: Any,
    fallback: Any,
    *,
    limit: int,
    item_limit: int = 240,
) -> list[str]:
    merged = _merge_string_lists(current, incoming, limit=limit, item_limit=item_limit)
    return merged or _as_string_list(fallback, limit, item_limit=item_limit)


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


def _merge_entry_lists_with_fallback(
    current: Any,
    incoming: Any,
    fallback: Any,
    *,
    limit: int,
) -> list[dict[str, str]]:
    merged: list[dict[str, str]] = []
    by_name: dict[str, dict[str, str]] = {}
    for value in (current, incoming):
        for entry in _as_entry_list(value, limit):
            name = entry["name"]
            existing = by_name.get(name)
            if existing is None:
                existing = entry
                by_name[name] = existing
                merged.append(existing)
            elif not existing.get("description") and entry.get("description"):
                existing["description"] = entry["description"]
            if len(merged) >= limit:
                return merged
    return merged or _as_entry_list(fallback, limit)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _default_living_world(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    daily_routines = [
        "角色与组织围绕各自目标持续行动，世界不会只在主角出现时运转。",
        "资源、信息与关系的变化会影响后续选择，并留下可追踪的结果。",
    ]
    game_channels: list[str] = []
    game_reactions: list[str] = []
    if _has_game_plugin(genre_plugins):
        daily_routines.append(
            "普通玩家、搬砖党、商人按各自目标持续探索、交易、组队或竞争，行动受公开规则、资源条件和可见信息限制。"
        )
        signals = _game_premise_signals(project)
        if signals["trade"]:
            game_channels.append("交易行行情与成交记录")
        if signals["guild"]:
            game_reactions.append("公会依据公开战绩与交易记录逐步评估玩家")
    player_ecology = [
        "不同角色与组织根据目标、能力、资源和风险偏好形成合作或竞争关系。",
    ]
    visibility_rules = [
        "角色只能依据可观察事实和可靠来源行动，不能无条件知道他人秘密。",
        "信息传播必须保留来源、延迟、误差和误判空间。",
    ]
    if _has_game_plugin(genre_plugins):
        player_ecology.append(
            "搬砖党、商人、公会各有自己的目标与资源约束，只按可见信息和公开行情行动。"
        )
        if any(_game_premise_signals(project)[key] for key in ("trade", "reality")):
            visibility_rules.append(
                "交易行、论坛、公会和NPC记录只能逐步暴露弱线索，不能直接还原主角全貌。"
            )
    return {
        "daily_routines": daily_routines,
        "economy": {
            "resource_flow": ["资源必须有明确来源、用途与消耗方式，具体形式服从当前项目设定。"],
            "pressure_points": ["资源稀缺", "信息差", "行动成本", "身份风险"],
        },
        "power_structure": {
            "dominant_groups": [],
            "control_methods": ["规则权限", "资源分配", "信息控制", "关系影响"],
        },
        "information_network": {
            "channels": ["公开信息", "私下沟通", "组织内部消息", "现场观察", *game_channels],
            "rumors": [],
        },
        "player_ecology": player_ecology,
        "information_visibility_rules": visibility_rules,
        "world_reaction_ladder": [
            "异常先形成局部痕迹，再经过观察、验证和多源汇总升级为明确反应。",
        ],
        "location_functions": [],
        "timeline": ["世界状态随角色行动和时间推进而变化。"],
        "reaction_rules": [
            "关键行动必须产生与其规模相称的后续反应。",
            "外部反应必须来自可观察痕迹，不能全知全能。",
            *game_reactions,
        ],
    }
def _merge_living_world(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("living_world"))
    current = _as_dict(current_world.get("living_world"))
    defaults = _default_living_world(project, genre_plugins)

    def nested(source: dict[str, Any], section: str, field: str) -> Any:
        return _as_dict(source.get(section)).get(field)

    return {
        "daily_routines": _merge_string_lists_with_fallback(
            current.get("daily_routines"), incoming.get("daily_routines"), defaults.get("daily_routines"),
            limit=12, item_limit=220,
        ),
        "economy": {
            "resource_flow": (
                _merge_string_lists(
                    [*market_rules(), *exchange_rules()],
                    nested(current, "economy", "resource_flow"),
                    nested(incoming, "economy", "resource_flow"),
                    nested(defaults, "economy", "resource_flow"),
                    limit=10,
                )
                if _has_game_plugin(genre_plugins) and any(_game_premise_signals(project, nested(current, "economy", "resource_flow"), nested(incoming, "economy", "resource_flow"))[key] for key in ("trade", "reality"))
                else _merge_string_lists_with_fallback(
                    nested(incoming, "economy", "resource_flow"),
                    nested(current, "economy", "resource_flow"),
                    nested(defaults, "economy", "resource_flow"),
                    limit=10,
                )
            ),
            "pressure_points": _merge_string_lists_with_fallback(
                nested(current, "economy", "pressure_points"),
                nested(incoming, "economy", "pressure_points"),
                nested(defaults, "economy", "pressure_points"),
                limit=10, item_limit=160,
            ),
        },
        "power_structure": {
            "dominant_groups": _merge_string_lists_with_fallback(
                nested(current, "power_structure", "dominant_groups"),
                nested(incoming, "power_structure", "dominant_groups"),
                nested(defaults, "power_structure", "dominant_groups"),
                limit=10, item_limit=120,
            ),
            "control_methods": _merge_string_lists_with_fallback(
                nested(current, "power_structure", "control_methods"),
                nested(incoming, "power_structure", "control_methods"),
                nested(defaults, "power_structure", "control_methods"),
                limit=10, item_limit=180,
            ),
        },
        "information_network": {
            "channels": _merge_string_lists_with_fallback(
                nested(current, "information_network", "channels"),
                nested(incoming, "information_network", "channels"),
                nested(defaults, "information_network", "channels"),
                limit=10, item_limit=120,
            ),
            "rumors": _merge_string_lists_with_fallback(
                nested(current, "information_network", "rumors"),
                nested(incoming, "information_network", "rumors"),
                nested(defaults, "information_network", "rumors"),
                limit=10, item_limit=220,
            ),
        },
        "player_ecology": _merge_string_lists_with_fallback(
            current.get("player_ecology"), incoming.get("player_ecology"), defaults.get("player_ecology"),
            limit=12, item_limit=220,
        ),
        "information_visibility_rules": _merge_string_lists_with_fallback(
            current.get("information_visibility_rules"), incoming.get("information_visibility_rules"),
            defaults.get("information_visibility_rules"), limit=12,
        ),
        "world_reaction_ladder": _merge_string_lists_with_fallback(
            current.get("world_reaction_ladder"), incoming.get("world_reaction_ladder"),
            defaults.get("world_reaction_ladder"), limit=10, item_limit=220,
        ),
        "location_functions": _merge_entry_lists_with_fallback(
            current.get("location_functions"), incoming.get("location_functions"),
            defaults.get("location_functions"), limit=16,
        ),
        "timeline": _merge_string_lists_with_fallback(
            current.get("timeline"), incoming.get("timeline"), defaults.get("timeline"), limit=12,
        ),
        "reaction_rules": _merge_string_lists_with_fallback(
            current.get("reaction_rules"), incoming.get("reaction_rules"),
            defaults.get("reaction_rules"), limit=12,
        ),
    }
def _default_world_systems(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    institutions: list[str] = []
    if _has_game_plugin(genre_plugins):
        signals = _game_premise_signals(project)
        if signals["trade"]:
            institutions.append("交换渠道按公开规则撮合资源流转，成交记录可追踪。")
        if signals["guild"]:
            institutions.append("玩家组织依据公开战绩与规则吸纳和管理成员。")
    return {
        "material_base": [
            "世界中的资源、能力与信息必须有明确来源、用途、限制和消耗。",
        ],
        "institutions": institutions,
        "social_order": [
            "角色与组织根据自身权限、目标和风险承受能力作出选择。",
        ],
        "conflict_engines": [
            "主角推进目标会改变既有关系或资源分配，并形成新的行动门槛。",
            "每个阶段冲突应同时包含外部压力、内部代价和下一步选择。",
        ],
        "causal_loops": [
            {"name": "行动反馈", "description": "角色行动 -> 世界状态变化 -> 其他角色反应 -> 新选择出现。"},
            {"name": "信息反馈", "description": "可观察痕迹出现 -> 信息传播与误判 -> 试探或合作 -> 认知更新。"},
        ],
    }
def _merge_world_systems(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("world_systems"))
    current = _as_dict(current_world.get("world_systems"))
    defaults = _default_world_systems(project, genre_plugins)
    return {
        "material_base": _merge_string_lists_with_fallback(
            current.get("material_base"), incoming.get("material_base"), defaults.get("material_base"),
            limit=10,
        ),
        "institutions": _merge_entry_lists_with_fallback(
            current.get("institutions"), incoming.get("institutions"), defaults.get("institutions"), limit=12,
        ),
        "social_order": _merge_string_lists_with_fallback(
            current.get("social_order"), incoming.get("social_order"), defaults.get("social_order"), limit=10,
        ),
        "conflict_engines": _merge_string_lists_with_fallback(
            current.get("conflict_engines"), incoming.get("conflict_engines"),
            defaults.get("conflict_engines"), limit=10, item_limit=260,
        ),
        "causal_loops": _merge_entry_lists_with_fallback(
            current.get("causal_loops"), incoming.get("causal_loops"), defaults.get("causal_loops"), limit=12,
        ),
    }
def _game_premise_signals(project: NovelProject, *extra_texts: Any) -> dict[str, bool]:
    """Detect which game sub-theme the project's own materials actually claim."""

    world = project.world_blueprint if isinstance(project.world_blueprint, dict) else {}
    living = world.get("living_world") if isinstance(world.get("living_world"), dict) else {}
    economy = living.get("economy") if isinstance(living.get("economy"), dict) else {}
    text = " ".join(
        str(item or "")
        for item in (
            project.seed_outline,
            project.world_summary,
            world.get("premise"),
            world.get("current_arc"),
            world.get("economy_rules"),
            economy.get("resource_flow"),
            *extra_texts,
        )
    )
    return {
        "trade": any(token in text for token in ("交易", "变现", "兑换", "出售", "售卖", "卖", "市场", "摆摊", "搬砖", "价格")),
        "guild": any(token in text for token in ("公会", "行会")),
        "reality": any(token in text for token in ("现实", "打工", "账单", "余额", "外包", "上班", "房租", "急账", "兼职", "千倍")),
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
    by_name: dict[str, dict[str, Any]] = {}
    for value in values:
        for entry in _as_rich_entry_list(value, limit, allowed_keys=allowed_keys):
            name = str(entry.get("name", "")).strip()
            existing = by_name.get(name)
            if name and existing is None:
                merged.append(entry)
                by_name[name] = entry
            elif existing is not None:
                for key, item in entry.items():
                    if key != "name" and existing.get(key) in (None, "", [], {}):
                        existing[key] = item
            if len(merged) >= limit:
                return merged
    return merged


def _default_npc_system(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "npcs": [],
        "rules": [
            "关键 NPC 应有独立目标、可提供的功能、信息边界和对玩家行动的反馈。",
            "NPC 只能依据自身经历、权限和可观察记录作出判断。",
        ],
    }
def _merge_npc_system(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("npc_system"))
    current = _as_dict(current_world.get("npc_system"))
    defaults = _default_npc_system(project, genre_plugins)
    allowed = ("role", "location", "services", "agenda", "knowledge_limit", "quest_hooks", "voice", "description")
    npcs = _merge_rich_entry_lists(current.get("npcs"), incoming.get("npcs"), limit=16, allowed_keys=allowed)
    if not npcs:
        npcs = _as_rich_entry_list(defaults.get("npcs"), 16, allowed_keys=allowed)
    return {
        "npcs": npcs,
        "rules": _merge_string_lists_with_fallback(
            current.get("rules"), incoming.get("rules"), defaults.get("rules"), limit=10, item_limit=220,
        ),
    }
def _default_quest_network(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "quest_types": ["主线目标", "支线目标", "探索目标"],
        "active_chains": [],
        "reward_rules": [
            "目标收益必须与难度、投入和风险相称，具体奖励服从当前项目规则。",
        ],
        "failure_costs": [
            "失败应改变时间、资源、关系或后续机会中的至少一项。",
        ],
    }
def _merge_quest_network(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("quest_network"))
    current = _as_dict(current_world.get("quest_network"))
    defaults = _default_quest_network(project, genre_plugins)
    allowed = ("description", "stages", "npc_links", "risk", "reward")
    chains = _merge_rich_entry_lists(
        current.get("active_chains"), incoming.get("active_chains"), limit=12, allowed_keys=allowed,
    )
    if not chains:
        chains = _as_rich_entry_list(defaults.get("active_chains"), 12, allowed_keys=allowed)
    return {
        "quest_types": _merge_string_lists_with_fallback(
            current.get("quest_types"), incoming.get("quest_types"), defaults.get("quest_types"),
            limit=12, item_limit=80,
        ),
        "active_chains": chains,
        "reward_rules": _merge_string_lists_with_fallback(
            current.get("reward_rules"), incoming.get("reward_rules"), defaults.get("reward_rules"),
            limit=10, item_limit=220,
        ),
        "failure_costs": _merge_string_lists_with_fallback(
            current.get("failure_costs"), incoming.get("failure_costs"), defaults.get("failure_costs"),
            limit=8, item_limit=180,
        ),
    }
def _default_server_runtime(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "phase": "",
        "channels": [],
        "announcement_rules": [],
        "gm_rules": [
            "系统或运营边界只执行当前项目已经确立的规则，不替角色解释未知真相。",
        ],
        "anti_cheat_rules": [
            "异常行为的识别必须依据项目已有监测规则与可验证记录。",
        ],
        "instance_rules": [
            "独立场景或挑战的进入条件、失败后果与重复规则必须明确。",
        ],
    }
def _merge_server_runtime(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("server_runtime"))
    current = _as_dict(current_world.get("server_runtime"))
    defaults = _default_server_runtime(project, genre_plugins)
    return {
        "phase": compact_text(str(current.get("phase") or incoming.get("phase") or defaults.get("phase") or ""), 220),
        "channels": _merge_string_lists_with_fallback(
            current.get("channels"), incoming.get("channels"), defaults.get("channels"), limit=12, item_limit=80,
        ),
        "announcement_rules": _merge_string_lists_with_fallback(
            current.get("announcement_rules"), incoming.get("announcement_rules"),
            defaults.get("announcement_rules"), limit=8, item_limit=200,
        ),
        "gm_rules": _merge_string_lists_with_fallback(
            current.get("gm_rules"), incoming.get("gm_rules"), defaults.get("gm_rules"), limit=8, item_limit=200,
        ),
        "anti_cheat_rules": _merge_string_lists_with_fallback(
            current.get("anti_cheat_rules"), incoming.get("anti_cheat_rules"),
            defaults.get("anti_cheat_rules"), limit=8, item_limit=200,
        ),
        "instance_rules": _merge_string_lists_with_fallback(
            current.get("instance_rules"), incoming.get("instance_rules"),
            defaults.get("instance_rules"), limit=8, item_limit=200,
        ),
    }
def _default_map_ecology(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "zones": [],
        "rules": [
            "地点必须承担行动、资源、关系或信息功能，并具有与之匹配的风险。",
            "角色移动会改变时间成本、可用机会和被观察范围。",
        ],
    }
def _merge_map_ecology(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("map_ecology"))
    current = _as_dict(current_world.get("map_ecology"))
    defaults = _default_map_ecology(project, genre_plugins)
    allowed = ("description", "resources", "npcs", "player_density", "risk", "outputs")
    zones = _merge_rich_entry_lists(current.get("zones"), incoming.get("zones"), limit=16, allowed_keys=allowed)
    if not zones:
        zones = _as_rich_entry_list(defaults.get("zones"), 16, allowed_keys=allowed)
    return {
        "zones": zones,
        "rules": _merge_string_lists_with_fallback(
            current.get("rules"), incoming.get("rules"), defaults.get("rules"), limit=8, item_limit=220,
        ),
    }
def _default_opening_arc(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    if _has_game_plugin(genre_plugins):
        signals = _game_premise_signals(project)
        chapter_1_must = ["具体场景入口", "主角当前目标", "一次有效行动", "行动结果与代价", "职业/工作状态与面板门槛", "金手指或核心机制的触发条件"]
        if signals["trade"]:
            chapter_1_must.append("交易行或等价交换渠道的入口")
        if signals["guild"]:
            chapter_1_must.append("公会或玩家组织的可见存在")
        chapter_1_conflicts = ["当下困境", "行动条件", "首次反馈"]
        if signals["reality"]:
            chapter_1_conflicts.insert(0, "现实压力")
        chapter_1_forbidden = ["禁止无铺垫升级为全局冲突", "禁止凭空增加项目未设定的能力或背景", "禁止外部势力未凭公开痕迹就精准锁定主角"]
        chapter_1_beats = ["通过行动结果交代规则", "通过角色选择交代动机"]
        if signals["reality"]:
            chapter_1_beats.extend(["用外包测试或等价杂务交代现实技能来源", "用底层日志或面板记录交代游戏侧异常"])
        chapter_1_required = ["主角目标", "行动规则"]
        chapter_1_required.insert(1, "现实入口与游戏入口" if signals["reality"] else "游戏入口")
        chapter_2_conflicts = ["资源选择", "行动成本", "外部观察"]
        if signals["trade"]:
            chapter_2_conflicts.insert(0, "资源路线")
        chapter_3_conflicts = ["具体试探", "策略应对", "长期选择"]
        if signals["reality"] or signals["guild"]:
            chapter_3_conflicts.insert(0, "职业门槛")
        return {
            "golden_three_chapters": {
                "chapter_1": {
                    "purpose": "建立现实压力、游戏入口、主角目标与金手指触发条件，完成第一次有效反馈。" if signals["reality"] else "建立游戏入口、主角目标与金手指触发条件，完成第一次有效反馈。",
                    "conflict_modes": chapter_1_conflicts,
                    "forbidden_conflicts": chapter_1_forbidden,
                    "must_include": chapter_1_must,
                    "exposition_beats": chapter_1_beats,
                    "background_budget": {
                        "required_layers": chapter_1_required,
                        "allowed_layers": ["一个外部角色或群体的有限反应"],
                        "forbidden_layers": ["连续堆叠设定", "多个命名NPC同时登场", "多个组织完整视角"],
                    },
                    "ending_hook": "第一次行动结果打开下一步选择。",
                },
                "chapter_2": {
                    "purpose": "扩展行动空间，验证规则，并让外部反应逐步形成。",
                    "conflict_modes": chapter_2_conflicts,
                    "forbidden_conflicts": ["禁止其他角色无证据掌握主角秘密"],
                    "must_include": ["规则再次验证", "新收益或新信息", "外部反应", "下一阶段条件"],
                    "exposition_beats": ["用交换、协作或冲突补充世界规则", "用配角反应展示世界持续运转"],
                    "background_budget": {
                        "required_layers": ["行动代价", "外部反应"],
                        "allowed_layers": ["一个新地点或新关系"],
                        "forbidden_layers": ["无依据的全知反应"],
                    },
                    "ending_hook": "新的条件或线索使主角必须调整计划。",
                },
                "chapter_3": {
                    "purpose": "形成首个阶段高潮，明确长期目标与持续压力。",
                    "conflict_modes": chapter_3_conflicts,
                    "forbidden_conflicts": ["禁止提前进入全书终局"],
                    "must_include": ["具体对抗或考验", "主角主动选择", "阶段目标", "持续压力"],
                    "exposition_beats": ["用冲突展示秩序", "用选择展示主角路线"],
                    "background_budget": {
                        "required_layers": ["具体考验", "长期目标"],
                        "allowed_layers": ["阶段小高潮"],
                        "forbidden_layers": ["提前终局化"],
                    },
                    "ending_hook": "更高阶段的条件或对手开始显现。",
                },
            }
        }
    return {
        "golden_three_chapters": {
            "chapter_1": {
                "purpose": "建立世界入口、主角目标、行动规则与第一次有效反馈。",
                "conflict_modes": ["当下目标", "当下困境", "行动条件", "首次反馈"],
                "forbidden_conflicts": ["禁止无铺垫升级为全局冲突", "禁止凭空增加项目未设定的能力或背景"],
                "must_include": ["具体场景入口", "主角当前目标", "一次有效行动", "行动结果与代价"],
                "exposition_beats": ["通过行动结果交代规则", "通过角色选择交代动机"],
                "background_budget": {
                    "required_layers": ["主角目标", "世界入口", "行动规则"],
                    "allowed_layers": ["一个外部角色或群体的有限反应"],
                    "forbidden_layers": ["连续堆叠设定", "多个组织完整视角"],
                },
                "ending_hook": "第一次行动结果打开下一步选择。",
            },
            "chapter_2": {
                "purpose": "扩展行动空间，验证规则，并让外部反应逐步形成。",
                "conflict_modes": ["资源选择", "行动成本", "行动条件", "外部观察"],
                "forbidden_conflicts": ["禁止其他角色无证据掌握主角秘密"],
                "must_include": ["规则再次验证", "新收益或新信息", "外部反应", "下一阶段条件"],
                "exposition_beats": ["用交换、协作或冲突补充世界规则", "用配角反应展示世界持续运转"],
                "background_budget": {
                    "required_layers": ["行动代价", "外部反应"],
                    "allowed_layers": ["一个新地点或新关系"],
                    "forbidden_layers": ["无依据的全知反应"],
                },
                "ending_hook": "新的条件或线索使主角必须调整计划。",
            },
            "chapter_3": {
                "purpose": "形成首个阶段高潮，明确长期目标与持续压力。",
                "conflict_modes": ["具体试探", "策略应对", "长期选择"],
                "forbidden_conflicts": ["禁止提前进入全书终局"],
                "must_include": ["具体对抗或考验", "主角主动选择", "阶段目标", "持续压力"],
                "exposition_beats": ["用冲突展示秩序", "用选择展示主角路线"],
                "background_budget": {
                    "required_layers": ["具体考验", "长期目标"],
                    "allowed_layers": ["阶段小高潮"],
                    "forbidden_layers": ["提前终局化"],
                },
                "ending_hook": "更高阶段的条件或对手开始显现。",
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
        combined = _deep_merge_dicts(
            _as_dict(incoming_golden.get(key)),
            _as_dict(current_golden.get(key)),
            preserve_empty=True,
        )
        merged = _as_opening_chapter(combined or default_golden.get(key))
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
            "volume_title": "第一卷 起势",
            "target_chapters": 50,
            "core_goal": "完成现实入口、游戏入口、主角行动路线与首卷目标的完整建立和兑现。",
            "phase_beats": [
                {"range": "1-3", "purpose": "黄金三章完成现实压力、登录建号与金手指首次验证。"},
                {"range": "4-20", "purpose": "扩展行动空间，形成稳定推进方式与持续代价。"},
                {"range": "21-40", "purpose": "让关系、信息和外部压力升级，并迫使主角调整策略。"},
                {"range": "41-50", "purpose": "完成首卷高潮与阶段目标，同时留下下一卷的具体入口。"},
            ],
            "long_threads": [
                "主角长期目标线。",
                *(
                    ["等级里程碑线：10级前后各有一次职业或能力跃迁。"]
                    if _game_premise_signals(project)["reality"]
                    else []
                ),
                "世界规则与行动代价线。",
                "关系和外部压力演变线。",
            ],
            "chapter_anchors": [
                "第1章完成世界入口与首次行动。",
                "第5章形成稳定推进目标。",
                "第20章兑现第一次阶段转折。",
                "第40章进入首卷高潮准备。",
                "第50章完成首卷目标并打开后续路线。",
            ],
        }
    return {
        "volume_title": "第一卷 起势",
        "target_chapters": 50,
        "core_goal": "完成世界入口、主角行动路线、阶段矛盾与首卷目标的完整建立和兑现。",
        "phase_beats": [
            {"range": "1-5", "purpose": "建立世界入口、主角目标、关键规则与第一次有效反馈。"},
            {"range": "6-20", "purpose": "扩展行动空间，形成稳定推进方式与持续代价。"},
            {"range": "21-40", "purpose": "让关系、信息和外部压力升级，并迫使主角调整策略。"},
            {"range": "41-50", "purpose": "完成首卷高潮与阶段目标，同时留下下一卷的具体入口。"},
        ],
        "long_threads": [
            "主角长期目标线。",
            "世界规则与行动代价线。",
            "关系和外部压力演变线。",
        ],
        "chapter_anchors": [
            "第1章完成世界入口与首次行动。",
            "第5章形成稳定推进目标。",
            "第20章兑现第一次阶段转折。",
            "第40章进入首卷高潮准备。",
            "第50章完成首卷目标并打开后续路线。",
        ],
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
    current_target = _as_int(current.get("target_chapters"), 0)
    proposed_target = _as_int(incoming.get("target_chapters"), int(defaults["target_chapters"]))
    is_final_arc = (
        current.get("is_final_arc") is True
        or ("is_final_arc" not in current and incoming.get("is_final_arc") is True)
    )
    minimum_chapters = 10 if is_final_arc else 50 if _has_game_plugin(genre_plugins) else 10
    target = max(minimum_chapters, current_target or proposed_target)
    phase_beats = _merge_phase_beats(
        current.get("phase_beats"), incoming.get("phase_beats"), limit=8,
    ) or _merge_phase_beats(defaults.get("phase_beats"), limit=8)
    source_target = current_target or proposed_target
    if phase_beats and not is_final_arc and 0 < source_target < target and len(phase_beats) < 8:
        phase_beats.append(
            {
                "range": f"{source_target + 1}-{target}",
                "purpose": "补足本卷中后段推进，完成阶段目标并形成卷末转折。",
            }
        )
    plan = {
        "volume_title": compact_text(str(current.get("volume_title") or incoming.get("volume_title") or defaults["volume_title"]), 80),
        "target_chapters": max(10, target),
        "core_goal": compact_text(str(current.get("core_goal") or incoming.get("core_goal") or defaults["core_goal"]), 260),
        "phase_beats": phase_beats,
        "long_threads": _merge_string_lists_with_fallback(
            current.get("long_threads"), incoming.get("long_threads"), defaults.get("long_threads"),
            limit=10, item_limit=220,
        ),
        "chapter_anchors": _merge_string_lists_with_fallback(
            current.get("chapter_anchors"), incoming.get("chapter_anchors"), defaults.get("chapter_anchors"),
            limit=10, item_limit=180,
        ),
    }
    if "is_final_arc" in current or "is_final_arc" in incoming:
        plan["is_final_arc"] = is_final_arc
    return plan


def _default_longform_framework(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    premise = compact_text(
        str(
            _as_dict(project.world_blueprint).get("premise")
            or project.world_summary
            or project.seed_outline
            or "主角从局部目标出发，在持续行动中进入更大的世界层级。"
        ),
        420,
    )
    return {
        "target_words": 1000000,
        "series_premise": premise,
        "volume_ladder": [
            {"range": "1-50", "title": "起势", "unlock": "核心规则与第一阶段目标", "pressure_cap": "局部压力"},
            {"range": "51-150", "title": "扩展", "unlock": "更大行动空间与关系网络", "pressure_cap": "区域压力"},
            {"range": "151-300", "title": "对抗", "unlock": "主要矛盾与关键选择", "pressure_cap": "组织压力"},
            {"range": "301-600", "title": "转折", "unlock": "核心谜团与世界变化", "pressure_cap": "世界压力"},
            {"range": "601-1000", "title": "终局", "unlock": "最终规则与核心目标", "pressure_cap": "终局压力"},
        ],
        "progression_ladder": ["能力、资源、关系和信息必须分阶段解锁。"],
        "faction_ladder": ["外部压力从个体或局部群体逐步扩展，具体组织由项目定义。"],
        "economy_ladder": ["资源收益与消耗必须匹配当前阶段，具体交换机制由项目定义。"],
        "reality_ladder": [],
        "mystery_ladder": ["核心谜团按现象、证据、误判、局部真相和总真相分阶段揭露。"],
        "map_ladder": ["行动空间按阶段开放，每个地点承担不同叙事功能。"],
        "npc_evolution_ladder": ["配角随事件获得新目标、新信息和新关系。"],
        "simulation_rules": [
            "章节推进必须遵守当前阶段上限，不能提前终局化。",
            "角色反应必须依据其掌握的信息、权限与利益。",
            "任何成长与收益都必须记录来源、代价和后续影响。",
        ],
    }
def _merge_ladder_entries(*values: Any, limit: int = 12) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    seen: set[str] = set()
    kept_ranges: list[tuple[int, int]] = []

    def ladder_span(text: str) -> tuple[int, int] | None:
        match = re.match(r"^\s*(\d+)\s*[-—~]\s*(\d+)\s*$", str(text or ""))
        if not match:
            return None
        return int(match.group(1)), int(match.group(2))

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
            if not key.strip() or key in seen:
                continue
            span = ladder_span(entry["range"])
            if span is not None and any(span[0] <= kept[1] and kept[0] <= span[1] for kept in kept_ranges):
                continue
            result.append(entry)
            seen.add(key)
            if span is not None:
                kept_ranges.append(span)
            if len(result) >= limit:
                return result
    return result


def _merge_longform_framework(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    incoming = _as_dict(incoming_world.get("longform_framework"))
    current = _as_dict(current_world.get("longform_framework"))
    defaults = _default_longform_framework(project, genre_plugins)
    target_words = _as_int(current.get("target_words") or incoming.get("target_words"), int(defaults["target_words"]))
    def preferred(field: str) -> Any:
        for source in (current, incoming, defaults):
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
        "series_premise": compact_text(str(current.get("series_premise") or incoming.get("series_premise") or defaults["series_premise"]), 420),
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
            "protagonist": {"stage": "起步", "location": "", "level": 1},
            "economy": {
                "inventory": [],
                "currency": (
                    "游戏币（金币/银币/铜币）"
                    if _game_premise_signals(project)["trade"]
                    else "游戏币"
                ),
            },
            "equipment": {},
            "skills": {"active": [], "locked": []},
            "quests": {"active": [], "completed": []},
            "relations": {},
            "pressure": {"external_attention": 0, "system_risk": 0, "guild_attention": 0},
        }
    return {
        "protagonist": {"stage": "起步", "location": ""},
        "economy": {"inventory": []},
        "equipment": {},
        "skills": {"active": [], "locked": []},
        "quests": {"active": [], "completed": []},
        "relations": {},
        "pressure": {"external_attention": 0, "system_risk": 0},
    }
def _deep_merge_dicts(
    base: dict[str, Any],
    override: dict[str, Any],
    *,
    preserve_empty: bool = False,
) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = _deep_merge_dicts(
                result[key], value, preserve_empty=preserve_empty
            )
        elif preserve_empty or value not in (None, "", [], {}):
            result[key] = deepcopy(value)
    return result


def _merge_progression_ledger(project: NovelProject, incoming_world: dict[str, Any], current_world: dict[str, Any], genre_plugins: list[dict[str, Any]]) -> dict[str, Any]:
    defaults = _default_progression_ledger(project, genre_plugins)
    current = _as_dict(current_world.get("progression_ledger"))
    incoming = _as_dict(incoming_world.get("progression_ledger"))
    return _deep_merge_dicts(
        _deep_merge_dicts(defaults, incoming),
        current,
        preserve_empty=True,
    )


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


def _merge_relationships(current: Any, incoming: Any, *, limit: int) -> list[dict[str, Any]]:
    current_items = current if isinstance(current, list) else []
    incoming_items = incoming if isinstance(incoming, list) else []
    merged: list[dict[str, Any]] = []
    positions: dict[tuple[str, str], int] = {}

    for item in current_items:
        if not isinstance(item, dict):
            continue
        source = compact_text(str(item.get("source", "")), 80)
        target = compact_text(str(item.get("target", "")), 80)
        if not source or not target:
            continue
        identity = (source, target)
        if identity not in positions:
            positions[identity] = len(merged)
            merged.append(deepcopy(item))
        if len(merged) >= limit:
            break

    for item in incoming_items:
        if not isinstance(item, dict):
            continue
        source = compact_text(str(item.get("source", "")), 80)
        target = compact_text(str(item.get("target", "")), 80)
        if not source or not target:
            continue
        identity = (source, target)
        index = positions.get(identity)
        if index is None:
            if len(merged) >= limit:
                break
            positions[identity] = len(merged)
            merged.append(deepcopy(item))
            continue
        saved = merged[index]
        for field in ("bond", "tension", "trust"):
            if saved.get(field) in (None, "", [], {}) and item.get(field) not in (None, "", [], {}):
                saved[field] = deepcopy(item[field])
    return _as_relationships(merged, limit)


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
        profile = {
            "name": name,
            "role": compact_text(str(item.get("role", "")), 80),
            "motivation": compact_text(str(item.get("motivation", "")), 220),
            "current_state": compact_text(str(item.get("current_state", "")), 220),
            "personality": compact_text(str(item.get("personality", "")), 220),
            "speech_style": compact_text(str(item.get("speech_style", "")), 160),
            "goals": _as_string_list(item.get("goals", []), 5),
            "secrets": _as_string_list(item.get("secrets", []), 5),
            "conflict_hooks": _as_string_list(item.get("conflict_hooks", []), 5),
        }
        game_id = compact_text(str(item.get("game_id", "")), 80)
        if game_id:
            profile["game_id"] = game_id
        profiles.append(profile)
        if len(profiles) >= limit:
            break
    return profiles


def _merge_character_profiles(current: Any, incoming: Any, limit: int = 24) -> list[dict[str, Any]]:
    current_profiles = _as_character_profiles(current, [], limit)
    incoming_profiles = _as_character_profiles(incoming, [], limit)
    merged = deepcopy(current_profiles)

    positions_by_game_id = {
        str(profile.get("game_id") or "").strip(): index
        for index, profile in enumerate(merged)
        if str(profile.get("game_id") or "").strip()
    }
    positions_by_name = {
        str(profile.get("name") or "").strip(): index
        for index, profile in enumerate(merged)
        if str(profile.get("name") or "").strip()
    }
    for profile in incoming_profiles:
        game_id = str(profile.get("game_id") or "").strip()
        name = str(profile.get("name") or "").strip()
        index = positions_by_game_id.get(game_id) if game_id else None
        if index is None:
            index = positions_by_name.get(name)
        if index is None:
            if len(merged) >= limit:
                break
            index = len(merged)
            merged.append(profile)
            if game_id:
                positions_by_game_id[game_id] = index
            if name:
                positions_by_name[name] = index
            continue
        existing = merged[index]
        for field, value in profile.items():
            if existing.get(field) in (None, "", [], {}) and value not in (None, "", [], {}):
                existing[field] = value
        saved_game_id = str(existing.get("game_id") or "").strip()
        if saved_game_id:
            positions_by_game_id[saved_game_id] = index
    return merged


def _default_character_profiles(project: NovelProject, genre_plugins: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return []


def _derive_author_constraints(world_blueprint: dict[str, Any]) -> list[str]:
    constraints: list[str] = []
    plugin_ids = {str(item).strip() for item in world_blueprint.get("genre_plugin_ids", []) if str(item).strip()}
    if "game_webnovel" in plugin_ids:
        constraints.append(
            "角色卡同时提供姓名和游戏ID时，游戏内行动优先使用游戏ID；未提供时不得凭空补写另一套身份。"
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
    metadata: list[dict[str, Any]] = []
    for plugin in plugins:
        if plugin.plugin_id == "game_webnovel":
            metadata.append(
                {
                    "id": plugin.plugin_id,
                    "name": plugin.name,
                    "core_promises": ["游戏规则保持一致，行动产生可追踪反馈。"],
                    "ledger_fields": ["角色状态", "资源", "能力", "装备", "目标", "关系", "外部压力"],
                    "quality_checks": ["规则一致", "行动闭环", "信息边界", "状态连续"],
                }
            )
        else:
            metadata.append(
                {
                    "id": plugin.plugin_id,
                    "name": plugin.name,
                    "core_promises": list(plugin.core_promises),
                    "ledger_fields": list(plugin.ledger_fields),
                    "quality_checks": list(plugin.quality_checks),
                }
            )
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

    if current_validated is not None:
        return deepcopy(current_validated), False

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
        return deepcopy(incoming_validated), True

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

    saved_relationships = project.relationship_graph or current_world.get("relationship_graph")
    incoming_relationships = [
        *(
            incoming_world.get("relationship_graph")
            if isinstance(incoming_world.get("relationship_graph"), list)
            else []
        ),
        *(
            parsed.get("relationship_graph")
            if isinstance(parsed.get("relationship_graph"), list)
            else []
        ),
    ]
    relationships = _merge_relationships(
        saved_relationships,
        incoming_relationships,
        limit=48,
    )
    world_blueprint: dict[str, Any] = {
        "premise": compact_text(str(current_world.get("premise") or incoming_world.get("premise") or project.world_summary), 360),
        "world_rules": _merge_string_lists(current_world.get("world_rules"), incoming_world.get("world_rules"), limit=16),
        "locations": _merge_entry_lists_with_fallback(current_world.get("locations"), incoming_world.get("locations"), [], limit=16),
        "factions": _merge_entry_lists_with_fallback(current_world.get("factions"), incoming_world.get("factions"), [], limit=16),
        "current_arc": compact_text(str(current_world.get("current_arc") or incoming_world.get("current_arc") or project.current_focus), 520),
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
                current_world.get("power_system"),
                incoming_world.get("power_system"),
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
        world_blueprint["genre_plugin_ids"] = current_world.get("genre_plugin_ids") or incoming_world.get("genre_plugin_ids")

    for field in RULEBOOK_FIELDS:
        if field in {"quest_rules", "panel_rules"} and not uses_game_modules:
            continue
        plugin_fallback = [] if uses_game_modules else plugin_rulebook.get(field, [])
        if field == "economy_rules" and uses_game_modules and any(_game_premise_signals(project, current_world.get(field), incoming_world.get(field))[key] for key in ("trade", "reality")):
            world_blueprint[field] = _merge_string_lists(
                [*market_rules(), *appraisal_rules(), *exchange_rules()],
                current_world.get(field),
                incoming_world.get(field),
                limit=12,
                item_limit=260,
            )
        elif field == "economy_rules":
            world_blueprint[field] = _merge_string_lists_with_fallback(
                incoming_world.get(field),
                current_world.get(field),
                plugin_fallback,
                limit=12,
                item_limit=260,
            )
        else:
            world_blueprint[field] = _merge_string_lists_with_fallback(
                current_world.get(field),
                incoming_world.get(field),
                plugin_fallback,
                limit=12,
                item_limit=260,
            )

    derived_constraints = _derive_author_constraints(world_blueprint)
    merged_constraints = _merge_string_lists(
        current_world.get("constraints"),
        incoming_world.get("constraints"),
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
    next_project.character_profiles = _merge_character_profiles(
        project.character_profiles,
        parsed.get("character_profiles"),
    )
    next_project.relationship_graph = relationships
    if project.world_summary:
        next_project.world_summary = project.world_summary
    elif parsed.get("world_summary"):
        next_project.world_summary = compact_text(str(parsed["world_summary"]), 360)
    elif world_blueprint["premise"]:
        next_project.world_summary = world_blueprint["premise"]
    if project.current_focus:
        next_project.current_focus = project.current_focus
    elif parsed.get("current_focus"):
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
    base_prompt = _build_prompt(project, rules_only=rules_only)
    validation_feedback = ""
    for attempt in range(2):
        prompt = base_prompt
        if validation_feedback:
            prompt += (
                "\n\n上一次返回的力量体系未通过确定性校验。"
                f"错误：{validation_feedback}。"
                "请完整重写 power_system_spec，逐项满足题材模板中的最少层级、"
                "固定里程碑、路径和连续性账本要求；仍只返回完整 JSON。"
            )
        response = gateway.complete_stage(
            "planner",
            ModelRequest(
                prompt=prompt,
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
            try:
                return _merge_enrichment(project, parsed, rules_only=rules_only)
            except TypeError as error:
                if "unexpected keyword argument 'rules_only'" not in str(error):
                    raise
                return _merge_enrichment(project, parsed)
        except ValueError as error:
            detail = str(error)
            if attempt == 0 and detail.startswith("invalid_power_system_spec:"):
                validation_feedback = detail
                continue
            raise
    raise WorldEnrichmentError("world_enrichment_validation_retry_exhausted")


def _build_world_module_prompt(
    project: NovelProject,
    module: WorldBuildModule,
) -> str:
    """Build a small, field-owned prompt instead of the old omnibus request."""

    selected_plugin = _selected_novel_type_plugin(project)
    payload = _compact_project_payload(project, budget=12_000)
    field_list = ", ".join(module.fields)
    lines = [
        "你是中文长篇网文的世界观编辑。只返回 JSON，不要 Markdown，不要小说正文。",
        f"当前题材：{selected_plugin.name}（{selected_plugin.plugin_id}）。",
        f"当前模块：{module.title}。",
        f"本模块唯一职责：{module.instructions}",
        f"只允许输出 world_blueprint 的这些字段：{field_list}。不要输出任何其他字段。",
        "沿用输入中的人名、地名、既有事实；没有依据时不补具体数字、专名或剧情。",
        "避免空话，如“存在复杂势力”“资源很重要”；每一条规则都要说明可观察的结果或限制。",
        "输出结构：{\"world_blueprint\": { ... }}。",
    ]
    if "power_system_spec" in module.fields:
        lines.extend(
            [
                "power_system_spec 必须包含 name、origin、attributes、paths、stages、skills、equipment、resources、advancement、costs、counters、boundaries、social_impact、visibility、continuity_ledger。",
                "每条路径说明定位、来源、强弱项、能力类别、分支和推进条件；每个阶段写进入条件、能力变化和失败后果。",
                "如果是网游且项目明确职业等级，基础职业转职节点固定为 Lv.10、Lv.30、Lv.60；否则不得编造等级或职业。",
            ]
        )
    lines.append(f"项目资料：{_serialized_json(payload)}")
    prompt = "\n".join(lines)
    if len(prompt) > _FINAL_PROMPT_MAX:
        raise WorldEnrichmentError("world_build_module_prompt_budget_exceeded")
    return prompt


def _module_world_payload(parsed: Any, module: WorldBuildModule) -> dict[str, Any]:
    if not isinstance(parsed, dict):
        raise WorldEnrichmentError(f"world_build_module_invalid_json:{module.module_id}")
    world = parsed.get("world_blueprint")
    if not isinstance(world, dict):
        raise WorldEnrichmentError(f"world_build_module_missing_payload:{module.module_id}")
    payload = {field: deepcopy(world[field]) for field in module.fields if field in world}
    if not payload:
        raise WorldEnrichmentError(f"world_build_module_empty_payload:{module.module_id}")
    missing = [
        field
        for field in module.required_fields
        if field not in payload or _is_blank_world_value(payload[field])
    ]
    if missing:
        raise WorldEnrichmentError(
            f"world_build_module_incomplete:{module.module_id}:{','.join(missing)}"
        )
    return payload


def _world_build_artifact(module: WorldBuildModule, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "module_id": module.module_id,
        "title": module.title,
        "status": "completed",
        "fields": list(payload),
        "output": _bounded_json_projection(payload, chars=280, items=16, depth=5),
    }


def _is_blank_world_value(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _apply_module_owned_fields(
    project: NovelProject,
    *,
    source_world: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> None:
    """Let a module replace only values that were absent before this build.

    ``_merge_enrichment`` deliberately fills defaults to keep an old project
    runnable.  Those newly-created defaults must not mask a later module in
    the same build.  A value the author had before pressing "AI 补全" remains
    authoritative.
    """

    for field, value in payload.items():
        if field in source_world and not _is_blank_world_value(source_world[field]):
            continue
        project.world_blueprint[field] = deepcopy(value)
        if field == "relationship_graph" and isinstance(value, list):
            project.relationship_graph = deepcopy(value)
        elif field == "current_arc" and isinstance(value, str) and value.strip():
            project.current_focus = compact_text(value, 620)


def _world_build_context_project(
    source_project: NovelProject,
    completed_outputs: Mapping[str, Any],
) -> NovelProject:
    """Project a context for the next module's prompt.

    The projection merges only validated completed-module outputs onto the
    original ``world_blueprint`` so later prompts do not see the placeholder
    defaults that ``_merge_enrichment`` adds during persistence.  The
    ``_merge_enrichment`` defaults exist so an old, half-filled project is
    still runnable; they must never leak back into a later model call.
    """

    context = source_project.model_copy(deep=True)
    context.world_blueprint = {
        **deepcopy(source_project.world_blueprint or {}),
        **deepcopy(dict(completed_outputs)),
    }
    return context


def _call_world_build_modules(
    project: NovelProject,
    *,
    model_gateway: RuntimeModelGateway | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> NovelProject:
    gateway = model_gateway or RuntimeModelGateway(runtime_resolver=resolve_stage_runtime)
    working = project.model_copy(deep=True)
    source_world = deepcopy(project.world_blueprint or {})
    artifacts: list[dict[str, Any]] = []
    completed_outputs: dict[str, Any] = {}
    for module in world_build_modules(project):
        if progress_callback is not None:
            progress_callback(
                {
                    "module_id": module.module_id,
                    "title": module.title,
                    "status": "running",
                    "message": f"正在构建：{module.title}",
                }
            )
        context_project = _world_build_context_project(project, completed_outputs)
        request = ModelRequest(
            prompt=_build_world_module_prompt(context_project, module),
            system_prompt="You are a senior Chinese webnovel worldbuilding editor. Return JSON only.",
            provider="",
            model="",
            operation=f"world_build_{module.module_id}",
            max_tokens=module.max_tokens,
            json_mode=True,
            metadata={
                "reasoning_effort": "low",
                "enable_thinking": False,
                "world_build_module": module.module_id,
            },
        )
        response = gateway.complete_stage("planner", request)
        if not response.ok:
            raise WorldEnrichmentError(
                f"world_build_module_failed:{module.module_id}:{response.error or 'model_call_failed'}"
            )
        parsed = parse_json_message_content(
            {"choices": [{"message": {"content": response.text}}]}
        )
        payload = _module_world_payload(parsed, module)
        # Capture raw validated output for downstream prompts before any
        # merge-default padding enters the next context.
        completed_outputs.update(deepcopy(payload))
        try:
            working = _merge_enrichment(
                working,
                {"world_blueprint": payload},
                rules_only=False,
            )
        except ValueError as exc:
            raise WorldEnrichmentError(
                f"world_build_module_validation_failed:{module.module_id}:{exc}"
            ) from exc
        _apply_module_owned_fields(
            working,
            source_world=source_world,
            payload=payload,
        )
        artifact = _world_build_artifact(module, payload)
        artifacts.append(artifact)
        if progress_callback is not None:
            progress_callback(
                {
                    "module_id": module.module_id,
                    "title": module.title,
                    "status": "done",
                    "message": f"已完成：{module.title}",
                    "artifact": artifact,
                }
            )

    working.world_blueprint["world_build_artifacts"] = artifacts
    return working


def enrich_project_world(
    project: NovelProject,
    *,
    model_gateway: RuntimeModelGateway | None = None,
    progress_callback: Callable[[dict[str, Any]], None] | None = None,
) -> NovelProject:
    return _call_world_build_modules(
        project,
        model_gateway=model_gateway,
        progress_callback=progress_callback,
    )


def enrich_project_rulebook(project: NovelProject) -> NovelProject:
    return _call_world_enrichment_model(project, rules_only=True)
