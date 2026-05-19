from __future__ import annotations

from typing import Any

from packages.story_core.models import StoryState
from packages.story_core.systemic_simulation import resolve_systemic_game_simulation


def _usable_identity(value: str | None) -> str:
    cleaned = str(value or "").strip()
    if not cleaned or set(cleaned) <= {"?", "？", "\ufffd"}:
        return ""
    return cleaned


def _lead_game_id(story: StoryState) -> str:
    for character in story.characters:
        if character.role in {"protagonist", "主角"}:
            return (
                _usable_identity(character.game_id)
                or _usable_identity(character.game_panel.game_id)
                or _usable_identity(character.name)
                or "主角"
            )
    if story.characters:
        character = story.characters[0]
        return (
            _usable_identity(character.game_id)
            or _usable_identity(character.game_panel.game_id)
            or _usable_identity(character.name)
            or "主角"
        )
    return "主角"


def _variant_id(chapter_seed: dict[str, Any] | None, simulation_plan: dict[str, Any] | None) -> str:
    for source in (simulation_plan, chapter_seed):
        if not isinstance(source, dict):
            continue
        raw = source.get("simulation_variant")
        if isinstance(raw, dict):
            value = str(raw.get("id") or raw.get("variant_id") or "").strip()
            if value:
                return value
        value = str(source.get("simulation_variant") or "").strip()
        if value:
            return value
    return "boundary-combat-cost"


