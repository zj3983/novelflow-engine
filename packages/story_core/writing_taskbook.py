from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any

from packages.story_core.book_style import book_style_prompt


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
    "对话场面：一人问/催/提醒，主角用完整句子给表面理由，对方再接一句生活化反应；台词必须改变信息、关系、价格、风险或下一步行动。",
    "现代中文对话：不要把后台事实直译成台词；“先试，不深入”要改成“我就在门口看一眼，不往里走”，“柜台不认”要改成“没材料也交不了”。",
    "章末压句：如果本章有误判、羞辱、卡任务或资源压力，结尾允许一句白话反打承诺；必须来自当章具体矛盾，不套成语、不喊口号。",
    "情绪场面：不要写抽象感慨，写手指停住、视线移开、话说到一半、笑意收住、把东西重新放回去这类能看见的动作。",
)

GAME_CRAFT_TEMPLATES = (
    "选择场面：先写夜烬看见一个具体东西（价牌、角色面板、背包格、任务牌、队伍、怪物位置），再写麻烦（钱不够、蓝不够、法杖快坏、背包快满、别人会抢），最后做一个小决定；不要直接写“控制成本/规划路线”。",
    "对话场面：别人问、催或提醒；夜烬用完整句子给表面理由，比如钱、蓝、耐久、材料、排队或前置任务；对方再有一句像普通玩家的反应。夜烬不能只说两个字装高手，也不能说出隐藏机制。",
    "现代中文对话：不要把后台事实直译成台词；“先试，不深入”要改成“我就在坡口打两只看看，不往里走”，“柜台不认/背包里没有毒腺”要改成“你手里没毒腺，接了也交不了”。",
    "章末压句：如果本章有误判、卡任务或资源压力，结尾允许一句白话反打承诺；必须来自当章具体矛盾，不套成语、不喊口号。例：先让他们抢。等他们卡在任务牌前，就该轮到他往前走了。",
    "战斗场面：怪怎么来，夜烬先被逼一下或犯一个小错，消耗落到血蓝和法杖耐久，掉落异常出现后先写他的动作反应；不要只写火球命中、怪倒地、掉落入包。",
    "怪物面板：同类普通怪第一次正式交战前显示一次名称、等级、生命和攻击方式，后面不重复刷；精英怪和首领首次出现时再加技能和特性，掉落必须等击杀后结算。",
    "爽点场面：先写普通玩家还卡在哪里，再写夜烬因为异常掉落提前够到什么前置，接着写他为什么不能公开用，章末让读者知道下一章能抢什么。",
)


