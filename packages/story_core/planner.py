from __future__ import annotations

from packages.story_core.character_agent import CharacterAgent
from packages.story_core.models import StoryState


def _participant_entry(name: str, goal: str = "") -> dict:
    return {
        "name": name,
        "goal": goal,
    }


def _participant_name(item: dict | str) -> str:
    if isinstance(item, dict):
        return item.get("name", "")
    return item


def _goal_polarity(goal: str) -> str:
    goal_text = goal.lower()
    if any(word in goal_text for word in ("protect", "save", "guard", "help", "hide")):
        return "defensive"
    if any(word in goal_text for word in ("expose", "find", "accuse", "hunt")):
        return "aggressive"
    return "neutral"


def _goal_topic(goal: str) -> str:
    goal_text = goal.lower()
    # Genre-agnostic topic extraction: try to find the most meaningful noun
    # If no known keyword matches, fall back to the last meaningful word
    for candidate in (
        "witness", "ledger", "truth", "forgery", "letter",
        "archives", "archive", "secret", "artifact", "power",
        "cultivation", "treasure", "legacy", "realm", "formation",
    ):
        if candidate in goal_text:
            return candidate
    return goal_text.split()[-1] if goal_text.split() else "truth"


def _latest_next_focus(story: StoryState) -> str:
    if not story.chapter_summaries:
        return ""
    return story.chapter_summaries[-1].next_focus


def _is_game_opening_chapter(story: StoryState) -> bool:
    if story.current_chapter != 1:
        return False
    context = " ".join([story.genre, story.style, story.outline, *story.world_facts]).lower()
    return any(token in context for token in ("网游", "vrmmo", "游戏", "game_webnovel", "天启之门"))


def _is_game_opening_arc(story: StoryState) -> bool:
    if story.current_chapter not in (1, 2, 3):
        return False
    context = " ".join([story.genre, story.style, story.outline, *story.world_facts]).lower()
    return any(token in context for token in ("网游", "vrmmo", "游戏", "game_webnovel", "天启之门"))


def _early_game_opposition(rival: dict) -> str:
    name = str(rival.get("name", "")).strip()
    if any(token in name for token in ("商人", "铁算盘", "赵胖子")):
        return name
    if any(token in name for token in ("公会", "白袍", "赤焰", "星河")):
        return "公会外围与资源点秩序"
    return "交易行、补给消耗与公会外围"


def _topic_zh(topic: str, genre: str = "") -> str:
    """Map English topic keywords to Chinese chapter title words.
    
    Falls back to genre-appropriate defaults when the topic is generic.
    """
    genre_lower = genre.lower()
    is_xianxia = any(w in genre_lower for w in ("xianxia", "cultivation", "仙侠", "修真", "修仙"))
    is_fantasy = any(w in genre_lower for w in ("fantasy", "奇幻", "玄幻", "魔幻"))
    is_wuxia = any(w in genre_lower for w in ("wuxia", "武侠", "江湖"))

    mapping: dict[str, str] = {
        "witness": "证人",
        "ledger": "账本",
        "truth": "真相",
        "forgery": "伪证",
        "letter": "密信",
        "archives": "档案",
        "archive": "秘档",
        "pressure": "压痕",
        # Cultivation / Xianxia
        "secret": "秘辛",
        "artifact": "神器",
        "power": "灵力",
        "cultivation": "修行",
        "treasure": "法宝",
        "legacy": "传承",
        "realm": "境界",
        "formation": "阵法",
    }
    
    result = mapping.get(topic, "")
    if result:
        return result
    
    # Genre-appropriate fallback for unknown topics
    if is_xianxia or is_fantasy:
        return "玄机"
    if is_wuxia:
        return "暗流"
    return "迷局"


def _pressure_zh(pressure: str) -> str:
    mapping = {
        "time": "时间",
        "setup": "铺垫",
    }
    return mapping.get(pressure, pressure or "局势")


def compute_chapter_cadence(
    story: StoryState,
    action_briefs: list[dict],
    conflict_summary: dict,
) -> str:
    score = 0

    cast_size = len(action_briefs)
    if cast_size >= 4:
        score += 3
    elif cast_size >= 3:
        score += 2
    elif cast_size == 2:
        score += 1

    lead_priority = action_briefs[0].get("priority", 0) if action_briefs else 0
    if lead_priority >= 9:
        score += 2
    elif lead_priority >= 7:
        score += 1

    if story.chapter_summaries:
        prior_threads = len(story.chapter_summaries[-1].unresolved_threads)
        if prior_threads >= 3:
            score += 2
        elif prior_threads >= 2:
            score += 1

    if story.foreshadowing:
        score += 1

    primary = (conflict_summary or {}).get("primary_conflict", {})
    lead_name = primary.get("lead", "")
    opposition_name = primary.get("opposition", "")
    if lead_name and opposition_name and action_briefs:
        by_name = {brief.get("name", ""): brief for brief in action_briefs}
        lead_goal = by_name.get(lead_name, {}).get("goal", "")
        opp_goal = by_name.get(opposition_name, {}).get("goal", "")
        if lead_goal and opp_goal and _goal_polarity(lead_goal) != _goal_polarity(opp_goal):
            score += 1

    if score >= 6:
        return "urgent"
    if score >= 3:
        return "measured"
    return "breathing"


