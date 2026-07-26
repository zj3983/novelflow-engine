from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin
from packages.story_core.power_system_templates import copy_power_system_template


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
    power_system_template=copy_power_system_template("rules_mystery"),
    trope_templates=(
        {
            "id": "rule_text_with_trap",
            "name": "规则文本藏陷阱",
            "trigger": "副本、怪谈场所或异常空间需要给出第一组行动边界。",
            "beats": ["规则出现", "找出歧义词", "低成本验证", "发现代价", "保留一条可疑规则"],
            "payoff": "规则从气氛文本变成推理和生存工具。",
            "avoid": ["不要规则随意改口", "不要所有规则都是真的", "不要主角凭直觉跳过验证"],
        },
        {
            "id": "failed_test_by_side_character",
            "name": "试错死人",
            "trigger": "需要展示禁忌危险，但主角不能无脑送死。",
            "beats": ["配角误读规则", "小违规", "异常反应", "死亡或污染代价", "主角获得可验证信息"],
            "payoff": "危险边界被证明，恐惧和推理同时推进。",
            "avoid": ["不要配角纯降智", "不要死亡没有信息价值", "不要把试错写成猎奇展示"],
        },
        {
            "id": "safe_zone_betrayal",
            "name": "安全区失效",
            "trigger": "玩家以为某处、某身份或某时间段绝对安全，故事需要升级规则层级。",
            "beats": ["建立安全认知", "出现异常例外", "找出触发条件", "牺牲资源脱身", "揭示更高层规则"],
            "payoff": "副本难度升级，但仍保持规则可推理。",
            "avoid": ["不要无理由取消安全区", "不要让更高规则不可验证", "不要连续推翻读者已知全部信息"],
        },
        {
            "id": "truth_fragment_after_clearance",
            "name": "通关真相碎片",
            "trigger": "阶段通关或逃离后，需要把单副本和主线世界观连接起来。",
            "beats": ["阶段奖励", "幸存者损失", "旧案/幕后碎片", "道具或污染后遗症", "下一副本线索"],
            "payoff": "副本有闭环，长线谜团向前移动。",
            "avoid": ["不要通关后只清算奖励", "不要大段讲完世界观", "不要让副本真相和主线无关"],
        },
    ),
)
