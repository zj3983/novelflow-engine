from __future__ import annotations

import re
from typing import Any

from packages.story_core.agent_base import compact_list, compact_text
from packages.story_core.genre_plugins import is_game_genre, merge_plugin_rulebooks, plugin_simulation_blueprint, select_genre_plugins
from packages.story_core.models import NovelProject, StoryState
from packages.story_core.novel_type_catalog import (
    normalize_novel_type_ids,
    novel_type_id_from_metadata_fact,
    resolve_novel_type_id,
)


LONGFORM_FACT_PREFIXES = (
    "百万字",
    "长期卷阶梯",
    "长期成长阶梯",
    "长期势力阶梯",
    "长期经济阶梯",
    "现实线阶梯",
    "真相揭露阶梯",
    "地图解锁阶梯",
    "NPC演化阶梯",
    "长期推演规则",
)


def _proxy_project(story: StoryState) -> NovelProject:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    genre_ids = normalize_novel_type_ids(story.genre_plugin_ids)
    if not genre_ids:
        explicit_genre = resolve_novel_type_id(story.genre)
        genre_ids = [explicit_genre] if explicit_genre else []
    if not genre_ids:
        explicit_genre = ""
        for fact in story.world_facts:
            explicit_genre = novel_type_id_from_metadata_fact(fact)
            if explicit_genre:
                break
        genre_ids = [explicit_genre] if explicit_genre else []
    if not genre_ids and _is_game_story(story):
        genre_ids = ["game_webnovel"]
    return NovelProject(
        project_id=story.story_id,
        title=story.outline[:80] or story.story_id,
        seed_outline=story.outline,
        world_summary="\n".join(story.world_facts[:24]),
        current_focus=(latest.next_focus if latest else ""),
        author_constraints=list(story.author_constraints),
        world_blueprint={"genre_plugin_ids": genre_ids} if genre_ids else {},
    )


def _is_game_story(story: StoryState) -> bool:
    text = "\n".join(
        [
            story.genre,
            story.style,
            story.outline,
            "\n".join(story.world_facts[:24]),
            "\n".join(story.author_constraints[:12]),
        ]
    )
    return is_game_genre(text)


def _phase(chapter_number: int, *, is_game: bool = True) -> str:
    if not is_game:
        if chapter_number <= 3:
            return f"黄金三章第{chapter_number}章：推进当前核心矛盾，兑现一个具体进展，并留下下一步行动。"
        return "常规连载章节：目标、行动、结果、代价和章末钩子。"
    if chapter_number == 1:
        return "黄金三章第1章：立主角、立游戏入口、立千倍爆率，让读者看到主角会比普通玩家快一步。"
    if chapter_number == 2:
        return "黄金三章第2章：用千倍爆率完成新手任务/装备前置条件，制造第一次明确领先。"
    if chapter_number == 3:
        return "黄金三章第3章：形成第一个小高潮，确立职业试炼和长期路线。"
    return "常规连载章节：目标、行动、收益、代价、外部反应和章末钩子。"


def _latest_continuity(story: StoryState) -> dict[str, Any]:
    latest = story.chapter_summaries[-1] if story.chapter_summaries else None
    return {
        "latest_summary": compact_text(latest.summary if latest else "", 220),
        "must_keep_facts": compact_list(latest.facts if latest else [], max_items=10, item_chars=150),
        "unresolved_threads": compact_list(latest.unresolved_threads if latest else [], max_items=6, item_chars=120),
        "next_focus": compact_text(latest.next_focus if latest else "", 160),
    }


def _longform_constraints(story: StoryState) -> list[str]:
    return compact_list(
        [fact for fact in story.world_facts if fact.startswith(LONGFORM_FACT_PREFIXES)],
        max_items=16,
        item_chars=220,
    )


