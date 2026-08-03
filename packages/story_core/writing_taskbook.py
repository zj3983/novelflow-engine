from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from packages.story_core.attribute_allocation import parse_level, planned_level_target
from packages.story_core.book_style import book_style_prompt
from packages.story_core.web_game_economy import opening_market_exchange_flow_lines


FIRST_CHAPTER_NOISE_BANS = (
    "材料公开处理成大钱",
    "交易行寄售已经完成",
    "公开扣费或大额收款反馈",
    "一次性交空全部材料",
    "完整NPC服务戏",
    "商人盯盘",
    "玩家势力追过来",
    "论坛或公共频道扩散",
    "公共频道追过来",
    "市场玩家盯上主角",
)

WRITER_TERM_REPLACEMENTS = (
    ("让世界根据主角行动给出可见反应", "主角动手以后，马上出现一个具体结果或麻烦"),
    ("收益和代价落到账本或关系里", "让收获和代价都能看见，并改变下一步或人物关系"),
    ("NPC/环境/任务/对手反应", "现场人物、环境或对手的反应"),
    ("关键账本或状态", "眼前最要紧的东西或处境"),
    ("确认边界", "试清楚能不能走"),
    ("验边界", "试清楚"),
    ("边界", "规矩"),
    ("底层逻辑", "规矩"),
    ("推演", "计划"),
    ("审稿", "检查"),
    ("场景卡", "场面材料"),
    ("结算链", "账"),
    ("基准", "底线"),
    ("诊断", "检查"),
)


GENERIC_CRAFT_TEMPLATES = (
    "选择场面：先写角色看见一个具体东西（信、门、价牌、队伍、伤口、物件），再写这个东西带来的麻烦，最后让角色做一个小决定；不要直接写“他权衡利弊”。",
    "对话场面：人物先听懂上一句再作答；只有关系和情境允许时，才使用玩笑、调侃或省略说法。",
    "现代中文对话：台词说人物当场知道、在意和愿意说出口的事，不替作者解释设定或流程。",
    "章末压句：如果本章有误判、羞辱、卡任务或资源压力，结尾允许一句白话反打承诺；必须来自当章具体矛盾，不套成语、不喊口号。",
    "情绪场面：不要写抽象感慨，写手指停住、视线移开、话说到一半、笑意收住、把东西重新放回去这类能看见的动作。",
)

GAME_CRAFT_TEMPLATES = (
    "选择场面：先写主角看见一个具体东西，例如价牌、角色面板、任务提示、队伍或敌人位置，再写眼前麻烦，最后让主角做一个会影响后续的小决定。",
    "对话场面：玩家和NPC先回应眼前发生的事，再按关系、身份和各自利益继续谈，不说应当隐藏的机制。",
    "现代中文对话：不要把后台事实直译成台词。玩家会说自己看见了什么、缺什么、准备怎么做，不会替系统解释整套流程。",
    "章末压句：如果本章有误判、卡任务或资源压力，结尾允许一句白话反打承诺；必须来自当章具体矛盾，不套成语、不喊口号。",
    "战斗场面：敌人怎么逼近，主角如何应对，技能、生命或装备产生什么消耗，战斗结果怎样改变下一步；不要只写命中、倒地和掉落。",
    "怪物面板：同类普通怪第一次正式交战前显示一次名称、等级、生命和攻击方式，后面不重复刷；精英怪和首领首次出现时再加技能和特性，掉落必须等击杀后结算。",
    "爽点场面：先写其他玩家面对的正常困难，再写主角凭本书已有优势取得什么具体领先；优势是否隐藏、怎样使用以及下一步目标都服从本章计划。",
)


