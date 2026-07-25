from __future__ import annotations

from typing import Any

from packages.story_core.agent_base import LONGFORM_FACT_PREFIXES, compact_list, compact_text
from packages.story_core.chapter_governance import build_chapter_governance, governance_quality_gate
from packages.story_core.dual_state import project_character_for_scene, scene_kind_for_cards
from packages.story_core.memory import build_character_cards
from packages.story_core.simulation import is_game_story
from packages.story_core.writing_learning import learning_snapshot
from packages.story_core.web_game_economy import (
    normalize_legacy_economy_prompt_value,
    opening_market_exchange_flow_lines,
)
from packages.story_core.writing_taskbook import first_chapter_whole_body_contract


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
        state_delta = raw.get("state_delta") if isinstance(raw.get("state_delta"), dict) else {}
        result.append(
            {
                "index": index,
                "id": str(raw.get("template_id") or raw.get("scene_id") or f"scene-{index}"),
                "location": str(raw.get("location") or "当前场景"),
                "pov": str(raw.get("pov") or ""),
                "purpose": compact_text(str(raw.get("purpose") or "推进本章目标"), 120),
                "conflict": compact_text(str(raw.get("conflict") or "形成场景阻力"), 120),
                "must_show": _as_list(raw.get("must_show"), max_items=8, item_chars=80),
                "avoid": _as_list(raw.get("must_not_explain") or raw.get("avoid"), max_items=8, item_chars=80),
                "ending_pressure": compact_text(str(raw.get("ending_pressure") or ""), 160),
                "state_delta": state_delta,
                "scene_contract": raw.get("scene_contract") if isinstance(raw.get("scene_contract"), dict) else {},
                "sensory_anchors": _as_list(raw.get("sensory_anchors"), max_items=4, item_chars=40),
                "subtext": compact_text(str(raw.get("subtext") or ""), 120),
                "rhythm_hint": compact_text(str(raw.get("rhythm_hint") or ""), 80),
            }
        )
        if not result[-1]["scene_contract"]:
            result[-1].pop("scene_contract", None)
        for key in ("line", "scene_line"):
            if raw.get(key) not in (None, ""):
                result[-1][key] = str(raw[key])
    return result


def _packet_scene_kind(scene_cards: list[dict[str, Any]], *, is_game_story: bool) -> str:
    return scene_kind_for_cards(scene_cards, is_game_story=is_game_story)


def _character_model_payload(character: Any) -> dict[str, Any]:
    if hasattr(character, "model_dump"):
        try:
            payload = character.model_dump(mode="json")
        except TypeError:
            payload = character.model_dump()
        return payload if isinstance(payload, dict) else {}
    return dict(character) if isinstance(character, dict) else {}


def _project_packet_character_cards(story: Any, cards: list[dict[str, Any]], *, scene_kind: str) -> list[dict[str, Any]]:
    raw_cards = [_character_model_payload(character) for character in getattr(story, "characters", []) or []]
    by_name = {str(card.get("name") or "").strip(): card for card in raw_cards if str(card.get("name") or "").strip()}
    by_game_id = {str(card.get("game_id") or "").strip(): card for card in raw_cards if str(card.get("game_id") or "").strip()}
    projected_cards: list[dict[str, Any]] = []
    for card in cards:
        identity = card.get("identity") if isinstance(card.get("identity"), dict) else {}
        raw = by_name.get(str(identity.get("name") or card.get("name") or "").strip())
        if raw is None:
            raw = by_game_id.get(str(identity.get("game_id") or "").strip(), {})
        source = dict(card)
        for key in ("real_state", "game_state", "game_panel", "secrets", "story_drive", "relationship_notes"):
            if key in raw:
                source[key] = raw[key]
        projected = project_character_for_scene(source, scene_kind=scene_kind)
        projected_cards.append(projected)
    return projected_cards


