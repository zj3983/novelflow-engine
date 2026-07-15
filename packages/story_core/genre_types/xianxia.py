from __future__ import annotations

from copy import deepcopy

from packages.story_core.genre_types.base import GenrePlugin
from packages.story_core.genre_types.eastern_fantasy import EASTERN_FANTASY, EASTERN_FANTASY_SIMULATION_BLUEPRINT


_LEGACY_SHARED_METHOD_MARKERS = tuple(
    marker
    for marker in ("残缺机缘", "宗门差事")
    if any(marker in promise for promise in EASTERN_FANTASY.core_promises)
)


XIANXIA = GenrePlugin(
    plugin_id="xianxia",
    name="修仙仙侠",
    keywords=("修仙", "仙侠", "灵根", "修真", "境界", "道法", "剑修", "炼丹", "法宝", "因果", "天劫", "渡劫", "飞升"),
    core_promises=(
        "力量成长围绕灵根、修真境界、道法传承和修炼资源展开。",
        "道法传承可以具体表现为剑修、炼丹和法宝祭炼等仙侠路径。",
        "长期推动力来自长生求道、道法因果、天劫考验和渡劫飞升。",
    ),
    ledger_fields=("灵根", "修真境界", "灵力", "道法", "法宝", "灵石", "因果债", "天劫"),
    rulebook={
        "progression_rules": (
            "修真境界、灵力和道法必须前后一致，突破需要资源、心境、机缘或风险。",
            "剑修的剑诀、剑意和本命剑成长要与境界、悟性及实战积累对应。",
            "越阶斗法必须有明确凭依，例如克制、阵法、法宝、情报差或代价。",
        ),
        "economy_rules": (
            "炼丹所需的丹方、药材和成丹率，以及灵石、材料和法宝，都要体现稀缺程度、宗门控制和交易风险。",
        ),
        "quest_rules": (
            "修真试炼和秘境要与道法传承、因果或境界成长发生联系。",
        ),
        "faction_rules": (
            "宗门、家族和修真势力围绕道统、资源、因果和飞升机会作出反应。",
        ),
        "panel_rules": (
            "灵根、境界和道法信息通过感知、斗法、传承或鉴定自然呈现。",
        ),
        "chapter_formula": (
            "每章至少推动境界压力、修炼资源、道法因果或求道选择中的一项。",
        ),
        "forbidden_breaks": (
            "禁止无代价顿悟、境界体系混乱和天劫只作装饰。",
            "禁止把渡劫飞升写成没有积累、因果和风险的固定奖励。",
        ),
    },
    quality_checks=("境界一致", "修炼代价", "道法因果", "天劫铺垫", "渡劫合理", *_LEGACY_SHARED_METHOD_MARKERS),
    trope_templates=(
        {
            "id": "spirit_root_test",
            "name": "灵根/资质测试",
            "trigger": "入门、收徒、外门晋升或宗门小比前，需要公开确认修炼起点。",
            "beats": ["测试规则", "资质结果", "旁人反应", "主角发现例外线索", "获得低阶路径或限制"],
            "payoff": "境界成长从明确起点出发，并留下可翻盘的例外条件。",
            "avoid": ["不要测试后立刻无敌", "不要只写羞辱", "不要忽略宗门资源分配"],
        },
        {
            "id": "manual_or_artifact_inheritance",
            "name": "功法/法宝传承",
            "trigger": "主角需要道法路径、剑修路线、炼丹入口或法宝线索。",
            "beats": ["残本/旧器出现", "传承条件", "首次祭炼或参悟", "因果或反噬", "下一层解锁门槛"],
            "payoff": "传承成为长期成长线，而不是一次性奖励。",
            "avoid": ["不要完整传承一次到手", "不要法宝无消耗救场", "不要跳过因果债"],
        },
        {
            "id": "tribulation_or_bottleneck",
            "name": "瓶颈/劫数",
            "trigger": "主角接近突破、因果清算或重要选择节点。",
            "beats": ["瓶颈征兆", "资源/心境缺口", "外部干扰", "付出代价突破或暂缓", "劫数留下后续影响"],
            "payoff": "修炼推进带来风险、选择和性格变化。",
            "avoid": ["不要把天劫当烟花", "不要无代价突破", "不要每次都靠外物硬推"],
        },
    ),
)


# 兼容尚未迁移到共享模板的旧调用方；Task 2 会改为直接读取共享模板。
XIANXIA_SIMULATION_BLUEPRINT = deepcopy(EASTERN_FANTASY_SIMULATION_BLUEPRINT)
XIANXIA_SIMULATION_BLUEPRINT["plugin_id"] = "xianxia"