def build_chapter_title(
    chapter_number: int,
    conflict_summary: dict | None = None,
    next_focus: str = "",
    genre: str = "",
) -> str:
    genre_lower = (genre or "").lower()
    source_probe = " ".join([str(next_focus or ""), str(conflict_summary or "")])
    if any(token in genre_lower for token in ("网游", "game_webnovel", "vrmmo", "游戏")):
        if any(token in source_probe for token in ("清道夫", "灰狼", "毒腺", "委托")):
            return "清道夫委托"
        if any(token in source_probe for token in ("补给", "耐久", "成本", "铜币", "寄售", "材料")):
            return "回村补给"

    allowed_topics = {
        "witness", "ledger", "forgery", "letter",
        "archives", "archive", "truth", "secret",
        "artifact", "power", "cultivation", "treasure",
        "legacy", "realm", "formation",
    }

    source_text = next_focus
    if not source_text and conflict_summary:
        primary = conflict_summary.get("primary_conflict", {})
        source_text = primary.get("collision", "") or conflict_summary.get("summary", "")

    topic = _goal_topic(source_text or "pressure").strip(" \t\r\n.,;:!?\"'()[]{}").lower()
    if not topic or topic not in allowed_topics:
        topic = "truth"

    if "mystery" in genre_lower or "suspense" in genre_lower:
        flavor = "疑云"
    elif "court" in genre_lower or "intrigue" in genre_lower or "political" in genre_lower:
        flavor = "风声"
    elif "xianxia" in genre_lower or "cultivation" in genre_lower or "仙侠" in genre_lower or "修真" in genre_lower:
        flavor = "道韵"
    elif "fantasy" in genre_lower or "奇幻" in genre_lower or "玄幻" in genre_lower:
        flavor = "异兆"
    elif "wuxia" in genre_lower or "武侠" in genre_lower:
        flavor = "剑影"
    elif "noir" in genre_lower:
        flavor = "暗影"
    else:
        flavor = "交锋"

    return f"{_topic_zh(topic, genre)}{flavor}"


def build_action_briefs(story: StoryState) -> list[dict]:
    return [proposal.model_dump() for proposal in CharacterAgent().propose_all(story)]


def select_primary_pair(action_briefs: list[dict]) -> tuple[dict, dict | None]:
    if not action_briefs:
        return {}, None

    lead = action_briefs[0]
    rival = None
    best_score = -1
    for candidate in action_briefs[1:]:
        score = 0
        if _goal_topic(candidate["goal"]) == _goal_topic(lead["goal"]):
            score += 2
        if _goal_polarity(candidate["goal"]) != _goal_polarity(lead["goal"]):
            score += 2
        if candidate["emotion"] != lead["emotion"]:
            score += 1
        if score > best_score:
            best_score = score
            rival = candidate
    return lead, rival


