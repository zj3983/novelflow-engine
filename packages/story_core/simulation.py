from __future__ import annotations

from typing import Any

from packages.story_core.agent_base import LONGFORM_FACT_PREFIXES
from packages.story_core.chapter_direction import normalize_chapter_direction_choice
from packages.story_core.genre_plugins import is_game_genre
from packages.story_core.models import CharacterState, ChapterSimulationPlan, StoryState
from packages.story_core.novel_type_catalog import normalize_novel_type_id
from packages.story_core.plot_contract import build_longform_plot_contract
from packages.story_core.web_game_author_craft import build_web_game_author_craft, build_web_game_director_card
from packages.story_core.world_pulse import visibility_inbox_for_chapter


def is_game_story(story: StoryState) -> bool:
    """Detect whether a story is game-themed, using the unified keyword set."""
    explicit_genre = normalize_novel_type_id(story.genre)
    if explicit_genre:
        return explicit_genre == "game_webnovel"
    haystack = " ".join([story.genre, story.style, story.outline, *story.world_facts])
    return is_game_genre(haystack)


def _compact_list(items: Any, *, limit: int = 5, chars: int = 120) -> list[str]:
    if not isinstance(items, list):
        return []
    result: list[str] = []
    for item in items:
        text = str(item).strip()
        if not text:
            continue
        result.append(text[:chars])
        if len(result) >= limit:
            break
    return result


def _lead_character(story: StoryState) -> CharacterState | None:
    for character in story.characters:
        if character.role in {"protagonist", "主角"}:
            return character
    return story.characters[0] if story.characters else None


def _character_goal(character: CharacterState) -> str:
    return character.goals[0] if character.goals else "推进当前主线"


def _longform_constraints(story: StoryState, chapter_seed: dict) -> list[str]:
    seeded = chapter_seed.get("longform_constraints")
    if isinstance(seeded, list) and seeded:
        return _compact_list(seeded, limit=18, chars=220)
    return _compact_list(
        [fact for fact in story.world_facts if fact.startswith(LONGFORM_FACT_PREFIXES)],
        limit=18,
        chars=220,
    )


def _default_performance(character: CharacterState, *, game_story: bool) -> dict:
    profile = character.performance_profile
    goal = _character_goal(character)
    risk_posture = profile.risk_posture
    if not risk_posture and character.role in {"protagonist", "主角"} and game_story:
        risk_posture = (
            "低调验证优势，避免一次性暴露收益、坐标、现实身份和隐藏天赋。"
            "每次行动前计算成本、撤退路线和背包容量，不贪心、不主动接触陌生人。"
        )
    elif not risk_posture:
        risk_posture = "围绕自身目标行动，不为推动剧情突然降智。"

    return {
        "name": character.name,
        "role": character.role,
        "goal": goal,
        "speech_style": profile.speech_style or "说话方式需要和身份、压力、关系一致。",
        "action_style": profile.action_style or "行动要体现目标、误判、底线和当章压力。",
        "risk_posture": risk_posture,
        "decision_rules": profile.decision_rules
        or [
            "先根据自己知道的信息判断，再行动。",
            "不能使用角色不可见的信息。",
        ],
        "reveal_limits": profile.reveal_limits
        or [
            "不主动解释全部设定。",
            "秘密只能通过可观察痕迹逐步暴露。",
        ],
        "voice": _voice_dict(character),
    }


def _voice_dict(character: CharacterState) -> dict:
    """Project a character's voice signature for the writer prompt.

    Empty fields are kept (not omitted) so the writer prompt always shows the
    full slot list — an empty signature_phrases is itself a signal that this
    character has not yet earned a catchphrase.
    """
    voice = character.performance_profile.voice
    return {
        "signature_phrases": list(voice.signature_phrases),
        "lexicon": list(voice.lexicon),
        "taboo": list(voice.taboo),
        "sentence_rhythm": voice.sentence_rhythm,
        "self_reference": voice.self_reference,
        "subtext_habit": voice.subtext_habit,
    }


