from __future__ import annotations

from copy import deepcopy
from typing import Any


_OPENING_CORE_REFERENCES: dict[str, dict[str, Any]] = {
    "game_webnovel": {
        "core_advantage": {
            "purpose": "确定主角持续领先的方式、成长规则和能力边界。",
            "instructions": "可以组合或创新，但必须说明限制、成长方式和前期首次兑现。",
            "examples": [
                "唯一隐藏职业或可成长天赋",
                "高倍爆率、合成或资源获取优势",
                "无冷却、真实伤害或范围增幅等机制突破",
            ],
        },
        "central_mystery": {
            "purpose": "确定游戏影响现实的长期答案和分阶段揭露路径。",
            "instructions": "完整答案只供开书与大纲使用，正文只能读取当前已经公开的线索。",
            "examples": [
                "高维文明把游戏当作练兵场或筛选器",
                "真实异世界与现实逐步融合，游戏影响现实",
                "主脑 AI 推动现实数据化或数据现实化",
            ],
        },
        "initial_drive": {
            "purpose": "确定主角为什么现在进入游戏，以及何时转向长期目标。",
            "instructions": "根据人物背景生成，不默认套用重病亲属、巨债或重生。",
            "examples": [
                "现实经济压力促使主角通过游戏获得第一笔稳定收入",
                "重生或背叛经历促使主角抢占关键先机",
                "游戏天赋和职业追求促使主角证明自己的能力",
            ],
        },
    }
}


def opening_core_reference(novel_type_id: str) -> dict[str, Any]:
    return deepcopy(_OPENING_CORE_REFERENCES.get(str(novel_type_id or "").strip(), {}))
