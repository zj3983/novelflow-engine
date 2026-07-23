from __future__ import annotations

from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.writing_taskbook import writer_facing_text


def build_web_game_author_craft(chapter_number: int, *, chapter_goal: str = "") -> dict[str, Any]:
    """Return a compact craft profile for web-game chapters.

    This is not an author imitation pack. It distills reusable web-game craft:
    rule accuracy, player ecology, visible cost, and data-flow payoff. Keep the
    structure small so writer prompts can read it as a method card instead of a
    pile of JSON.
    """

    early = chapter_number <= 3
    boundary_focus = chapter_number == 1 or any(token in chapter_goal for token in ("边界", "验证", "试探", "boundary"))
    return {
        "schema_version": "web-game-author-craft/v1",
        "lineage": [
            "规则准确型：高手感来自判断、操作和生态位置，不来自作者宣告。",
            "数据爽感型：数值、装备、任务和帮会压力要兑现，但必须先有代价和可见证据。",
        ],
        "chapter_engine": [
            "现实压力",
            "游戏规则试探",
            "系统/NPC即时反馈",
            "资源或风险代价",
            "玩家生态弱反应",
            "下一步麻烦",
        ],
        "craft_laws": [
            "高手感写判断：主角看懂别人忽略的规则缝隙，而不是开口解释自己很聪明。",
            "规则靠操作显形：掉落、背包、耐久、法力、路线、任务门槛和NPC回答替代百科说明。",
            "网游不是单机：玩家、NPC、市场、论坛、公会各有视角，但早期只露弱线索和误读。",
            "爽点优先是'我懂了'：读者看到主角试出一个小答案，再被更大的麻烦卡住。",
            "每章必须有代价：血量、蓝量、耐久、药水、背包格、等待、路线风险或暴露风险至少落一项。",
        ],
        "early_arc_exposure": {
            "phase": "opening" if early else "growth",
            "allowed": [
                "低级地图",
                "一个命名NPC柜台",
                "普通玩家的表层行为",
                "任务/背包/耐久/补给等可见规则",
                "市场或公会的滞后弱线索" if not boundary_focus else "不写正式市场/公会反应，只保留路牌级存在感",
            ],
            "blocked": [
                "公会内部频道",
                "论坛全景热帖",
                "商人正面盯盘",
                "后台分析",
                "隐藏机制全解释",
            ],
        },
        "boundary_chapter_contract": {
            "enabled": boundary_focus,
            "pleasure": "第一章的爽点不是到账，而是试清楚系统认什么、不认什么。",
            "must_answer": [
                "系统承认什么反馈",
                "NPC这边能办什么、不能办什么",
                "主角付出什么资源代价",
                "下一步还缺哪一个条件",
            ],
            "must_not_drift_to": [
                "实际寄售",
                "成交到账",
                "手续费扣款",
                "人民币换算",
                "论坛或公会追查",
            ],
        },
    }


def _reaction_ladder(chapter_number: int, boundary_focus: bool) -> list[str]:
    if boundary_focus:
        return [
            "玩家：只看见一个散人在低级地图反复试错，不知道异常。",
            "NPC：只按柜台规矩回应数量、价格、任务或登记结果。",
            "市场：本章不正式启动交易反应。",
            "论坛：本章不出现热帖，只能有路牌级公共频道噪音。",
            "公会：本章无正面追查，无内部频道。",
        ]
    if chapter_number <= 3:
        return [
            "玩家：先误读为运气、路线或刷怪效率。",
            "NPC：记录服务结果，不解释隐藏原因。",
            "市场：只出现价格、数量、批次、时间戳等弱线索。",
            "论坛：只允许零散猜测，不形成结论。",
            "公会：只做外围记录或资源点秩序动作，不锁定身份。",
        ]
    return [
        "玩家：根据可见收益跟风或竞争。",
        "NPC：基于岗位记录触发任务、门槛或拒绝。",
        "市场：重复模式才带来价格和商人反应。",
        "论坛：多源信息后才出现误读、争论或榜单。",
        "公会：只根据公开证据逐步试探、拉拢或压制。",
    ]