def _extract_scene_contracts(scene_cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    contracts: list[dict[str, Any]] = []
    for card in scene_cards:
        contract = card.get("scene_contract") if isinstance(card.get("scene_contract"), dict) else {}
        if contract:
            contracts.append(contract)
    return contracts


def _extract_systemic_simulation(scene_cards: list[dict[str, Any]]) -> dict[str, Any]:
    for card in scene_cards:
        state_delta = card.get("state_delta") if isinstance(card.get("state_delta"), dict) else {}
        game_world = state_delta.get("game_world_simulation") if isinstance(state_delta.get("game_world_simulation"), dict) else {}
        systemic = game_world.get("systemic_simulation") if isinstance(game_world.get("systemic_simulation"), dict) else {}
        if not systemic:
            continue
        ledger_delta = systemic.get("ledger_delta") if isinstance(systemic.get("ledger_delta"), dict) else {}
        visibility_layers = systemic.get("visibility_layers") if isinstance(systemic.get("visibility_layers"), dict) else {}
        return {
            "schema_version": systemic.get("schema_version", "systemic-simulation/v1"),
            "rules_fired": _as_list(systemic.get("rules_fired"), max_items=8, item_chars=80),
            "causal_chain": _as_list(systemic.get("causal_chain"), max_items=8, item_chars=120),
            "ledger_delta": ledger_delta,
            "visibility_layers": {
                "private": _as_list(visibility_layers.get("private"), max_items=5, item_chars=160),
                "public": _as_list(visibility_layers.get("public"), max_items=5, item_chars=160),
                "npc": _as_list(visibility_layers.get("npc"), max_items=5, item_chars=160),
                "guild": _as_list(visibility_layers.get("guild"), max_items=5, item_chars=160),
            },
            "final_state": systemic.get("final_state") if isinstance(systemic.get("final_state"), dict) else {},
        }
    return {}


def _default_first_chapter_scenes_game() -> list[dict[str, Any]]:
    return [
        {
            "index": 1,
            "id": "setup",
            "location": "现实出租屋",
            "pov": "",
            "purpose": "建立主角的现实压力、职业经验和进入游戏的理由。",
            "conflict": "房租与欠费逼近，但他不能靠情绪解决，只能寻找一条可验证的路径。",
            "must_show": ["催租/欠费", "旧头盔或登录入口", "前外包经验", "克制、会算账的行为细节"],
            "avoid": ["百科式介绍游戏", "突然获得金手指", "提前写交易行成交或公会追查"],
            "ending_pressure": "现实姓名与游戏ID必须分层。",
            "state_delta": {},
            "sensory_anchors": ["楼道里的潮味或楼下噪音", "手边一个具体物件的触感（账单/旧头盔/凉茶杯）", "光线偏暗的色温"],
            "subtext": "表面是登录游戏，里子是不肯承认现实已经压过来了。",
            "rhythm_hint": "breathing：节奏放慢，让现实的重量先落在主角身上一两拍。",
        },
        {
            "index": 2,
            "id": "login",
            "location": "角色创建界面 / 新手村入口",
            "pov": "",
            "purpose": "完成登录、游戏ID、统一初始身份、武器/技能选择和简短角色面板。",
            "conflict": "开局所有玩家都是见习冒险者，夜烬只是选了法杖和基础火球术，前期容错低但能拉开距离。",
            "must_show": ["游戏ID", "见习冒险者（未转职）", "Lv.1", "经验0/100", "生命/法力/基础属性", "新手武器/粗布衣"],
            "avoid": ["隐藏职业", "开局满级", "多NPC同时登场"],
            "ending_pressure": "现实段落用现实姓名，游戏内优先用游戏ID。",
            "state_delta": {},
            "sensory_anchors": ["视野里浮动的光面板/虚拟UI的微光", "选项切换时的细微反馈音", "指尖在虚拟按钮上的停留与犹豫"],
            "subtext": "表面是选法杖和基础技能，里子是给自己留一条可撤的退路。",
            "rhythm_hint": "紧凑推进：选项→停顿→选项，呈现计算与犹豫。",
        },
        {
            "index": 3,
            "id": "validation",
            "location": "新手村外刷怪点",
            "pov": "",
            "purpose": "通过一次低级战斗验证掉落异常，同时展示代价和克制。",
            "conflict": "主角必须确认异常是否真实，但不能表现得不像新手。",
            "must_show": ["低级怪物", "基础法术", "法力消耗/受伤/走位", "首杀经验", "材料掉落"],
            "avoid": ["全程法杖近战", "一次掉落引发全服市场风暴"],
            "ending_pressure": "怪物类型前后一致；隐藏优势只做首次领先验证，重点是前置任务、装备条件或技能条件被压短。",
            "state_delta": {},
            "sensory_anchors": ["怪物倒地时一个具体的声音/材料落地的反光", "主角呼吸或心跳的一次明显变化", "环境光在掉落物上的折射"],
            "subtext": "表面是验证爆率，里子是怕这只是个错觉。",
            "rhythm_hint": "dense：动作密度高，连续动作推进，给读者首次兑现的爽感。",
        },
        {
            "index": 4,
            "id": "npc-landing",
            "location": "新手村服务点",
            "pov": "",
            "purpose": "只露出服务点、队伍或前置任务，让下一章成长目标清楚。",
            "conflict": "材料已经接近前置任务要求，但主角需要先确认怎样把爆率优势转成经验、装备或技能路线。",
            "must_show": ["服务点入口", "前置任务", "清道夫委托或价牌", "补给价格", "币制轻量露出"],
            "avoid": ["实际寄售成交", "公会锁定身份", "交易行精确百分比预测"],
            "ending_pressure": "单卖价和任务奖励要解释清楚；金币只是大额单位，新手村主要用铜币。",
            "state_delta": {},
            "sensory_anchors": ["NPC柜台/工位上一个反复出现的物件", "NPC一个标志性的小动作（贴标签/擦杯/翻账）", "店里某个底色气味（药/油/纸）"],
            "subtext": "表面是问价或交任务，里子是观察NPC会不会记住自己。",
            "rhythm_hint": "breathing：对话留白，NPC的口吻和细节先于内容信息。",
        },
    ]


def _default_first_chapter_scenes_generic() -> list[dict[str, Any]]:
    return [
        {
            "index": 1,
            "id": "hook",
            "location": "主角当下所处空间",
            "pov": "",
            "purpose": "用一个具体事件抓住读者，建立主角处境与即时压力。",
            "conflict": "主角必须立刻面对一个无法回避的难题或诱惑。",
            "must_show": ["主角当下处境", "立刻冲击的事件", "情绪与本能反应", "本章目标的雏形"],
            "avoid": ["大段背景说明", "直接揭穿核心秘密", "无关人物群像"],
            "ending_pressure": "把第一幕的张力推到必须做选择的位置。",
            "state_delta": {},
            "sensory_anchors": ["主角当下能听到的一个具体声音", "环境里一个反复出现的气味或光线", "身体上一个具体的触感或不适"],
            "subtext": "表面是被事件击中，里子是某件不愿承认的旧事被重新触发。",
            "rhythm_hint": "breathing：用慢一拍的节奏让事件落地，再切入主角反应。",
        },
        {
            "index": 2,
            "id": "stakes",
            "location": "推进所需的关键场景",
            "pov": "",
            "purpose": "通过一次行动或对话放大代价，让读者明白主角的目标和风险。",
            "conflict": "主角的选择必须付出资源、关系或情绪上的真实代价。",
            "must_show": ["主角的目标", "外部阻力", "选择产生的代价", "关系或资源的可见变化"],
            "avoid": ["让目标轻易达成", "把冲突推给配角解决", "用旁白替代场景"],
            "ending_pressure": "让阻力升级，逼出更困难的下一步。",
            "state_delta": {},
            "sensory_anchors": ["对手身上一个细节（口吻、表情、配饰、节奏）", "环境里能加强压迫感的一处声/光/触", "主角身体一个紧张反应（手汗、屏息、肩线）"],
            "subtext": "表面在博弈眼前的事，里子是双方在试探彼此的底牌。",
            "rhythm_hint": "紧凑推进：对话和动作交错，呈现拉锯。",
        },
        {
            "index": 3,
            "id": "turn",
            "location": "本章高潮承载的场景",
            "pov": "",
            "purpose": "完成本章核心冲突的一次小高潮或反转。",
            "conflict": "主角必须在压力下做出关键决定，并承担直接后果。",
            "must_show": ["关键反转或决断", "对手或环境的反应", "主角立场的微调", "本章兑现的承诺"],
            "avoid": ["巧合解决冲突", "强行降智配合主角", "回避承诺过的兑现"],
            "ending_pressure": "兑现本章承诺的同时留下更大的疑问。",
            "state_delta": {},
            "sensory_anchors": ["决断瞬间一个非语言细节（眼神、动作、停顿）", "环境里一处突然的安静或突兀的声响", "身体上一个不可逆的小变化（伤痕、出汗、心跳被听见）"],
            "subtext": "表面是做选择，里子是主角认下了某种代价。",
            "rhythm_hint": "dense：核心反转处节奏密集，反转之后给一两拍呼吸。",
        },
        {
            "index": 4,
            "id": "hook-out",
            "location": "章末收束的过渡场景",
            "pov": "",
            "purpose": "把本章结果转化为下一章的悬念与目标。",
            "conflict": "主角面对新出现的威胁、机遇或线索，必须接住。",
            "must_show": ["本章结果的余波", "新出现的悬念或线索", "主角下一步意图", "情绪或关系的小变化"],
            "avoid": ["突然转换主角", "提前剧透核心反转", "用说明句结尾"],
            "ending_pressure": "留下一个让读者想立刻翻下一章的钩子。",
            "state_delta": {},
            "sensory_anchors": ["章末环境的一处余响（脚步、灯熄、风停）", "主角身体上一个未完成的动作", "新出现的物件/讯息留下的具体痕迹"],
            "subtext": "表面是收束，里子是新的不安已经在角落生根。",
            "rhythm_hint": "紧凑收束，结尾留半口气。",
        },
    ]


def _default_first_chapter_scenes(game_genre: bool) -> list[dict[str, Any]]:
    return _default_first_chapter_scenes_game() if game_genre else _default_first_chapter_scenes_generic()


def _hard_locks(game_genre: bool, target_chapter: int, *, first_chapter_trade: bool = False) -> list[str]:
    if game_genre:
        locks = [
            "现实姓名和游戏ID必须分层；现实段落可称现实姓名，游戏内行动优先称游戏ID。",
            "开局玩家初始身份统一为见习冒险者（未转职）；主角只是选择法杖和基础火球术，战斗核心围绕已确立的武器/法术和法力消耗。",
            "背包按同类道具堆叠计算格子，灰狼毒腺×8和粗糙狼皮×7只占两个材料格，章末背包应写2/20或占用两个材料格。",
            "新手阶段主要用铜币；币制是 1金币=100银币=10000铜币，金币只作为大额单位轻量露出。",
            "低级材料不会一次扰乱市场；交易行、公会、商人只能看到价格波动、批次、时间戳等弱线索。",
        ]
        if target_chapter == 1:
            locks.append("第一章聚焦现实压力、登录建号、职业面板、首杀验证、爆率领先感和章末下一步。")
            locks.append(
                "第一章按顺序完成：" + " ".join(opening_market_exchange_flow_lines()) + " 禁止公会正面追查和论坛爆帖。"
                if first_chapter_trade
                else "第一章禁止交易行实际成交、官方兑换、现实账户到账、公会正面追查和论坛爆帖。"
            )
            locks.append("怪物类型前后一致。")
        return locks

    locks = [
        "人物姓名、关系、身份和已建立的事实必须前后一致，不要中途改写。",
        "本章必须形成可感知的推进：收益、反转、关系变化、谜团进展或压力升级中至少一项。",
        "外部反应必须基于已暴露的可见信息逐步逼近，不能让世界全知主角隐情。",
        "数值、时间、地点、道具必须可追踪，回写到下一章的承接信息里。",
    ]
    if target_chapter == 1:
        locks.extend(
            [
                "第一章只聚焦：开场钩子、主角处境、本章核心目标、一次小高潮和章末新压力。",
                "第一章避免一次性堆设定、世界史、势力史或多地点巡礼。",
            ]
        )
    return locks


def _style_rules(game_genre: bool) -> list[str]:
    base = [
        "句子按场面自然长短；人物对话要像正常说话，不能把理由压成几个词。",
        "人物行动、选择和结果要接得上，不用抽象总结代替正在发生的事情。",
        "每个场景都要有目标、阻力、结果或危机；对话不能省略必要的连接词、原因、条件和态度。",
        "章节标题贴近番茄常见短章名：4到10字左右，优先用具体事件、地点、道具、关系或冲突；不要写营销句、说明句或后台账本。",
        "用动作、对话、环境细节表现设定，不要停下来写说明书。",
        "人物说话要符合身份、关系和场合，配角有自己的立场和口吻，但不要全知。",
    ]
    if game_genre:
        base.extend(
            [
                "数值必须可追踪：等级、经验、货币、背包、装备、任务奖励前后一致。",
                "奖励差异必须解释清楚：单卖材料价、任务打包价、声望或村务补贴不能混在一起。",
                "前10章节奏要快，连续两章不能只拿线索不给成长；下一章至少兑现一个可见成长：等级、经验大幅推进、技能、装备、货币补给或任务权限。",
            ]
        )
    else:
        base.append("关键事实可追踪：时间、地点、人物、物品、关系状态前后一致。")
    return base


def _title_examples(game_genre: bool) -> list[str]:
    if game_genre:
        return ["灰烬村登录", "见习冒险者", "清道夫委托", "灰狼坡", "回村补给"]
    return ["旧楼回信", "雨夜来客", "未送出的礼物", "第三次约见", "门口的影子"]


def _previous_chapter_summary(story: Any, target_chapter: int) -> str:
    if target_chapter <= 1:
        return ""
    summaries = getattr(story, "chapter_summaries", []) or []
    for entry in summaries:
        chapter_no = getattr(entry, "chapter_number", None)
        if isinstance(entry, dict):
            chapter_no = entry.get("chapter_number")
            summary_text = str(entry.get("summary") or "")
        else:
            summary_text = str(getattr(entry, "summary", "") or "")
        if chapter_no == target_chapter - 1:
            return summary_text
    return ""


def _event_plan_summary(bundle: Any) -> dict[str, Any]:
    plan = getattr(bundle, "event_plan", None)
    if not isinstance(plan, dict):
        return {}
    return {
        "chapter_title": plan.get("chapter_title") or getattr(bundle, "chapter_title", ""),
        "turn": compact_text(str(plan.get("turn") or ""), 180),
        "pivot": compact_text(str(plan.get("pivot") or ""), 180),
        "stakes": compact_text(str(plan.get("stakes") or ""), 180),
        "next_focus": compact_text(str(plan.get("next_focus") or ""), 180),
        "next_chapter_outline": compact_text(str(getattr(bundle, "next_outline", "") or ""), 180),
        "ordered_actions": _as_list(plan.get("ordered_actions"), max_items=8, item_chars=100),
        "wow_beat": compact_text(str(plan.get("wow_beat") or ""), 240),
        "escalation_break": compact_text(str(plan.get("escalation_break") or ""), 220),
        "core_mystery_reinforcement": compact_text(str(plan.get("core_mystery_reinforcement") or ""), 220),
        "explicit_chapter_end_hook": compact_text(str(plan.get("explicit_chapter_end_hook") or ""), 240),
        "reality_game_bridge": compact_text(str(plan.get("reality_game_bridge") or ""), 240),
    }


def _latest_panel_locks(story: Any, *, game_genre: bool) -> dict[str, Any]:
    from packages.story_core.agent_base import find_protagonist
    protagonist = find_protagonist(story)
    if protagonist is None:
        return {}
    panel = getattr(protagonist, "game_panel", None)
    panel_data = panel.model_dump() if hasattr(panel, "model_dump") else {}
    profile = getattr(protagonist, "performance_profile", None)
    voice = getattr(profile, "voice", None) if profile is not None else None
    voice_dict = voice.model_dump() if hasattr(voice, "model_dump") else {}
    locks: dict[str, Any] = {
        "real_name": getattr(protagonist, "name", ""),
        "role": getattr(protagonist, "role", ""),
        "goals": _as_list(getattr(protagonist, "goals", []), max_items=6, item_chars=80),
        "location": compact_text(str(getattr(protagonist, "location", "")), 120),
        "voice": voice_dict,
    }
    if game_genre:
        locks["game_id"] = getattr(protagonist, "game_id", "") or panel_data.get("game_id", "")
        locks["game_panel"] = {
            key: value for key, value in panel_data.items() if value not in (None, "", [], {})
        }
    return locks


def prose_renderer_contract() -> dict[str, Any]:
    """Declare how a prose skill may consume the writing packet.

    The renderer is deliberately downstream of simulation and review. It should
    turn approved scene cards into chapter prose, not invent new world logic or
    echo internal planning language into the body.
    """

    return {
        "skill": "chinese-novelist",
        "role": "prose_renderer_only",
        "use_for": [
            "render approved scene cards into Chinese webnovel prose",
            "show facts through action, dialogue, visible objects, local procedures, and physical constraints",
            "polish rhythm and chapter hook after continuity facts are fixed",
        ],
        "do_not_use_for": [
            "world_simulation",
            "economy_rules",
            "continuity_decisions",
            "review_verdicts",
        ],
        "input_boundary": {
            "allowed": [
                "chapter_number",
                "target_chars",
                "protagonist",
                "governance",
                "event_plan",
                "plot_simulation",
                "longform_plot_contract",
                "scene_cards",
                "hard_locks",
                "style_rules",
                "continuity",
            ],
            "avoid": [
                "raw project dumps",
                "review internals",
                "system rulebooks",
                "backend-only explanation fields",
            ],
        },
        "body_contract": [
            "write chapter body only",
            "do not output analysis, plans, rule explanations, or reviewer language",
            "do not replace scenes with abstract conclusions",
            "keep numbers, names, objects, places, and visible state traceable to the packet",
            "consume every scene_contract.visible_consequences item on page; if it is not visible to a reader, the scene is unfinished",
            "keep sentences complete and make each action, reason, and consequence easy to follow",
            "make dialogue fit the speaker, relationship, and situation instead of compressing it into command fragments",
        ],
    }


def build_codex_writing_packet(story: Any, bundle: Any | None = None, *, chapter_number: int | None = None) -> dict[str, Any]:
    """Build a compact handoff packet for Codex/manual prose drafting.

    The packet is intentionally not a prompt for a normal LLM. It is a contract:
    simulation and ledger facts stay structured, while the final prose can be
    written by Codex or a human without dragging rule text into the chapter.
    """

    target_chapter = int(chapter_number or getattr(bundle, "chapter_number", None) or (getattr(story, "current_chapter", 0) + 1))
    game_genre = is_game_story(story)
    raw_world_facts = getattr(story, "world_facts", []) or []
    world_facts = _as_list(
        [fact for fact in raw_world_facts if not str(fact).startswith(LONGFORM_FACT_PREFIXES)],
        max_items=28,
        item_chars=140,
    )
    author_constraints = _as_list(getattr(story, "author_constraints", []), max_items=18, item_chars=160)
    writing_learning = learning_snapshot(getattr(story, "writing_lessons", []), max_items=8)
    existing_body = getattr(bundle, "body", "") if bundle is not None else ""
    scene_cards = _extract_scene_cards(bundle) if bundle is not None else []
    simulation_plan = getattr(bundle, "simulation_plan", {}) if bundle is not None else {}
    plot_simulation = (
        simulation_plan.get("plot_simulation")
        if isinstance(simulation_plan, dict) and isinstance(simulation_plan.get("plot_simulation"), dict)
        else {}
    )
    longform_plot_contract = (
        simulation_plan.get("longform_plot_contract")
        if isinstance(simulation_plan, dict) and isinstance(simulation_plan.get("longform_plot_contract"), dict)
        else {}
    )
    systemic_simulation = _extract_systemic_simulation(scene_cards)
    scene_contracts = _extract_scene_contracts(scene_cards)
    if target_chapter == 1 and not scene_cards:
        scene_cards = _default_first_chapter_scenes(game_genre)
        scene_contracts = _extract_scene_contracts(scene_cards)

    scene_kind = _packet_scene_kind(scene_cards, is_game_story=game_genre)
    protagonist_locks = _latest_panel_locks(story, game_genre=game_genre)
    character_cards = _project_packet_character_cards(
        story,
        build_character_cards(story),
        scene_kind=scene_kind,
    )
    governance = build_chapter_governance(story, bundle, chapter_number=target_chapter)
    governance_intent = governance.get("chapter_intent") if isinstance(governance.get("chapter_intent"), dict) else {}
    hard_locks = _hard_locks(
        game_genre,
        target_chapter,
        first_chapter_trade=bool(governance_intent.get("first_chapter_trade_authorized")),
    )
    real_name = str(protagonist_locks.get("real_name") or "").strip()
    game_id = str(protagonist_locks.get("game_id") or "").strip()
    if game_genre and (real_name or game_id):
        hard_locks.insert(0, f"现实姓名：{real_name or '未定'}；游戏ID：{game_id or '未定'}；现实段落和游戏内称呼必须分层。")
    elif real_name:
        hard_locks.insert(0, f"主角姓名：{real_name}；通篇称呼必须一致。")

    style_rules = _style_rules(game_genre)
    governance_gate = governance_quality_gate(governance)

    packet = {
        "schema_version": "codex-writing-packet/v1",
        "chapter_number": target_chapter,
        "scene_kind": scene_kind,
        "chapter_title": getattr(bundle, "chapter_title", "") if bundle is not None else "",
        "title_contract": {
            "style": "tomato_concrete_short_title",
            "rules": [
                "4到10字左右，像真实章节目录，不像广告文案",
                "优先使用具体事件、地点、道具、身份、人物关系或当章冲突",
                "可以有悬念，但不要用“他/别人/没人知道”这类营销句式",
                "避免材料数量、账目明细、抽象核算、后台规则和说明句",
            ],
            "examples": _title_examples(game_genre),
        },
        "goal": "把结构化推演写成读者可读的网文正文，而不是继续堆规则。",
        "target_chars": {"min": 4200, "max": 5500},
        "story": {
            "story_id": getattr(story, "story_id", ""),
            "outline": compact_text(str(getattr(story, "outline", "")), 500),
            "genre": getattr(story, "genre", ""),
            "style": getattr(story, "style", ""),
            "current_chapter": getattr(story, "current_chapter", 0),
        },
        "protagonist": protagonist_locks,
        "character_cards": character_cards,
        "protagonist_card": next(
            (
                card
                for card in character_cards
                if card.get("identity", {}).get("role") in {"protagonist", "主角"}
                or card.get("identity", {}).get("name") == real_name
                or card.get("identity", {}).get("game_id") == game_id
            ),
            {},
        ),
        "prose_renderer": prose_renderer_contract(),
        "whole_chapter_contract": first_chapter_whole_body_contract(game_genre=game_genre) if target_chapter == 1 else {},
        "governance": governance,
        "governance_gate": governance_gate,
        "event_plan": _event_plan_summary(bundle) if bundle is not None else {},
        "plot_simulation": plot_simulation,
        "longform_plot_contract": longform_plot_contract,
        "systemic_simulation": systemic_simulation,
        "scene_contracts": scene_contracts,
        "scene_cards": scene_cards,
        "hard_locks": compact_list(hard_locks, max_items=16, item_chars=160),
        "style_rules": style_rules,
        "writing_learning": writing_learning,
        "author_constraints": author_constraints,
        "world_facts": world_facts,
        "continuity": {
            "previous_summary": compact_text(_previous_chapter_summary(story, target_chapter), 260),
            "existing_body_chars": _chapter_body_chars(existing_body),
        },
        "submission_contract": {
            "mode": "auto_generation_only",
            "note": "Manual draft submission is disabled. Use continue_generation or agent-revise for chapter progression.",
        },
    }
    return normalize_legacy_economy_prompt_value(
        packet,
        game_context=game_genre,
        chapter_number=target_chapter,
    )
