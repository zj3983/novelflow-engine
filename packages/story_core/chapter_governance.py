from __future__ import annotations

from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.genre_plugins import is_game_genre
from packages.story_core.novel_type_catalog import normalize_novel_type_id
from packages.story_core.web_game_economy import (
    first_chapter_market_exchange_authorized,
    opening_market_exchange_flow_lines,
)


def _as_list(value: Any, *, max_items: int = 8, item_chars: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    return compact_list([str(item) for item in value if str(item).strip()], max_items=max_items, item_chars=item_chars)


def _protagonist_context(story: Any, *, include_game_panel: bool) -> dict[str, Any]:
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
    context = {
        "real_name": getattr(protagonist, "name", ""),
        "game_id": getattr(protagonist, "game_id", "") or panel_data.get("game_id", ""),
        "role": getattr(protagonist, "role", ""),
        "goals": _as_list(getattr(protagonist, "goals", []), max_items=6, item_chars=80),
        "location": compact_text(str(getattr(protagonist, "location", "")), 120),
    }
    if include_game_panel:
        context["game_panel"] = {
            key: value for key, value in panel_data.items() if value not in (None, "", [], {})
        }
    return context


def _event_plan(bundle: Any) -> dict[str, Any]:
    plan = getattr(bundle, "event_plan", None)
    return plan if isinstance(plan, dict) else {}


def _story_text(story: Any) -> str:
    return "\n".join(
        [
            str(getattr(story, "genre", "") or ""),
            str(getattr(story, "style", "") or ""),
            str(getattr(story, "outline", "") or ""),
            "\n".join(str(item) for item in (getattr(story, "world_facts", []) or [])[:40]),
            "\n".join(str(item) for item in (getattr(story, "author_constraints", []) or [])[:12]),
        ]
    )


def _is_game_context(story: Any) -> bool:
    explicit_type = _explicit_story_type(story)
    if explicit_type:
        return is_game_genre(explicit_type)
    return is_game_genre(_story_text(story))


def _explicit_story_type(story: Any) -> str:
    for genre_id in getattr(story, "genre_plugin_ids", []) or []:
        normalized = normalize_novel_type_id(genre_id)
        if normalized:
            return normalized
    genre_id = normalize_novel_type_id(getattr(story, "genre", ""))
    if genre_id:
        return genre_id
    for fact in (getattr(story, "world_facts", []) or [])[:40]:
        text = str(fact)
        if text.startswith(("小说类型：", "小说类型:")):
            return normalize_novel_type_id(text.split("：", 1)[-1].split(":", 1)[-1])
    return ""


def _is_xuanhuan_context(story: Any) -> bool:
    return _explicit_story_type(story) == "xuanhuan"


def _is_xianxia_context(story: Any) -> bool:
    return _explicit_story_type(story) == "xianxia"


def _chapter_intent(
    chapter_number: int,
    bundle: Any,
    *,
    game_context: bool,
    xuanhuan_context: bool,
    xianxia_context: bool,
    chapter_one_trade: bool,
) -> dict[str, Any]:
    event_plan = _event_plan(bundle)
    if game_context and chapter_number == 1:
        must_include = [
            "现实压力",
            "登录建号",
            "游戏ID、初始身份与武器选择",
            "角色面板",
            "首次灰狼验证",
            "千倍爆率带来的领先预期",
            "章末下一步目标",
        ]
        must_avoid = [
            "赵胖子正面登场",
            "公会正面追查",
            "论坛爆帖",
            "第一章禁止把低级材料写成扰乱市场",
        ]
        if chapter_one_trade:
            must_include.extend(
                [
                    "交易行游戏币成交 -> 官方兑换 -> 现实账户到账 -> 处理急账",
                    *opening_market_exchange_flow_lines(),
                ]
            )
            ending_change = "夜烬先在交易行获得游戏币，再通过官方兑换让现实账户到账并处理急账，确认千倍爆率能带来实际收益。"
        else:
            must_avoid[:0] = ["交易行实际成交", "官方兑换", "现实账户到账"]
            ending_change = "夜烬确认异常存在，并意识到千倍爆率能让自己在任务、装备或路线进度上领先一步。"
    elif xuanhuan_context and chapter_number == 1:
        must_include = [
            "主角当前的低位处境",
            "当章具体压力",
            "核心异物或自创力量线索",
            "资源限制或使用代价",
            "主角做出一个有代价的小选择",
            "只兑现一个小反馈",
            "章末下一步麻烦",
        ]
        must_avoid = [
            "无代价获得完整力量",
            "一章解开异物全部秘密",
            "路人全员嘲讽",
            "旧式逆袭口号",
            "大段讲力量等级表或世界历史",
            "擅自加入本书世界观之外的能力、资源或结算机制",
        ]
        ending_change = compact_text(str(event_plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180)
    elif xianxia_context and chapter_number == 1:
        must_include = [
            "外门处境或低位身份",
            "当章具体压力",
            "宗门差事的来处和没人愿接的原因",
            "题材核心物件或地点",
            "主角做出一个有代价的小选择",
            "只兑现一个小反馈",
            "章末下一步麻烦",
        ]
        must_avoid = [
            "废丹房捡漏",
            "一章顿悟大功法",
            "长老无理由送核心资源",
            "路人全员嘲讽",
            "旧式逆袭口号",
            "大段讲境界表、宗门史或功法说明",
            "擅自加入本书世界观之外的能力、资源或结算机制",
        ]
        ending_change = compact_text(str(event_plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180)
    elif chapter_number == 1:
        must_include = [
            "主角当前处境",
            "当章具体压力",
            "题材核心物件或地点",
            "主角做出一个有代价的小选择",
            "章末下一步目标",
        ]
        must_avoid = [
            "擅自加入本书设定之外的规则、资源或结算方式",
            "无铺垫直接变强",
            "旧式逆袭口号",
            "把后台规则写成正文说明",
        ]
        ending_change = compact_text(str(event_plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180)
    elif game_context:
        must_include = [
            "承接上一章状态",
            "明确本章目标",
            "展示世界对主角行动的反应",
            "更新面板/背包/任务或NPC关系",
            "留下下一章门槛",
        ]
        must_avoid = [
            "无铺垫跳过结算",
            "让角色知道不该知道的信息",
            "把审稿词或规则词写进正文",
        ]
        ending_change = compact_text(str(event_plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180)
    elif xuanhuan_context or xianxia_context:
        must_include = [
            "承接上一章状态",
            "明确本章目标",
            "展示世界对主角行动的反应",
            "更新境界、资源、伤势或人物关系",
            "留下下一章门槛",
        ]
        must_avoid = [
            "擅自加入本书设定之外的规则、资源或结算方式",
            "无铺垫跳过结算",
            "让角色知道不该知道的信息",
            "把审稿词或规则词写进正文",
        ]
        ending_change = compact_text(str(event_plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180)
    else:
        must_include = [
            "承接上一章状态",
            "明确本章目标",
            "展示世界对主角行动的反应",
            "更新资源、伤势、线索或人物关系",
            "留下下一章门槛",
        ]
        must_avoid = [
            "擅自加入本书设定之外的规则、资源或结算方式",
            "无铺垫跳过结算",
            "让角色知道不该知道的信息",
            "把审稿词或规则词写进正文",
        ]
        ending_change = compact_text(str(event_plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180)

    return {
        "chapter_number": chapter_number,
        "goal": compact_text(
            str(event_plan.get("turn") or event_plan.get("next_focus") or getattr(bundle, "next_outline", "")),
            220,
        ),
        "must_include": must_include,
        "must_avoid": must_avoid,
        "ending_change": ending_change,
        "first_chapter_trade_authorized": chapter_one_trade,
    }


def _runtime_context(
    story: Any,
    bundle: Any,
    chapter_number: int,
    *,
    game_context: bool,
) -> dict[str, Any]:
    event_plan = _event_plan(bundle)
    previous = [
        summary
        for summary in (getattr(story, "chapter_summaries", []) or [])
        if int(getattr(summary, "chapter_number", 0) or 0) < chapter_number
    ]
    latest = max(previous, key=lambda summary: int(getattr(summary, "chapter_number", 0) or 0), default=None)
    return {
        "chapter_number": chapter_number,
        "protagonist": _protagonist_context(story, include_game_panel=game_context),
        "world_facts": _as_list(getattr(story, "world_facts", []), max_items=24, item_chars=130),
        "author_constraints": _as_list(getattr(story, "author_constraints", []), max_items=12, item_chars=150),
        "previous_summary": compact_text(str(getattr(latest, "summary", "")), 220) if latest else "",
        "next_focus": compact_text(str(event_plan.get("next_focus") or getattr(bundle, "next_outline", "")), 180),
        "event_plan": {
            "chapter_title": event_plan.get("chapter_title") or getattr(bundle, "chapter_title", ""),
            "turn": compact_text(str(event_plan.get("turn") or ""), 180),
            "stakes": compact_text(str(event_plan.get("stakes") or ""), 180),
        },
    }


def _rule_stack(
    chapter_number: int,
    *,
    game_context: bool,
    xuanhuan_context: bool,
    xianxia_context: bool,
) -> dict[str, list[str]]:
    if game_context:
        hard_facts = [
            "现实姓名：苏叶；游戏ID：夜烬；现实段落可称苏叶，游戏内行动优先称夜烬。",
            "开局玩家初始身份统一为见习冒险者（未转职）；夜烬只是选择法杖和基础火球术倾向，不是隐藏职业或特殊职业。",
            "背包按同类道具堆叠计算格子：灰狼毒腺×8和粗糙狼皮×7只占两个材料格，章末背包应写2/20或占用两个材料格。",
            "灰烬村新手阶段主要用铜币；币制是 1金币=100银币=10000铜币，金币只作为大额单位轻量露出。",
            "低级材料不会一次扰乱市场；交易行、公会、商人只能看到价格波动、批次、时间戳等弱线索。",
        ]
        if chapter_number == 1:
            hard_facts.extend(
                [
                    "怪物统一为灰狼，不要写成灰鼠或其他怪。",
                    "第一章只做首次验证，重点是看出千倍爆率会让夜烬比普通玩家更快完成任务/装备门槛，不写市场风暴。",
                ]
            )
    elif xuanhuan_context:
        hard_facts = [
            "东方玄幻规则只取本项目世界观、作者约束和当章计划，未写明的机制不要自行补充。",
            "自创力量和异常物件必须有可见反馈、成长条件和使用代价，不能直接解决所有问题。",
            "资源成长、势力反应和世界秘密要随主角行动逐步推进，不一次讲完力量体系。",
            "章末钩子必须来自当章具体矛盾，不套旧式逆袭口号。",
        ]
    elif xianxia_context:
        hard_facts = [
            "修仙题材规则只取本项目世界观、作者约束和当章计划，未写明的机制不要自行补充。",
            "主角的身份、境界、资源、差事和机缘必须沿用本书设定，不能擅自改换身份或修行路径。",
            "残缺机缘只能逐步反馈：先给异常、线索、小物件或一息变化，不直接送完整传承或大境界突破。",
            "宗门差事必须有具体利益关系：谁安排、谁不愿接、为什么没油水或有忌讳，都要落到场面里。",
            "章末钩子必须来自当章具体矛盾，不套旧式逆袭口号。",
        ]
    else:
        hard_facts = [
            "题材规则只取本项目世界观、作者约束和当章计划，未写明的机制不要自行补充。",
            "主角的能力、身份、资源和处境必须沿用本书设定，不能擅自改换身份或行动逻辑。",
            "章末钩子必须来自当章具体矛盾，不套旧式口号。",
        ]

    if game_context:
        soft_guidance = [
            "人物只能依据自己已经看到、听到、问到或试出的信息行动。",
            "等级、经验、货币、背包、装备、任务和关系变化必须与本章前后的账本一致。",
        ]
    elif xuanhuan_context or xianxia_context:
        soft_guidance = [
            "人物只能依据自己已经看到、听到、问到或试出的信息行动。",
            "术法、法宝、境界、伤势、资源和因果变化必须与本章前后的账本一致。",
        ]
    else:
        soft_guidance = [
            "人物只能依据自己已经看到、听到、问到或试出的信息行动。",
            "资源、伤势、线索和人物关系变化必须与本章前后的账本一致。",
        ]

    return {
        "hard_facts": hard_facts,
        "soft_guidance": soft_guidance,
        "diagnostic_only": [
            "爽点、节奏、读者期待、AI味、审稿、生成、规则要求都只用于诊断，禁止进入正文。",
            "规则未明、信息边界、NPC门槛、材料暂不外露属于后台标签，必须翻译成动作/对话/界面反馈。",
        ],
    }


DIAGNOSTIC_TERMS = (
    "爽点",
    "节奏",
    "读者期待",
    "AI味",
    "审稿",
    "生成",
    "规则要求",
    "信息边界",
    "NPC门槛",
)

FIRST_CHAPTER_REQUIRED_BANS = (
    "交易行实际成交",
    "官方兑换",
    "现实账户到账",
    "赵胖子正面登场",
    "公会正面追查",
)


def review_chapter_governance(governance: dict[str, Any]) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    if not isinstance(governance, dict):
        return {
            "reviewer": "chapter_governance/v1",
            "pass": False,
            "issues": [
                {
                    "type": "invalid_governance",
                    "reason": "governance 不是对象。",
                    "suggestion": "重新编译 chapter_governance。",
                }
            ],
        }

    intent = governance.get("chapter_intent", {}) if isinstance(governance.get("chapter_intent"), dict) else {}
    rules = governance.get("rule_stack", {}) if isinstance(governance.get("rule_stack"), dict) else {}
    hard_facts = _as_list(rules.get("hard_facts"), max_items=50, item_chars=300)
    diagnostic_only = _as_list(rules.get("diagnostic_only"), max_items=20, item_chars=300)
    must_avoid = _as_list(intent.get("must_avoid"), max_items=30, item_chars=160)
    chapter_number = int(intent.get("chapter_number") or 0)

    for fact in hard_facts:
        leaked = [term for term in DIAGNOSTIC_TERMS if term in fact]
        if leaked:
            issues.append(
                {
                    "type": "diagnostic_term_in_hard_facts",
                    "reason": f"硬事实中混入诊断词：{'、'.join(leaked)}。",
                    "suggestion": "把爽点、节奏、读者期待、审稿等词移入 diagnostic_only，不要作为世界事实。",
                }
            )

    if not hard_facts:
        issues.append(
            {
                "type": "missing_hard_facts",
                "reason": "治理层缺少 hard_facts。",
                "suggestion": "至少提供主角身份、职业路线、币制/数值和本章关键事实锁。",
            }
        )
    if not diagnostic_only:
        issues.append(
            {
                "type": "missing_diagnostic_only",
                "reason": "治理层缺少 diagnostic_only。",
                "suggestion": "声明爽点、节奏、读者期待、AI味、审稿等只用于诊断，禁止进入正文。",
            }
        )

    hard_text = "、".join(hard_facts)
    game_first_chapter = chapter_number == 1 and (
        "见习冒险者" in hard_text
        or "灰烬村" in hard_text
        or "千倍爆率" in hard_text
        or "怪物统一" in hard_text
    )
    if game_first_chapter:
        required_bans = FIRST_CHAPTER_REQUIRED_BANS
        if bool(intent.get("first_chapter_trade_authorized")):
            required_bans = tuple(
                ban for ban in required_bans if ban not in {"交易行实际成交", "官方兑换", "现实账户到账"}
            )
        missing = [ban for ban in required_bans if not any(ban in item for item in must_avoid)]
        if missing:
            issues.append(
                {
                    "type": "missing_first_chapter_ban",
                    "reason": f"第一章禁写项不完整：缺少 {'、'.join(missing)}。",
                    "suggestion": f"补入第一章 must_avoid：{'、'.join(missing)}。",
                }
            )

    return {
        "reviewer": "chapter_governance/v1",
        "pass": not issues,
        "issues": issues,
    }


def governance_quality_gate(governance: dict[str, Any]) -> dict[str, Any]:
    review = review_chapter_governance(governance)
    issues = review.get("issues", []) if isinstance(review.get("issues"), list) else []
    issue_types = [str(issue.get("type", "unknown")) for issue in issues if isinstance(issue, dict)]
    passed = bool(review.get("pass"))
    return {
        "reviewer": "chapter_governance_gate/v1",
        "pass": passed,
        "blocking": not passed,
        "next_action": "write_or_revise_chapter" if passed else "fix_governance_before_writing",
        "issue_types": issue_types,
        "issues": issues,
    }


def build_chapter_governance(story: Any, bundle: Any | None = None, *, chapter_number: int | None = None) -> dict[str, Any]:
    target_chapter = int(chapter_number or getattr(bundle, "chapter_number", None) or (getattr(story, "current_chapter", 0) + 1))
    game_context = _is_game_context(story)
    xuanhuan_context = (not game_context) and _is_xuanhuan_context(story)
    xianxia_context = (not game_context) and _is_xianxia_context(story)
    chapter_one_trade = target_chapter == 1 and first_chapter_market_exchange_authorized(
        _event_plan(bundle),
        list(getattr(story, "world_facts", []) or []),
    )
    governance = {
        "schema_version": "chapter-governance/v1",
        "chapter_intent": _chapter_intent(
            target_chapter,
            bundle,
            game_context=game_context,
            xuanhuan_context=xuanhuan_context,
            xianxia_context=xianxia_context,
            chapter_one_trade=chapter_one_trade,
        ),
        "runtime_context": _runtime_context(
            story,
            bundle,
            target_chapter,
            game_context=game_context,
        ),
        "rule_stack": _rule_stack(
            target_chapter,
            game_context=game_context,
            xuanhuan_context=xuanhuan_context,
            xianxia_context=xianxia_context,
        ),
    }
    governance["governance_review"] = review_chapter_governance(governance)
    return governance