def build_conflict_summary(story: StoryState, action_briefs: list[dict]) -> dict:
    if not action_briefs:
        return {
            "summary": "当前还没有真正爆发的正面冲突。",
            "stakes": "这一章首先要完成局势铺垫，让压力有落点。",
            "primary_conflict": {
                "lead": "",
                "opposition": "",
                "collision": "碰撞尚未成形。",
            },
            "secondary_conflict": {
                "pressure": "setup",
                "detail": "人物与线索都还需要一个足够强的引爆点。",
                "participants": [],
            },
        }

    lead, rival = select_primary_pair(action_briefs)
    if rival is None:
        return {
            "summary": f"{lead['name']}独自推进，试图{lead['goal']}。",
            "stakes": f"如果{lead['name']}失手，刚刚浮出的线索就会迅速失温。",
            "primary_conflict": {
                "lead": lead["name"],
                "opposition": "circumstance",
                "collision": f"{lead['name']}必须尽快{lead['goal']}，否则线索会先一步断掉。",
            },
            "secondary_conflict": {
                "pressure": "time",
                "detail": "拖延只会让新线索重新沉回流言和噪音里。",
                "participants": [_participant_entry(lead["name"], lead["goal"])],
            },
        }

    secondary_candidates = [
        _participant_entry(candidate["name"], candidate["goal"])
        for candidate in action_briefs[1:]
        if candidate["name"] != rival["name"]
    ]

    if _is_game_opening_chapter(story):
        return {
            "summary": f"{lead['name']}想要完成首次收益闭环并隐藏异常优势，而{rival['name']}只能从交易行价格、匿名批次和时间戳里试探货源。",
            "stakes": "第一章的风险不是正面夺资源，而是现实资金压力、隐藏优势是否可靠，以及主角能不能把高爆率转成进度领先。",
            "primary_conflict": {
                "lead": lead["name"],
                "opposition": rival["name"],
                "collision": f"{lead['name']}必须先确认高爆率能否让自己少跑几趟、早一步完成前置任务或凑齐装备条件，{rival['name']}此时最多只能看到价格曲线、时间戳、普通玩家误读或资源点传闻。",
            },
            "secondary_conflict": {
                "pressure": "market-signal",
                "detail": "低级材料只是大型服务器噪音；外部势力需要稀有物、榜单、资源点目击、NPC任务异常或多源记录汇总后才能逼近。",
                "participants": secondary_candidates or [_participant_entry(rival["name"], rival["goal"])],
            },
        }

    if _is_game_opening_arc(story):
        opposition = _early_game_opposition(rival)
        return {
            "summary": (
                f"{lead['name']}继续验证千倍爆率、补给消耗和交易节奏，"
                f"{opposition}只能通过材料价格、匿名批次、资源点目击和NPC服务记录逐步逼近。"
            ),
            "stakes": "第二、三章的压力应来自可见规则逐步收紧，而不是商人或公会突然全知全能。",
            "primary_conflict": {
                "lead": lead["name"],
                "opposition": opposition,
                "collision": (
                    f"{lead['name']}必须在耐久、背包、前置任务和路线选择之间继续滚雪球，"
                    f"{opposition}只能从价格曲线、补给流水、任务进度、资源点传闻、榜单变化和NPC反馈里慢慢缩小范围。"
                ),
            },
            "secondary_conflict": {
                "pressure": "market-signal",
                "detail": "NPC任务进度、补给消耗、资源点目击和普通玩家对比共同形成弱线索，公会只能外围试探，不能直接锁定真相。",
                "participants": secondary_candidates or [_participant_entry(rival["name"], rival["goal"])],
            },
        }

    return {
        "summary": f"{lead['name']}想要{lead['goal']}，而{rival['name']}则试图{rival['goal']}。",
        "stakes": "无论谁在这一局赢得太干净，关键的控制权都会立刻倾斜。",
        "primary_conflict": {
            "lead": lead["name"],
            "opposition": rival["name"],
            "collision": f"{lead['name']}与{rival['name']}正面撞上，争的就是核心资源的控制权。",
        },
        "secondary_conflict": {
            "pressure": "time",
            "detail": "每拖一步，局势就会更加复杂。",
            "participants": secondary_candidates or [_participant_entry(rival["name"], rival["goal"])],
        },
    }


def build_event_beat(conflict_summary: dict) -> dict:
    primary = conflict_summary.get("primary_conflict", {})
    secondary = conflict_summary.get("secondary_conflict", {})
    pivot = primary.get("collision", "这一章还缺少真正的转折。")
    participant_names = [
        _participant_name(item)
        for item in secondary.get("participants", [])
        if _participant_name(item)
    ]
    if participant_names:
        pivot = f"{pivot} 与此同时，{'、'.join(participant_names)}也在侧面不断挤压局势。"
    return {
        "turn": "pressure spike",
        "pivot": pivot,
    }


def plan_next_outline(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None = None,
    cadence: str | None = None,
) -> str:
    lead = story.characters[0].name if story.characters else "主角"
    next_focus = _latest_next_focus(story)
    cadence_clause = ""
    if cadence == "urgent":
        cadence_clause = " 下一章要更快，不给人物太多喘息空间。"
    elif cadence == "breathing":
        cadence_clause = " 下一章可以稍微放缓，但要把暗流托起来。"
    elif cadence == "measured":
        cadence_clause = " 下一章继续稳稳加压，不要泄劲。"
    if conflict_summary and conflict_summary.get("primary_conflict"):
        primary = conflict_summary["primary_conflict"]
        secondary = conflict_summary.get("secondary_conflict", {})
        focus_clause = f" 继续咬住上一轮焦点：{next_focus}。" if next_focus else ""
        pressure_zh = _pressure_zh(secondary.get('pressure', '时机'))
        return (
            f"第{chapter_number + 1}章：逼{primary['lead']}与{primary['opposition']}把这场碰撞再往前推一步，"
            f'同时继续放大"{pressure_zh}"带来的压迫，'
            "并明确下一轮究竟是谁先抓住关键线索。"
            f"{focus_clause}{cadence_clause}"
        )

    if next_focus:
        return (
            f'第{chapter_number + 1}章：从"{next_focus}"切入，继续抬高信任与紧张，'
            f"让至少一条未解线索更接近曝光。{cadence_clause}"
        )

    return (
        f"第{chapter_number + 1}章：逼{lead}立刻对最新线索做出行动，"
        f"继续抬高信任与紧张，并让至少一条未解线索更接近曝光。{cadence_clause}"
    )
