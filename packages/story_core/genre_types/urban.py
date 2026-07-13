from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin


URBAN = GenrePlugin(
    plugin_id="urban",
    name="都市现代",
    keywords=("都市", "职场", "豪门", "商业", "娱乐圈", "直播", "校园", "现代", "公司", "资本"),
    core_promises=(
        "读者期待现实压力下的资源翻盘、人际博弈、身份反差和阶段性打脸兑现。",
    ),
    ledger_fields=("金钱", "人脉", "事业阶段", "舆论", "身份秘密", "对手压力"),
    rulebook={
        "progression_rules": (
            "事业、财富、人脉和名声的提升必须有事件来源和现实阻力。",
        ),
        "economy_rules": (
            "合同、资金、流量、资源置换和商业利益必须符合现实逻辑。",
        ),
        "quest_rules": (
            "每个阶段目标要能落在项目、比赛、合同、舆论或关系节点上。",
        ),
        "faction_rules": (
            "公司、家族、平台、媒体和竞争者要对主角行动产生真实反馈。",
        ),
        "panel_rules": (
            "现实题材少用说明书旁白，优先通过对话、信息差和现场压力展示规则。",
        ),
        "chapter_formula": (
            "用现实困境开场，通过选择和博弈制造反转，结尾留下更高层对手或更大机会。",
        ),
        "forbidden_breaks": (
            "禁止无逻辑暴富，禁止所有人突然配合主角，禁止现实系统失真。",
        ),
    },
    quality_checks=("现实逻辑", "利益闭环", "反转可信", "人际压力", "舆论反馈"),
)
