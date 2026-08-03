from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping


OUTLINE_TEMPLATE_VERSION = "novel-outline-template/v1"

_OVERALL_FIELDS = [
    "core_selling_point",
    "protagonist_final_goal",
    "ending_state",
    "theme_statement",
    "main_conflict",
    "long_term_lines",
    "planned_arc_count",
    "planned_length",
    "expansion_route",
    "closing_route",
]
_ARC_FIELDS = [
    "arc_goal",
    "active_long_term_lines",
    "stage_antagonist",
    "core_loop",
    "escalations",
    "midpoint_turn",
    "climax",
    "payoff",
    "relationship_changes",
    "foreshadowing_in",
    "foreshadowing_out",
    "irreversible_change",
    "next_arc_entry",
]
_CHAPTER_FIELDS = [
    "goal",
    "obstacle",
    "protagonist_action",
    "opponent_response",
    "emotional_change",
    "gain_or_loss",
    "turn",
    "ending_hook",
]

_GENRE_CONTENT: dict[str, dict[str, list[str]]] = {
    "generic_webnovel": {
        "long_term_lines": ["主角成长线", "核心冲突线", "关系变化线", "世界秘密线"],
        "overall": ["先确定全书终点，再安排能够持续升级的阶段目标。"],
        "arc": ["每卷解决一个阶段问题，同时改变至少一条长期主线。"],
        "chapter": ["章节必须发生可见变化，不能只说明设定或重复上一章结论。"],
    },
    "game_webnovel": {
        "long_term_lines": ["游戏成长线", "现实处境线", "势力竞争线", "世界融合秘密线"],
        "overall": ["游戏线与现实线必须互相影响，成长成果要改变现实处境。"],
        "arc": ["每卷包含明确的等级区间、核心玩法、阶段对手和现实结果。"],
        "chapter": ["用行动呈现任务、战斗、交易与玩家关系，面板只报告必要变化。"],
    },
    "xuanhuan": {
        "long_term_lines": ["力量成长线", "家族宗门线", "宿敌冲突线", "世界本源线"],
        "overall": ["力量提升必须带来身份、关系或生存处境的变化。"],
        "arc": ["每卷更换舞台和主要矛盾，并揭开一层世界秘密。"],
        "chapter": ["机缘必须经过争夺或代价兑现，不能只靠旁白发放。"],
    },
    "xianxia": {
        "long_term_lines": ["修行求道线", "宗门因果线", "道侣故旧线", "天地劫数线"],
        "overall": ["境界推进、道心选择和因果代价共同推动全书。"],
        "arc": ["每卷完成一次修行阶段跨越，并留下新的因果。"],
        "chapter": ["修炼、斗法与人物选择都要产生具体后果。"],
    },
    "urban": {
        "long_term_lines": ["事业上升线", "利益对抗线", "家庭关系线", "身份秘密线"],
        "overall": ["主角每次获得资源，都要改变现实利益格局。"],
        "arc": ["每卷围绕一个现实目标和一组利益相关者展开。"],
        "chapter": ["冲突通过具体工作、金钱、人情和选择落地。"],
    },
    "romance": {
        "long_term_lines": ["亲密关系线", "个人成长线", "外部阻碍线", "秘密揭示线"],
        "overall": ["关系变化必须由共同经历和选择推动。"],
        "arc": ["每卷改变双方对彼此的判断，并提高关系代价。"],
        "chapter": ["对话、行动和误解都要符合当前关系距离。"],
    },
    "suspense": {
        "long_term_lines": ["核心谜案线", "调查成长线", "嫌疑关系线", "幕后动机线"],
        "overall": ["终局真相必须能由前文证据回溯验证。"],
        "arc": ["每卷解决一个子谜团，同时推翻一项重要判断。"],
        "chapter": ["每章新增、验证或推翻一条有效信息。"],
    },
    "rules_mystery": {
        "long_term_lines": ["规则验证线", "污染代价线", "幸存者关系线", "异常源头线"],
        "overall": ["规则必须可验证、有边界、有违反后的具体代价。"],
        "arc": ["每卷揭示一层规则机制，并迫使主角改变生存方法。"],
        "chapter": ["通过试错和后果揭示规则，不能集中讲解答案。"],
    },
}


def _template_for(type_id: str) -> dict[str, object]:
    content = _GENRE_CONTENT.get(type_id, _GENRE_CONTENT["generic_webnovel"])
    return {
        "schema_version": OUTLINE_TEMPLATE_VERSION,
        "overall": {
            "required_fields": list(_OVERALL_FIELDS),
            "long_term_lines": list(content["long_term_lines"]),
            "instructions": list(content["overall"]),
        },
        "arc": {
            "required_fields": list(_ARC_FIELDS),
            "minimum_arc_count": 3,
            "maximum_chapter_span": 60,
            "instructions": list(content["arc"]),
        },
        "chapter": {
            "required_fields": list(_CHAPTER_FIELDS),
            "opening_window_size": 10,
            "instructions": list(content["chapter"]),
        },
    }


OUTLINE_TEMPLATES = {type_id: _template_for(type_id) for type_id in _GENRE_CONTENT}


def normalize_outline_template(value: Any) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError("outline_template must be an object")
    template = deepcopy(dict(value))
    if template.get("schema_version") != OUTLINE_TEMPLATE_VERSION:
        raise ValueError(f"outline_template.schema_version must be {OUTLINE_TEMPLATE_VERSION}")
    for layer_name in ("overall", "arc", "chapter"):
        layer = template.get(layer_name)
        if not isinstance(layer, Mapping):
            raise ValueError(f"outline_template.{layer_name} must be an object")
        for list_name in ("required_fields", "instructions"):
            items = layer.get(list_name)
            if not isinstance(items, list) or not items or any(
                not isinstance(item, str) or not item.strip() for item in items
            ):
                raise ValueError(
                    f"outline_template.{layer_name}.{list_name} must contain non-blank strings"
                )
    overall = template["overall"]
    long_term_lines = overall.get("long_term_lines")
    if not isinstance(long_term_lines, list) or len(long_term_lines) < 2:
        raise ValueError("outline_template.overall.long_term_lines requires at least two lines")
    arc = template["arc"]
    if not isinstance(arc.get("minimum_arc_count"), int) or arc["minimum_arc_count"] < 3:
        raise ValueError("outline_template.arc.minimum_arc_count must be at least 3")
    if not isinstance(arc.get("maximum_chapter_span"), int) or arc["maximum_chapter_span"] < 10:
        raise ValueError("outline_template.arc.maximum_chapter_span must be at least 10")
    chapter = template["chapter"]
    if chapter.get("opening_window_size") != 10:
        raise ValueError("outline_template.chapter.opening_window_size must be 10")
    return template


def copy_outline_template(type_id: str) -> dict[str, object]:
    template = OUTLINE_TEMPLATES.get(str(type_id or "").strip())
    if template is None:
        template = OUTLINE_TEMPLATES["generic_webnovel"]
    return normalize_outline_template(template)
