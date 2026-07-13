from __future__ import annotations

from typing import Any

from packages.story_core.genre_plugins import is_game_genre
from packages.story_core.models import StoryState


def _compact(value: Any, limit: int = 120) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _is_game_story(story: StoryState) -> bool:
    haystack = " ".join([story.genre, story.style, story.outline, *story.world_facts])
    return is_game_genre(haystack)


def _lead_name(story: StoryState) -> str:
    for character in story.characters:
        if character.role in {"protagonist", "主角"}:
            return character.game_id or character.game_panel.game_id or character.name or "主角"
    if story.characters:
        character = story.characters[0]
        return character.game_id or character.game_panel.game_id or character.name or "主角"
    return "主角"


def _ledger_line(story: StoryState) -> str:
    ledger = story.progression_ledger if isinstance(story.progression_ledger, dict) else {}
    protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
    economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
    equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
    quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
    parts = [
        str(protagonist.get("level") or "").strip(),
        str(protagonist.get("mp") or "").strip(),
        str(economy.get("game_currency") or economy.get("currency") or "").strip(),
        str(equipment.get("durability") or "").strip(),
    ]
    quest_line = "；".join(f"{key}{value}" for key, value in quests.items()) if quests else ""
    parts.append(quest_line)
    return "，".join(part for part in parts if part)


def _option(
    *,
    option_id: str,
    name: str,
    chapter_goal: str,
    reader_promise: str,
    main_scenes: list[str],
    wow_beat: str,
    ending_hook: str,
    state_delta: str,
    risk: str,
    recommended: bool = False,
) -> dict[str, Any]:
    return {
        "id": option_id,
        "name": name,
        "recommended": recommended,
        "chapter_goal": chapter_goal,
        "reader_promise": reader_promise,
        "main_scenes": main_scenes,
        "wow_beat": wow_beat,
        "ending_hook": ending_hook,
        "state_delta": state_delta,
        "risk": risk,
    }


def _game_options(story: StoryState, chapter_number: int) -> list[dict[str, Any]]:
    protagonist = _lead_name(story)
    ledger = _ledger_line(story)
    inherited = f"承接账本：{ledger}。" if ledger else "承接上一章等级、背包、装备、货币和任务状态。"
    return [
        _option(
            option_id="trade-bridge",
            name="交易渠道线",
            recommended=True,
            chapter_goal=f"{protagonist}把上一章材料优势拿去试正规收购、NPC报价和散人渠道，第一次把游戏收益同现实压力接上。",
            reader_promise="读者能看到小额铜币、压价、收购传闻和现实催租之间出现第一根桥。",
            main_scenes=[
                inherited,
                "先到NPC或任务窗口问价，发现岗位只认清单和价格，不替玩家解释来源。",
                "再听到散人摊位或队伍里有人提铜币收购/提现传闻，但条件含糊、风险不明。",
                "最后留下一个必须选择的渠道：按规矩卖、找散人、还是继续攒材料。",
            ],
            wow_beat="异常掉落不直接公开，落在报价差、材料批次或NPC记账上，让夜烬意识到自己比普通玩家更快碰到变现门槛。",
            ending_hook="章末出现铜币收购或提现传闻的具体口子，但对方只收队内/熟人/固定批次，夜烬还进不去。",
            state_delta="更新材料、铜币预期、NPC记账痕迹、现实催租压力和下一章渠道目标。",
            risk="只能写弱传闻和小额渠道，不写正式提现到账、全服市场震动或公会追查。",
        ),
        _option(
            option_id="chaos-seed-trace",
            name="混沌之种线",
            chapter_goal=f"{protagonist}继续补齐低级任务材料时，让混沌之种留下第二次可见痕迹，但不解释机制。",
            reader_promise="读者能看到千倍爆率真正露一次马脚，不再只是几倍收益。",
            main_scenes=[
                inherited,
                "夜烬回到低级怪点补材料，普通玩家还卡在低掉率和法力消耗上。",
                "某一次掉落或系统短提示出现不该有的残片/未解析记录，主角先藏起来不声张。",
                "回村后NPC只按普通材料处理，反而让这份异常物更扎眼。",
            ],
            wow_beat="掉出一份非基准稀有物或未解析残片，系统只短促记录，不给说明书。",
            ending_hook="章末【混沌之种：记录+1】或同级短提示再闪一次，提示主角的小额操作已被底层机制记下。",
            state_delta="更新背包异常物、材料数、法力/耐久成本、隐藏系统记录和主角警惕。",
            risk="不能让NPC、公会或玩家知道混沌之种，只能让读者和主角看到可见痕迹。",
        ),
        _option(
            option_id="guild-ecology",
            name="公会生态线",
            chapter_goal=f"{protagonist}在新手村补任务和服务时撞见公会、散人、NPC三套规矩，明白低调发育也会被渠道卡住。",
            reader_promise="读者能看到世界不是背景板：队伍、摊位、NPC岗位和公会占点各自运转。",
            main_scenes=[
                inherited,
                "白袍公会只收队内材料或固定路线，散人被挤到边缘摊位。",
                "NPC服务按岗位收费、排队和登记，不为任何玩家破例。",
                "夜烬用普通玩家身份绕过一个小阻碍，但留下被误认成运气好的表面痕迹。",
            ],
            wow_beat="夜烬用异常掉落提前满足某个小前置，旁人却只以为他排队快或运气好。",
            ending_hook="章末公会占点规则挡住下一处资源点，夜烬必须找另一条散人路线。",
            state_delta="更新新手村渠道生态、NPC服务边界、散人路线压力和下一章资源点选择。",
            risk="不能把公会写成主动追杀主角；他们只能基于占点、收队内、压价和误判产生低强度压力。",
        ),
    ]