def _contract_for_game(chapter_number: int) -> dict[str, list[str]]:
    if chapter_number == 1:
        return {
            "required_beats": [
                "现实压力和主角现实职业/技能来源必须自然出现。",
                "登录或建号阶段必须写出游戏ID/网名。",
                "必须写出初始身份和武器/技能选择：开局统一是见习冒险者（未转职），夜烬只是选择法杖和基础火球术倾向。",
                "必须出现短角色面板：ID、等级、身份/职业状态、经验、生命/法力、主武器或基础技能、背包/钱袋关键项；不要写成“货币：0铜”，不要展开易漂移的扩展属性。",
                "背包必须按同类道具堆叠：灰狼毒腺×8、粗糙狼皮×7应显示为两个材料格或背包2/20，不得按15件占15格。",
                "金手指必须先有触发伏笔，再完成首次验证，让读者看到爆率优势会转化为任务、装备、技能或路线前置任务上的提前一步。",
                "NPC服务节点只作为价牌、队伍、路牌或下一章目标轻量露出；第一章不强制完整办理业务。",
                "第一章只聚焦一个核心事件：登录建号后首次验证隐藏优势，并让读者看见优势已经开始滚动。",
                "任务提交、修理、补给或小额材料处理必须由项目账本或本章计划允许；未允许时只能露出价牌、队伍、前置条件和下一步目标。",
                "本章结尾必须给出已兑现账本：经验、库存、铜币、装备耐久、补给和下一步路线，让读者明确主角已经在幕后领先一截。",
            ],
            "forbidden_moves": [
                "禁止单次低级材料交易暴露坐标、现实身份、隐藏天赋或精确刷怪点。",
                "禁止写死金币兑人民币汇率，除非世界档案已有明确官方兑换或黑市行情。",
                "禁止第一章出现赵胖子追债、商人脚本盯盘、公会会长、白袍据点、论坛围观或任何公会追查戏。",
                "禁止第一章把交易、任务提交或补给写成公开炫耀；若项目账本未允许办理服务，第一章不得擅自提交、到账、修理或买药。",
                "禁止第一章提现、换算人民币、商人盯盘或形成市场追踪；游戏内铜币和补给收益只有在项目账本/章节计划允许时才兑现。",
                "禁止第一章完整展开多个命名NPC、多个服务点或多地图跑腿。",
                "禁止把规则写成百科说明，必须通过界面、交易、对话和行动展示。",
                "禁止在正文出现作者术语或创作术语，例如爽点、钩子、节奏、读者、网文规则、生成、审稿。",
                "禁止出现卖出16份毒腺后仍剩余8份这类库存矛盾；禁止未提交材料却写成任务已提交。",
            ],
            "world_reaction_targets": [
                "主角只得到个人层面的首次收益反馈、账本变化和领先预期。",
                "命名NPC只能基于岗位服务或任务入口给出一句边界清楚的反应。",
                "章末只留下下一章任务、装备、技能或路线前置目标，不让外部势力正式介入。",
            ],
        }
    if chapter_number == 2:
        return {
            "required_beats": [
                "继承第一章等级、经验、职业、货币、库存和装备耐久。",
                "本章仍属于Lv.1新手村任务推进：围绕清道夫委托、灰狼坡/后坡、基础火球术记录、修理和补给做可见进度。",
                "通过千倍爆率更快补齐任务、装备、技能或路线前置条件，让主角相对普通玩家明确领先。",
                "至少一个命名NPC以服务、价格、任务或信息边界影响选择。",
                "外部反应只能停留在普通玩家觉得运气好、NPC照规矩办事，不能升级成追查。",
            ],
            "forbidden_moves": [
                "禁止不记账地改变材料价格、货币余额、装备或经验。",
                "禁止Lv.1接取或开始转职任务、职业试炼、元素回廊试炼、法师塔试炼；10级之前只能看见线索或远期前置任务，不能正式办理。",
                "禁止直接完成元素回廊前置或直接升级，除非正文完整写出材料、经验和消耗账本。",
                "禁止公会精准锁定坐标、现实身份或隐藏天赋。",
            ],
            "world_reaction_targets": [
                "普通玩家还在重复刷材料时，主角已经完成任务、修好装备或拿到下一条路线。",
                "NPC只按任务/服务规则反馈，不主动怀疑隐藏天赋。",
                "公会和商人暂不介入；大型服务器会吞掉新手村小额噪音。",
            ],
        }
    return {
        "required_beats": [
            "每章必须有目标、行动、收益反馈、新压力。",
            "继承并更新等级、经验、货币、装备、任务和外部压力账本。",
            "世界反应必须来自可见痕迹和利益链条。",
        ],
        "forbidden_moves": [
            "禁止势力全知全能。",
            "禁止规则直接硬讲成长段说明。",
            "禁止跳过成本获得高阶收益。",
        ],
        "world_reaction_targets": [
            "市场、NPC、公会、普通玩家或论坛至少一方做出具体反应。",
        ],
    }