def plain_writer_phrase(text: str) -> str:
    """Translate internal planning words before they reach writer prompts."""

    replacements = (
        ("实际寄售", "把材料拿去处理"),
        ("匿名寄售", "匿名处理材料"),
        ("寄售成功", "材料处理成功"),
        ("寄售", "材料处理"),
        ("上架", "摆上去处理"),
        ("挂单", "挂出去处理"),
        ("成交到账", "交易完成"),
        ("成交", "交易完成"),
        ("到账", "收到反馈"),
        ("手续费扣款", "扣掉一笔费用"),
        ("手续费", "扣费"),
        ("人民币换算", "现实换钱"),
        ("换钱", "处理材料"),
        ("交易行", "市场柜台"),
        ("商人正面盯盘", "市场玩家盯上来"),
        ("商人正面登场", "市场玩家正面登场"),
        ("商人玩家", "市场玩家"),
        ("商人", "市场玩家"),
        ("赵胖子", "现实债主"),
        ("白袍据点视角", "玩家势力据点视角"),
        ("白袍", "玩家势力"),
        ("公会追查", "玩家势力追过来"),
        ("公会内部频道", "玩家势力内部频道"),
        ("公会完整追查", "玩家势力完整追查"),
        ("公会", "玩家势力"),
        ("论坛热帖", "公共频道热帖"),
        ("论坛全景热帖", "公共频道全景热帖"),
        ("论坛", "公共频道"),
        ("锁定坐标", "追到位置"),
        ("灰狼坡验边界", "灰狼坡试水"),
        ("背包格验边界", "背包快满了"),
        ("法杖耐久验边界", "法杖快断了"),
        ("验门路", "试水"),
        ("首次验证对象", "第一次试怪对象"),
        ("首次验证", "第一次试"),
        ("确认边界", "试清楚能不能走"),
        ("边界验证", "试一把"),
        ("验证边界", "试一把"),
        ("服务节点", "柜台"),
        ("服务边界", "能办什么、不能办什么"),
        ("信息边界", "能知道什么、不知道什么"),
        ("岗位边界", "柜台规矩"),
        ("规则边界", "这条路能不能走"),
        ("边界章", "第一章"),
        ("边界", "门路"),
        ("验证", "试"),
    )
    result = text
    for old, new in replacements:
        result = result.replace(old, new)
    return writer_facing_text(result)


def _plain_writer_phrase(text: str) -> str:
    return plain_writer_phrase(text)


def _variant_fact_locks(simulation_plan: dict[str, Any], event_plan: dict[str, Any]) -> list[str]:
    text = "\n".join([str(simulation_plan), str(event_plan)])
    variant_id = str(simulation_plan.get("simulation_variant") or "")
    locks: list[str] = []
    if "灰狼" in text or variant_id.startswith("boundary-"):
        locks.extend(
            [
                "本章首次验证对象固定为灰狼，地点固定为灰狼坡；不得写成灰鼠、灰鼠坡、鼠皮或灰鼠毒囊。",
                "本章材料固定为灰狼毒腺和粗糙狼皮；不得把材料名改成毒囊、鼠皮或其他怪物材料。",
                "现实压力只沿用项目档案里已经存在的账单和工作处境；不得套用其他作品的金额或账单，也不得新增前世、穿越、网贷、靶向药费或重病亲属。",
            ]
        )
    if variant_id == "boundary-inventory-route" or "铁栓" in text:
        locks.append("本章服务NPC固定为仓库管理员铁栓；他只懂仓储格、寄存门槛和背包占用，不讲公会、论坛、市场分析。")
    elif variant_id == "boundary-durability-route" or "老葛" in text:
        locks.append("本章服务NPC固定为修理匠老葛；他只懂修理价格、耐久红线和装备损耗，不讲公会、论坛、市场分析。")
    elif variant_id == "boundary-combat-cost" or "洛婶" in text:
        locks.append("本章服务NPC固定为药剂师洛婶；她只懂药价、补给和药材门槛，不讲公会、论坛、市场分析。")
    return locks