def first_chapter_whole_body_contract(*, game_genre: bool, trade_authorized: bool = False) -> dict[str, Any]:
    if not game_genre:
        return {}
    beat_map = (
        "现实压力 -> 登录建号 -> 低级验证 -> 交易行游戏币成交 -> 官方兑换 -> 现实账户到账 -> 处理急账 -> 下一步"
        if trade_authorized
        else "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子"
    )
    return {
        "mode": "whole_body_only",
        "beat_map": beat_map,
        "beats": [
            "开篇处境：用本书章纲要求的现实处境或游戏入口说明主角为什么现在开始行动。",
            "进入游戏：按本书设定写清游戏ID、初始身份、当前状态和第一项可执行目标，不擅自指定职业、武器或技能。",
            "首次行动：用小规模任务、探索或战斗让主角亲眼看见游戏规则和本书核心优势，并写清实际消耗与结果。",
            "下一步钩子：把本章结果落到任务、装备、技能、关系或地图进度上，留下下一章可以立即执行的目标。",
        ],
        "style": [
            "句子要完整，动作、原因和结果要接得上。",
            "读者要看得出角色在做什么、怕什么、想试什么、下一步去哪里。",
            "少写验证、逻辑、收益、路线这种判断词，改成试一把、看一眼、包快满、前置任务还没做完。",
        ],
        "dialogue": [
            "自然对话：人物先回应对方刚说的内容，再谈自己关心的事；允许解释、犹豫、回避和自然接话。",
            "台词不能替作者讲规则、讲设定或讲审稿结论。",
            "整场谈话结束后，信息、态度、关系或下一步行动有所变化即可，不要求每句话都承担剧情任务。",
        ],
        "avoid": [
            "按整章连续正文自然写出四拍。",
            "变现、成交、到账和手续费扣款必须服从本章计划；公共频道扩散、论坛爆帖、公会追查或市场玩家盯盘不得擅自提前。",
            "NPC只能处理本书设定中属于其岗位和权限的事务，不能为了讲设定突然全知全能。",
            "提交任务、交易、修理、购买或转职必须跟随项目账本和章节计划，未安排的流程不要擅自提前完成。",
            "开局身份、职业、技能、装备和背包规则必须来自本书设定；同类物品是否堆叠也以项目规则为准。",
            "不要写边界、推演、审稿、场景卡、模型、算法、变量、规则被撬开、这意味着、这说明。",
            "不要写施法前摇、验证路线、验证逻辑、收益路径或抽象收益词。",
            "不要写谜语式省略回答或故意绕弯的悬疑腔。",
        ],
    }


@dataclass(frozen=True)
class WritingTaskScene:
    key: str
    title: str
    goal: str
    required_surface: str
    forbidden_surface: str = ""
    entry_state: str = ""
    exit_state: str = ""
    handoff: str = ""
    target_chars: int = 1000
    source_ids: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class WritingTaskBook:
    chapter_number: int
    genre_mode: str = "general"
    chapter_title: str = ""
    chapter_goal: str = ""
    target_chars: str = ""
    style_contract: list[str] = field(default_factory=list)
    craft_templates: list[str] = field(default_factory=list)
    global_required: list[str] = field(default_factory=list)
    global_forbidden: list[str] = field(default_factory=list)
    scenes: list[WritingTaskScene] = field(default_factory=list)
    source: str = "compiled_from_plan"


def writer_facing_text(value: Any) -> str:
    """Translate planning language before it reaches an author or model."""

    raw = str(value or "").strip()
    for old, new in WRITER_TERM_REPLACEMENTS:
        raw = raw.replace(old, new)
    return re.sub(r"\s+", " ", raw)


def _text(value: Any, limit: int = 160) -> str:
    raw = writer_facing_text(value)
    if len(raw) <= limit:
        return raw
    return raw[: max(0, limit - 1)].rstrip() + "…"


def _as_list(value: Any, *, max_items: int = 8, item_chars: int = 60) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]
    result: list[str] = []
    for item in items:
        if isinstance(item, dict):
            item = item.get("action") or item.get("goal") or item.get("content") or item.get("summary") or item
        text = _text(item, item_chars)
        if text and text not in result:
            result.append(text)
        if len(result) >= max_items:
            break
    return result


def _join(items: list[str], fallback: str = "按本章推演自然表面化") -> str:
    clean = [item for item in items if item]
    return "、".join(clean) if clean else fallback


def _target_chars_text(plan: dict[str, Any]) -> str:
    target = plan.get("target_chars")
    if isinstance(target, dict):
        minimum = target.get("min")
        maximum = target.get("max")
        if minimum and maximum:
            return f"{minimum}到{maximum}字"
        if minimum:
            return f"不少于{minimum}字"
        if maximum:
            return f"不超过{maximum}字"
    if isinstance(target, int) and target > 0:
        return f"约{target}字"
    return "按章节目标字数，正文要完整，不写摘要"