def _generic_contract() -> dict[str, list[str]]:
    return {
        "required_beats": [
            "本章必须明确目标、阻力、行动选择、阶段收益和章末新压力。",
            "设定必须通过场景、对话、行动和后果展示。",
        ],
        "forbidden_moves": [
            "禁止摘要化正文。",
            "禁止角色为推动剧情突然降智。",
            "禁止忘记上一章事实和未解钩子。",
        ],
        "world_reaction_targets": ["至少一个角色、势力或环境系统对主角行动做出反馈。"],
    }


def _simulation_axes(story: StoryState, plugin_ids: list[str]) -> dict[str, list[str]]:
    if "game_webnovel" in plugin_ids:
        return {
            "protagonist": ["现实身份", "游戏ID", "职业路线", "等级经验", "技能装备", "行事习惯"],
            "economy": ["币制", "材料单价", "挂单批次", "手续费", "库存", "现实兑换边界"],
            "npc": ["地点", "服务", "价格/前置条件", "利益诉求", "口吻", "信息边界"],
            "factions": ["公会外围", "商人玩家", "散人玩家", "生活职业需求", "论坛传闻"],
            "visibility": ["交易行时间戳", "价格曲线", "资源点目击", "NPC服务数据", "多源交叉延迟"],
        }
    return {
        "protagonist": ["目标", "代价", "关系变化", "当前能力"],
        "world": ["资源流动", "势力反应", "信息传播", "地点功能"],
    }


def _simulation_variant(story: StoryState, chapter_number: int) -> dict[str, Any]:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    raw = ledger.get("simulation_variant")
    if not isinstance(raw, dict):
        raw = {}
    variant_id = str(raw.get("id") or raw.get("variant_id") or "").strip()
    if not variant_id and chapter_number == 1:
        variant_id = "boundary-combat-cost"
    axes = raw.get("axes") if isinstance(raw.get("axes"), list) else []
    avoid = raw.get("avoid") if isinstance(raw.get("avoid"), list) else []
    variant = {
        "id": variant_id,
        "axes": compact_list(axes, max_items=6, item_chars=80),
        "avoid": compact_list(avoid, max_items=8, item_chars=80),
    }
    for flag in ("skip_style_adapt", "skip_expansion"):
        if raw.get(flag) is True:
            variant[flag] = True
    return variant


def _ledger_value(story: StoryState, *path: str) -> Any:
    value: Any = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def _current_level_label(story: StoryState) -> str:
    level_number = _current_level_number(story)
    return f"Lv.{level_number}" if level_number is not None else ""


def _current_level_number(story: StoryState) -> int | None:
    raw = _ledger_value(story, "protagonist", "level")
    if raw not in (None, ""):
        if isinstance(raw, int):
            return raw
        match = re.search(r"\d{1,3}", str(raw))
        if match:
            return int(match.group(0))
    latest_text = "\n".join(_latest_continuity(story).get("must_keep_facts", []))
    match = re.search(r"(?:Lv\.?|等级[：:]?)\s*(\d{1,3})", latest_text, flags=re.IGNORECASE)
    if match:
        return int(match.group(1))
    return None


