from __future__ import annotations

from packages.story_core.genre_types.base import GenrePlugin


XUANHUAN = GenrePlugin(
    plugin_id="xuanhuan",
    name="东方玄幻",
    keywords=("玄幻", "血脉", "体质", "武魂", "异火", "遗物", "古族"),
    core_promises=(
        "允许自创力量体系、异常物件、血脉、体质、武魂、异火和古老遗物。",
        "长期推动力来自力量成长、资源争夺、势力竞争和世界秘密。",
    ),
    ledger_fields=("特殊体质", "血脉", "异常物件", "力量位阶", "世界秘密"),
    rulebook={
        "progression_rules": (
            "自创力量必须先说明可见反馈、提升条件和使用代价。",
        ),
        "economy_rules": (),
        "quest_rules": (),
        "faction_rules": (
            "势力争夺围绕资源、遗物、血脉和地盘展开。",
        ),
        "panel_rules": (),
        "chapter_formula": (
            "每章至少推动力量、资源、关系或世界秘密中的一项。",
        ),
        "forbidden_breaks": (
            "本类型的终极目标由项目设定决定，不预设其他细分类型的修炼终点。",
        ),
    },
    quality_checks=("自创体系清楚", "异物反馈可见", "世界秘密递进"),
)
