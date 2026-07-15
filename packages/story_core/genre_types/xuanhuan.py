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
    trope_templates=(
        {
            "id": "bloodline_or_body_awaken",
            "name": "血脉/体质觉醒",
            "trigger": "主角接触压力、遗物、药材、战斗或旧地后，特殊体质首次出现反馈。",
            "beats": ["身体异常", "外界误判", "力量小幅显现", "代价或副作用", "留下血脉/体质来源疑问"],
            "payoff": "自创力量体系有第一处可见证据，并牵出世界秘密。",
            "avoid": ["不要觉醒即无敌", "不要混用修仙渡劫终点", "不要把反馈写成纯旁白"],
        },
        {
            "id": "ancient_object_secret",
            "name": "古老遗物揭密",
            "trigger": "主角获得来历不明的器物、残片、骨纹、异火或旧族信物。",
            "beats": ["低价/低位获得", "别人识别失败", "主角触发小反应", "需要资源继续解锁", "被相关势力或旧敌注意"],
            "payoff": "遗物既是爽点也是长期谜团入口。",
            "avoid": ["不要一次解锁完整世界观", "不要让所有旁人都愚蠢", "不要没有使用限制"],
        },
        {
            "id": "power_rank_challenge",
            "name": "力量位阶挑战",
            "trigger": "主角需要证明新力量、争夺资源或进入更高层圈子。",
            "beats": ["明确位阶差", "找到克制/代价", "公开交锋", "险胜或局部胜利", "引出更高层关注"],
            "payoff": "越级感建立在规则、克制和代价上。",
            "avoid": ["不要无凭依越阶碾压", "不要只靠怒吼突破", "不要战后没人反馈"],
        },
    ),
)