def _game_progression_stage(level_number: int | None) -> str:
    if level_number is None or level_number < 10:
        return "newbie_low"
    if level_number < 30:
        return "trial_ready"
    return "midgame"


def _newbie_scene_plan(chapter_number: int) -> list[dict[str, str]]:
    if chapter_number == 1:
        return [
            {"key": "entry", "goal": "现实压力和登录建号落地"},
            {"key": "first_kill", "goal": "用低级怪验证千倍爆率和代价"},
            {"key": "decision", "goal": "材料先不处理，留下下一步任务或路线前置条件"},
        ]
    if chapter_number == 2:
        return [
            {"key": "risk_probe", "goal": "后坡入口试打一只，确认血蓝、耐久和能不能退回安全线"},
            {"key": "village_counter", "goal": "回村办理清道夫，NPC只按十份毒腺规则办事"},
            {"key": "service_nodes", "goal": "修法杖、买药，写清铜币、耐久、药水冷却"},
            {"key": "quest_gate", "goal": "看见后坡探路条件仍未满足，按钮或登记不可用"},
            {"key": "record_push", "goal": "回入口刷基础火球术命中记录，章末仍未碰高阶任务"},
        ]
    return [
        {"key": "state_check", "goal": "先核对等级、经验、铜币、背包、耐久和药水"},
        {"key": "low_map_goal", "goal": "在新手村或低级地图推进一个具体任务，不碰高阶任务"},
        {"key": "visible_cost", "goal": "写清补给、排队、血蓝、耐久、背包格或失败后的具体损失"},
        {"key": "small_gain", "goal": "只兑现经验、材料、任务进度或基础技能记录"},
        {"key": "next_gate", "goal": "章末留下10级、材料、导师登记或地图前置任务作为下一步目标"},
    ]


def _game_emotional_arc(chapter_number: int, stage: str) -> list[str]:
    if chapter_number == 1:
        return [
            "章首让现实余额、催缴或旧设备压住主角，情绪落到停顿、看余额或不舍得花钱。",
            "第一次打怪时写怕亏、怕死、蓝条见底或法杖耐久掉下去的后怕，不要只写计算。",
            "掉落变多后要给读者爽感：让他迅速收拢材料、交掉一小部分、修好关键装备或换到补给，但表面仍像普通玩家碰巧顺手。",
            "章末留下松一口气后的新贪念：他已经有第一笔优势，下一步要把这笔优势藏到更深处继续滚。",
        ]
    if stage == "newbie_low":
        return [
            "章首接现实余额或上一章账本，让主角先有一点舍不得花、怕亏或怕被人看穿。",
            "中段遇到排队、受伤、蓝不够、耐久掉或NPC规矩时，给一拍烦躁、迟疑或硬忍。",
            "拿到收益时不要写成装高手，写他把收益拆开处理：一部分交任务，一部分藏背包，一部分换修理或补给。",
            "章末让主角已经赚到一点、修好一点、推进一点，但外人只看到他像普通散人一样排队办事。",
        ]
    if stage == "trial_ready":
        return [
            "章首写到10级后的紧张，不是得意，而是担心材料、费用、排队和失败惩罚。",
            "导师验看或登记时要有一次被规矩卡住的尴尬、忍耐或试探。",
            "准备补给时写钱花出去的肉疼、背包格不够或药水冷却带来的不踏实。",
            "章末只给进入前置任务前的压力和期待，不用热血宣言替代具体担心。",
        ]
    return [
        "章首承接上一章未解决的压力，让角色带着一个具体担心行动。",
        "中段的选择要有情绪代价，例如忍让、试探、误判、舍不得或不甘心。",
        "收益兑现后写一拍真实反应，再让新压力压回来。",
    ]


