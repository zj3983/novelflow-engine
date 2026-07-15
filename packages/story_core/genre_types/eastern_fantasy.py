from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin


EASTERN_FANTASY = GenrePlugin(
    plugin_id="eastern_fantasy",
    name="东方幻想基础",
    keywords=(),
    core_promises=(
        "力量成长必须有资源、门槛、风险或代价。",
        "宗门、家族、王朝和地方势力围绕资源、传承和地位作出反应。",
        "开篇机缘优先写成残缺机缘：先给异常、线索或小反馈，不直接送出完整传承。",
        "宗门差事要落到具体的人、利益和麻烦上，用行动说明主角处境。",
    ),
    ledger_fields=("境界", "力量", "功法", "资源", "势力关系", "遗物线索"),
    rulebook={
        "progression_rules": (
            "境界、功法和资源必须前后一致，越阶需要明确凭依和代价。",
        ),
        "economy_rules": (
            "修炼资源要体现稀缺程度、势力控制和交换代价。",
        ),
        "quest_rules": (
            "差事、试炼和秘境要有进入条件、竞争者、失败代价和阶段收获。",
        ),
        "faction_rules": (
            "宗门、家族、王朝和地方势力按可见利益逐步反应。",
        ),
        "panel_rules": (
            "力量信息通过感知、战斗、传承或鉴定自然呈现。",
        ),
        "chapter_formula": (
            "开篇可从低位处境、具体麻烦、核心物件、小反馈和章末新压力展开。",
            "残缺机缘要逐步兑现：线索先于奖励，小反馈先于大突破。",
        ),
        "forbidden_breaks": (
            "禁止无代价顿悟、力量体系混乱和长辈无理由送出核心资源。",
            "禁止开篇大段讲境界表、势力历史或功法说明。",
        ),
    },
    quality_checks=("力量一致", "资源代价", "势力反馈", "机缘递进", "宗门差事"),
    trope_templates=(
        {
            "id": "low_status_assignment",
            "name": "低位差事",
            "trigger": "主角在宗门、家族、王朝或地方势力中地位低，需要用具体事务建立处境。",
            "beats": ["差事来源", "别人不愿接的原因", "主角接下的理由", "现场麻烦", "差事牵出旧线索"],
            "payoff": "低位不是口号，而是资源、人情和风险的具体限制。",
            "avoid": ["不要只写路人嘲讽", "不要让差事无成本变成大机缘", "不要开篇讲完整势力史"],
        },
        {
            "id": "incomplete_fortuitous_encounter",
            "name": "残缺机缘",
            "trigger": "主角接触遗物、祖地、旧殿、禁地或异常物件，需要给出本书独有钩子。",
            "beats": ["发现异常", "小规模验证", "得到残缺反馈", "暴露缺口或代价", "指向下一次查证"],
            "payoff": "机缘可信且可持续，不会一次把成长线发完。",
            "avoid": ["不要直接送完整传承", "不要无代价顿悟", "不要让长辈替主角解释全部秘密"],
        },
        {
            "id": "trial_resource_competition",
            "name": "试炼资源争夺",
            "trigger": "主角需要名额、材料、功法、秘境入口或身份认可。",
            "beats": ["公布门槛", "竞争者出现", "规则限制", "主角用信息差/代价破局", "胜出后引来势力反馈"],
            "payoff": "成长和地位变化通过公开竞争兑现。",
            "avoid": ["不要比赛规则临时为主角让路", "不要越阶无凭依", "不要只打脸不推进资源账"],
        },
    ),
)


EASTERN_FANTASY_SIMULATION_BLUEPRINT = {
    "plugin_id": "eastern_fantasy",
    "opening_scene_templates": [
        {
            "id": "low_status_assignment",
            "location": "势力内部的低位差事地点",
            "purpose": "用一件具体差事说明主角处境、资源短缺和利益分配。",
            "conflict": "差事少有人愿意接，主角接下后要承担具体麻烦。",
            "must_show": ["主角身份", "差事来源", "别人不愿接的原因", "主角接下的原因"],
        },
        {
            "id": "core_object_anomaly",
            "location": "旧殿、库房、祖地、山门角落或类似地点",
            "purpose": "让核心物件出现一个小异常，建立本书独有的线索。",
            "conflict": "异常不能直接变成完整传承，只指向一个可验证的小动作。",
            "must_show": ["核心物件", "异常反应", "主角能验证的一步"],
        },
        {
            "id": "small_feedback",
            "location": "同一场景内",
            "purpose": "兑现一个小反馈，让读者确认机缘有效但仍然残缺。",
            "conflict": "反馈有限，并带来下一步麻烦、误会或外部注意。",
            "must_show": ["小反馈", "代价或风险", "章末下一步"],
        },
    ],
    "conflict_ladders": {
        "chapter_1": ["低位处境", "具体差事", "核心物件", "小异常", "小反馈", "章末麻烦"],
        "chapter_2": ["查证线索", "势力人情", "资源限制", "外人误判", "第一次主动选择"],
        "chapter_3": ["反馈兑现", "内部竞争", "旧事线索", "公开压力", "小高潮"],
    },
    "forbidden_conflict_modes": {
        "chapter_1": [
            "不要直接送完整传承",
            "不要一章顿悟大功法",
            "不要长辈无理由送核心资源",
            "不要让路人集体嘲讽主角",
            "不要套用旧式逆袭口号",
        ]
    },
}
