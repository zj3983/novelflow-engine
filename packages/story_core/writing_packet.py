from __future__ import annotations

from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.chapter_governance import build_chapter_governance, governance_quality_gate


def _as_list(value: Any, *, max_items: int = 8, item_chars: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    return compact_list([str(item) for item in value if str(item).strip()], max_items=max_items, item_chars=item_chars)


def _chapter_body_chars(body: str) -> int:
    return len("".join(str(body or "").split()))


def _extract_scene_cards(bundle: Any) -> list[dict[str, Any]]:
    cards = getattr(bundle, "scene_cards", None)
    if not isinstance(cards, list):
        return []
    result: list[dict[str, Any]] = []
    for index, raw in enumerate(cards, start=1):
        if not isinstance(raw, dict):
            continue
        result.append(
            {
                "index": index,
                "id": str(raw.get("template_id") or raw.get("scene_id") or f"scene-{index}"),
                "location": str(raw.get("location") or "当前场景"),
                "purpose": compact_text(str(raw.get("purpose") or "推进本章目标"), 120),
                "conflict": compact_text(str(raw.get("conflict") or "形成场景阻力"), 120),
                "must_show": _as_list(raw.get("must_show"), max_items=8, item_chars=80),
                "avoid": _as_list(raw.get("avoid") or raw.get("must_not_explain"), max_items=8, item_chars=80),
                "fact_locks": _as_list(raw.get("fact_locks"), max_items=8, item_chars=90),
            }
        )
    return result


def _default_first_chapter_scenes() -> list[dict[str, Any]]:
    return [
        {
            "index": 1,
            "id": "setup",
            "location": "现实出租屋",
            "purpose": "建立苏叶的现实压力、职业经验和进入游戏的理由。",
            "conflict": "房租与欠费逼近，但他不能靠情绪解决，只能寻找一条可验证的路径。",
            "must_show": ["催租/欠费", "旧头盔或登录入口", "前外包经济模型/风控测试经验", "克制、会算账的行为细节"],
            "avoid": ["百科式介绍游戏", "突然获得金手指", "提前写交易行成交或公会追查"],
            "fact_locks": ["现实姓名：苏叶", "游戏ID稍后创建为夜烬"],
        },
        {
            "index": 2,
            "id": "login",
            "location": "角色创建界面 / 灰烬村入口",
            "purpose": "完成登录、游戏ID、职业选择和简短角色面板。",
            "conflict": "元素法师学徒前期容错低，但成本低、适合长线计算。",
            "must_show": ["游戏ID：夜烬", "职业：元素法师学徒", "Lv.1", "经验0/100", "生命/法力/基础属性", "新手木杖/粗布衣"],
            "avoid": ["隐藏职业", "开局满级", "多NPC同时登场"],
            "fact_locks": ["现实段落叫苏叶，游戏内优先叫夜烬"],
        },
        {
            "index": 3,
            "id": "validation",
            "location": "灰烬村外灰鼠坡",
            "purpose": "通过一次低级战斗验证掉落异常，同时展示代价和克制。",
            "conflict": "夜烬必须确认异常是否真实，但不能表现得不像新手。",
            "must_show": ["灰鼠 Lv.1", "微光弹或基础法术", "法力消耗/受伤/走位", "首杀经验", "灰鼠毒腺/灰鼠皮掉落"],
            "avoid": ["把灰鼠写成狼", "全程法杖近战", "一次掉落引发全服市场风暴"],
            "fact_locks": ["怪物统一为灰鼠", "千倍爆率只做小额验证"],
        },
        {
            "index": 4,
            "id": "npc-landing",
            "location": "灰烬村药剂铺",
            "purpose": "用一个NPC服务点落地任务、补给和币制，让下一章目标清楚。",
            "conflict": "材料已经够交任务，但夜烬需要先确认价格、门槛和风险。",
            "must_show": ["药剂师洛婶", "毒腺单卖价", "清道夫委托", "补给价格", "1金币=100银币=10000铜币的轻量露出"],
            "avoid": ["实际寄售成交", "赵胖子正面登场", "公会锁定身份", "交易行精确百分比预测"],
            "fact_locks": ["单卖价和任务奖励要解释清楚，例如任务奖励含村务补贴", "金币只是大额单位，新手村主要用铜币"],
        },
    ]


def _event_plan_summary(bundle: Any) -> dict[str, Any]:
    plan = getattr(bundle, "event_plan", None)
    if not isinstance(plan, dict):
        return {}
    return {
        "chapter_title": plan.get("chapter_title") or getattr(bundle, "chapter_title", ""),
        "turn": compact_text(str(plan.get("turn") or ""), 180),
        "pivot": compact_text(str(plan.get("pivot") or ""), 180),
        "stakes": compact_text(str(plan.get("stakes") or ""), 180),
        "next_focus": compact_text(str(plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180),
        "ordered_actions": _as_list(plan.get("ordered_actions"), max_items=8, item_chars=100),
    }


def _latest_panel_locks(story: Any) -> dict[str, Any]:
    characters = getattr(story, "characters", []) or []
    protagonist = next(
        (
            character
            for character in characters
            if getattr(character, "role", "") in {"主角", "protagonist"} or getattr(character, "name", "") == "苏叶"
        ),
        characters[0] if characters else None,
    )
    if protagonist is None:
        return {}
    panel = getattr(protagonist, "game_panel", None)
    panel_data = panel.model_dump() if hasattr(panel, "model_dump") else {}
    return {
        "real_name": getattr(protagonist, "name", ""),
        "game_id": getattr(protagonist, "game_id", "") or panel_data.get("game_id", ""),
        "role": getattr(protagonist, "role", ""),
        "goals": _as_list(getattr(protagonist, "goals", []), max_items=6, item_chars=80),
        "location": compact_text(str(getattr(protagonist, "location", "")), 120),
        "game_panel": {key: value for key, value in panel_data.items() if value not in (None, "", [], {})},
    }


def build_codex_writing_packet(story: Any, bundle: Any | None = None, *, chapter_number: int | None = None) -> dict[str, Any]:
    """Build a compact handoff packet for Codex/manual prose drafting.

    The packet is intentionally not a prompt for a normal LLM. It is a contract:
    simulation and ledger facts stay structured, while the final prose can be
    written by Codex or a human without dragging rule text into the chapter.
    """

    target_chapter = int(chapter_number or getattr(bundle, "chapter_number", None) or (getattr(story, "current_chapter", 0) + 1))
    world_facts = _as_list(getattr(story, "world_facts", []), max_items=28, item_chars=140)
    author_constraints = _as_list(getattr(story, "author_constraints", []), max_items=18, item_chars=160)
    existing_body = getattr(bundle, "body", "") if bundle is not None else ""
    scene_cards = _extract_scene_cards(bundle) if bundle is not None else []
    if target_chapter == 1 and not scene_cards:
        scene_cards = _default_first_chapter_scenes()

    hard_locks = [
        "现实姓名：苏叶；游戏ID：夜烬；现实段落可称苏叶，游戏内行动优先称夜烬。",
        "夜烬职业路线固定为元素法师学徒/元素法师，战斗核心围绕法杖、基础法术、法力消耗和元素试炼门槛。",
        "灰烬村新手阶段主要用铜币；币制是 1金币=100银币=10000铜币，金币只作为大额单位轻量露出。",
        "低级材料不会一次扰乱市场；交易行、公会、商人只能看到价格波动、批次、时间戳等弱线索。",
    ]
    if target_chapter == 1:
        hard_locks.extend(
            [
                "第一章只聚焦：现实压力、登录建号、职业面板、首杀验证、一个NPC服务点和章末下一步。",
                "第一章禁止实际寄售成交、到账、手续费结算、赵胖子正面登场、公会正面追查和论坛爆帖。",
                "怪物统一为灰鼠，不要写成狼或其他怪。",
            ]
        )

    style_rules = [
        "短句为主，长短交错；少成语套话，少华丽辞藻。",
        "用动作、对话、界面、环境细节表现设定，不要停下来写说明书。",
        "人物说话要接地气，NPC有服务边界和口吻，但不要全知。",
        "数值必须可追踪：等级、经验、货币、背包、装备、任务奖励前后一致。",
        "奖励差异必须解释清楚：单卖材料价、任务打包价、声望或村务补贴不能混在一起。",
    ]
    governance = build_chapter_governance(story, bundle, chapter_number=target_chapter)
    governance_gate = governance_quality_gate(governance)

    return {
        "schema_version": "codex-writing-packet/v1",
        "chapter_number": target_chapter,
        "chapter_title": getattr(bundle, "chapter_title", "") if bundle is not None else "",
        "goal": "把结构化推演写成读者可读的网文正文，而不是继续堆规则。",
        "target_chars": {"min": 4200, "max": 5500},
        "story": {
            "story_id": getattr(story, "story_id", ""),
            "outline": compact_text(str(getattr(story, "outline", "")), 500),
            "genre": getattr(story, "genre", ""),
            "style": getattr(story, "style", ""),
            "current_chapter": getattr(story, "current_chapter", 0),
        },
        "protagonist": _latest_panel_locks(story),
        "governance": governance,
        "governance_gate": governance_gate,
        "event_plan": _event_plan_summary(bundle) if bundle is not None else {},
        "scene_cards": scene_cards,
        "hard_locks": compact_list(hard_locks, max_items=16, item_chars=160),
        "style_rules": style_rules,
        "author_constraints": author_constraints,
        "world_facts": world_facts,
        "continuity": {
            "previous_summary": compact_text(str(getattr(bundle, "chapter_summary", {}).get("summary", "")) if bundle is not None and isinstance(getattr(bundle, "chapter_summary", {}), dict) else "", 260),
            "existing_body_chars": _chapter_body_chars(existing_body),
        },
        "submission_contract": {
            "endpoint": "POST /projects/{project_id}/manual-draft",
            "required_fields": ["chapter_number", "body"],
            "after_submit": ["refresh metadata", "run local writing review", "update character panel", "persist replacement"],
        },
    }