def _game_genre_craft(chapter_number: int, stage: str) -> dict[str, Any]:
    if stage == "trial_ready":
        action_chain = [
            "想去试炼或转职登记",
            "先被导师、材料、费用、排队或失败惩罚卡住",
            "主角问清楚一个办理口径，或补齐一小项准备",
            "花掉时间、药水、耐久、背包格或铜币",
            "只拿到登记、入口线索或第一步资格，不直接通关",
            "章末留下下一项明确缺口",
        ]
    else:
        action_chain = [
            "主角想完成一个低级目标并暗中兑现收益",
            "先遇到血蓝、耐久、背包、排队、路程、NPC口径或药水冷却的麻烦",
            "他试一次，不讲大道理，只做一个玩家会做的动作",
            "马上出现掉血、少蓝、背包快满、任务进度变化或旁人误判",
            "主角付出一点代价后拿到实在收益：经验、铜币、修理、补给、任务进度或路线资格",
            "章末让读者看到优势已经滚起来，同时外人仍只看见零散动作",
        ]
    return {
        "method_card": [
            "把一章写成玩家行动，不写成作者讲解。读者要看见主角想做什么、被什么卡住、怎么试、花了什么、得了什么。",
            "先写代价，再写收获。收获要实在：任务完成、铜币到账、装备修好、药水入包、路线打开，至少兑现一项。",
            "面板、任务、装备和NPC不是装饰；它们每出现一次，都要逼主角做一个选择。",
            "苟不是不拿收益，而是不让别人看懂收益来源；读者要看见他在幕后把好处吃下去。",
            "玩家和NPC要像活在游戏里的人：旁人会排队、误判、嫌麻烦；NPC只按岗位办事。",
        ],
        "action_chain": action_chain,
        "panel_method": [
            "只弹出本场用得上的数字，例如经验、生命、法力、耐久、背包格、任务进度。",
            "提示出现后，下一句接动作或后果，不接解释。",
        ],
        "dialogue_method": [
            "对话要围绕办事、问价、组队、提醒、拒绝或误判，不要互相说设定。",
            "主角回答要像人，不要只回两个字装冷静；能说理由就说一句理由。",
            "每章至少写一轮连续问答：对方先说一句带原因或抱怨的话，主角接一句正常解释或拒绝，再由对方给出反应；不要只写口令式回答。",
            "玩家说话要像临场聊天，可以带一点催促、抱怨、试探或顺嘴提醒；NPC说话要像柜台办事，能说清价钱、数量和后果。",
        ],
        "micro_example": {
            "weak": "夜烬打开面板，发现后坡收益更高，于是决定去那里刷怪。",
            "better": "任务牌上的后坡一栏还是灰的。夜烬把背包里的毒腺数了一遍，又看了眼法杖耐久，先没往柜台前挤。旁边有人催他交清道夫，他摇头说还差一次试打，先看看蓝够不够退回来。",
        },
    }