def _generic_options(story: StoryState, chapter_number: int) -> list[dict[str, Any]]:
    protagonist = _lead_name(story)
    focus = _compact(story.chapter_summaries[-1].next_focus if story.chapter_summaries else story.outline, 90)
    return [
        _option(
            option_id="pressure-choice",
            name="压力选择线",
            recommended=True,
            chapter_goal=f"{protagonist}围绕{focus or '当前目标'}做一个有代价的选择。",
            reader_promise="读者看到角色主动选择，而不是被剧情推着走。",
            main_scenes=["承接上一章未解压力", "让一个可见阻碍逼近", "主角用一个小代价换取推进"],
            wow_beat="一个旧线索在行动中改变用途。",
            ending_hook="章末落到下一步马上要付的代价。",
            state_delta="更新关系、资源或时间压力。",
            risk="不能跳过因果直接给大收益。",
        ),
        _option(
            option_id="relationship-friction",
            name="关系摩擦线",
            chapter_goal=f"{protagonist}通过一次对话或合作把关系压力推到台前。",
            reader_promise="读者看到人物互相误判和试探。",
            main_scenes=["旧关系带来请求或拒绝", "对话改变筹码", "选择留下新误会"],
            wow_beat="一句话让旧关系出现新用途。",
            ending_hook="章末留下一个必须面对的人。",
            state_delta="更新角色关系和信任/张力。",
            risk="不能让对话替作者讲设定。",
        ),
        _option(
            option_id="world-rule-payoff",
            name="规则兑现线",
            chapter_goal=f"{protagonist}用行动试出一条世界规则的代价。",
            reader_promise="读者从场面里看懂规则，而不是读百科。",
            main_scenes=["看见规则表面", "试一次并付成本", "拿到有限收益"],
            wow_beat="规则在一个小地方反转角色判断。",
            ending_hook="章末露出规则的下一层门槛。",
            state_delta="更新世界规则的可见证据。",
            risk="不能写成说明书。",
        ),
    ]


def build_chapter_direction_options(story: StoryState, chapter_number: int) -> dict[str, Any]:
    """Build legal next-chapter branches after world state is loaded."""

    options = _game_options(story, chapter_number) if _is_game_story(story) else _generic_options(story, chapter_number)
    recommended = next((item["id"] for item in options if item.get("recommended")), options[0]["id"] if options else "")
    return {
        "schema_version": "chapter-direction-options/v1",
        "chapter_number": chapter_number,
        "recommended_id": recommended,
        "selection_rule": "Choose one id before drafting to lock chapter_goal, wow_beat, ending_hook, and state_delta into the simulation plan.",
        "options": options,
    }


def normalize_chapter_direction_choice(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        return {}
    option_id = str(value.get("id") or "").strip()
    if not option_id:
        return {}
    return {
        key: value.get(key)
        for key in (
            "id",
            "name",
            "chapter_goal",
            "reader_promise",
            "main_scenes",
            "wow_beat",
            "ending_hook",
            "state_delta",
            "risk",
        )
        if value.get(key) not in (None, "", [], {})
    }