def _default_npc_boundary(character: CharacterState) -> dict | None:
    role_text = f"{character.role} {character.npc_profile.service_role}".lower()
    is_npc = "npc" in role_text or "村长" in character.name or "导师" in character.name or "管理员" in character.name
    profile = character.npc_profile
    if not is_npc and not any(
        [profile.service_role, profile.authority_scope, profile.information_limits, profile.incentives, profile.interaction_rules]
    ):
        return None
    return {
        "name": character.name,
        "service_role": profile.service_role or "提供有限服务或任务反馈的世界节点。",
        "authority_scope": profile.authority_scope
        or [
            "只能处理本职范围内的任务、交易、登记、修理、教学或情报反馈。",
            "不能替主角开后门，不能直接送核心资源。",
        ],
        "information_limits": profile.information_limits
        or [
            "只能知道系统记录、公开交易、玩家可见行为或自身岗位能接触的信息。",
            "不能知道主角现实身份、隐藏天赋、完整坐标和未公开意图。",
        ],
        "incentives": profile.incentives or ["维护岗位规则、声望、库存、任务秩序或村庄安全。"],
        "interaction_rules": profile.interaction_rules
        or [
            "出场时必须通过服务、价格、前置条件、口吻或信息边界影响主角选择。",
        ],
    }


def _game_visibility_rules() -> list[str]:
    return [
        "交易行低级材料匿名上架只能暴露价格、数量、批次和时间戳等弱线索。",
        "十几个低级材料、几个铜币或十几枚铜币的小额交易属于新手村正常噪音，不触发交易行检查、异常记录、商人盯人或公会注意。",
        "大型服务器会吞掉低级材料波动；旁人看到少量高掉落，最多理解为运气好、组队效率高或刷怪路线熟。",
        "公会只能通过连续重复模式、明显超量出货、稀有物、资源点目击、NPC任务异常或多源信息汇总逐步逼近。",
        "单次小额掉落不能扰乱全服市场，也不能直接锁定主角坐标、现实身份、刷怪点或隐藏天赋。",
    ]


def _game_economy_rules() -> list[str]:
    return [
        "新手阶段收益优先使用铜币、银币、材料和询价，避免无依据写现实货币汇率。",
        "小额收益的主要作用是缩短前置任务、装备条件、技能条件和路线条件；耐久、补给、背包容量只是节奏摩擦，不是主线焦点。",
        "只有大额或重复收益才需要拆单、考虑手续费、买家来源、压价、追踪和信誉风险。",
        "外部反应应按规模递进：小额低级材料是服务器噪音；多章连续领先、稀有物、榜单、资源点目击或多源叠加后，才允许商人、玩家势力或论坛升级反应。",
    ]


def _game_required_beats(chapter_number: int) -> list[str]:
    if chapter_number == 1:
        return [
            "现实入口：说明主角现实职业/技能来源/压力，不只写缺钱。",
            "登录建号：写出游戏ID、职业选择和第一版角色面板，面板必须包含生命/法力、主武器或基础技能，不展开扩展属性。",
            "首次验证：用低级怪或任务反馈验证千倍爆率，让读者看到主角会比普通玩家更快凑齐前置任务或装备条件。",
            "交易行弱钩子：交易行只作背景入口或路牌，章末主钩子落在下一步任务、装备、技能或路线领先。",
            "大型游戏噪音：本章不出现检查、异常记录、商人盯人或公会注意，旁人最多觉得他运气好。",
        ]
    if chapter_number == 2:
        return [
            "继承第一章价格、背包、装备、经验和任务状态。",
            "通过千倍爆率更快完成任务、修理装备、购买补给或触达新路线，写出相对普通玩家的领先。",
            "让外部世界继续把低级收益当普通运气或新手噪音，不产生正式追查。",
        ]
    return [
        "继承前文账本和角色表演状态。",
        "让收益、代价、任务、装备或关系至少推进一项。",
        "把新规则写成场景反应，不写成百科说明。",
    ]


def _game_forbidden_moves(chapter_number: int) -> list[str]:
    moves = [
        "禁止让NPC全知全能或无理由送核心资源。",
        "禁止把规则直接写成说明书列表。",
        "禁止改写已建立的职业、装备、价格、背包和货币状态。",
        "禁止把低级材料单次交易写成扰乱全服市场。",
        "禁止交易行直接暴露现实身份、坐标、隐藏天赋或精确刷怪点。",
    ]
    if chapter_number == 1:
        moves.extend(
            [
                "第一章禁止完整公会追杀、反派正面登场和多NPC连续巡礼。",
                "第一章禁止开场直接给出完整隐藏面板，必须先有触发或验证过程。",
            ]
        )
    return moves