def _game_satisfaction_loop(chapter_number: int, stage: str) -> dict[str, str]:
    if chapter_number == 1:
        return {
            "emotion_target": "读者要看到第一笔优势落袋：不是主角解释自己很稳，而是他用两只怪的异常掉落完成一项别人还在排队凑的事。",
            "core_event": "登录建号后首次打怪，触发千倍爆率，回村只办理一项小服务。",
            "obstacle": "蓝少、血掉、法杖耐久低、背包快满，窗口排队且旁人可能误判。",
            "visible_payoff": "至少兑现一项账本变化或下一步前置条件；交任务、拿铜币、修法杖、买药必须由项目账本/章节计划允许，未允许时只写材料、损耗和前置条件。",
            "outsider_misread": "旁人只能以为他运气好、路线熟、排队办了普通低级服务，不知道他只打了几只、背包还剩多少。",
            "state_change": "章末必须更新钱、背包、耐久、补给、生命/法力或下一步前置任务，读者能看出他已经领先。",
            "next_hook": "结尾落在下一次可执行动作：再刷一轮、凑够铜、买技能书、试后坡入口，不要落在抽象感慨。",
        }
    if stage == "newbie_low":
        return {
            "emotion_target": "读者要看到滚雪球：上一章的小优势被换成新的技能、装备状态、任务进度或路线资格。",
            "core_event": "围绕一个低级目标推进：补材料、交任务、修法杖、买书、试入口或完成基础命中记录。",
            "obstacle": "资源不够、蓝耗限制、排队、NPC只按规则办事、普通玩家会误判或跟风。",
            "visible_payoff": "本章至少拿到一个看得见的结果：铜币到账、技能入包、任务推进、装备修好、路线试通。",
            "outsider_misread": "外人只能看到普通散人跑腿、排队、卖几件低级材料或运气好，拼不出完整收益来源。",
            "state_change": "章末用短账本落地等级、经验、铜币、背包、耐久、补给和已完成/未完成的前置任务。",
            "next_hook": "结尾给出下一章马上能做的事，最好带一个新限制：缺蓝、缺一件材料、入口怪挡路、钱刚花光。",
        }
    return {
        "emotion_target": "读者要看到阶段推进：主角用上一阶段积累换到新的资格，但还没直接通关。",
        "core_event": "围绕导师、登记、材料、费用、入口规则或失败惩罚推进一步。",
        "obstacle": "条件卡住、费用肉疼、补给不足、队伍干扰或NPC规则不通融。",
        "visible_payoff": "拿到登记、入口线索、关键材料、补给准备或一次低风险试探结果。",
        "outsider_misread": "外人只看见他按规矩补手续，不知道他提前准备了哪些隐藏材料和路线。",
        "state_change": "章末明确资格、消耗、剩余资源和下一项缺口。",
        "next_hook": "结尾留一个必须马上处理的前置任务或风险。",
    }


def _writing_contract_for_game(story: StoryState, chapter_number: int) -> dict[str, Any]:
    level_number = _current_level_number(story)
    level = _current_level_label(story)
    stage = _game_progression_stage(level_number)
    if stage == "newbie_low":
        current_level = level or "Lv.1"
        return {
            "current_level": current_level,
            "progression_stage": stage,
            "allowed_progress": [
                "登录/建号、初始身份和武器选择" if chapter_number == 1 else "新手村任务、低级地图和基础材料账本",
                "首只低级怪验证" if chapter_number == 1 else "清道夫委托登记/提交",
                "灰狼坡、后坡入口或同级资源点试打",
                "基础火球术命中记录推进但不直接变成转职",
                "修理、药水、背包、经验和耐久账本",
            ],
            "forbidden_unlocks": [
                "10级前正式接取转职任务",
                "10级前开始职业试炼",
                "元素回廊试炼",
                "法师塔试炼",
                "主城/高阶地图",
                "公会正式追查或锁定身份",
            ],
            "scene_plan": _newbie_scene_plan(chapter_number),
            "emotional_arc": _game_emotional_arc(chapter_number, stage),
            "genre_craft": _game_genre_craft(chapter_number, stage),
            "satisfaction_loop": _game_satisfaction_loop(chapter_number, stage),
        }
    if stage == "trial_ready":
        return {
            "current_level": level,
            "progression_stage": stage,
            "allowed_progress": [
                "职业导师验看等级、材料和费用",
                "职业试炼登记或排队",
                "元素回廊前置材料核对",
                "补给、修理、技能冷却和失败后的具体损失",
                "试炼入口规则确认，但必须写清条件",
            ],
            "forbidden_unlocks": [
                "不写材料、费用、排队或失败后的具体损失就直接完成元素回廊",
                "跳过职业导师登记直接获得进阶职业",
                "无经验账本连续升级",
                "用系统提示替代全部试炼过程",
            ],
            "scene_plan": [
                {"key": "mentor_check", "goal": "职业导师核验10级、材料、费用或登记资格"},
                {"key": "cost_prepare", "goal": "补材料、修装备、买药或确认冷却，费用和背包要落账"},
                {"key": "entry_rule", "goal": "只写到试炼入口或第一道低风险规则，不白送通关"},
                {"key": "new_pressure", "goal": "给出排队、失败惩罚、竞争玩家或材料缺口"},
            ],
            "emotional_arc": _game_emotional_arc(chapter_number, stage),
            "genre_craft": _game_genre_craft(chapter_number, stage),
            "satisfaction_loop": _game_satisfaction_loop(chapter_number, stage),
        }
    return {
        "current_level": level,
        "progression_stage": stage,
        "allowed_progress": ["继承上一章账本", "只推进本章计划允许的任务、地图、装备或关系"],
        "forbidden_unlocks": ["跳过等级/材料/声望/任务条件获得高阶收益", "无铺垫转职或进入高阶地图"],
        "scene_plan": [
            {"key": "inherit", "goal": "先承接上一章状态和本章目标"},
            {"key": "pressure", "goal": "通过可见规则或服务节点形成阻力"},
            {"key": "payoff", "goal": "只兑现本章允许的阶段收益"},
            {"key": "hook", "goal": "留下下一章具体可执行目标"},
        ],
        "emotional_arc": _game_emotional_arc(chapter_number, stage),
        "genre_craft": _game_genre_craft(chapter_number, stage),
        "satisfaction_loop": _game_satisfaction_loop(chapter_number, stage),
    }


