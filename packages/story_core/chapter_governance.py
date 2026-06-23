from __future__ import annotations

from typing import Any

from packages.story_core.agent_base import compact_list, compact_text


def _as_list(value: Any, *, max_items: int = 8, item_chars: int = 120) -> list[str]:
    if not isinstance(value, list):
        return []
    return compact_list([str(item) for item in value if str(item).strip()], max_items=max_items, item_chars=item_chars)


def _protagonist_context(story: Any) -> dict[str, Any]:
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


def _event_plan(bundle: Any) -> dict[str, Any]:
    plan = getattr(bundle, "event_plan", None)
    return plan if isinstance(plan, dict) else {}


def _chapter_intent(chapter_number: int, bundle: Any) -> dict[str, Any]:
    event_plan = _event_plan(bundle)
    if chapter_number == 1:
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
            "交易行实际成交",
            "到账/手续费结算",
            "赵胖子正面登场",
            "公会正面追查",
            "论坛爆帖",
            "第一章禁止把低级材料写成扰乱市场",
        ]
        ending_change = "夜烬确认异常存在，并意识到千倍爆率能让自己在任务、装备或路线进度上领先一步。"
    else:
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

    return {
        "chapter_number": chapter_number,
        "goal": compact_text(
            str(event_plan.get("turn") or event_plan.get("next_focus") or getattr(bundle, "next_outline", "")),
            220,
        ),
        "must_include": must_include,
        "must_avoid": must_avoid,
        "ending_change": ending_change,
    }


def _runtime_context(story: Any, bundle: Any, chapter_number: int) -> dict[str, Any]:
    event_plan = _event_plan(bundle)
    latest = (getattr(story, "chapter_summaries", []) or [])[-1] if getattr(story, "chapter_summaries", []) else None
    return {
        "chapter_number": chapter_number,
        "protagonist": _protagonist_context(story),
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


def _rule_stack(chapter_number: int) -> dict[str, list[str]]:
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

    return {
        "hard_facts": hard_facts,
        "soft_guidance": [
            "句子按场面自然长短；人物对话要像正常说话，不能把理由压成几个词。少成语套话，少华丽辞藻。",
            "用动作、对话、界面、环境细节表现设定，不要停下来写说明书。",
            "NPC有服务边界和口吻，但不要全知。",
            "数值变化必须可追踪：等级、经验、货币、背包、装备、任务奖励前后一致。",
        ],
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
    "到账/手续费结算",
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

    if chapter_number == 1:
        missing = [ban for ban in FIRST_CHAPTER_REQUIRED_BANS if not any(ban in item for item in must_avoid)]
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
    governance = {
        "schema_version": "chapter-governance/v1",
        "chapter_intent": _chapter_intent(target_chapter, bundle),
        "runtime_context": _runtime_context(story, bundle, target_chapter),
        "rule_stack": _rule_stack(target_chapter),
    }
    governance["governance_review"] = review_chapter_governance(governance)
    return governance
