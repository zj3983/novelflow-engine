from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin


RULES_MYSTERY = GenrePlugin(
    plugin_id="rules_mystery",
    name="规则怪谈",
    keywords=("规则怪谈", "怪谈", "禁忌", "规则", "污染", "异常", "诡异", "副本规则"),
    core_promises=(
        "读者期待规则逐条验证、禁忌代价、异常污染和规则背后真相逐步揭开。",
    ),
    ledger_fields=("已知规则", "可疑规则", "违规代价", "污染度", "安全区", "异常实体"),
    rulebook={
        "progression_rules": (
            "规则必须被验证、误读或反转，不能只作为气氛文本。",
        ),
        "economy_rules": (
            "安全信息、道具、时间和信任都是稀缺资源，使用必须有代价。",
        ),
        "quest_rules": (
            "每章要验证至少一条规则或发现一条规则的漏洞、代价或例外。",
        ),
        "faction_rules": (
            "异常实体、幸存者、管理员或幕后机制都应围绕规则产生行为逻辑。",
        ),
        "panel_rules": (
            "规则文本要简短、明确、可疑，正文通过行动验证其真实含义。",
        ),
        "chapter_formula": (
            "开场给禁忌，中段测试规则并付出代价，结尾揭示规则矛盾或更高层规则。",
        ),
        "forbidden_breaks": (
            "禁止规则随意改口，禁止没有代价的试错，禁止用梦境或幻觉轻易取消危机。",
        ),
    },
    quality_checks=("规则验证", "禁忌代价", "污染递进", "异常逻辑", "真相碎片"),
)
