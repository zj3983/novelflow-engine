from __future__ import annotations

from typing import Any

from packages.story_core.genre_plugins import GAME_WEBNOVEL, plugin_simulation_blueprint
from packages.story_core.game_world_simulator import simulate_game_world
from packages.story_core.models import SceneCard, StoryState, WorldEvent
from packages.story_core.simulation import is_game_story
from packages.story_core.world_pulse import visibility_inbox_consumed_ids, visibility_inbox_for_chapter


META_TERMS = ["爽点", "钩子", "节奏", "读者", "网文规则", "生成", "审稿"]


def _usable_identity(value: str | None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or set(cleaned) <= {"?", "？", "�"}:
        return ""
    return cleaned


def _fallback_game_id(story: StoryState, real_name: str) -> str:
    """Generate a generic game ID from the character's real name."""
    story_text = f"{story.genre}\n{story.outline}\n{story.style}"
    if real_name == "苏叶" and any(token in story_text for token in ("网游", "游戏", "《界域》", "天启之门", "VRMMO")):
        return "夜烬"
    if real_name and any(token in story_text for token in ("网游", "游戏", "VRMMO")):
        # Use last character of name as game ID (common convention)
        return real_name[-1] if len(real_name) <= 2 else f"{real_name[-2]}{real_name[-1]}"
    return real_name


def _lead_name(story: StoryState) -> tuple[str, str]:
    for character in story.characters:
        if character.role in {"protagonist", "主角"}:
            real_name = _usable_identity(character.name) or "主角"
            game_id = _usable_identity(character.game_id) or _usable_identity(character.game_panel.game_id)
            return real_name, game_id or _fallback_game_id(story, real_name)
    if story.characters:
        character = story.characters[0]
        real_name = _usable_identity(character.name) or "主角"
        game_id = _usable_identity(character.game_id) or _usable_identity(character.game_panel.game_id)
        return real_name, game_id or _fallback_game_id(story, real_name)
    return "主角", "主角"


def _lead_class_path(story: StoryState) -> str:
    for character in story.characters:
        if character.role in {"protagonist", "主角"}:
            class_path = _usable_identity(character.game_panel.class_path)
            if class_path:
                return class_path
            break
    if story.characters:
        class_path = _usable_identity(story.characters[0].game_panel.class_path)
        if class_path:
            return class_path
    return "元素法师学徒"


def _chapter_contract(chapter_seed: dict[str, Any]) -> dict[str, Any]:
    contract = chapter_seed.get("chapter_contract")
    return contract if isinstance(contract, dict) else {}


GAME_TEMPLATE_IDS = {
    "reality_entry",
    "character_creation",
    "small_verification",
    "single_npc_service",
    "chapter_1_next_step",
    "visibility_inbox_pressure",
}

VISIBILITY_INBOX_FORBIDDEN = ["hidden_talent", "real_identity", "precise_coordinates"]


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


def _visibility_inbox_event(story: StoryState, chapter_number: int, protagonist: str) -> WorldEvent | None:
    inbox_items = visibility_inbox_for_chapter(story, chapter_number)
    if not inbox_items:
        return None
    surface = "; ".join(
        f"{item.get('channel', 'visible_trace')}: {item.get('text', '')}"
        for item in inbox_items
        if str(item.get("text") or "").strip()
    )
    newly_consumed_ids = [str(item.get("id")) for item in inbox_items if str(item.get("id") or "").strip()]
    consumed_ids = [*visibility_inbox_consumed_ids(story)]
    for item_id in newly_consumed_ids:
        if item_id not in consumed_ids:
            consumed_ids.append(item_id)
    return _event(
        event_id=f"c{chapter_number}-visibility-inbox",
        template_id="visibility_inbox_pressure",
        actor="world_pulse",
        action=surface,
        target="next_scene_pressure",
        location="visible_world_surface",
        cause="persistent world pulse produced player-visible traces",
        visible_to=[protagonist],
        consequences=[
            "Treat these as next-scene pressure, not solved background exposition.",
            "Do not upgrade weak traces into hidden talent, real identity, or precise coordinates.",
        ],
        state_delta={
            "visibility_inbox_pressure": {
                "items": inbox_items,
                "consumed_ids": consumed_ids,
                "newly_consumed_ids": newly_consumed_ids,
                "visibility_limits": VISIBILITY_INBOX_FORBIDDEN,
            }
        },
        prose_priority=8,
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
    class_path = _lead_class_path(story)
    contract = _chapter_contract(chapter_seed)
    required = " ".join(str(item) for item in contract.get("required_beats", []))
    simulation_variant = simulation_plan.get("simulation_variant") if isinstance(simulation_plan.get("simulation_variant"), dict) else {}
    variant_id = str(simulation_variant.get("id") or "").strip()
    is_game = is_game_story(story) or "game_webnovel" in chapter_seed.get("genre_plugins", [])
    game_world = (
        simulate_game_world(
            story,
            chapter_number,
            chapter_seed=chapter_seed,
            simulation_plan=simulation_plan,
        )
        if is_game
        else {}
    )

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
                    target=class_path,
                    location="角色创建界面",
                    visible_to=[protagonist, "系统界面"],
                    consequences=["角色面板获得职业、生命、法力、基础属性和初始装备。"],
                    state_delta={
                        "protagonist": {
                            "game_id": protagonist,
                            "class_path": class_path,
                            "level": 1,
                        }
                    },
                    prose_priority=10,
                    template_id="character_creation",
                ),
                _event(
                    event_id="c1-small-verify",
                    actor=protagonist,
                    action=(
                        "通过背包容量和低级怪物掉落验证边界。"
                        if variant_id == "boundary-inventory-route"
                        else "通过装备耐久和低级怪物掉落验证边界。"
                        if variant_id == "boundary-durability-route"
                        else "通过低级怪物和任务材料小额验证千倍爆率。"
                    ),
                    target="低级材料",
                    location="灰烬村外",
                    cause="必须先确认隐藏优势是否稳定。",
                    visible_to=[protagonist, "附近普通玩家"],
                    consequences=[
                        "只产生个人收益和少量可见打怪痕迹，不足以扰动全服。",
                        str(game_world.get("chapter_pressure") or "低级验证留下补给与耐久压力。"),
                    ],
                    state_delta={
                        "economy": {"inventory_hint": "新增低级材料"},
                        "game_world_simulation": game_world,
                    },
                    prose_priority=9,
                    template_id="small_verification",
                ),
                _event(
                    event_id="c1-npc-service",
                    actor=(
                        "仓库管理员铁栓"
                        if variant_id == "boundary-inventory-route"
                        else "修理匠老葛"
                        if variant_id == "boundary-durability-route"
                        else "药剂师洛婶"
                    ),
                    action=(
                        "以仓储格、押金和背包容量边界影响主角选择。"
                        if variant_id == "boundary-inventory-route"
                        else "以修理费、法杖耐久和下一轮战斗风险影响主角选择。"
                        if variant_id == "boundary-durability-route"
                        else "以岗位服务、报价或任务门槛影响主角选择。"
                    ),
                    location=(
                        "灰烬村仓库窗口"
                        if variant_id == "boundary-inventory-route"
                        else "灰烬村修理铺门口"
                        if variant_id == "boundary-durability-route"
                        else "灰烬村"
                    ),
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
        inbox_event = _visibility_inbox_event(story, chapter_number, protagonist)
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
        if inbox_event:
            events.append(inbox_event)

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


_SCENE_TEXTURE_BY_TEMPLATE: dict[str, dict[str, Any]] = {
    "reality_entry": {
        "sensory_anchors": ["楼道里的潮味或楼下噪音", "手边一个具体物件的触感（账单/旧头盔/凉茶杯）", "光线偏暗的色温"],
        "subtext": "表面是登录游戏，里子是不肯承认现实已经压过来了。",
        "rhythm_hint": "breathing：节奏放慢，让现实的重量落在主角身上一两拍后再进入游戏。",
    },
    "character_creation": {
        "sensory_anchors": ["视野里浮动的光面板/虚拟UI的微光", "选项切换时的细微反馈音", "指尖在虚拟按钮上的停留与犹豫"],
        "subtext": "表面是选职业，里子是给自己留一条可撤的退路。",
        "rhythm_hint": "staccato：选项→停顿→选项，短节拍，呈现计算与犹豫的交替。",
    },
    "small_verification": {
        "sensory_anchors": ["怪物倒地时一个具体的声音/材料落地的反光", "主角呼吸或心跳的一次明显变化", "环境光在掉落物上的折射"],
        "subtext": "表面是验证爆率，里子是怕这只是个错觉。",
        "rhythm_hint": "dense：动作密度高，连续短句推进，给读者首次兑现的爽感。",
    },
    "single_npc_service": {
        "sensory_anchors": ["NPC柜台/工位上一个反复出现的物件", "NPC一个标志性的小动作（贴标签/擦杯/翻账）", "店里某个底色气味（药/油/纸）"],
        "subtext": "表面是问价或交任务，里子是观察NPC会不会记住自己。",
        "rhythm_hint": "breathing：对话留白，NPC的口吻和细节先于内容信息。",
    },
    "chapter_1_next_step": {
        "sensory_anchors": ["主角把材料收进背包时的一个动作", "环境里一个未解决的余响（脚步/远处招呼/天光变化）", "身体上一个轻微的疲劳信号"],
        "subtext": "表面是收材料，里子是把决策推迟到下一章去赌。",
        "rhythm_hint": "staccato：短句收束，留下未完成感，避免把张力一次性放完。",
    },
}

_SCENE_TEXTURE_GENERIC = {
    "sensory_anchors": [
        "环境里一个反复出现的声音或气味",
        "角色身体上一个具体的小动作（手指、呼吸、视线落点）",
        "光线/温度/材质中可被身体记住的一处细节",
    ],
    "subtext": "表面在做眼前的事，里子在博弈一件主角不愿明说的事。",
    "rhythm_hint": "根据本场是收益、抉择还是过渡决定密度：兑现密、抉择慢、过渡稀。",
}


def _scene_texture(template_id: str) -> dict[str, Any]:
    return _SCENE_TEXTURE_BY_TEMPLATE.get(template_id, _SCENE_TEXTURE_GENERIC)


def _game_world_surface_lines(simulation: dict[str, Any]) -> list[str]:
    if not isinstance(simulation, dict) or not simulation.get("ticks"):
        return []
    lines: list[str] = []
    for tick in simulation.get("ticks", []):
        if not isinstance(tick, dict) or tick.get("kind") != "combat":
            continue
        index = str(tick.get("tick_id", "")).rsplit("-", 1)[-1]
        drop = tick.get("drop_roll", {}).get("actual", {}) if isinstance(tick.get("drop_roll"), dict) else {}
        drop_text = "、".join(f"{name}x{amount}" for name, amount in drop.items())
        cost = tick.get("cost", {}) if isinstance(tick.get("cost"), dict) else {}
        state_after = tick.get("state_after", {}) if isinstance(tick.get("state_after"), dict) else {}
        lines.append(
            f"第{index}只灰狼：{drop_text}；成本 hp{cost.get('hp', 0)}、mp{cost.get('mp', 0)}、耐久{cost.get('durability', 0)}；"
            f"之后生命{state_after.get('hp', '?')}、法力{state_after.get('mp', '?')}、法杖{state_after.get('weapon_durability', '?')}。"
        )
    aggregate = simulation.get("aggregate", {}) if isinstance(simulation.get("aggregate"), dict) else {}
    variant = str(simulation.get("simulation_variant") or "").strip()
    if variant:
        lines.append(f"推演变体：{variant}。本次重推必须围绕该变体改换验证路径、代价或NPC服务点。")
    inventory = aggregate.get("inventory", {}) if isinstance(aggregate.get("inventory"), dict) else {}
    if aggregate:
        lines.append(
            "最终："
            f"生命{aggregate.get('hp')}，法力{aggregate.get('mp')}，法杖{aggregate.get('weapon_durability')}，"
            f"毒腺{inventory.get('灰狼毒腺', 0)}，狼皮{inventory.get('粗糙狼皮', 0)}，{aggregate.get('currency')}。"
        )
    attention = simulation.get("external_attention", {}) if isinstance(simulation.get("external_attention"), dict) else {}
    if attention:
        lines.append(f"公会注意力{attention.get('guild', 0)}；市场注意力{attention.get('market', 0)}；NPC异常注意力{attention.get('npc', 0)}。")
    observability = simulation.get("observability", {}) if isinstance(simulation.get("observability"), dict) else {}
    if observability:
        lines.append(
            "可见性："
            f"{observability.get('nearby_players', '')}；{observability.get('npc_service') or observability.get('npc_luoshen', '')}；"
            f"公会信号{observability.get('guild_signal', 'none')}；市场信号{observability.get('market_signal', 'none')}。"
        )
    systemic = simulation.get("systemic_simulation") if isinstance(simulation.get("systemic_simulation"), dict) else {}
    ledger_delta = systemic.get("ledger_delta") if isinstance(systemic.get("ledger_delta"), dict) else {}
    if ledger_delta:
        lines.append(
            "SYSTEMIC_LEDGER: "
            f"minutes={ledger_delta.get('clock_minutes')}; "
            f"inventory_delta={ledger_delta.get('inventory_delta')}; "
            f"cost_delta={ledger_delta.get('cost_delta')}; "
            f"hidden={ledger_delta.get('hidden_system_delta')}."
        )
    causal_chain = systemic.get("causal_chain") if isinstance(systemic.get("causal_chain"), list) else []
    if causal_chain:
        lines.append("SYSTEMIC_CAUSE: " + " -> ".join(str(item) for item in causal_chain[:4]))
    visibility_layers = systemic.get("visibility_layers") if isinstance(systemic.get("visibility_layers"), dict) else {}
    if visibility_layers:
        public = visibility_layers.get("public") if isinstance(visibility_layers.get("public"), list) else []
        private = visibility_layers.get("private") if isinstance(visibility_layers.get("private"), list) else []
        lines.append(
            "SYSTEMIC_VISIBILITY: "
            f"private={private[:2]}; public={public[:2]}; "
            "NPC/guild knowledge must stay inside these layers."
        )
    return lines


def _scene_contract_from_game_world(
    *,
    event: WorldEvent,
    scene_id: str,
    game_world: dict[str, Any],
) -> dict[str, Any]:
    systemic = game_world.get("systemic_simulation") if isinstance(game_world.get("systemic_simulation"), dict) else {}
    if not systemic:
        return {}

    ledger_delta = systemic.get("ledger_delta") if isinstance(systemic.get("ledger_delta"), dict) else {}
    visibility_layers = systemic.get("visibility_layers") if isinstance(systemic.get("visibility_layers"), dict) else {}
    cost_delta = ledger_delta.get("cost_delta") if isinstance(ledger_delta.get("cost_delta"), dict) else {}
    inventory_delta = ledger_delta.get("inventory_delta") if isinstance(ledger_delta.get("inventory_delta"), dict) else {}
    hidden_delta = ledger_delta.get("hidden_system_delta") if isinstance(ledger_delta.get("hidden_system_delta"), dict) else {}

    visible_consequences: list[dict[str, Any]] = []
    if any(int(value or 0) < 0 for value in cost_delta.values()):
        visible_consequences.append(
            {
                "id": "resource_cost_surface",
                "description": "Show the simulated HP, mana, or durability cost in prose.",
                "requires_any": [
                    "mana",
                    "mp",
                    "MP",
                    "low mana",
                    "mana bottomed out",
                    "health",
                    "HP",
                    "durability",
                    "法力",
                    "蓝量",
                    "生命",
                    "血量",
                    "耐久",
                ],
                "revision": "Add a panel, body feedback, or equipment detail that makes the simulated resource cost visible.",
            }
        )
    if inventory_delta:
        visible_consequences.append(
            {
                "id": "inventory_delta_surface",
                "description": "Show the material batch entering the protagonist inventory or backpack.",
                "requires_any": [
                    "backpack",
                    "inventory",
                    "loot",
                    "drop",
                    "material",
                    "背包",
                    "掉落",
                    "获得",
                    "材料",
                ],
                "revision": "Add loot feedback, backpack count, or material handling so the ledger delta reaches the page.",
            }
        )
    if visibility_layers:
        visible_consequences.append(
            {
                "id": "visibility_boundary_surface",
                "description": "Keep outside observers inside the simulated visibility layer.",
                "requires_any": [
                    "weak trace",
                    "weak public trace",
                    "cannot know",
                    "only see",
                    "only saw",
                    "只看到",
                    "不能知道",
                    "弱线索",
                    "痕迹",
                    "批次",
                    "价格",
                    "数量",
                ],
                "revision": "Show public knowledge as weak traces, route noise, batches, timestamps, prices, or service records.",
            }
        )

    hidden_consequences = []
    if hidden_delta:
        hidden_consequences.append(f"Backend-only hidden_system_delta={hidden_delta}")
    private_layer = visibility_layers.get("private") if isinstance(visibility_layers.get("private"), list) else []
    hidden_consequences.extend(str(item) for item in private_layer[:3])

    return {
        "schema_version": "scene-contract/v1",
        "scene_id": scene_id,
        "source_event": event.event_id,
        "required_state_changes": {
            "clock_minutes": ledger_delta.get("clock_minutes", 0),
            "inventory_delta": inventory_delta,
            "cost_delta": cost_delta,
            "market_delta": ledger_delta.get("market_delta", {}),
            "hidden_system_delta": hidden_delta,
            "next_pressure": ledger_delta.get("next_pressure", []),
        },
        "visible_consequences": visible_consequences,
        "hidden_consequences": hidden_consequences,
        "visibility_limits": {
            "private": visibility_layers.get("private", []),
            "public": visibility_layers.get("public", []),
            "npc": visibility_layers.get("npc", []),
            "guild": visibility_layers.get("guild", []),
        },
    }


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
        game_world = event.state_delta.get("game_world_simulation") if isinstance(event.state_delta, dict) else None
        if isinstance(game_world, dict):
            must_show.extend(_game_world_surface_lines(game_world))
        event_plan = simulation_plan.get("event_plan", {}) if isinstance(simulation_plan.get("event_plan"), dict) else {}
        if event.template_id == "small_verification":
            for key in ("wow_beat", "escalation_break"):
                if event_plan.get(key):
                    must_show.append(str(event_plan[key]))
        if event.template_id == "chapter_1_next_step":
            for key in ("core_mystery_reinforcement", "explicit_chapter_end_hook", "reality_game_bridge"):
                if event_plan.get(key):
                    must_show.append(str(event_plan[key]))
        visibility_inbox_forbidden = (
            VISIBILITY_INBOX_FORBIDDEN if event.template_id == "visibility_inbox_pressure" else []
        )
        if visibility_inbox_forbidden:
            must_show.append("Only surface player-visible inbox channels; do not reveal background actor internals.")
        ending_pressure = (
            "Treat these as next-scene pressure, not solved background exposition."
            if event.template_id == "visibility_inbox_pressure"
            else (event.consequences[-1] if event.consequences else "留下下一步压力。")
        )

        scene_id = f"s{len(cards) + 1}-{event.event_id}"
        scene_contract = (
            _scene_contract_from_game_world(event=event, scene_id=scene_id, game_world=game_world)
            if isinstance(game_world, dict)
            else {}
        )
        texture = _scene_texture(event.template_id)
        cards.append(
            SceneCard(
                scene_id=scene_id,
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
                    *visibility_inbox_forbidden,
                    "不要把推演规则、审稿意见或后台术语写进正文。",
                ],
                state_delta=event.state_delta,
                scene_contract=scene_contract,
                ending_pressure=ending_pressure,
                sensory_anchors=list(texture.get("sensory_anchors", [])),
                subtext=str(texture.get("subtext", "")),
                rhythm_hint=str(texture.get("rhythm_hint", "")),
            )
        )

    return cards
