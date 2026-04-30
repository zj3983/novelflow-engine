from __future__ import annotations

from typing import Any

from packages.story_core.genre_plugins import GAME_WEBNOVEL, plugin_simulation_blueprint
from packages.story_core.models import SceneCard, StoryState, WorldEvent
from packages.story_core.simulation import is_game_story


META_TERMS = ["爽点", "钩子", "节奏", "读者", "网文规则", "生成", "审稿"]


def _usable_identity(value: str | None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or set(cleaned) <= {"?", "？", "�"}:
        return ""
    return cleaned


def _fallback_game_id(story: StoryState, real_name: str) -> str:
    story_text = f"{story.genre}\n{story.outline}\n{story.style}"
    if real_name == "苏叶" and any(token in story_text for token in ("网游", "游戏", "《界域》", "天启之门")):
        return "夜烬"
    return real_name


def _lead_name(story: StoryState) -> tuple[str, str]:
    for character in story.characters:
        if character.role in {"protagonist", "主角", "涓昏"}:
            real_name = _usable_identity(character.name) or "主角"
            game_id = _usable_identity(character.game_id) or _usable_identity(character.game_panel.game_id)
            return real_name, game_id or _fallback_game_id(story, real_name)
    if story.characters:
        character = story.characters[0]
        real_name = _usable_identity(character.name) or "主角"
        game_id = _usable_identity(character.game_id) or _usable_identity(character.game_panel.game_id)
        return real_name, game_id or _fallback_game_id(story, real_name)
    return "主角", "主角"


def _chapter_contract(chapter_seed: dict[str, Any]) -> dict[str, Any]:
    contract = chapter_seed.get("chapter_contract")
    return contract if isinstance(contract, dict) else {}


GAME_TEMPLATE_IDS = {
    "reality_entry",
    "character_creation",
    "small_verification",
    "single_npc_service",
    "chapter_1_next_step",
}


def _simulation_blueprint(chapter_seed: dict[str, Any], *, allow_default_game: bool = False) -> dict[str, Any]:
    blueprint = chapter_seed.get("simulation_blueprint")
    if isinstance(blueprint, dict) and blueprint.get("opening_scene_templates"):
        return blueprint
    return plugin_simulation_blueprint([GAME_WEBNOVEL]) if allow_default_game else {}


def _template_by_id(chapter_seed: dict[str, Any], *, allow_default_game: bool = False) -> dict[str, dict[str, Any]]:
    templates = _simulation_blueprint(chapter_seed, allow_default_game=allow_default_game).get("opening_scene_templates")
    if not isinstance(templates, list):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for template in templates:
        if isinstance(template, dict) and template.get("id"):
            result[str(template["id"])] = template
    return result


def _template_order(chapter_seed: dict[str, Any], *, allow_default_game: bool = False) -> dict[str, int]:
    return {
        template_id: index
        for index, template_id in enumerate(_template_by_id(chapter_seed, allow_default_game=allow_default_game))
    }


def _forbidden_conflicts(chapter_seed: dict[str, Any], *, allow_default_game: bool = False) -> list[str]:
    chapter_number = int(chapter_seed.get("chapter_number", 0) or 0)
    forbidden = _simulation_blueprint(chapter_seed, allow_default_game=allow_default_game).get("forbidden_conflict_modes")
    if not isinstance(forbidden, dict):
        return []
    values = forbidden.get(f"chapter_{chapter_number}", [])
    return [str(item) for item in values if str(item).strip()] if isinstance(values, list) else []


def _event(
    *,
    event_id: str,
    actor: str,
    action: str,
    target: str = "",
    location: str = "",
    cause: str = "",
    visible_to: list[str] | None = None,
    consequences: list[str] | None = None,
    state_delta: dict | None = None,
    prose_priority: int = 0,
    template_id: str = "",
) -> WorldEvent:
    return WorldEvent(
        event_id=event_id,
        template_id=template_id,
        actor=actor,
        action=action,
        target=target,
        location=location,
        cause=cause,
        visible_to=visible_to or [],
        consequences=consequences or [],
        state_delta=state_delta or {},
        prose_priority=prose_priority,
    )


def simulate_world_events(
    story: StoryState,
    chapter_number: int,
    *,
    chapter_seed: dict[str, Any] | None = None,
    simulation_plan: dict[str, Any] | None = None,
) -> list[WorldEvent]:
    """Simulate what happens in-world before prose generation.

    This deliberately produces small, bounded events. The writer can dramatize
    them, but cannot promote weak traces into omniscient reactions.
    """

    chapter_seed = chapter_seed or {}
    simulation_plan = simulation_plan or {}
    real_name, game_id = _lead_name(story)
    protagonist = game_id or real_name
    contract = _chapter_contract(chapter_seed)
    required = " ".join(str(item) for item in contract.get("required_beats", []))
    is_game = is_game_story(story) or "game_webnovel" in chapter_seed.get("genre_plugins", [])

    if not is_game:
        chapter_goal = str(simulation_plan.get("chapter_goal") or "推进当前章节目标")
        return [
            _event(
                event_id=f"c{chapter_number}-goal",
                actor=protagonist,
                action=chapter_goal,
                visible_to=[protagonist],
                consequences=["形成本章行动结果与下一步压力。"],
                prose_priority=8,
            )
        ]

    events: list[WorldEvent] = []
    if chapter_number == 1:
        events.extend(
            [
                _event(
                    event_id="c1-reality-entry",
                    actor=real_name,
                    action="在现实压力下登录游戏，决定用游戏内身份试探机会。",
                    location="现实出租屋",
                    visible_to=[real_name],
                    consequences=["现实职业和风险判断成为后续藏拙依据。"],
                    prose_priority=10,
                    template_id="reality_entry",
                ),
                _event(
                    event_id="c1-character-create",
                    actor=protagonist,
                    action="完成建号、游戏ID与职业选择。",
                    target="元素法师学徒",
                    location="角色创建界面",
                    visible_to=[protagonist, "系统界面"],
                    consequences=["角色面板获得职业、生命、法力、基础属性和初始装备。"],
                    state_delta={
                        "protagonist": {
                            "game_id": protagonist,
                            "class_path": "元素法师学徒",
                            "level": 1,
                        }
                    },
                    prose_priority=10,
                    template_id="character_creation",
                ),
                _event(
                    event_id="c1-small-verify",
                    actor=protagonist,
                    action="通过低级怪物和任务材料小额验证千倍爆率。",
                    target="低级材料",
                    location="灰烬村外",
                    cause="必须先确认隐藏优势是否稳定。",
                    visible_to=[protagonist, "附近普通玩家"],
                    consequences=["只产生个人收益和少量可见打怪痕迹，不足以扰动全服。"],
                    state_delta={"economy": {"inventory_hint": "新增低级材料"}},
                    prose_priority=9,
                    template_id="small_verification",
                ),
                _event(
                    event_id="c1-npc-service",
                    actor="命名NPC",
                    action="以岗位服务、报价或任务门槛影响主角选择。",
                    location="灰烬村",
                    visible_to=[protagonist, "该NPC"],
                    consequences=["NPC只知道岗位范围内的信息，不知道隐藏天赋或现实身份。"],
                    prose_priority=8,
                    template_id="single_npc_service",
                ),
                _event(
                    event_id="c1-next-step-hook",
                    actor=protagonist,
                    action="保留首次验证得到的低级材料，把交易行、补给或任务提交作为下一章目标。",
                    target="下一步目标",
                    location="灰烬村",
                    cause="第一章只完成登录建号和首次验证，不提前展开交易线。",
                    visible_to=[protagonist],
                    consequences=[
                        "本章不发生寄售、成交、到账、提现或商人追踪。",
                        "章末只留下材料如何变现或提交任务的选择压力。",
                    ],
                    state_delta={"economy": {"inventory_hint": "保留低级材料"}},
                    prose_priority=9,
                    template_id="chapter_1_next_step",
                ),
            ]
        )
    else:
        goal = str(simulation_plan.get("chapter_goal") or chapter_seed.get("phase") or "继续推进当前目标")
        events.extend(
            [
                _event(
                    event_id=f"c{chapter_number}-inherit-ledger",
                    actor=protagonist,
                    action="继承上一章等级、职业、装备、库存和货币账本继续行动。",
                    visible_to=[protagonist],
                    consequences=["本章所有收益必须从既有账本变化而来。"],
                    state_delta=story.progression_ledger,
                    prose_priority=10,
                ),
                _event(
                    event_id=f"c{chapter_number}-chapter-goal",
                    actor=protagonist,
                    action=goal,
                    visible_to=[protagonist],
                    consequences=["形成阶段收益、代价和下一步压力。"],
                    prose_priority=9,
                ),
            ]
        )

        for index, reaction in enumerate(simulation_plan.get("event_plan", {}).get("world_reactions", [])[:3], start=1):
            events.append(
                _event(
                    event_id=f"c{chapter_number}-reaction-{index}",
                    actor="世界系统",
                    action=str(reaction),
                    visible_to=["相关玩家", "相关NPC"],
                    consequences=["外部反应只能基于可见痕迹逐步逼近。"],
                    prose_priority=7,
                )
            )

    if required and not any("角色面板" in consequence for event in events for consequence in event.consequences):
        events.append(
            _event(
                event_id=f"c{chapter_number}-panel-ledger",
                actor=protagonist,
                action="结算并更新角色面板。",
                visible_to=[protagonist, "系统界面"],
                consequences=["角色面板必须进入章节账本。"],
                prose_priority=7,
            )
        )
    return events


def select_scene_cards(
    events: list[WorldEvent],
    *,
    chapter_seed: dict[str, Any] | None = None,
    simulation_plan: dict[str, Any] | None = None,
) -> list[SceneCard]:
    """Convert world events into a compact scene plan for the writer."""

    chapter_seed = chapter_seed or {}
    simulation_plan = simulation_plan or {}
    allow_default_game = any(event.template_id in GAME_TEMPLATE_IDS for event in events)
    templates = _template_by_id(chapter_seed, allow_default_game=allow_default_game)
    order_rank = _template_order(chapter_seed, allow_default_game=allow_default_game)
    forbidden_conflicts = _forbidden_conflicts(chapter_seed, allow_default_game=allow_default_game)
    sorted_events = sorted(
        events,
        key=lambda event: (order_rank.get(event.template_id, 999), -event.prose_priority),
    )
    cards: list[SceneCard] = []
    for event in sorted_events[:5]:
        template = templates.get(event.template_id, {})
        must_show = [event.action, *event.consequences[:2]]
        template_must_show = template.get("must_show")
        if isinstance(template_must_show, list):
            must_show.extend(str(item) for item in template_must_show if str(item).strip())
        if event.state_delta:
            must_show.append("把状态变化写成可回写账本的结果。")
        if "角色" in event.action or "面板" in " ".join(event.consequences):
            must_show.append("短角色面板：ID、等级、职业、生命/法力、基础属性、装备、背包。")
        if "交易行" in event.location:
            must_show.append("交易行只显示价格、数量、批次、手续费、到账或时间戳。")
        if "NPC" in event.actor or "NPC" in event.action:
            must_show.append("NPC的地点、服务、利益诉求、口吻和信息边界。")

        cards.append(
            SceneCard(
                scene_id=f"s{len(cards) + 1}-{event.event_id}",
                template_id=event.template_id,
                location=str(template.get("location") or event.location or "当前场景"),
                pov=event.actor,
                purpose=str(template.get("purpose") or event.action),
                conflict=str(
                    template.get("conflict")
                    or event.cause
                    or simulation_plan.get("chapter_goal")
                    or chapter_seed.get("phase")
                    or "推进本章目标"
                ),
                source_events=[event.event_id],
                must_show=must_show,
                must_not_explain=[
                    *META_TERMS,
                    *forbidden_conflicts,
                    "不要把推演规则、审稿意见或后台术语写进正文。",
                ],
                state_delta=event.state_delta,
                ending_pressure=(event.consequences[-1] if event.consequences else "留下下一步压力。"),
            )
        )

    return cards[:5]
