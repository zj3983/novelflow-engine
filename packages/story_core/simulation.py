from __future__ import annotations

from typing import Any

from packages.story_core.models import CharacterState, ChapterSimulationPlan, StoryState


GAME_TOKENS = ("网游", "游戏", "系统", "等级", "公会", "交易行", "VRMMO", "副本", "NPC")
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


def is_game_story(story: StoryState) -> bool:
    haystack = " ".join([story.genre, story.style, story.outline, *story.world_facts])
    return any(token in haystack for token in GAME_TOKENS)


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
        if character.role in {"protagonist", "主角", "涓昏"}:
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
    if not risk_posture and character.role in {"protagonist", "主角", "涓昏"} and game_story:
        risk_posture = "低调验证优势，避免一次性暴露收益、坐标、现实身份和隐藏天赋。"
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
            "出场时必须通过服务、价格、门槛、口吻或信息边界影响主角选择。",
        ],
    }


def _game_visibility_rules() -> list[str]:
    return [
        "交易行低级材料匿名上架只能暴露价格、数量、批次和时间戳等弱线索。",
        "公会只能通过重复模式、稀有物、资源点目击、NPC任务异常或多源风控逐步逼近。",
        "单次小额掉落不能扰乱全服市场，也不能直接锁定主角坐标、现实身份或隐藏天赋。",
    ]


def _game_economy_rules() -> list[str]:
    return [
        "新手阶段收益优先使用铜币、银币、材料和询价，避免无依据写现实货币汇率。",
        "大额收益必须拆单、考虑手续费、买家来源、压价、追踪和信誉风险。",
        "市场反应应是局部价格波动、商人关注、普通玩家跟风或公会外围试探。",
    ]


def _game_required_beats(chapter_number: int) -> list[str]:
    if chapter_number == 1:
        return [
            "现实入口：说明主角现实职业/技能来源/压力，不只写缺钱。",
            "登录建号：写出游戏ID、职业选择和第一版角色面板，面板必须包含生命/法力和基础属性。",
            "小额验证：用低级怪、低级材料或任务反馈验证千倍爆率。",
            "一个NPC服务节点：只完整展开一个命名NPC，交代职责、服务和信息边界。",
            "交易行弱钩子：只留下价格/批次/商人关注等弱线索，不升级为正面对抗。",
        ]
    if chapter_number == 2:
        return [
            "继承第一章价格、背包、装备、经验和任务状态。",
            "通过路线、耐久、补给、NPC门槛或拆单成本放大压力。",
            "让外部势力只看到弱线索，并产生试探而非全知追杀。",
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


def build_chapter_simulation_plan(
    story: StoryState,
    chapter_number: int,
    *,
    event_plan: dict | None = None,
    memory_constraints: dict | None = None,
    chapter_seed: dict | None = None,
) -> ChapterSimulationPlan:
    game_story = is_game_story(story)
    lead = _lead_character(story)
    event_plan = event_plan or {}
    memory_constraints = memory_constraints or {}
    chapter_seed = chapter_seed or {}

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
        required_beats = [*required_beats, *_game_required_beats(chapter_number)]
        forbidden_moves = [*forbidden_moves, *_game_forbidden_moves(chapter_number)]

    protagonist_strategy = {}
    if lead:
        protagonist_strategy = {
            "name": lead.name,
            "game_id": lead.game_id or lead.game_panel.game_id,
            "goal": _character_goal(lead),
            "risk_posture": lead.performance_profile.risk_posture
            or ("低调验证、拆分收益、避免暴露。" if game_story else "按当前目标谨慎推进。"),
            "known_panel": lead.game_panel.model_dump(),
        }

    panel_expectations = [
        "每章结束必须同步等级、职业、经验、生命/法力、基础属性、货币、装备、背包、任务和风险状态。",
        "正文中的面板变化必须能被 ledger_updates 回写到角色卡。",
    ]
    if memory_constraints.get("ledger_updates"):
        panel_expectations.append("优先继承 memory_constraints.ledger_updates 中已规划的状态变化。")

    review_focus = [
        "角色行为是否符合目标、风险偏好和信息可见性。",
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

    chapter_goal = (
        str(event_plan.get("turn") or event_plan.get("pivot") or memory_constraints.get("current_focus") or "").strip()
        or "推进当前章节目标"
    )

    return ChapterSimulationPlan(
        chapter_number=chapter_number,
        chapter_goal=chapter_goal,
        event_plan=event_plan,
        protagonist_strategy=protagonist_strategy,
        character_performance=character_performance,
        npc_boundaries=npc_boundaries,
        information_visibility=information_visibility[:10],
        economy_expectations=economy_expectations[:10],
        panel_expectations=panel_expectations,
        longform_constraints=longform_constraints,
        required_beats=required_beats[:12],
        forbidden_moves=forbidden_moves[:12],
        review_focus=review_focus,
    )