def _writing_contract(story: StoryState, chapter_number: int, is_game: bool) -> dict[str, Any]:
    if is_game:
        return _writing_contract_for_game(story, chapter_number)
    return {
        "current_level": "",
        "allowed_progress": ["承接上一章事实", "推进本章目标", "留下具体下一步"],
        "forbidden_unlocks": ["跳过因果获得重大收益", "忘记上一章关键事实"],
        "scene_plan": [],
        "emotional_arc": ["章首承接上一章情绪余波", "中段让选择付出情绪代价", "章末留下未解决的关系或处境压力"],
        "genre_craft": {},
    }


def build_chapter_seed(story: StoryState, chapter_number: int) -> dict[str, Any]:
    """Build the compact pre-writing contract that connects world simulation to prose."""
    proxy_project = _proxy_project(story)
    plugins = select_genre_plugins(proxy_project)
    plugin_ids = [plugin.plugin_id for plugin in plugins]
    explicit_ids = normalize_novel_type_ids(
        proxy_project.world_blueprint.get("genre_plugin_ids")
    )
    explicit_order = {plugin_id: index for index, plugin_id in enumerate(explicit_ids)}
    original_order = {plugin.plugin_id: index for index, plugin in enumerate(plugins)}
    prompt_plugins = sorted(
        plugins,
        key=lambda plugin: (
            (0, explicit_order[plugin.plugin_id])
            if plugin.plugin_id in explicit_order
            else (2, original_order[plugin.plugin_id])
            if plugin.plugin_id == "generic_webnovel"
            else (1, original_order[plugin.plugin_id])
        ),
    )
    rulebook = merge_plugin_rulebooks(prompt_plugins)
    is_game = "game_webnovel" in plugin_ids
    contract = _contract_for_game(chapter_number) if is_game else _generic_contract()
    return {
        "schema_version": "chapter-seed/v1",
        "chapter_number": chapter_number,
        "phase": _phase(chapter_number, is_game=is_game),
        "genre_plugins": plugin_ids,
        "core_promises": compact_list(
            [promise for plugin in prompt_plugins for promise in plugin.core_promises],
            max_items=6,
            item_chars=150,
        ),
        "rulebook": {
            key: compact_list(value, max_items=5, item_chars=170)
            for key, value in rulebook.items()
        },
        "current_state": story.progression_ledger or {},
        "continuity": _latest_continuity(story),
        "chapter_contract": contract,
        "writing_contract": _writing_contract(story, chapter_number, is_game),
        "simulation_axes": _simulation_axes(story, plugin_ids),
        "simulation_variant": _simulation_variant(story, chapter_number),
        "simulation_blueprint": plugin_simulation_blueprint(plugins),
        "longform_constraints": _longform_constraints(story),
        "world_facts": compact_list(story.world_facts, max_items=18, item_chars=180),
        "author_constraints": compact_list(story.author_constraints, max_items=12, item_chars=180),
    }