def _game_director_event_plan(event_plan: dict[str, Any], chapter_number: int) -> dict[str, Any]:
    enriched = dict(event_plan)
    if chapter_number != 1:
        return enriched

    enriched.setdefault(
        "wow_beat",
        (
            "wow_beat: 必须让千倍爆率至少露一次可见马脚。不要只写成2-8倍收益；"
            "用低概率额外掉落、非基准稀有材料、或系统统计异常兑现一次读者能算出来的'哇'时刻，"
            "并让读者明白这会让夜烬比普通玩家更快完成下一道前置任务或装备条件。"
        ),
    )
    enriched.setdefault(
        "escalation_break",
        (
            "连续刷怪/验证不能平均重复；至少一段发生质变事件，例如武器耐久骤降、怪物反扑、"
            "路线被迫改变、或掉落物类型异常，让战斗节奏从重复动作升级为决策。"
        ),
    )
    enriched.setdefault(
        "core_mystery_reinforcement",
        (
            "混沌之种不能只在登录界面闪过；章内或章末必须再给一次短促、克制的提示，"
            "只暗示底层机制已记录主角的小额操作，不解释真相。"
        ),
    )
    enriched.setdefault(
        "explicit_chapter_end_hook",
        (
            "explicit_chapter_end_hook: 章末必须留下具体下一章诱饵，而不是情绪闭环；"
            "优先落在任务进度、技能条件、装备条件、地图入口或下一只更高收益怪上。"
        ),
    )
    enriched.setdefault(
        "reality_game_bridge",
        (
            "reality_game_bridge: 章末必须把游戏内收益和现实压力挂上第一根线，"
            "例如传闻中的铜币收购、黑市比例、工作室收材料、或债务倒计时与游戏材料价格并置；"
            "只给线索，不做正式提现。"
        ),
    )
    return enriched


def _plot_simulation(
    story: StoryState,
    chapter_number: int,
    *,
    chapter_goal: str,
    game_story: bool,
) -> dict[str, Any]:
    lead = _lead_character(story)
    protagonist = ""
    if lead is not None:
        protagonist = lead.game_id or lead.game_panel.game_id or lead.name
    protagonist = str(protagonist or "").strip()
    if not protagonist or set(protagonist) <= {"?", "？"}:
        protagonist = "主角"
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    protagonist_ledger = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
    economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
    equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
    quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
    level = str(protagonist_ledger.get("level") or "Lv.1")
    hp = str(protagonist_ledger.get("hp") or "")
    mp = str(protagonist_ledger.get("mp") or "")
    currency = str(economy.get("game_currency") or economy.get("currency") or "")
    durability = str(equipment.get("durability") or protagonist_ledger.get("weapon_durability") or "")
    quest_text = "；".join(f"{name}{value}" for name, value in quests.items()) if quests else "当前任务未明"

    if not game_story:
        return {
            "mode": "plot-first",
            "reader_hook": "读者要看到主角这章面对一个具体问题，而不是阅读设定说明。",
            "chapter_desire": f"{protagonist}想完成本章目标：{chapter_goal or '推进当前主线'}。",
            "obstacle_chain": ["旧问题没有完全解决", "外部压力逼近", "主角必须做一个有代价的选择"],
            "choice_point": "主角选择立刻处理眼前阻碍，还是保留资源等更稳的机会。",
            "payoff": "本章至少兑现一个可见进展。",
            "cost": "时间、关系、资源或暴露风险至少付出一项。",
            "emotional_turn": "从被压力推着走，转成主动抓住一个小机会。",
            "outsider_misread": "旁人只看到表层动作，看不到主角真正的判断。",
            "ending_hook": "章末落到下一章马上能执行的一步。",
        }

    if chapter_number == 1:
        desire = f"{protagonist}想先确认千倍爆率能不能变成实际领先。"
        payoff = "第一次异常掉落让读者看到优势已经落袋，但外人只会当成运气好。"
        ending = "章末落到补齐清道夫委托或下一步低级路线，不能提前跳到转职。"
    elif "清道夫委托" in quest_text and "未" in quest_text:
        desire = f"{protagonist}想把还差的材料补齐，低调完成清道夫委托。"
        payoff = "把第一章的材料优势换成任务奖励、修理或补给资格。"
        ending = "章末让后坡入口、补给压力或下一轮任务成为马上能接的目标。"
    elif "后坡巡查" in quest_text:
        desire = f"{protagonist}想在后坡巡查里多推进一格，同时不暴露掉落异常。"
        payoff = "巡查进度、材料、经验或路线信息至少推进一项。"
        ending = "章末留下最后一段巡查、血蓝补给或更高收益怪点。"
    else:
        desire = f"{protagonist}想把上一章的小优势滚成新的任务、装备或路线进度。"
        payoff = "读者要看到经验、任务、补给、装备或路线里至少有一项实在变化。"
        ending = "章末落到下一项具体前置任务或资源缺口。"

    resource_line = "，".join(
        item
        for item in (
            f"等级{level}" if level else "",
            f"生命{hp}" if hp else "",
            f"法力{mp}" if mp else "",
            f"钱袋{currency}" if currency else "",
            f"耐久{durability}" if durability else "",
        )
        if item
    )
    resource_line = resource_line or "资源状态必须从上一章承接"

    return {
        "mode": "plot-first",
        "reader_hook": "读者要看到夜烬把隐藏优势藏在普通玩家动作里，悄悄滚出下一步领先。",
        "chapter_desire": desire,
        "obstacle_chain": [
            f"先承接账本：{resource_line}。",
            "再让血蓝、耐久、排队、NPC规矩、背包或旁人误判卡住行动。",
            "最后用千倍爆率带来的小优势换成一个看得见的进度，但不让外人看懂来源。",
        ],
        "choice_point": "夜烬必须选择是立刻兑现收益，还是为了隐藏来源多绕一步、少拿一点表面好处。",
        "payoff": payoff,
        "cost": "付出血蓝、耐久、铜币、药水、等待时间或暴露风险中的至少一项。",
        "emotional_turn": "从现实和资源都紧的压迫感，转成拿到一小步领先后的克制和警惕。",
        "outsider_misread": "普通玩家或NPC只能看到他运气不错、路线熟、排队办事，不能知道千倍爆率和完整背包账本。",
        "ending_hook": ending,
    }