def _target_chars_int(plan: dict[str, Any], fallback: int = 4200) -> int:
    target = plan.get("target_chars")
    if isinstance(target, dict):
        minimum = target.get("min")
        maximum = target.get("max")
        if isinstance(minimum, int) and isinstance(maximum, int):
            return max(900, (minimum + maximum) // 2)
        if isinstance(minimum, int):
            return max(900, minimum)
    if isinstance(target, int):
        return max(900, target)
    return fallback


def _event_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return plan.get("event_plan") if isinstance(plan.get("event_plan"), dict) else {}


def _simulation_plan(plan: dict[str, Any]) -> dict[str, Any]:
    return plan.get("simulation_plan") if isinstance(plan.get("simulation_plan"), dict) else {}


def _plot_simulation(simulation_plan: dict[str, Any]) -> dict[str, Any]:
    plot = simulation_plan.get("plot_simulation") if isinstance(simulation_plan.get("plot_simulation"), dict) else {}
    return plot


def _plot_required_lines(plot: dict[str, Any]) -> list[str]:
    if not plot:
        return []
    lines: list[str] = []
    for key, label in (
        ("reader_hook", "剧情主线"),
        ("chapter_desire", "主角目标"),
        ("choice_point", "选择点"),
        ("payoff", "爽点兑现"),
        ("cost", "代价"),
        ("emotional_turn", "情绪转折"),
        ("outsider_misread", "外人误判"),
        ("ending_hook", "章末钩子"),
    ):
        text = _text(plot.get(key), 90)
        if text:
            lines.append(f"{label}：{text}")
    obstacles = _as_list(plot.get("obstacle_chain"), max_items=5, item_chars=38)
    if obstacles:
        lines.append(f"阻碍：{'；'.join(obstacles)}")
    arc = plot.get("longform_position") if isinstance(plot.get("longform_position"), dict) else {}
    arc_name = _text(arc.get("name"), 40)
    arc_purpose = _text(arc.get("purpose"), 90)
    arc_bound = _text(arc.get("upper_bound"), 100)
    if arc_name or arc_purpose:
        lines.append(f"长篇位置：{arc_name}；{arc_purpose}".strip("；"))
    if arc_bound:
        lines.append(f"阶段上限：{arc_bound}")
    for key, label in (
        ("payoff_requirement", "本章必须兑现"),
        ("anti_drag_rule", "防拖沓"),
        ("future_use_rule", "后续用途"),
        ("reader_reason_to_continue", "追读理由"),
    ):
        text = _text(plot.get(key), 110)
        if text:
            lines.append(f"{label}：{text}")
    return lines


def _longform_contract_required_lines(contract: dict[str, Any]) -> list[str]:
    if not contract:
        return []
    lines: list[str] = []
    arc = contract.get("arc_window") if isinstance(contract.get("arc_window"), dict) else {}
    arc_name = _text(arc.get("name"), 40)
    arc_purpose = _text(arc.get("purpose"), 90)
    arc_bound = _text(arc.get("upper_bound"), 100)
    if arc_name or arc_purpose:
        lines.append(f"长篇阶段：{arc_name}；{arc_purpose}".strip("；"))
    if arc_bound:
        lines.append(f"本阶段不能越界：{arc_bound}")
    for key, label in (
        ("payoff_requirement", "本章兑现"),
        ("anti_drag_rule", "不能拖"),
        ("future_use_rule", "新增内容要有后续用途"),
        ("reader_reason_to_continue", "章末追读"),
    ):
        text = _text(contract.get(key), 120)
        if text:
            lines.append(f"{label}：{text}")
    lines.extend(f"滚雪球：{item}" for item in _as_list(contract.get("snowball_logic"), max_items=4, item_chars=90))
    lines.extend(f"网游爽感：{item}" for item in _as_list(contract.get("webgame_satisfaction"), max_items=3, item_chars=90))
    return lines


def _plot_text(plot: dict[str, Any], key: str, limit: int = 100) -> str:
    return _text(plot.get(key), limit) if plot else ""


def _scene_cards(plan: dict[str, Any]) -> list[dict[str, Any]]:
    cards = plan.get("scene_cards")
    return [card for card in cards if isinstance(card, dict)] if isinstance(cards, list) else []


def _chapter_goal(plan: dict[str, Any]) -> str:
    event_plan = _event_plan(plan)
    simulation_plan = _simulation_plan(plan)
    plot = _plot_simulation(simulation_plan)
    return _text(
        plot.get("chapter_desire")
        or simulation_plan.get("chapter_goal")
        or event_plan.get("next_focus")
        or event_plan.get("stakes")
        or event_plan.get("chapter_title")
        or "完成本章推进",
        140,
    )


def _world_context_requirements(simulation_plan: dict[str, Any]) -> tuple[list[str], list[str]]:
    context = simulation_plan.get("world_context") if isinstance(simulation_plan.get("world_context"), dict) else {}
    if not context:
        return [], []
    visible_items = context.get("visible_inbox") if isinstance(context.get("visible_inbox"), list) else []
    channels: list[str] = []
    for item in visible_items:
        if not isinstance(item, dict):
            continue
        channel = _text(item.get("channel"), 40)
        if channel and channel not in channels:
            channels.append(channel)
    required = [
        "Use world pulse as long-running background state first, then write only this chapter's visible slice.",
    ]
    if channels:
        required.append(f"Visible world pulse channels for this chapter: {', '.join(channels)}.")
    forbidden = [
        "Do not write hidden_state, persistent_world internals, guild_intel internals, or background-only world pulse logic into prose.",
    ]
    rule = _text(context.get("visibility_rule"), 160)
    if rule:
        forbidden.append(rule)
    return required, forbidden


def _chapter_title(plan: dict[str, Any]) -> str:
    event_plan = _event_plan(plan)
    return _text(event_plan.get("chapter_title") or plan.get("chapter_title") or "", 60)


def _looks_like_game_context(plan: dict[str, Any], genre: str) -> bool:
    if not genre:
        return True
    haystack = " ".join(
        [
            genre,
            str(plan.get("genre") or ""),
            str(_event_plan(plan).get("chapter_title") or ""),
            str(_chapter_goal(plan)),
        ]
    )
    strong_tokens = ("网游", "游戏", "VRMMO", "系统流", "铜币", "交易行", "背包", "NPC", "职业", "任务")
    return any(token in haystack for token in strong_tokens)


def _slug(value: Any, fallback: str) -> str:
    raw = str(value or "").strip().lower()
    raw = re.sub(r"[^a-z0-9_\-\u4e00-\u9fff]+", "_", raw).strip("_")
    return raw[:40] or fallback


def _scene_source_id(card: dict[str, Any], index: int) -> str:
    return str(card.get("template_id") or card.get("scene_id") or card.get("id") or f"scene_{index}")


def _apply_plot_to_scenes(
    scenes: list[WritingTaskScene],
    plot: dict[str, Any],
    *,
    game_context: bool,
) -> list[WritingTaskScene]:
    if not plot:
        return scenes

    reader_hook = _plot_text(plot, "reader_hook", 100)
    desire = _plot_text(plot, "chapter_desire", 100)
    obstacles = _as_list(plot.get("obstacle_chain"), max_items=5, item_chars=34)
    obstacle_text = "；".join(obstacles)
    choice = _plot_text(plot, "choice_point", 100)
    payoff = _plot_text(plot, "payoff", 90)
    cost = _plot_text(plot, "cost", 90)
    emotional_turn = _plot_text(plot, "emotional_turn", 90)
    outsider_misread = _plot_text(plot, "outsider_misread", 90)
    ending_hook = _plot_text(plot, "ending_hook", 100)

    result: list[WritingTaskScene] = []
    for scene in scenes:
        updates: dict[str, Any] = {}
        if scene.key == "opening" and (desire or reader_hook):
            updates["goal"] = " ".join(item for item in (desire, reader_hook) if item)
            updates["required_surface"] = _join(
                [scene.required_surface, f"主角目标必须落地：{desire}" if desire else ""],
                scene.required_surface,
            )
        elif scene.key == "pressure" and obstacle_text:
            updates["goal"] = f"让阻碍具体出现：{obstacle_text}。"
            surface_channels = (
                "用NPC回答、界面、背包、路况、价格、生命法力或装备状态承载"
                if game_context
                else "用人物反应、现场物件、身体状态、环境变化或关系后果承载"
            )
            updates["required_surface"] = f"阻碍必须可见：{obstacle_text}。{surface_channels}，不写后台解释。"
        elif scene.key == "choice" and (choice or payoff or cost):
            updates["goal"] = choice or scene.goal
            updates["required_surface"] = _join(
                [
                    scene.required_surface,
                    payoff and f"爽点兑现：{payoff}",
                    cost and f"代价：{cost}",
                ],
                scene.required_surface,
            )
            if payoff or cost:
                updates["exit_state"] = f"选择完成，{payoff or '收益'}和{cost or '代价'}落到账本、关系或路线里。"
        elif scene.key == "hook" and (ending_hook or emotional_turn or outsider_misread):
            updates["goal"] = f"收住本章事件，更新状态，并把章末落到：{ending_hook}" if ending_hook else scene.goal
            updates["required_surface"] = _join(
                [
                    scene.required_surface,
                    emotional_turn and f"情绪转折：{emotional_turn}",
                    outsider_misread and f"外人误判：{outsider_misread}",
                ],
                scene.required_surface,
            )
            if ending_hook:
                updates["exit_state"] = ending_hook
        if updates:
            result.append(WritingTaskScene(**{**asdict(scene), **updates}))
        else:
            result.append(scene)
    return result


def _attribute_decision(plan: dict[str, Any]) -> dict[str, Any]:
    decision = _event_plan(plan).get("attribute_allocation_decision")
    if not isinstance(decision, dict):
        return {}
    mode = str(decision.get("mode") or "").strip().lower()
    remaining = decision.get("remaining")
    if isinstance(remaining, bool) or not isinstance(remaining, int) or remaining < 0:
        return {}
    if mode == "carry":
        return {"mode": mode, "remaining": remaining, "reason": _text(decision.get("reason"), 80)}
    allocations = decision.get("allocations")
    if mode != "allocate" or not isinstance(allocations, dict) or not allocations:
        return {}
    normalized = {
        str(name): points
        for name, points in allocations.items()
        if str(name).strip() and isinstance(points, int) and not isinstance(points, bool) and points > 0
    }
    return {"mode": mode, "allocations": normalized, "remaining": remaining} if normalized else {}


def _attribute_decision_requirement(decision: dict[str, Any]) -> str:
    if decision["mode"] == "allocate":
        allocations = decision["allocations"]
        spent = sum(allocations.values())
        chosen = "、".join(f"{name}+{points}" for name, points in allocations.items())
        return f"看到新增{spent}点、按路线选择{chosen}、确认属性和剩余{decision['remaining']}点；只展示本次涉及属性，不完整重复面板"
    reason = decision.get("reason") or "为后续路线保留"
    return f"看到剩余{decision['remaining']}点，并给出保留原因：{reason}"


def _protagonist_level_scene_index(plan: dict[str, Any], scenes: list[WritingTaskScene], chapter_number: int) -> int | None:
    for index, card in enumerate(_scene_cards(plan)[: len(scenes)]):
        state_delta = card.get("state_delta") if isinstance(card.get("state_delta"), dict) else {}
        protagonist = state_delta.get("protagonist") if isinstance(state_delta.get("protagonist"), dict) else {}
        if parse_level(protagonist.get("level")) is not None:
            return index
    if chapter_number == 1:
        return 1 if len(scenes) > 1 else 0
    return None


def _apply_attribute_decision_to_scenes(
    scenes: list[WritingTaskScene],
    decision: dict[str, Any],
    *,
    plan: dict[str, Any],
    chapter_number: int,
) -> tuple[list[WritingTaskScene], bool]:
    if not scenes or not decision:
        return scenes, False
    target_index = _protagonist_level_scene_index(plan, scenes, chapter_number)
    if target_index is None:
        return scenes, False
    requirement = _attribute_decision_requirement(decision)
    return [
        WritingTaskScene(**{**asdict(item), "required_surface": _join([item.required_surface, requirement], item.required_surface)})
        if index == target_index
        else item
        for index, item in enumerate(scenes)
    ], True


def _generic_scenes(plan: dict[str, Any], *, game_context: bool) -> list[WritingTaskScene]:
    cards = _scene_cards(plan)
    plot = _plot_simulation(_simulation_plan(plan))
    if not cards:
        total = _target_chars_int(plan)
        scenes = [
            WritingTaskScene(
                key="opening",
                title="承接与目标",
                goal="承接上一章状态，明确本章目标、资源和可见风险。",
                required_surface="上一章结果、当前目标、眼前处境和场景入口",
                entry_state="承接上一章章末状态。",
                exit_state="目标、资源和第一处行动地点已经清楚。",
                handoff="下一场从已明确的行动地点推进阻力。",
                target_chars=max(750, total // 4),
            ),
            WritingTaskScene(
                key="pressure",
                title="阻力出现",
                goal="让世界根据主角行动给出可见反应，形成具体阻力。",
                required_surface="可观察痕迹、人物、环境或对手反应，以及主角当场判断",
                entry_state="主角开始行动，阻力尚未完全显形。",
                exit_state="阻力改变了路线、花费、信息或关系。",
                handoff="下一场必须基于这个阻力做选择。",
                target_chars=max(900, total // 4),
            ),
            WritingTaskScene(
                key="choice",
                title="选择与代价",
                goal="主角做选择，兑现一点收益，同时付出可见代价。",
                required_surface="选择过程、行动细节、收益、代价、状态变化",
                entry_state="主角面对上一场形成的阻力。",
                exit_state="选择完成，结果和代价已经改变处境或人物关系。",
                handoff="下一场收束结果并抛出新的问题或行动。",
                target_chars=max(950, total // 4),
            ),
            WritingTaskScene(
                key="hook",
                title="收束与下一步",
                goal="收住本章事件，更新状态，并留下下一章具体问题。",
                required_surface="结果回收、状态更新、未解问题、下一章目标",
                entry_state="核心选择已完成。",
                exit_state="本章结果已落地，下一章要做什么已经清楚。",
                handoff="下一章必须承接这个行动。",
                target_chars=max(700, total // 4),
            ),
        ]
        return _apply_plot_to_scenes(scenes, plot, game_context=game_context)

    total = _target_chars_int(plan)
    planned_scene_count = min(5, max(3, len(cards)))
    per_scene = max(750, total // planned_scene_count)
    scenes: list[WritingTaskScene] = []
    for index, card in enumerate(cards[:5], start=1):
        source_id = _scene_source_id(card, index)
        must_show = _as_list(card.get("must_show"), max_items=8, item_chars=38)
        write_as = _as_list(card.get("write_as"), max_items=4, item_chars=38)
        fact_locks = [f"事实锁：{item}" for item in _as_list(card.get("fact_locks"), max_items=5, item_chars=38)]
        avoid = [
            *_as_list(card.get("must_not_explain"), max_items=5, item_chars=40),
            *_as_list(card.get("avoid"), max_items=5, item_chars=40),
        ]
        required = must_show + write_as + fact_locks
        location = _text(card.get("location") or "当前地点", 30)
        purpose = _text(card.get("purpose") or card.get("goal") or "推进本章目标", 90)
        conflict = _text(card.get("conflict") or "出现可见阻力", 70)
        scenes.append(
            WritingTaskScene(
                key=_slug(source_id, f"scene_{index}"),
                title=f"{location}：{purpose}",
                goal=f"{purpose}；阻力是{conflict}。",
                required_surface=_join(required, "地点、行动、反馈、代价"),
                forbidden_surface=_join(avoid, "不要写成规则解释，不要越过主角视角"),
                entry_state=_text(card.get("entry_state") or f"进入{location}。", 90),
                exit_state=_text(card.get("exit_state") or card.get("ending_pressure") or "形成下一场压力。", 100),
                handoff=_text(card.get("handoff") or "下一场必须承接本场结果，不重置状态。", 100),
                target_chars=per_scene,
                source_ids=[source_id],
            )
        )
    if len(scenes) < 3:
        scenes.append(
            WritingTaskScene(
                key="choice",
                title="选择与变化",
                goal="人物根据前面的发现做出选择，让局面发生具体变化。",
                required_surface="选择过程、实际行动、可见结果，以及为此付出的代价",
                entry_state="人物已经看见阻力，不能再按原计划轻松推进。",
                exit_state="选择已经产生结果，人物的资源、关系或处境发生变化。",
                handoff="下一场承接这个结果收束本章。",
                target_chars=per_scene,
                source_ids=["compiled-choice"],
            )
        )
    if len(scenes) < 3:
        scenes.append(
            WritingTaskScene(
                key="hook",
                title="结果与下一步",
                goal="收住本章事件，让结果落地，并留下下一章可以立即行动的问题。",
                required_surface="本章结果、人物反应、尚未解决的问题和明确的下一步",
                entry_state="本章主要选择已经完成。",
                exit_state="本章结果已经落地，下一步清楚但还没有执行。",
                handoff="下一章直接承接这个行动，不重复本章结论。",
                target_chars=per_scene,
                source_ids=["compiled-hook"],
            )
        )
    return _apply_plot_to_scenes(scenes, plot, game_context=game_context)


def build_writing_taskbook(
    *,
    chapter_number: int,
    plan: dict[str, Any] | None = None,
    genre: str = "",
    style: str = "",
) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    game_context = _looks_like_game_context(plan, genre)
    governance = plan.get("governance") if isinstance(plan.get("governance"), dict) else {}
    chapter_intent = governance.get("chapter_intent") if isinstance(governance.get("chapter_intent"), dict) else {}
    trade_authorized = bool(chapter_intent.get("first_chapter_trade_authorized"))
    scenes = _generic_scenes(plan, game_context=game_context)
    simulation_plan = _simulation_plan(plan)
    event_plan = _event_plan(plan)
    decision = _attribute_decision(plan)
    scenes, decision_attached_to_scene = _apply_attribute_decision_to_scenes(
        scenes,
        decision,
        plan=plan,
        chapter_number=chapter_number,
    )
    global_required = [
        *_plot_required_lines(_plot_simulation(simulation_plan)),
        *_longform_contract_required_lines(
            simulation_plan.get("longform_plot_contract")
            if isinstance(simulation_plan.get("longform_plot_contract"), dict)
            else {}
        ),
        *_as_list(simulation_plan.get("required_beats"), max_items=6, item_chars=50),
        *_as_list(event_plan.get("exposition_beats"), max_items=4, item_chars=50),
    ]
    outline_anchor = plan.get("outline_anchor") if isinstance(plan.get("outline_anchor"), dict) else {}
    opening_balance = str(outline_anchor.get("opening_balance") or "").strip()
    if opening_balance:
        global_required.append(f"章首现实可用余额：{opening_balance}；只能按正文中的收支结果变化。")
    global_forbidden = [
        *_as_list(simulation_plan.get("forbidden_moves"), max_items=8, item_chars=56),
        *_as_list(chapter_intent.get("must_avoid"), max_items=6, item_chars=56),
    ]
    if decision.get("mode") == "carry":
        global_required.append(f"属性点保留原因必须在场：{decision.get('reason') or '为后续路线保留'}")
    if decision and not decision_attached_to_scene:
        placement = "发生升级的场景" if planned_level_target(plan) is not None else "人物实际处理属性点的场景"
        global_required.append(f"属性点决策必须在{placement}落地：{_attribute_decision_requirement(decision)}")
    world_required, world_forbidden = _world_context_requirements(simulation_plan)
    global_required.extend(world_required)
    global_forbidden.extend(world_forbidden)
    if chapter_number == 1 and game_context:
        noise_bans = FIRST_CHAPTER_NOISE_BANS
        if trade_authorized:
            noise_bans = tuple(
                item
                for item in noise_bans
                if item not in {"材料公开处理成大钱", "交易行寄售已经完成", "公开扣费或大额收款反馈"}
            )
        global_forbidden.extend(item for item in noise_bans if item not in global_forbidden)
        global_required.append(
            "第一章按本书章纲完成进入游戏、第一次有效行动和下一步目标；交易、兑换、论坛或公会反应只有在章纲明确安排时才能出现。"
        )
        global_required.append("重要情绪落到人物当场的动作、停顿、回答或选择里，不写空泛感慨。")
    taskbook = WritingTaskBook(
        chapter_number=chapter_number,
        genre_mode="game" if game_context else "general",
        chapter_title=_chapter_title(plan),
        chapter_goal=_chapter_goal(plan),
        target_chars=_target_chars_text(plan),
        style_contract=[style_prompt] if (style_prompt := book_style_prompt(style)) else [],
        craft_templates=list(GAME_CRAFT_TEMPLATES if game_context else GENERIC_CRAFT_TEMPLATES),
        global_required=global_required,
        global_forbidden=global_forbidden,
        scenes=scenes,
        source=f"compiled_from_{len(_scene_cards(plan))}_scene_cards",
    )
    return asdict(taskbook)


def ensure_writing_taskbook(
    chapter_number: int,
    plan: dict[str, Any] | None,
    *,
    genre: str = "",
    style: str = "",
) -> dict[str, Any]:
    plan = plan if isinstance(plan, dict) else {}
    existing = plan.get("writing_taskbook")
    if isinstance(existing, dict) and isinstance(existing.get("scenes"), list):
        existing_mode = str(existing.get("genre_mode") or "").strip()
        if not genre and existing_mode in {"game", "general"}:
            return existing
        expected_mode = "game" if _looks_like_game_context(plan, genre) else "general"
        compiled_cache = str(existing.get("source") or "").startswith("compiled_from_")
        if existing_mode == expected_mode or (not existing_mode and not compiled_cache):
            return existing
    return build_writing_taskbook(chapter_number=chapter_number, plan=plan, genre=genre, style=style)


def _scene_lines(scene: dict[str, Any], index: int) -> list[str]:
    return [
        f"场面{index} [{scene.get('key')}] {scene.get('title')}",
        f"- 这一场要推进：{scene.get('goal')}",
        f"- 开场状态：{scene.get('entry_state')}",
        f"- 读者要看见：{scene.get('required_surface')}",
        f"- 先别写：{scene.get('forbidden_surface')}",
        f"- 收束到：{scene.get('exit_state')}",
        f"- 下一场接住：{scene.get('handoff')}",
        f"- 大约：{scene.get('target_chars')}字",
    ]


def format_taskbook_prompt_section(
    taskbook: dict[str, Any] | None,
    *,
    include_all_scenes: bool = True,
) -> str:
    taskbook = taskbook if isinstance(taskbook, dict) else {}
    scenes = [scene for scene in taskbook.get("scenes", []) if isinstance(scene, dict)]
    scene_block = scenes
    if not include_all_scenes:
        scene_block = scenes[:3]
    lines = [
        "## 本章写法材料",
        "下面是给作者的场面材料；写正文时只吸收内容，不输出这些提示。",
        f"章节：第{taskbook.get('chapter_number') or ''}章",
        f"标题参考：{taskbook.get('chapter_title') or '由正文自然生成'}",
        f"这一章要推进：{taskbook.get('chapter_goal') or '完成本章推进'}",
        f"篇幅：{taskbook.get('target_chars') or '按目标字数'}",
        "文字口径：",
    ]
    lines.extend(f"- {item}" for item in _as_list(taskbook.get("style_contract"), max_items=8, item_chars=120))
    craft_templates = _as_list(taskbook.get("craft_templates"), max_items=6, item_chars=160)
    if craft_templates:
        lines.append("场面参考：")
        lines.extend(f"- {item}" for item in craft_templates)
    required = _as_list(taskbook.get("global_required"), max_items=8, item_chars=80)
    forbidden = _as_list(taskbook.get("global_forbidden"), max_items=10, item_chars=80)
    if required:
        lines.append("这一章要让读者看到：")
        lines.extend(f"- {item}" for item in required)
    if forbidden:
        lines.append("先别写这些：")
        lines.extend(f"- {item}" for item in forbidden)
    lines.append("场面安排：")
    for index, scene in enumerate(scene_block, start=1):
        lines.extend(_scene_lines(scene, index))
    return "\n".join(str(line) for line in lines if str(line).strip())


def format_taskbook_brief_section(
    taskbook: dict[str, Any] | None,
    *,
    max_scenes: int = 3,
) -> str:
    taskbook = taskbook if isinstance(taskbook, dict) else {}
    scenes_all = [scene for scene in taskbook.get("scenes", []) if isinstance(scene, dict)]
    scenes = scenes_all[:max_scenes]
    lines = [
        "## 本章方向",
        f"这一章要推进：{writer_facing_text(taskbook.get('chapter_goal') or '完成本章推进')}",
        f"篇幅：{taskbook.get('target_chars') or '按目标字数'}",
    ]
    required = _as_list(taskbook.get("global_required"), max_items=4, item_chars=70)
    forbidden = _as_list(taskbook.get("global_forbidden"), max_items=4, item_chars=70)
    if required:
        lines.append("读者要看见：")
        lines.extend(f"- {item}" for item in required)
    if forbidden:
        lines.append("先别写：")
        lines.extend(f"- {item}" for item in forbidden)
    if scenes:
        lines.append("场面：")
        for index, scene in enumerate(scenes, start=1):
            lines.append(
                f"{index}. {scene.get('title') or scene.get('key')}: "
                f"{_text(scene.get('goal'), 70)}；读者要看见：{_text(scene.get('required_surface'), 90)}；"
                f"收束到：{_text(scene.get('exit_state') or scene.get('handoff'), 70)}"
            )
    return "\n".join(str(line) for line in lines if str(line).strip())