def _opening_combat_ticks(game_id: str, *, variant: str = "boundary-combat-cost") -> list[dict[str, Any]]:
    """Concrete first-chapter sandbox ticks.

    This is simulation, not prose. It gives the writer exact costs, drops,
    visibility, and limits so the chapter cannot drift into vague "爽点"
    or premature market reactions.
    """

    variants: dict[str, list[dict[str, Any]]] = {
        "boundary-combat-cost": [
            {"index": 1, "monster": "灰狼Lv1", "time_delta": "3分钟", "cost": {"hp": 0, "mp": -12, "durability": -1}, "after": {"hp": "100/100", "mp": "48/60", "weapon_durability": "9/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "附近木剑玩家只掉狼皮并抱怨毒腺难出。"},
            {"index": 2, "monster": "灰狼Lv1", "time_delta": "4分钟", "cost": {"hp": -8, "mp": -12, "durability": -1}, "after": {"hp": "92/100", "mp": "36/60", "weapon_durability": "8/10"}, "drop": {"灰狼毒腺": 1, "粗糙狼皮": 1}, "nearby_noise": "爪击擦破布衣，说明收益不能抹掉战斗代价。"},
            {"index": 3, "monster": "灰狼Lv1", "time_delta": "5分钟", "cost": {"hp": -19, "mp": -12, "durability": -1}, "after": {"hp": "73/100", "mp": "24/60", "weapon_durability": "7/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "有玩家逃跑带乱仇恨，夜烬等待刷新重取样本。"},
            {"index": 4, "monster": "灰狼Lv2", "time_delta": "6分钟", "cost": {"hp": -21, "mp": -16, "durability": -2}, "after": {"hp": "52/100", "mp": "8/60", "weapon_durability": "5/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "Lv2灰狼更痛，掉落仍偏高，但风险明显上升。"},
            {"index": 5, "monster": "灰狼Lv1", "time_delta": "4分钟", "cost": {"hp": -6, "mp": -8, "durability": -1}, "after": {"hp": "46/100", "mp": "0/60", "weapon_durability": "4/10"}, "drop": {"灰狼毒腺": 1, "粗糙狼皮": 1}, "nearby_noise": "法力清空后只能用法杖补最后一截血。"},
        ],
        "boundary-inventory-route": [
            {"index": 1, "monster": "灰狼Lv1", "time_delta": "3分钟", "cost": {"hp": -4, "mp": -10, "durability": -1}, "after": {"hp": "96/100", "mp": "50/60", "weapon_durability": "9/10"}, "drop": {"灰狼毒腺": 1, "粗糙狼皮": 2}, "nearby_noise": "坡口玩家把狼皮丢给同伴，背包格很快亮红。"},
            {"index": 2, "monster": "灰狼Lv1", "time_delta": "4分钟", "cost": {"hp": -10, "mp": -10, "durability": -1}, "after": {"hp": "86/100", "mp": "40/60", "weapon_durability": "8/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "背包提示占用格增加，收益先变成负重和取舍。"},
            {"index": 3, "monster": "灰狼Lv1", "time_delta": "5分钟", "cost": {"hp": -12, "mp": -12, "durability": -1}, "after": {"hp": "74/100", "mp": "28/60", "weapon_durability": "7/10"}, "drop": {"灰狼毒腺": 1, "粗糙狼皮": 2}, "nearby_noise": "掉落不低，但每多一件都在挤压补给栏。"},
            {"index": 4, "monster": "灰狼Lv1", "time_delta": "5分钟", "cost": {"hp": -14, "mp": -12, "durability": -1}, "after": {"hp": "60/100", "mp": "16/60", "weapon_durability": "6/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "旁边散人开始回村清包，没有人关注夜烬的完整掉落。"},
            {"index": 5, "monster": "灰狼Lv2", "time_delta": "7分钟", "cost": {"hp": -18, "mp": -16, "durability": -2}, "after": {"hp": "42/100", "mp": "0/60", "weapon_durability": "4/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "背包格逼近上限，剩下的问题变成带不带得回去。"},
        ],
        "boundary-durability-route": [
            {"index": 1, "monster": "灰狼Lv1", "time_delta": "3分钟", "cost": {"hp": -2, "mp": -12, "durability": -2}, "after": {"hp": "98/100", "mp": "48/60", "weapon_durability": "8/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "法杖第一次格挡就掉了两点耐久。"},
            {"index": 2, "monster": "灰狼Lv1", "time_delta": "4分钟", "cost": {"hp": -9, "mp": -12, "durability": -1}, "after": {"hp": "89/100", "mp": "36/60", "weapon_durability": "7/10"}, "drop": {"灰狼毒腺": 1, "粗糙狼皮": 1}, "nearby_noise": "耐久红线比掉落更早进入视野。"},
            {"index": 3, "monster": "灰狼Lv2", "time_delta": "6分钟", "cost": {"hp": -20, "mp": -16, "durability": -2}, "after": {"hp": "69/100", "mp": "20/60", "weapon_durability": "5/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "Lv2灰狼逼他用法杖挡第二下，收益被修理成本咬住。"},
            {"index": 4, "monster": "灰狼Lv1", "time_delta": "4分钟", "cost": {"hp": -11, "mp": -12, "durability": -1}, "after": {"hp": "58/100", "mp": "8/60", "weapon_durability": "4/10"}, "drop": {"灰狼毒腺": 2, "粗糙狼皮": 1}, "nearby_noise": "法杖耐久变红后，附近玩家已经有人骂着回修理铺。"},
            {"index": 5, "monster": "灰狼Lv1", "time_delta": "5分钟", "cost": {"hp": -12, "mp": -8, "durability": -2}, "after": {"hp": "46/100", "mp": "0/60", "weapon_durability": "2/10"}, "drop": {"灰狼毒腺": 1, "粗糙狼皮": 1}, "nearby_noise": "最后一击后法杖几乎撑不到下一轮。"},
        ],
    }
    specs = variants.get(variant) or variants["boundary-combat-cost"]
    return [
        {
            "tick_id": f"c1-wolf-{spec['index']}",
            "kind": "combat",
            "time_delta": spec["time_delta"],
            "actor": game_id,
            "action": f"击杀第{spec['index']}只{spec['monster']}",
            "location": "灰狼坡侧沟",
            "cost": spec["cost"],
            "state_after": spec["after"],
            "drop_roll": {
                "baseline": "普通玩家常见结果为狼皮或少量毒腺。",
                "actual": spec["drop"],
            },
            "visible_to": [game_id, "附近普通玩家"],
            "world_noise": [spec["nearby_noise"]],
            "observability": "附近玩家只能看见战斗和抱怨，看不见完整掉落账本。",
        }
        for spec in specs
    ]


def simulate_game_world(
    story: StoryState,
    chapter_number: int,
    *,
    chapter_seed: dict[str, Any] | None = None,
    simulation_plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Simulate game mechanics and visibility before narrative selection."""

    game_id = _lead_game_id(story)
    variant = _variant_id(chapter_seed, simulation_plan)
    if chapter_number != 1:
        systemic = resolve_systemic_game_simulation(
            story,
            chapter_number,
            variant=variant,
            ticks=[],
        )
        return {
            "schema_version": "game-world-simulation/v1",
            "chapter_number": chapter_number,
            "ticks": [],
            "aggregate": {},
            "systemic_simulation": systemic,
            "world_state": systemic["final_state"],
            "causal_chain": systemic["causal_chain"],
            "visibility_layers": systemic["visibility_layers"],
            "ledger_delta": systemic["ledger_delta"],
            "systemic_rules": systemic["rules_fired"],
            "observability": {"guild_signal": "unchanged", "market_signal": "unchanged"},
            "external_attention": {"guild": 0, "market": 0, "npc": 0},
        }

    combat_ticks = _opening_combat_ticks(game_id, variant=variant)
    npc_by_variant = {
        "boundary-combat-cost": {
            "actor": "洛婶",
            "location": "灰烬村药剂铺",
            "action": "药剂铺门口的委托牌写着十份毒腺可交清道夫委托；是否提交、领奖、修理或买药必须跟随项目账本，本章未允许时只写价牌、队伍和下一步目标。",
            "knowledge_scope": ["药材数量", "委托规则", "药剂库存"],
            "state_delta": {"quest_threshold": "灰狼毒腺10份", "reward_visible_only": "30铜", "submit_forbidden_this_chapter": True},
        },
        "boundary-inventory-route": {
            "actor": "仓库管理员铁栓",
            "location": "灰烬村仓库窗口",
            "action": "只按格子和押金规则解释临时仓储，不问材料来路，不替玩家搬运。",
            "knowledge_scope": ["背包格", "仓储押金", "窗口排队"],
            "state_delta": {"storage_threshold": "临时格需要押金", "inventory_pressure": "背包接近上限"},
        },
        "boundary-durability-route": {
            "actor": "修理匠老葛",
            "location": "灰烬村修理铺门口",
            "action": "只看装备耐久和修理费，提醒低耐久法杖可能影响下一轮战斗。",
            "knowledge_scope": ["装备耐久", "修理费", "新手武器损耗"],
            "state_delta": {"repair_threshold": "法杖耐久过低", "repair_cost_pending": True},
        },
    }
    npc_spec = npc_by_variant.get(variant) or npc_by_variant["boundary-combat-cost"]
    npc_tick = {
        "tick_id": f"c1-npc-{variant}",
        "kind": "npc_service",
        "time_delta": "2分钟",
        "actor": npc_spec["actor"],
        "action": npc_spec["action"],
        "location": npc_spec["location"],
        "knowledge_scope": npc_spec["knowledge_scope"],
        "cannot_know": ["混沌之种", "现实身份", "完整刷怪路线", "公会内部消息"],
        "visible_to": [game_id, "排队玩家"],
        "state_delta": npc_spec["state_delta"],
    }
    aggregate = combat_ticks[-1]["state_after"] if combat_ticks else {}
    drops: dict[str, int] = {}
    for tick in combat_ticks:
        actual = tick.get("drop_roll", {}).get("actual", {}) if isinstance(tick.get("drop_roll"), dict) else {}
        for name, amount in actual.items():
            drops[name] = drops.get(name, 0) + int(amount or 0)
    ticks = [npc_tick, *combat_ticks]
    systemic = resolve_systemic_game_simulation(
        story,
        chapter_number,
        variant=variant,
        ticks=ticks,
    )
    return {
        "schema_version": "game-world-simulation/v1",
        "chapter_number": 1,
        "simulation_variant": variant,
        "ticks": ticks,
        "aggregate": {
            "level": 1,
            "exp": "30/100",
            "hp": aggregate.get("hp", "46/100"),
            "mp": aggregate.get("mp", "0/60"),
            "currency": "0铜",
            "weapon": "新手法杖",
            "weapon_durability": aggregate.get("weapon_durability", "4/10"),
            "inventory": drops or {"灰狼毒腺": 8, "粗糙狼皮": 5},
            "quest_progress": "清道夫委托0/10",
            "opening_rule": "第一章要验证千倍爆率能让任务/装备/技能/路线提前一步；是否交低级委托、领取铜币、修装备或买药水必须跟随项目账本，未允许时只保留前置条件和下一步目标。",
        },
        "systemic_simulation": systemic,
        "world_state": systemic["final_state"],
        "causal_chain": systemic["causal_chain"],
        "visibility_layers": systemic["visibility_layers"],
        "ledger_delta": systemic["ledger_delta"],
        "systemic_rules": systemic["rules_fired"],
        "observability": {
            "nearby_players": "只能看见夜烬在灰狼坡打怪，无法确认完整掉落数量。",
            "npc_service": f"{npc_spec['actor']}只按岗位规则服务。",
            "guild_signal": "none",
            "market_signal": "none",
        },
        "external_attention": {"guild": 0, "market": 0, "npc": 0},
        "chapter_pressure": f"变体{variant}：生命{aggregate.get('hp', '46/100')}、法力{aggregate.get('mp', '0/60')}、法杖{aggregate.get('weapon_durability', '4/10')}，材料要转成一项小闭环；章末让读者看见任务/装备/技能或路线前置任务已经被暗中提前一步，外人只看见普通排队。",
    }