def _director_plot_projection(event_plan: dict, *, chapter_goal: str) -> dict[str, Any]:
    """Expose the director's decisions without making a second plot plan."""

    satisfaction = (
        event_plan.get("chapter_satisfaction")
        if isinstance(event_plan.get("chapter_satisfaction"), dict)
        else {}
    )
    chapter_end_hook = event_plan.get("chapter_end_hook")
    if isinstance(chapter_end_hook, dict):
        ending_hook = str(
            chapter_end_hook.get("content")
            or chapter_end_hook.get("hook")
            or chapter_end_hook.get("text")
            or ""
        ).strip()
    else:
        ending_hook = str(chapter_end_hook or "").strip()
    ending_hook = ending_hook or str(
        event_plan.get("explicit_chapter_end_hook")
        or event_plan.get("next_focus")
        or ""
    ).strip()

    obstacle_chain = _compact_list(
        [event_plan.get("collision"), satisfaction.get("obstacle")],
        limit=4,
    )
    return {
        "mode": "director-projection",
        "source": "director_event_plan",
        "reader_hook": ending_hook,
        "chapter_desire": str(satisfaction.get("core_event") or chapter_goal).strip(),
        "obstacle_chain": obstacle_chain,
        "choice_point": str(event_plan.get("pivot") or "").strip(),
        "payoff": str(satisfaction.get("visible_payoff") or "").strip(),
        "cost": str(satisfaction.get("cost") or event_plan.get("cost") or "").strip(),
        "emotional_turn": str(satisfaction.get("emotion_target") or "").strip(),
        "outsider_misread": str(satisfaction.get("outsider_misread") or "").strip(),
        "ending_hook": ending_hook,
    }


def _world_context(story: StoryState, chapter_number: int) -> dict[str, Any]:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    pulse_store = ledger.get("world_pulse") if isinstance(ledger.get("world_pulse"), dict) else {}
    persistent_world = ledger.get("persistent_world") if isinstance(ledger.get("persistent_world"), dict) else {}
    latest_pulse = pulse_store.get("latest") if isinstance(pulse_store.get("latest"), dict) else {}
    history = pulse_store.get("history") if isinstance(pulse_store.get("history"), list) else []
    return {
        "schema_version": "world-context/v1",
        "simulation_horizon": "long_running_world_then_chapter_slice",
        "latest_pulse": latest_pulse,
        "recent_pulses": history[-3:],
        "persistent_world": persistent_world,
        "visible_inbox": visibility_inbox_for_chapter(story, chapter_number, max_items=6),
        "visibility_rule": "Only visible_inbox and protagonist-visible traces may enter prose; hidden_state stays off-page.",
    }


