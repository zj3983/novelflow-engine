from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin


ROMANCE = GenrePlugin(
    plugin_id="romance",
    name="言情关系流",
    keywords=("言情", "甜宠", "虐恋", "婚恋", "总裁", "古言", "宫斗", "宅斗", "替身", "追妻", "女频"),
    core_promises=(
        "读者期待关系拉扯、情绪递进、误会与靠近交替发生，不能跳过情感成本。",
    ),
    ledger_fields=("关系阶段", "亲密度", "误会", "情绪债", "身份压力", "外部阻碍"),
    rulebook={
        "progression_rules": (
            "关系推进必须有情绪触发、行为证据和心理变化，不能突然相爱或突然决裂。",
        ),
        "economy_rules": (
            "婚约、家族、地位、资源和名声会影响关系选择，不能只当背景。",
        ),
        "quest_rules": (
            "每章要推进一个情绪节点：靠近、误会、试探、吃醋、保护、摊牌或退让。",
        ),
        "faction_rules": (
            "家庭、宫廷、职场、闺蜜、情敌和利益方要对关系产生压力。",
        ),
        "panel_rules": (
            "情绪变化优先通过动作、停顿、细节和潜台词呈现，少用直白解释。",
        ),
        "chapter_formula": (
            "开场给情绪钩子，中段制造选择和误读，结尾留下关系问题或身份压力。",
        ),
        "forbidden_breaks": (
            "禁止无铺垫强行误会，禁止关系跳级，禁止角色为虐而虐或为甜而降智。",
        ),
    },
    quality_checks=("情绪递进", "关系拉扯", "误会合理", "潜台词", "外部阻碍"),
)
