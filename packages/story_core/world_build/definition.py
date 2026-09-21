"""The production WorldBuild graph definition.

This module contains only application-owned task declarations.  It does not
execute a model call and it does not mutate a project.  Keeping the graph
definition here makes the production runner use the same dependency,
ownership, revision and stale semantics as every other Build Graph client.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping

from packages.story_core.build_graph.definition import (
    BuildGraphDefinition,
    BuildTaskDefinition,
)
from packages.story_core.models import NovelProject
from packages.story_core.world_enrichment import (
    _requires_structured_power_system,
    _selected_novel_type_plugin,
    _uses_game_world_modules,
)


WORLD_BUILD_GRAPH_ID = "novelflow-project-build"
WorldTaskKind = Literal["imported", "model", "deterministic"]


@dataclass(frozen=True)
class WorldBuildTaskSpec:
    """Execution metadata adjacent to, but not duplicated in, a graph task."""

    task: BuildTaskDefinition
    kind: WorldTaskKind
    output_fields: tuple[str, ...]
    domain_paths: tuple[str, ...] = ()
    output_schema: Mapping[str, Any] | None = None
    instructions: str = ""

    @property
    def task_id(self) -> str:
        return self.task.task_id

    @property
    def max_tokens(self) -> int:
        budget = self.task.output_budget
        if isinstance(budget, Mapping):
            try:
                return int(budget.get("max_tokens") or 1800)
            except (TypeError, ValueError):
                return 1800
        return int(budget or 1800)


@dataclass(frozen=True)
class WorldBuildGraph:
    definition: BuildGraphDefinition
    specs: Mapping[str, WorldBuildTaskSpec]
    plugin_id: str
    structured_power: bool
    game_world: bool

    def spec(self, task_id: str) -> WorldBuildTaskSpec:
        return self.specs[task_id]


def _task(
    task_id: str,
    title: str,
    *,
    dependencies: tuple[str, ...] = (),
    reads: tuple[str, ...] = (),
    owns: tuple[str, ...] = (),
    forbidden_writes: tuple[str, ...] = (),
    validator_id: str | None = None,
    kind: WorldTaskKind = "model",
    output_fields: tuple[str, ...] = (),
    domain_paths: tuple[str, ...] = (),
    output_schema: Mapping[str, Any] | None = None,
    instructions: str = "",
    max_tokens: int = 1800,
) -> WorldBuildTaskSpec:
    task = BuildTaskDefinition(
        task_id=task_id,
        title=title,
        dependencies=dependencies,
        reads=reads,
        owns=owns,
        forbidden_writes=forbidden_writes,
        validator_id=validator_id,
        model_stage="planner" if kind == "model" else None,
        context_policy={
            "contract": "world-build-input/v1",
            "bounded": True,
            "dependency_closure_only": True,
        },
        output_budget={
            "max_tokens": int(max_tokens),
            "max_output_chars": int(max_tokens) * 8,
        },
        review_policy="auto",
        required_for_readiness=True,
    )
    return WorldBuildTaskSpec(
        task=task,
        kind=kind,
        output_fields=output_fields,
        domain_paths=domain_paths,
        output_schema=output_schema,
        instructions=instructions,
    )


def build_world_build_graph(project: NovelProject) -> WorldBuildGraph:
    """Build the genre-scoped WorldBuild slice used by production jobs."""

    plugin = _selected_novel_type_plugin(project)
    plugin_id = plugin.plugin_id
    structured_power = _requires_structured_power_system(plugin_id)
    game_world = _uses_game_world_modules(plugin_id)

    all_power_paths = (
        "build.power_system.foundation",
        "build.power_system.attributes",
        "build.power_system.paths",
        "build.power_system.stages",
        "build.power_system.resources",
        "build.power_system.constraints",
    )

    specs: list[WorldBuildTaskSpec] = [
        _task(
            "world_input",
            "世界输入",
            kind="imported",
            validator_id="world.input",
            owns=("build.world_input",),
            output_fields=("title", "seed_outline", "story_core", "author_constraints", "current_focus", "genre_plugin_ids", "source_premise"),
            output_schema={"title": "string", "story_core": "object", "genre_plugin_ids": "string[]"},
            instructions="版本化作者输入与题材契约，不生成任何世界事实。",
            max_tokens=800,
        ),
        _task(
            "world_core_rules",
            "核心规则",
            dependencies=("world_input",),
            reads=("build.world_input",),
            owns=(
                "world_blueprint.premise",
                "world_blueprint.world_rules",
                "world_blueprint.constraints",
            ),
            forbidden_writes=(
                "world_blueprint.power_system_spec",
                "world_blueprint.power_system",
                "world_blueprint.locations",
                "world_blueprint.factions",
                "world_blueprint.economy_rules",
                "world_blueprint.current_arc",
            ),
            validator_id="world.core_rules",
            output_fields=("premise", "world_rules", "constraints"),
            domain_paths=(
                "world_blueprint.premise",
                "world_blueprint.world_rules",
                "world_blueprint.constraints",
            ),
            output_schema={"premise": "string", "world_rules": "string[]", "constraints": "string[]"},
            instructions="只定义世界不可违背的底层规则、代价和边界。不要写力量体系的分节内容、地点、势力或剧情规划。",
            max_tokens=1600,
        ),
    ]

    if structured_power:
        specs.extend(
            [
                _task(
                    "power_system_foundation",
                    "力量体系基础",
                    dependencies=("world_core_rules",),
                    reads=("build.world_input", "world_blueprint.world_rules"),
                    owns=("build.power_system.foundation",),
                    forbidden_writes=all_power_paths[1:] + ("world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    validator_id="power.foundation",
                    output_fields=("name", "origin"),
                    output_schema={"name": "string", "origin": "string[]"},
                    instructions="只生成力量体系名称与来源。不得生成 attributes、paths、stages 或其他章节。",
                    max_tokens=1600,
                ),
                _task(
                    "power_system_attributes",
                    "力量体系属性",
                    dependencies=("power_system_foundation",),
                    reads=("build.world_input", "build.power_system.foundation"),
                    owns=("build.power_system.attributes",),
                    forbidden_writes=("build.power_system.foundation", *all_power_paths[2:], "world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    validator_id="power.attributes",
                    output_fields=("attributes",),
                    output_schema={"attributes": "{name:string,effect:string}[]"},
                    instructions="只生成 attributes，每项必须有 name 和可观察的 effect。不得生成 paths、stages 或资源规则。",
                    max_tokens=2000,
                ),
                _task(
                    "power_system_paths",
                    "力量体系路径",
                    dependencies=("power_system_foundation", "power_system_attributes"),
                    reads=("build.world_input", "build.power_system.foundation", "build.power_system.attributes"),
                    owns=("build.power_system.paths",),
                    forbidden_writes=("build.power_system.foundation", "build.power_system.attributes", *all_power_paths[3:], "world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    validator_id="power.paths",
                    output_fields=("paths",),
                    output_schema={"paths": "object[]"},
                    instructions="只生成 paths。依据已提交的 foundation 与 attributes，描述路线定位、资源、强弱、分支和推进条件。",
                    max_tokens=3200,
                ),
                _task(
                    "power_system_stages",
                    "力量体系阶段",
                    dependencies=("power_system_paths", "power_system_attributes"),
                    reads=("build.world_input", "build.power_system.attributes", "build.power_system.paths"),
                    owns=("build.power_system.stages",),
                    forbidden_writes=("build.power_system.foundation", "build.power_system.attributes", "build.power_system.paths", *all_power_paths[4:], "world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    validator_id="power.stages",
                    output_fields=("stages",),
                    output_schema={"stages": "{name,level,entry,change,failure}[]"},
                    instructions="只生成 stages。每阶段必须说明 name、entry、change、failure；没有等级制度时 level 留空，不得编造等级。",
                    max_tokens=2600,
                ),
                _task(
                    "power_system_resources",
                    "力量体系资源",
                    dependencies=("power_system_paths", "power_system_stages"),
                    reads=("build.world_input", "build.power_system.paths", "build.power_system.stages"),
                    owns=("build.power_system.resources",),
                    forbidden_writes=("build.power_system.foundation", "build.power_system.attributes", "build.power_system.paths", "build.power_system.stages", "build.power_system.constraints", "world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    validator_id="power.resources",
                    output_fields=("skills", "equipment", "resources", "advancement"),
                    output_schema={"skills": "string[]", "equipment": "string[]", "resources": "string[]", "advancement": "string[]"},
                    instructions="只生成 skills、equipment、resources、advancement。内容必须能落回已提交的路线与阶段。",
                    max_tokens=2600,
                ),
                _task(
                    "power_system_constraints",
                    "力量体系边界",
                    dependencies=("power_system_resources", "power_system_stages"),
                    reads=("build.world_input", "build.power_system.stages", "build.power_system.resources"),
                    owns=("build.power_system.constraints",),
                    forbidden_writes=("build.power_system.foundation", "build.power_system.attributes", "build.power_system.paths", "build.power_system.stages", "build.power_system.resources", "world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    validator_id="power.constraints",
                    output_fields=("costs", "counters", "boundaries", "social_impact", "visibility", "continuity_ledger", "attribute_allocation", "class_advancement_tiers"),
                    output_schema={"costs": "string[]", "counters": "string[]", "boundaries": "string[]", "social_impact": "string[]", "visibility": "string[]", "continuity_ledger": "string[]"},
                    instructions="只生成 costs、counters、boundaries、social_impact、visibility、continuity_ledger，以及题材明确要求的扩展字段。不得修改前面章节。",
                    max_tokens=2800,
                ),
                _task(
                    "power_system_final",
                    "力量体系确定性组装",
                    dependencies=(
                        "power_system_foundation",
                        "power_system_attributes",
                        "power_system_paths",
                        "power_system_stages",
                        "power_system_resources",
                        "power_system_constraints",
                    ),
                    reads=all_power_paths,
                    owns=("world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    forbidden_writes=all_power_paths,
                    validator_id="power.final",
                    kind="deterministic",
                    output_fields=("power_system_spec", "power_system"),
                    domain_paths=("world_blueprint.power_system_spec", "world_blueprint.power_system"),
                    output_schema={"power_system_spec": "object", "power_system": "string[]"},
                    instructions="只读取已提交的六个力量子产物，规范化、完整校验并生成 legacy summary；不调用模型。",
                    max_tokens=800,
                ),
            ]
        )

    core_dependency = "power_system_final" if structured_power else "world_core_rules"
    specs.extend(
        [
            _task(
                "world_economy",
                "世界经济与资源",
                dependencies=("world_core_rules", core_dependency) if core_dependency != "world_core_rules" else ("world_core_rules",),
                reads=("build.world_input", "world_blueprint.world_rules", "build.power_system.constraints") if structured_power else ("build.world_input", "world_blueprint.world_rules"),
                owns=("world_blueprint.economy_rules",),
                forbidden_writes=("world_blueprint.locations", "world_blueprint.factions", "world_blueprint.world_systems", "world_blueprint.living_world", "world_blueprint.power_system_spec"),
                validator_id="world.economy",
                output_fields=("economy_rules",),
                domain_paths=("world_blueprint.economy_rules",),
                output_schema={"economy_rules": "string[]"},
                instructions="只解释资源从哪里来、如何交换、谁分配以及可追踪的代价，不设计地点、势力或剧情。",
                max_tokens=1800,
            ),
            _task(
                "world_locations",
                "世界地点",
                dependencies=("world_economy",),
                reads=("build.world_input", "world_blueprint.economy_rules"),
                owns=("world_blueprint.locations",),
                forbidden_writes=("world_blueprint.factions", "world_blueprint.world_systems", "world_blueprint.living_world", "world_blueprint.economy_rules"),
                validator_id="world.locations",
                output_fields=("locations",),
                domain_paths=("world_blueprint.locations",),
                output_schema={"locations": "{name,description}[]"},
                instructions="只生成地点及其叙事/功能用途，不能生成势力、角色或章节剧情。",
                max_tokens=2200,
            ),
            _task(
                "world_factions",
                "世界势力",
                dependencies=("world_locations",),
                reads=("build.world_input", "world_blueprint.locations", "world_blueprint.economy_rules"),
                owns=("world_blueprint.factions",),
                forbidden_writes=("world_blueprint.locations", "world_blueprint.world_systems", "world_blueprint.living_world"),
                validator_id="world.factions",
                output_fields=("factions",),
                domain_paths=("world_blueprint.factions",),
                output_schema={"factions": "{name,description}[]"},
                instructions="只生成势力、资源控制和公开立场，不替角色或大纲做决定。",
                max_tokens=2200,
            ),
            _task(
                "world_society",
                "社会运行",
                dependencies=("world_factions",),
                reads=("build.world_input", "world_blueprint.factions", "world_blueprint.locations", "world_blueprint.economy_rules"),
                owns=("world_blueprint.world_systems", "world_blueprint.living_world", "world_blueprint.faction_rules"),
                forbidden_writes=("world_blueprint.locations", "world_blueprint.factions", "world_blueprint.economy_rules", "world_blueprint.current_arc"),
                validator_id="world.society",
                output_fields=("world_systems", "living_world", "faction_rules"),
                domain_paths=("world_blueprint.world_systems", "world_blueprint.living_world", "world_blueprint.faction_rules"),
                output_schema={"world_systems": "object", "living_world": "object", "faction_rules": "string[]"},
                instructions="只生成普通人日常、制度、信息网络和组织运行机制，不生成剧情大纲。",
                max_tokens=2600,
            ),
        ]
    )

    if game_world:
        specs.append(
            _task(
                "game_ecology",
                "游戏生态",
                dependencies=("world_society",),
                reads=("build.world_input", "world_blueprint.world_systems", "world_blueprint.factions"),
                owns=(
                    "world_blueprint.quest_rules",
                    "world_blueprint.panel_rules",
                    "world_blueprint.npc_system",
                    "world_blueprint.quest_network",
                    "world_blueprint.server_runtime",
                    "world_blueprint.map_ecology",
                ),
                forbidden_writes=("world_blueprint.locations", "world_blueprint.factions", "world_blueprint.power_system_spec"),
                validator_id="world.game_ecology",
                output_fields=("quest_rules", "panel_rules", "npc_system", "quest_network", "server_runtime", "map_ecology"),
                domain_paths=(
                    "world_blueprint.quest_rules",
                    "world_blueprint.panel_rules",
                    "world_blueprint.npc_system",
                    "world_blueprint.quest_network",
                    "world_blueprint.server_runtime",
                    "world_blueprint.map_ecology",
                ),
                output_schema={"npc_system": "object", "quest_network": "object", "server_runtime": "object", "map_ecology": "object"},
                instructions="只补充项目已明确的游戏运行规则；不得凭空添加等级、货币、现实反馈或交易行机制。",
                max_tokens=2800,
            )
        )

    story_dependencies = ("world_society", "game_ecology") if game_world else ("world_society",)
    story_reads = (
        "build.world_input",
        "world_blueprint.world_rules",
        "world_blueprint.factions",
        "world_blueprint.world_systems",
    )
    if game_world:
        story_reads += ("world_blueprint.server_runtime", "world_blueprint.map_ecology")
    specs.append(
        _task(
            "story_engine_compat",
            "长篇引擎兼容层",
            dependencies=story_dependencies,
            reads=story_reads,
            owns=(
                "world_blueprint.current_arc",
                "world_blueprint.progression_rules",
                "world_blueprint.chapter_formula",
                "world_blueprint.forbidden_breaks",
                "world_blueprint.opening_arc",
                "world_blueprint.volume_plan",
                "world_blueprint.longform_framework",
                "world_blueprint.progression_ledger",
            ),
            forbidden_writes=("world_blueprint.power_system_spec", "world_blueprint.locations", "world_blueprint.factions"),
            validator_id="world.story_engine_compat",
            output_fields=("current_arc", "progression_rules", "chapter_formula", "forbidden_breaks", "opening_arc", "volume_plan", "longform_framework", "progression_ledger"),
            domain_paths=(
                "world_blueprint.current_arc",
                "world_blueprint.progression_rules",
                "world_blueprint.chapter_formula",
                "world_blueprint.forbidden_breaks",
                "world_blueprint.opening_arc",
                "world_blueprint.volume_plan",
                "world_blueprint.longform_framework",
                "world_blueprint.progression_ledger",
            ),
            output_schema={"opening_arc": "object", "volume_plan": "object", "longform_framework": "object"},
            instructions="这是明确命名的 story_engine compatibility task。只把已验证世界依赖转成现有长篇运行字段，不扩张为新的规划权威。",
            max_tokens=3000,
        )
    )

    definition = BuildGraphDefinition(
        graph_id=WORLD_BUILD_GRAPH_ID,
        tasks=tuple(spec.task for spec in specs),
    )
    return WorldBuildGraph(
        definition=definition,
        specs={spec.task_id: spec for spec in specs},
        plugin_id=plugin_id,
        structured_power=structured_power,
        game_world=game_world,
    )


__all__ = [
    "WORLD_BUILD_GRAPH_ID",
    "WorldBuildGraph",
    "WorldBuildTaskSpec",
    "build_world_build_graph",
]