def build_chapter_simulation_plan(
    story: StoryState,
    chapter_number: int,
    *,
    event_plan: dict | None = None,
    memory_constraints: dict | None = None,
    chapter_seed: dict | None = None,
    plot_authority: str = "simulation",
) -> ChapterSimulationPlan:
    game_story = is_game_story(story)
    lead = _lead_character(story)
    event_plan = event_plan or {}
    memory_constraints = memory_constraints or {}
    chapter_seed = chapter_seed or {}
    director_owns_plot = plot_authority == "director"
    if game_story and not director_owns_plot:
        event_plan = _game_director_event_plan(event_plan, chapter_number)
    simulation_variant = dict(chapter_seed.get("simulation_variant")) if isinstance(chapter_seed.get("simulation_variant"), dict) else {}
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    selected_direction = normalize_chapter_direction_choice(
        chapter_seed.get("selected_chapter_direction") or ledger.get("chapter_direction")
    )
    if selected_direction:
        simulation_variant["chapter_direction"] = selected_direction
    if selected_direction and not director_owns_plot:
        event_plan = {
            **event_plan,
            "chapter_direction": selected_direction,
            "wow_beat": selected_direction.get("wow_beat") or event_plan.get("wow_beat", ""),
            "explicit_chapter_end_hook": selected_direction.get("ending_hook")
            or event_plan.get("explicit_chapter_end_hook", ""),
            "reality_game_bridge": selected_direction.get("state_delta") or event_plan.get("reality_game_bridge", ""),
        }

    character_performance = [
        _default_performance(character, game_story=game_story)
        for character in story.characters
        if character.lifecycle_state == "active" and not character.frozen
    ][:8]
    npc_boundaries = [
        boundary
        for character in story.characters
        if (boundary := _default_npc_boundary(character)) is not None
    ][:6]

    information_visibility = _compact_list(chapter_seed.get("information_visibility"), limit=6)
    economy_expectations = _compact_list(chapter_seed.get("economy_expectations"), limit=6)
    longform_constraints = _longform_constraints(story, chapter_seed)
    required_beats = _compact_list(chapter_seed.get("required_beats"), limit=8)
    forbidden_moves = _compact_list(chapter_seed.get("forbidden_moves"), limit=8)

    if game_story:
        information_visibility = [*information_visibility, *_game_visibility_rules()]
        economy_expectations = [*economy_expectations, *_game_economy_rules()]
        forbidden_moves = [*forbidden_moves, *_game_forbidden_moves(chapter_number)]
        if not director_owns_plot:
            required_beats = [*required_beats, *_game_required_beats(chapter_number)]
            for key in (
                "wow_beat",
                "escalation_break",
                "core_mystery_reinforcement",
                "explicit_chapter_end_hook",
                "reality_game_bridge",
            ):
                if event_plan.get(key):
                    required_beats.append(f"{key}: {event_plan[key]}")

    protagonist_strategy = {}
    if lead:
        protagonist_strategy = {
            "name": lead.name,
            "goal": _character_goal(lead),
            "risk_posture": lead.performance_profile.risk_posture or (
                "低调验证、拆分收益、避免暴露坐标和现实身份。"
                "每次行动先算成本和撤退路线，不贪、不炫、不主动接触陌生人。"
                "小额收益伪装成普通玩家噪音，不留下可追踪的重复模式。"
                if game_story
                else "按当前目标谨慎推进。"
            ),
        }
        if game_story:
            protagonist_strategy["game_id"] = lead.game_id or lead.game_panel.game_id
            protagonist_strategy["known_panel"] = lead.game_panel.model_dump()

    panel_expectations = (
        [
            "每章结束必须同步等级、职业、经验、生命/法力、基础属性、货币、装备、背包、任务和风险状态。",
            "正文中的面板变化必须能被 ledger_updates 回写到角色卡。",
        ]
        if game_story
        else []
    )
    if game_story and memory_constraints.get("ledger_updates"):
        panel_expectations.append("优先继承 memory_constraints.ledger_updates 中已规划的状态变化。")

    review_focus = [
        "角色行为是否符合目标、行事习惯和信息可见性。",
        "NPC是否遵守职责、权限和信息边界。",
        "世界反应是否来自可观察痕迹，而不是全知视角。",
        "章节是否完成目标、收益反馈和新压力。",
    ]
    if game_story:
        review_focus.extend(
            [
                "网游经济是否符合新手阶段规模和既有价格锚点。",
                "游戏ID、职业、装备、货币、背包是否连续。",
                "规则是否通过场景表现，而不是说明书式输出。",
                "章节是否遵守百万字长期框架：只解锁当前卷允许的地图、势力、经济、职业和真相层级。",
            ]
        )

    previous_next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""
    chapter_goal = (
        str(selected_direction.get("chapter_goal") or "").strip()
        or
        str(event_plan.get("turn") or event_plan.get("pivot") or memory_constraints.get("current_focus") or "").strip()
        or str(previous_next_focus or "").strip()
        or str(story.outline or "").strip()
        or "推进当前章节目标"
    )
    if selected_direction and not director_owns_plot:
        main_scenes = selected_direction.get("main_scenes") if isinstance(selected_direction.get("main_scenes"), list) else []
        required_beats.extend(
            [
                f"selected_chapter_direction: {selected_direction.get('name') or selected_direction.get('id')}",
                f"direction_reader_promise: {selected_direction.get('reader_promise')}",
                f"direction_wow_beat: {selected_direction.get('wow_beat')}",
                f"direction_ending_hook: {selected_direction.get('ending_hook')}",
                f"direction_state_delta: {selected_direction.get('state_delta')}",
                *[f"direction_scene: {scene}" for scene in main_scenes[:4]],
            ]
        )
        if selected_direction.get("risk"):
            forbidden_moves.append(str(selected_direction["risk"]))
    plot_simulation = (
        _director_plot_projection(event_plan, chapter_goal=chapter_goal)
        if director_owns_plot
        else _plot_simulation(
            story,
            chapter_number,
            chapter_goal=chapter_goal,
            game_story=game_story,
        )
    )
    longform_plot_contract = build_longform_plot_contract(
        story,
        chapter_number,
        chapter_goal=chapter_goal,
        game_story=game_story,
    )
    if not director_owns_plot:
        plot_simulation = {
            **plot_simulation,
            "longform_position": longform_plot_contract.get("arc_window", {}),
            "payoff_requirement": longform_plot_contract.get("payoff_requirement", ""),
            "anti_drag_rule": longform_plot_contract.get("anti_drag_rule", ""),
            "future_use_rule": longform_plot_contract.get("future_use_rule", ""),
            "reader_reason_to_continue": longform_plot_contract.get("reader_reason_to_continue", ""),
        }
    web_game_author_craft = build_web_game_author_craft(chapter_number, chapter_goal=chapter_goal) if game_story else {}
    web_game_director_card = (
        build_web_game_director_card(
            chapter_number=chapter_number,
            chapter_goal=chapter_goal,
            simulation_plan={"chapter_goal": chapter_goal, "simulation_variant": simulation_variant},
            event_plan=event_plan,
        )
        if game_story and not director_owns_plot
        else {}
    )

    return ChapterSimulationPlan(
        chapter_number=chapter_number,
        chapter_goal=chapter_goal,
        world_context=_world_context(story, chapter_number),
        event_plan=event_plan,
        plot_simulation=plot_simulation,
        longform_plot_contract=longform_plot_contract,
        protagonist_strategy=protagonist_strategy,
        character_performance=character_performance,
        npc_boundaries=npc_boundaries,
        information_visibility=information_visibility[:10],
        economy_expectations=economy_expectations[:10],
        # Controls regeneration diversity. A caller can rotate this id to
        # force a different first-chapter route/NPC/cost shape while keeping
        # the same hard story contract.
        simulation_variant=simulation_variant,
        web_game_author_craft=web_game_author_craft,
        web_game_director_card=web_game_director_card,
        panel_expectations=panel_expectations,
        longform_constraints=longform_constraints,
        required_beats=required_beats[:12],
        forbidden_moves=forbidden_moves[:12],
        review_focus=review_focus,
    )