def first_chapter_whole_body_contract(*, game_genre: bool, trade_authorized: bool = False) -> dict[str, Any]:
    if not game_genre:
        return {}
    beat_map = (
        "现实压力 -> 登录建号 -> 低级验证 -> 匿名交割与急账处理 -> 下一步"
        if trade_authorized
        else "现实压力 -> 登录建号 -> 低级验证 -> 下一步钩子"
    )
    return {
        "mode": "whole_body_only",
        "beat_map": beat_map,
        "beats": [
            "现实压力：用余额、房租、旧设备、身体反应或生活细节说明为什么现在必须登录。",
            "登录建号：必须出现“角色面板”四个字，写清游戏ID、统一初始身份见习冒险者（未转职）、Lv.1短面板、初始武器或技能，以及开服现场质感。",
            "低级验证：用一场小规模战斗或测试写出血蓝、耐久、可堆叠背包、掉落、任务进度和普通玩家更慢的对比；不要写施法前摇、验证逻辑或抽象收益词。",
            "下一步钩子：材料分开处理，章末优先落到职业导师木牌、任务牌、装备、技能或地图入口的前置任务；可以有柜台/窗口，也可以暗中办理一项小服务，但外人只看见普通排队。",
        ],
        "style": [
            "句子要完整，动作、原因和结果要接得上。",
            "读者要看得出角色在做什么、怕什么、想试什么、下一步去哪里。",
            "少写验证、逻辑、收益、路线这种判断词，改成试一把、看一眼、包快满、前置任务还没做完。",
        ],
        "dialogue": [
            "自然对话：人物说话要顺、接地气，可以有半句抱怨、解释和接话，不要全是口令式回答。",
            "主角必须至少主动开口一次，格式要能被识别，例如“夜烬问/说/低声道：……”；但不要只补一句装冷静，要让他说清一个理由或选择。",
            "每章至少有一轮连续问答：别人问/催/提醒，主角回答并给原因，对方再有一句反应；这轮对话要改变价钱、任务、误会或下一步行动。",
            "台词不能替作者讲规则、讲设定或讲审稿结论。",
            "对话要推进价格、任务、信任、误会、信息或行动。",
            "先判断关系和场合再定语气：陌生人客气试探，普通熟人可以轻微调侃，亲近关系才允许接梗或互相损；没有关系依据时不要突然开玩笑。",
            "关键台词要带一层人物情绪或关系目的：想隐瞒、怕被看轻、替自己找台阶、试探对方、压住火气或故意缓和气氛。",
        ],
        "avoid": [
            "不用分段生成；按整章连续正文自然写出四拍。",
            "变现、成交、到账和手续费扣款必须服从本章计划；公共频道扩散、论坛爆帖、公会追查或市场玩家盯盘不得擅自提前。",
            "第一章不要让药剂师或药铺承担职业任务、职业试炼、全局市场分析或玩家生态判断；药剂师若出现，只能讲药材、库存、价格和她不知道的边界。",
            "第一章可以写NPC窗口、任务牌或职业导师木牌；是否提交材料、领取铜币、修装备或买药水必须跟随项目账本/章节计划，未允许时只露出前置条件和下一步目标。",
            "不要把开局身份写成独有职业；第一章所有玩家都是见习冒险者，夜烬只是选了法杖和基础火球术。背包同类材料堆叠，灰狼毒腺×8、粗糙狼皮×7应写成占用两个材料格或2/20。",
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


def _apply_plot_to_scenes(scenes: list[WritingTaskScene], plot: dict[str, Any]) -> list[WritingTaskScene]:
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
            updates["required_surface"] = f"阻碍必须可见：{obstacle_text}。用NPC回答、面板、背包、路况、价格、血蓝或耐久承载，不写后台解释。"
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


def _first_chapter_scenes(plan: dict[str, Any], *, trade_authorized: bool = False) -> list[WritingTaskScene]:
    target = max(4200, _target_chars_int(plan, fallback=4200))
    first = max(950, int(target * 0.34))
    second = max(1100, int(target * 0.42))
    third = max(800, target - first - second)
    noise_bans = FIRST_CHAPTER_NOISE_BANS
    if trade_authorized:
        noise_bans = tuple(
            item
            for item in noise_bans
            if item not in {"材料公开处理成大钱", "交易行寄售已经完成", "公开扣费或大额收款反馈"}
        )
    forbidden = "、".join(noise_bans)
    outline_anchor = plan.get("outline_anchor") if isinstance(plan.get("outline_anchor"), dict) else {}
    opening_balance = str(outline_anchor.get("opening_balance") or "").strip()
    balance_surface = (
        f"银行卡或支付账户可用余额{opening_balance}"
        if opening_balance
        else "项目写作包中的现实可用余额"
    )
    return [
        WritingTaskScene(
            key="entry_login",
            title="现实压力与登录建号",
            goal="用一个具体生活瞬间交代夜烬的处境，再让他戴上旧设备进入本书设定的游戏，完成建号、初始身份确认和武器/基础技能选择。",
            required_surface=f"{balance_surface}、催缴压力、现实职业/技能来源、旧头盔或登录入口、本书设定的游戏名、全沉浸/开服倒计时/玩家涌入/登录公告至少一个可见背景入口、游戏ID夜烬、初始身份见习冒险者（未转职）、正文明确写出‘角色面板’四个字，Lv.1短面板固定为经验0/100、生命100/100、法力60/60、钱袋为空或背包为空、新手法杖10/10、基础火球术、章首一个具体情绪动作如手指停顿/喉咙发紧/苦笑半秒；不要展开力量/敏捷/体质/智力等扩展属性",
            forbidden_surface=f"首次打怪、掉落、NPC长谈、交易操作、家庭网络已断却不交代移动数据/设备eSIM等有效联网方式就直接登录、{forbidden}",
            entry_state="现实出租屋，夜烬还没进游戏。",
            exit_state="夜烬建号完成，职业、等级、经验、血蓝、货币和初始装备可见。",
            handoff="下一场从夜烬走向低级怪区开始，不重写现实入口和建号流程。",
            target_chars=first,
            source_ids=["ch1-entry-login"],
        ),
        WritingTaskScene(
            key="small_verification",
            title="低级怪小验证",
            goal="只打一小轮低级怪，让夜烬亲眼看到千倍爆率会把普通流程压短，让他比别人更快凑齐任务或装备前置条件。",
            required_surface="第一次低级怪战斗前正文明确写出‘怪物面板’四个字，并显示名称、等级、生命、攻击方式；写出基础火球术或明确的近身应急、击杀后才露出掉落异常、底层协议校验通过、千倍爆率、掉落判定×1000、混沌之种未解析、血蓝/法力/耐久消耗、经验或任务材料进度变化、旁人正常低掉落形成对比、没有铜币收益、战斗中一次疼痛/后怕/侥幸的身体反应",
            forbidden_surface=f"大量刷怪、材料换钱、市场波动、玩家势力追查、论坛扩散、{forbidden}",
            entry_state="夜烬Lv.1，装备和背包刚可见，尚未验证掉落。",
            exit_state="小规模验证结束：异常可信但没解释清楚，夜烬看见自己能比普通玩家更快完成下一步。",
            handoff="下一场只能整理状态和决定下一步，不扩大成交易、追查或世界风暴。",
            target_chars=second,
            source_ids=["ch1-small-verification"],
        ),
        WritingTaskScene(
            key="decision_hook",
            title="暗中吃下第一笔",
            goal=(
                "按本章计划完成裂纹狼心担保交易，让现实款项到账并处理急账；交易保持匿名，不扩大成市场风波。"
                if trade_authorized
                else "材料分开处理，至少兑现一个小收益闭环；让夜烬把多余材料和来源藏住，只把普通玩家也会做的一项服务办掉，留下下一章抢先完成任务或摸到新路线的钩子。"
            ),
            required_surface=(
                "担保交易到账并处理现实急账、交易匿名、金额沿用大纲、现实余额随付款结果更新、来源没有暴露、下一章具体行动目标"
                if trade_authorized
                else "面板或背包更新、职业/等级/经验/生命/法力/耐久沿用前文不重开一套属性、交掉一小份材料或任务、保留多余材料、少量铜币/修理/药水至少兑现一项、清道夫或柜台只按普通流程办理、现实压力仍在、下一章具体任务/装备/技能/地图前置任务、章末一个不华丽的情绪动作如松一口气/没忍住看余额/把背包关了又打开"
            ),
            forbidden_surface=(
                f"一次性交空全部材料、公会/论坛/公共频道反应、市场玩家盯盘、{forbidden}"
                if trade_authorized
                else f"材料公开换成大钱、一次性交空全部材料、完整公开服务戏、公会/论坛/公共频道反应、市场玩家盯盘、提现或换算人民币、{forbidden}"
            ),
            entry_state="夜烬刚完成小验证，手里有异常材料，但还没处理。",
            exit_state=(
                "担保交易和现实急账处理完成，来源没有暴露，下一章承接游戏内升级和任务进度。"
                if trade_authorized
                else "本章确认千倍爆率能带来领先；至少一个小收益已经兑现，来源没有暴露，下一章从任务进度、装备修理、技能或新路线前置任务继续。"
            ),
            handoff="下一章承接这个具体麻烦，不把第一章改成公开赚钱或被人追踪。",
            target_chars=third,
            source_ids=["ch1-decision-hook"],
        ),
    ]


def _generic_scenes(plan: dict[str, Any]) -> list[WritingTaskScene]:
    cards = _scene_cards(plan)
    plot = _plot_simulation(_simulation_plan(plan))
    if not cards:
        total = _target_chars_int(plan)
        scenes = [
            WritingTaskScene(
                key="opening",
                title="承接与目标",
                goal="承接上一章状态，明确本章目标、资源和可见风险。",
                required_surface="上一章结果、当前目标、关键账本或状态、场景入口",
                entry_state="承接上一章章末状态。",
                exit_state="目标、资源和第一处行动地点已经清楚。",
                handoff="下一场从已明确的行动地点推进阻力。",
                target_chars=max(750, total // 4),
            ),
            WritingTaskScene(
                key="pressure",
                title="阻力出现",
                goal="让世界根据主角行动给出可见反应，形成具体阻力。",
                required_surface="可观察痕迹、NPC/环境/任务/对手反应、主角判断",
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
                exit_state="选择完成，收益和代价落到账本或关系里。",
                handoff="下一场收束结果并抛出新的前置任务。",
                target_chars=max(950, total // 4),
            ),
            WritingTaskScene(
                key="hook",
                title="收束与新前置",
                goal="收住本章事件，更新状态，并留下下一章具体问题。",
                required_surface="结果回收、状态更新、未解问题、下一章目标",
                entry_state="核心选择已完成。",
                exit_state="本章结果已落地，下一章前置任务清楚。",
                handoff="下一章必须承接这个前置任务。",
                target_chars=max(700, total // 4),
            ),
        ]
        return _apply_plot_to_scenes(scenes, plot)

    total = _target_chars_int(plan)
    per_scene = max(750, total // max(1, min(len(cards), 5)))
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
    return scenes


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
    scenes = (
        _first_chapter_scenes(plan, trade_authorized=trade_authorized)
        if chapter_number == 1 and game_context
        else _generic_scenes(plan)
    )
    simulation_plan = _simulation_plan(plan)
    event_plan = _event_plan(plan)
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
    global_forbidden = [
        *_as_list(simulation_plan.get("forbidden_moves"), max_items=8, item_chars=56),
        *_as_list(chapter_intent.get("must_avoid"), max_items=6, item_chars=56),
    ]
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
            "第一章完成登录、低级验证、担保交易到账并处理现实急账；交易保持匿名，论坛、公会追查后移。"
            if trade_authorized
            else "第一章只完成登录、低级验证和领先预期；材料只是通行券，交易、论坛、公会追查后移，提交委托、修理和买药水也后移。"
        )
        global_required.append("三段各至少一个情绪锚点：章首现实压力、战斗受伤/后怕、章末决定都要落到身体动作，不写空泛感慨。")
    taskbook = WritingTaskBook(
        chapter_number=chapter_number,
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
        return existing
    return build_writing_taskbook(chapter_number=chapter_number, plan=plan, genre=genre, style=style)


def taskbook_segment_specs(chapter_number: int, plan: dict[str, Any] | None) -> list[dict[str, Any]]:
    taskbook = ensure_writing_taskbook(chapter_number, plan)
    scenes = taskbook.get("scenes") if isinstance(taskbook.get("scenes"), list) else []
    return [scene for scene in scenes if isinstance(scene, dict)]


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
    segment_key: str | None = None,
    include_all_scenes: bool = True,
) -> str:
    taskbook = taskbook if isinstance(taskbook, dict) else {}
    scenes = [scene for scene in taskbook.get("scenes", []) if isinstance(scene, dict)]
    selected = [scene for scene in scenes if not segment_key or scene.get("key") == segment_key]
    if not selected and segment_key:
        selected = scenes[:1]
    scene_block = selected if segment_key else scenes
    if not include_all_scenes and not segment_key:
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
    segment_key: str | None = None,
) -> str:
    taskbook = taskbook if isinstance(taskbook, dict) else {}
    scenes_all = [scene for scene in taskbook.get("scenes", []) if isinstance(scene, dict)]
    if segment_key:
        scenes = [scene for scene in scenes_all if scene.get("key") == segment_key][:1]
    else:
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
