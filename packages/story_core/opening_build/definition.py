"""Explicit expansion of the same project graph, never a second state machine."""
from dataclasses import replace

from packages.story_core.build_graph.definition import BuildGraphDefinition
from packages.story_core.world_build.definition import _task, build_world_build_graph
from .contracts import output_model


CHAPTER_COUNT = 3


def opening_graph(project):
    world = build_world_build_graph(project)
    specs = dict(world.specs)

    def add(task_id, title, dependencies=(), *, kind="model", instructions="", tokens=6000):
        model = output_model(task_id)
        fields = tuple(model.model_fields) if model else (task_id,)
        specs[task_id] = _task(
            task_id, title, dependencies=tuple(dependencies),
            reads=tuple(path for dep in dependencies for path in specs[dep].task.owns),
            owns=(f"build.opening.{task_id}",), kind=kind,
            validator_id=f"opening.{task_id}", output_fields=fields,
            output_schema=model.model_json_schema() if model else {},
            instructions=instructions, max_tokens=tokens,
        )

    add("opening_input", "作者开局输入", kind="imported")
    add("story_core", "故事核心", ("opening_input",), instructions="完整定义故事承诺、主角目标、核心冲突、失败代价和结局方向。", tokens=4000)
    add("character_seeds", "角色种子", ("story_core",), instructions="生成4至6名具名角色，包含主角、阶段反派、长期反派、配角；使用正式角色分类与动机契约。")
    root = specs["world_input"]
    specs["world_input"] = replace(root, kind="deterministic", task=replace(
        root.task, dependencies=("opening_input", "story_core", "character_seeds"),
        reads=("build.opening.opening_input", "build.opening.story_core", "build.opening.character_seeds"),
    ))
    add("detailed_characters", "详细角色", ("character_seeds", *world.definition.ordered_task_ids), instructions="沿用种子全部角色姓名与分类，补足正式角色卡，包括身份、经历、生活、动机、行为与声音。", tokens=14000)
    add("relationships", "角色关系", ("detailed_characters",), instructions="只在已提交角色之间定义关系。source和target使用角色姓名，禁止自环，id唯一。")
    add("longform_story_engine", "长篇故事引擎", ("story_core", "detailed_characters", "relationships", "story_engine_compat"), instructions="以既有世界约束和人物关系建立可持续的冲突循环、升级与最终兑现。")
    add("book_outline", "全书大纲", ("story_core", "longform_story_engine"), instructions="完整填写全书overall：故事、主题、前后台故事、目标、结局画面、主角目标、冲突、成长、结局方向、核心完结章与扩展上限。")
    add("volume_plan", "分卷规划", ("book_outline", "detailed_characters", "longform_story_engine"), instructions="覆盖全书。除最后一卷外每卷至少50章，区间连续不重叠；填写情绪曲线、钩子、不可逆变化、恰好三个key_results、具名阶段反派与长期反派痕迹，以及完整覆盖每卷区间的story_nodes。", tokens=10000)
    add("event_chains", "事件链", ("volume_plan", "relationships"), instructions="为每卷给出约每15章一个story node，完整覆盖分卷区间。每个节点包含目标、压力、转折、兑现和后续影响。", tokens=10000)
    previous = None
    for number in range(1, CHAPTER_COUNT + 1):
        task_id = f"chapter_outline_{number}"
        deps = ("book_outline", "volume_plan", "event_chains", "detailed_characters", "relationships")
        if previous:
            deps += (previous,)
        add(task_id, f"第{number}章细纲", deps, instructions=f"只输出第{number}章。必须填写具体目标、障碍、行动、转折、兑现、结尾钩子、cast，以及完整payoff_contract和chapter_sop；承接上章结果。", tokens=5000)
        previous = task_id
    add("outline_execution_contract", "章节执行契约", (
        "story_core", "book_outline", "volume_plan", "event_chains", "detailed_characters",
        *(f"chapter_outline_{n}" for n in range(1, CHAPTER_COUNT + 1)),
    ), kind="deterministic")
    definition = BuildGraphDefinition(graph_id=world.definition.graph_id, tasks=tuple(spec.task for spec in specs.values()))
    return replace(world, definition=definition, specs=specs)
