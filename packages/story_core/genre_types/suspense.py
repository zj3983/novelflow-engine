from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin


SUSPENSE = GenrePlugin(
    plugin_id="suspense",
    name="悬疑推理",
    keywords=("悬疑", "推理", "案件", "侦探", "凶手", "线索", "诡计", "调查", "谜团"),
    core_promises=(
        "读者期待公平线索、持续反转、调查推进和真相逼近，不能靠临时乱编解谜。",
    ),
    ledger_fields=("案件时间线", "线索", "嫌疑人", "证据", "误导", "真相碎片"),
    rulebook={
        "progression_rules": (
            "每章必须推进调查、排除嫌疑、揭示新线索或改变读者判断。",
        ),
        "economy_rules": (
            "信息就是资源，关键线索的获得需要行动成本和风险。",
        ),
        "quest_rules": (
            "调查目标要具体，询问、取证、追踪、复盘都要留下可验证结果。",
        ),
        "faction_rules": (
            "嫌疑人、警方、受害者关系网和幕后势力都要有自保或误导动机。",
        ),
        "panel_rules": (
            "推理过程要展示证据链，不要用作者旁白直接宣布真相。",
        ),
        "chapter_formula": (
            "开场抛异常，中段追线索并反转判断，结尾给更危险或更矛盾的新证据。",
        ),
        "forbidden_breaks": (
            "禁止关键证据凭空出现，禁止凶手临时更换，禁止用巧合解决核心谜题。",
        ),
    },
    quality_checks=("公平线索", "时间线一致", "嫌疑动机", "反转可信", "钩子强度"),
)