def build_web_game_director_card(
    *,
    chapter_number: int,
    chapter_goal: str = "",
    simulation_plan: dict[str, Any] | None = None,
    event_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compile web-game craft into a concise writer/director card."""

    simulation_plan = simulation_plan if isinstance(simulation_plan, dict) else {}
    event_plan = event_plan if isinstance(event_plan, dict) else {}
    goal = chapter_goal or str(simulation_plan.get("chapter_goal") or event_plan.get("turn") or event_plan.get("next_focus") or "")
    boundary_focus = chapter_number == 1 or any(token in goal for token in ("边界", "验证", "试探", "boundary"))
    visible_actions = compact_list(
        [
            str(item.get("action") if isinstance(item, dict) else item)
            for item in event_plan.get("ordered_actions", [])
            if str(item).strip()
        ],
        max_items=5,
        item_chars=60,
    )
    fact_locks = _variant_fact_locks(simulation_plan, event_plan)
    return {
        "schema_version": "web-game-director-card/v1",
        "read_feel": (
            "主角试出游戏世界的一条小缝，读者爽在'看懂他怎么钻过去'。"
            if boundary_focus
            else "主角利用已经试出来的门路推进收益，同时让世界生态产生滞后反应。"
        ),
        "scene_formula": "现实压力 -> 试探动作 -> 即时反馈 -> 资源代价 -> 半个答案 -> 更大问题",
        "boundary_focus": boundary_focus,
        "visible_actions": visible_actions,
        "reaction_ladder": _reaction_ladder(chapter_number, boundary_focus),
        "fact_locks": fact_locks,
        "write_rules": [
            "规则只能通过动作、面板变化、NPC岗位回答、玩家误读、环境阻力出现。",
            "不要把网游规则写成说明书；每条规则都要伴随一个可见代价。",
            "NPC只说岗位话；普通玩家只看表面；公会/论坛/市场必须按证据规模滞后反应。",
            "主角保持限知，只能使用自己看见、听见、问到、试出来的信息。",
        ],
        "boundary_chapter_bans": (
            ["寄售", "成交", "到账", "手续费扣款", "换钱", "论坛热帖", "公会追查"]
            if boundary_focus
            else []
        ),
        "one_line": compact_text(_plain_writer_phrase(goal), 120) or "让主角用一次可见行动试出一条路，并付出代价。",
    }


def format_web_game_director_card(card: dict[str, Any] | None) -> str:
    """Render the compact card as writer-readable text."""

    if not isinstance(card, dict) or not card:
        return "网游导演卡：无。"
    lines = [
        f"网游导演卡：{_plain_writer_phrase(str(card.get('read_feel') or '把网游规则写成可见场景。'))}",
        f"章法：{_plain_writer_phrase(str(card.get('scene_formula') or '压力 -> 试探 -> 反馈 -> 代价 -> 钩子'))}",
        f"本章一句话：{_plain_writer_phrase(str(card.get('one_line') or '先跑一小段，看这条路能不能走。'))}",
    ]
    reactions = compact_list([_plain_writer_phrase(str(item)) for item in (card.get("reaction_ladder") or [])], max_items=5, item_chars=80)
    if reactions:
        lines.append("生态反应阶梯：" + "；".join(reactions))
    rules = compact_list([_plain_writer_phrase(str(item)) for item in (card.get("write_rules") or [])], max_items=4, item_chars=80)
    if rules:
        lines.append("写法提醒：" + "；".join(rules))
    bans = compact_list(card.get("boundary_chapter_bans") or [], max_items=8, item_chars=20)
    if bans:
        lines.append("第一章先放后面：材料换钱、市场玩家盯上主角、公共频道扩散、玩家势力追过来")
    fact_locks = compact_list([_plain_writer_phrase(str(item)) for item in (card.get("fact_locks") or [])], max_items=6, item_chars=100)
    if fact_locks:
        lines.append("变体事实锁：" + "；".join(fact_locks))
    return "\n".join(lines)
