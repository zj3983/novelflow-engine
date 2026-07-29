from __future__ import annotations

from typing import Any

from packages.story_core.models import (
    ArcRecap,
    ChapterSummary,
    MemoryIndexEntry,
    StoryState,
    TimelineEvent,
)
from packages.story_core.character_portraits import complete_character_portrait
from packages.story_core.genre_plugins import is_game_genre
from packages.story_core.novel_type_catalog import normalize_novel_type_id
from packages.story_core.planner import build_chapter_title
from packages.story_core.post_draft_memory import fallback_post_draft_memory


MEMORY_KEYWORDS = {
    "characters": [
        "苏叶",
        "夜烬",
        "赵胖子",
        "铁算盘",
        "王宇",
        "药剂师洛婶",
        "职业导师艾伦",
        "白袍-巡林",
        "灰烬村村长",
        "仓库管理员铁栓",
        "修理匠老葛",
    ],
    "locations": ["灰烬村", "灰烬村广场", "交易行", "西林狼坡", "黑水沼泽", "废弃祭坛", "职业大厅", "药剂铺", "仓库"],
    "factions": ["白袍公会", "赤焰公会", "星河商会", "黑鸦商会", "散人玩家"],
    "quests": ["元素回廊", "职业试炼", "新手任务", "清理沼泽毒蛙", "毒腺", "火种碎片", "声望任务"],
    "items": ["狼皮", "狼牙", "毒腺", "湿地草药", "火种碎片", "新手法杖", "金币", "银币", "铜币"],
    "tags": ["交易行", "市场异常", "公会", "NPC", "任务链", "资源点", "金手指", "混沌之种", "千倍爆率", "风控", "论坛", "职业试炼"],
}


def _unique_matches(text: str, candidates: list[str]) -> list[str]:
    result: list[str] = []
    for candidate in candidates:
        if candidate and candidate in text and candidate not in result:
            result.append(candidate)
    return result


def _story_dynamic_keywords(story: StoryState) -> dict[str, list[str]]:
    """Build memory keywords from the current story instead of demo defaults."""
    keywords = {key: list(values) for key, values in MEMORY_KEYWORDS.items()}
    for character in story.characters:
        for value in (character.name, getattr(character, "game_id", "")):
            value = str(value or "").strip()
            if value and value not in keywords["characters"]:
                keywords["characters"].append(value)
    for fact in story.world_facts:
        text = str(fact or "").strip()
        if not text:
            continue
        if any(token in text for token in ("村", "城", "镇", "楼", "山", "谷", "门", "殿", "宫")) and "规则" not in text:
            if text not in keywords["locations"]:
                keywords["locations"].append(text)
        if any(token in text for token in ("公会", "商会", "宗", "门派", "公司", "集团", "帝国", "学院")):
            if text not in keywords["factions"]:
                keywords["factions"].append(text)
        if "任务" in text or "试炼" in text:
            if text not in keywords["quests"]:
                keywords["quests"].append(text)
    return keywords


def _memory_query_terms(query: str) -> set[str]:
    terms: set[str] = set()
    for candidates in MEMORY_KEYWORDS.values():
        for candidate in candidates:
            if candidate and candidate in query:
                terms.add(candidate)
    for raw in query.replace("，", " ").replace("。", " ").replace("、", " ").split():
        token = raw.strip()
        if len(token) >= 2:
            terms.add(token)
    return terms


def add_chapter_memory_index(
    story: StoryState,
    *,
    chapter_number: int,
    chapter_title: str,
    summary: str,
    facts: list[str] | None = None,
    unresolved_threads: list[str] | None = None,
) -> None:
    text = "\n".join([chapter_title, summary, *(facts or []), *(unresolved_threads or [])])
    keywords = _story_dynamic_keywords(story)
    entry = MemoryIndexEntry(
        chapter_number=chapter_number,
        chapter_title=chapter_title,
        summary=summary,
        tags=_unique_matches(text, keywords["tags"]),
        characters=_unique_matches(text, keywords["characters"]),
        locations=_unique_matches(text, keywords["locations"]),
        factions=_unique_matches(text, keywords["factions"]),
        quests=_unique_matches(text, keywords["quests"]),
        items=_unique_matches(text, keywords["items"]),
        facts=list(facts or [])[:6],
        unresolved_threads=list(unresolved_threads or [])[:6],
    )
    story.memory_index = [item for item in story.memory_index if item.chapter_number != chapter_number]
    story.memory_index.append(entry)
    story.memory_index.sort(key=lambda item: item.chapter_number)
    if len(story.memory_index) > 240:
        story.memory_index = story.memory_index[-240:]


def retrieve_relevant_memories(story: StoryState, query: str, *, limit: int = 6) -> list[MemoryIndexEntry]:
    if not story.memory_index:
        return []
    query_terms = _memory_query_terms(query)
    latest_chapter = max((entry.chapter_number for entry in story.memory_index), default=0)

    def score(entry: MemoryIndexEntry) -> tuple[int, int]:
        searchable = set(entry.tags + entry.characters + entry.locations + entry.factions + entry.quests + entry.items)
        text = " ".join([entry.chapter_title, entry.summary, *entry.facts, *entry.unresolved_threads])
        overlap = len(searchable & query_terms)
        fuzzy = sum(1 for term in query_terms if term and term in text)
        recency = max(0, entry.chapter_number - latest_chapter)
        return (overlap * 10 + fuzzy * 3 + entry.chapter_number // 3, recency)

    ranked = sorted(story.memory_index, key=score, reverse=True)
    selected = [entry for entry in ranked if score(entry)[0] > 0][:limit]
    if len(selected) < min(limit, len(story.memory_index)):
        recent = sorted(story.memory_index, key=lambda item: item.chapter_number, reverse=True)
        for entry in recent:
            if entry not in selected:
                selected.append(entry)
            if len(selected) >= limit:
                break
    return selected[:limit]


def _top_values(entries: list[MemoryIndexEntry], attr: str, limit: int = 8) -> list[str]:
    counts: dict[str, int] = {}
    for entry in entries:
        for value in getattr(entry, attr, []):
            counts[value] = counts.get(value, 0) + 1
    return [value for value, _ in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:limit]]


def build_arc_recap(story: StoryState, start_chapter: int, end_chapter: int) -> ArcRecap:
    summaries = [
        item
        for item in story.chapter_summaries
        if start_chapter <= item.chapter_number <= end_chapter
    ]
    memories = [
        item
        for item in story.memory_index
        if start_chapter <= item.chapter_number <= end_chapter
    ]
    summary_texts = [item.summary for item in summaries if item.summary]
    key_tags = _top_values(memories, "tags", 8)
    key_characters = _top_values(memories, "characters", 6)
    key_locations = _top_values(memories, "locations", 6)
    key_factions = _top_values(memories, "factions", 6)
    key_quests = _top_values(memories, "quests", 6)
    open_threads: list[str] = []
    for item in summaries[-5:]:
        for thread in item.unresolved_threads:
            if thread and thread not in open_threads:
                open_threads.append(thread)
    recap_parts = [
        f"第{start_chapter}-{end_chapter}章完成阶段推进。",
        f"核心标签：{'、'.join(key_tags) or '暂无'}。",
        f"关键地点：{'、'.join(key_locations) or '暂无'}。",
        f"关键势力：{'、'.join(key_factions) or '暂无'}。",
    ]
    if summary_texts:
        recap_parts.append(f"阶段摘要：{summary_texts[-1][:220]}")
    return ArcRecap(
        start_chapter=start_chapter,
        end_chapter=end_chapter,
        recap="".join(recap_parts),
        key_threads=[
            value
            for value in [
                *[f"标签：{tag}" for tag in key_tags[:4]],
                *[f"任务：{quest}" for quest in key_quests[:3]],
                *[f"势力：{faction}" for faction in key_factions[:3]],
            ]
            if value
        ][:10],
        resolved_threads=[fact for summary in summaries[-3:] for fact in summary.facts[:2]][:8],
        open_threads=open_threads[:8],
        character_changes=[
            f"{name}在第{start_chapter}-{end_chapter}章持续参与主线。"
            for name in key_characters[:6]
        ],
        ledger_snapshot=story.progression_ledger,
    )


def maybe_update_arc_recap(story: StoryState, chapter_number: int, *, interval: int = 10) -> None:
    if chapter_number <= 0 or chapter_number % interval != 0:
        return
    start = chapter_number - interval + 1
    recap = build_arc_recap(story, start, chapter_number)
    story.arc_recaps = [
        item
        for item in story.arc_recaps
        if not (item.start_chapter == recap.start_chapter and item.end_chapter == recap.end_chapter)
    ]
    story.arc_recaps.append(recap)
    story.arc_recaps.sort(key=lambda item: item.end_chapter)
    if len(story.arc_recaps) > 24:
        story.arc_recaps = story.arc_recaps[-24:]


def _normalize_participant(item: dict | str) -> dict:
    if isinstance(item, dict):
        return {
            "name": item.get("name", ""),
            "goal": item.get("goal", ""),
        }
    return {
        "name": item,
        "goal": "",
    }


def _relationship_shift(goals: list[str]) -> tuple[float, float]:
    goal_text = " ".join(goals).lower()

    cooperative_words = ("protect", "save", "guard", "help")
    adversarial_words = ("expose", "find", "accuse", "hunt")

    if any(word in goal_text for word in cooperative_words):
        return 0.1, -0.1
    if any(word in goal_text for word in adversarial_words):
        return -0.1, 0.1
    return 0.05, 0.05


def _goal_topic(text: str) -> str:
    if len(text) > 24 and any("\u4e00" <= char <= "\u9fff" for char in text):
        for candidate in ("资源", "交易", "公会", "试炼", "线索", "材料", "身份"):
            if candidate in text:
                return candidate
        return "当前目标"
    lowered = text.lower()
    # Genre-agnostic topic extraction
    for candidate in (
        "witness", "ledger", "truth", "forgery", "letter",
        "archives", "archive", "secret", "artifact", "power",
        "cultivation", "treasure", "legacy", "realm", "formation",
    ):
        if candidate in lowered:
            return candidate
    return lowered.split()[-1] if lowered.split() else "truth"


def _promote_goal(character, intent: str) -> None:
    if not intent:
        return
    remaining = [goal for goal in character.goals if goal != intent]
    character.goals = [intent, *remaining]


def _primary_follow_up_intent(character_name: str, primary: dict) -> str:
    topic = _goal_topic(primary.get("collision", "the core objective"))
    lead = primary.get("lead", "the lead")
    opposition = primary.get("opposition", "the opposition")
    if character_name == lead:
        return f"在{opposition}缓过来之前抢先控制{topic}"
    if character_name == opposition:
        return f"阻止{lead}拿到{topic}"
    return ""


def _secondary_follow_up_intent(goal: str, secondary: dict) -> str:
    topic = _goal_topic(goal or secondary.get("detail", "the core objective"))
    return f"在侧面压力失控前先稳住{topic}"


def _build_next_focus(
    chapter_number: int,
    primary: dict,
    secondary: dict,
    unresolved_threads: list[str],
) -> str:
    for thread in unresolved_threads:
        lowered = thread.lower()
        if primary.get("lead", "").lower() in lowered or primary.get("opposition", "").lower() in lowered:
            return thread
        for participant in secondary.get("participants", []):
            participant_name = participant.get("name", "").lower() if isinstance(participant, dict) else str(participant).lower()
            if participant_name and participant_name in lowered:
                return thread

    lead = primary.get("lead", "")
    opposition = primary.get("opposition", "")
    if lead and opposition:
        topic = _goal_topic(primary.get("collision", "the main clash"))
        return f"回到{lead}与{opposition}围绕{topic}的争夺"

    if unresolved_threads:
        return unresolved_threads[0]

    return f"第{chapter_number}章之后，需要重新掀开最近一次压力爆点。"


def _generic_foreshadowing_text(chapter_number: int) -> str:
    """Generate a genre-agnostic foreshadowing hook."""
    hooks = [
        "某个被隐藏的秘密即将浮出水面。",
        "一场更大的风暴正在暗处酝酿。",
        "一个意想不到的身影在暗处注视着一切。",
        "某种被遗忘的力量正在苏醒。",
        "一条未被发现的线索悄然浮现。",
    ]
    # Use chapter number to deterministically pick a hook
    return hooks[chapter_number % len(hooks)]


def apply_post_chapter_updates(
    story: StoryState,
    body: str,
    chapter_number: int,
    conflict_summary: dict | None = None,
    event_beat: dict | None = None,
    post_draft_memory: dict[str, Any] | None = None,
) -> None:
    memory = (
        post_draft_memory
        if isinstance(post_draft_memory, dict)
        else fallback_post_draft_memory(body)
    )
    summary_text = str(memory.get("summary") or "").strip() or body.strip()[:240]
    facts = [str(item).strip() for item in memory.get("facts", []) if str(item).strip()][:12]
    unresolved_threads = [
        str(item).strip() for item in memory.get("unresolved_threads", []) if str(item).strip()
    ][:8]
    next_focus = str(memory.get("next_focus") or "").strip()
    primary = (conflict_summary or {}).get("primary_conflict", {})
    secondary = (conflict_summary or {}).get("secondary_conflict", {})
    by_name = {character.name: character for character in story.characters}
    for update in memory.get("character_updates", []):
        if not isinstance(update, dict):
            continue
        character = by_name.get(str(update.get("name") or "").strip())
        if character is None or character.frozen:
            continue
        emotion = str(update.get("emotion") or "").strip()
        goal = str(update.get("goal") or "").strip()
        location = str(update.get("location") or "").strip()
        evidence = str(update.get("evidence") or "").strip()
        if emotion:
            character.current_emotion = emotion
        if goal:
            _promote_goal(character, goal)
        if location:
            character.location = location
        if evidence:
            note = f"第{chapter_number}章：{evidence}"
            if note not in character.memory:
                character.memory.append(note)

    for fact in facts:
        if fact not in story.world_facts:
            story.world_facts.append(fact)
    story.timeline.append(
        TimelineEvent(
            chapter_number=chapter_number,
            summary=summary_text,
            impact=(facts[0] if facts else (unresolved_threads[0] if unresolved_threads else summary_text)),
        )
    )

    chapter_summary = ChapterSummary(
        chapter_number=chapter_number,
        chapter_title=str(memory.get("chapter_title") or "").strip()
        or build_chapter_title(
            chapter_number,
            conflict_summary or {},
            next_focus,
            genre=story.genre,
        ),
        summary=summary_text,
        facts=facts,
        unresolved_threads=unresolved_threads,
        next_focus=next_focus,
        primary_conflict=primary,
        secondary_conflict=secondary,
        event_beat=event_beat or {},
    )
    story.chapter_summaries.append(chapter_summary)
    add_chapter_memory_index(
        story,
        chapter_number=chapter_number,
        chapter_title=chapter_summary.chapter_title,
        summary=summary_text,
        facts=chapter_summary.facts,
        unresolved_threads=chapter_summary.unresolved_threads,
    )


def _is_protagonist(character: Any) -> bool:
    return getattr(character, "role", "") in {"protagonist", "主角"} or getattr(character, "name", "") == "苏叶"


def _is_game_story_for_cards(story: StoryState) -> bool:
    explicit_ids = [
        normalize_novel_type_id(item)
        for item in (getattr(story, "genre_plugin_ids", []) or [])
        if normalize_novel_type_id(item)
    ]
    if explicit_ids:
        return any(is_game_genre(item) for item in explicit_ids)
    explicit_genre = normalize_novel_type_id(getattr(story, "genre", ""))
    if explicit_genre:
        return is_game_genre(explicit_genre)
    text = " ".join(
        [
            str(getattr(story, "genre", "") or ""),
            str(getattr(story, "style", "") or ""),
            str(getattr(story, "outline", "") or ""),
            " ".join(str(fact) for fact in getattr(story, "world_facts", [])[:12]),
        ]
    )
    # Explicit genre IDs win over negative constraints such as “不写游戏”.
    return is_game_genre(text)


def _clean_dict(value: dict[str, Any]) -> dict[str, Any]:
    return {key: item for key, item in value.items() if item not in (None, "", [], {})}


def _profile_defaults(character: Any, story: StoryState) -> dict[str, Any]:
    if _is_protagonist(character) and _is_game_story_for_cards(story):
        panel = getattr(character, "game_panel", None)
        panel_data = panel.model_dump() if hasattr(panel, "model_dump") else {}
        return {
            "character_type": "gap-driven webgame protagonist; staged-goal protagonist",
            "core_motivation": "现实压力没有解决前，先把游戏收益路径验证清楚；隐藏异常优势，靠信息差和节奏拉开差距。",
            "behavior_logic": "有现实压力，但行动重点是暗中抢进度和藏住异常；多看公告、提示、NPC回话和别人忽略的细节，不写成凡事先看成本、先退、先问价。",
            "interaction_mode": "对NPC只问业务边界；对普通玩家不炫耀、不解释底牌；回答用完整口语，别用装高手式省略回答。",
            "poison_points": [
                "装高手式省略回答",
                "把谨慎写成只盯钱",
                "公开暴露掉落异常",
                "让NPC或路人全知隐藏机制",
                "法师兄等生硬称呼",
                "用规则说明替代动作和对话",
            ],
            "social_profile": {
                "class_pressure": "现实余额、房租和欠费压着他，压力不能在开局被解决。",
                "work_history": "做过外包测试，习惯先复核流程和边界。",
                "equipment_reality": "旧头盔和有限现金让每一步投入都有重量。",
            },
            "psychological_profile": {
                "desire": "找到一条能翻身但不立刻暴露的路。",
                "fear": "赌错最后一点机会，或让异常优势过早被别人盯上。",
                "defense": "先验证，再下注；紧张时会把话说慢说完整。",
            },
            "moral_profile": {
                "bottom_line": "不主动坑普通新手，不拿没确认的收益骗自己。",
                "gray_zone": "会利用信息差和地形，不把底牌交给别人。",
            },
            "story_function": "把隐藏爆率写成幕后领先和阶段爽点，而不是当众开挂炫耀。",
            "chapter_role": "本章要用行动暴露处境、验证优势、留下下一步目标。",
            "game_panel": _clean_dict(panel_data),
        }
    return {
        "character_type": "function-anchored supporting character",
        "core_motivation": "围绕自己的职位、利益或关系压力行动，不替主角解释世界。",
        "behavior_logic": "先按本职工作和已知信息反应，再表现个性。",
        "interaction_mode": "说话带生活口吻，只透露自己能知道的事。",
        "poison_points": ["全知主角秘密", "纯工具人问答", "替作者讲设定"],
        "story_function": "用小动作、态度和边界让场景落地。",
        "chapter_role": "给主角制造信息、阻力、误会或交易边界。",
    }


def _character_card(character: Any, story: StoryState) -> dict[str, Any]:
    character = complete_character_portrait(
        character,
        genre=str(getattr(story, "genre", "") or ""),
        story_function=str(getattr(character, "story_function", "") or ""),
    )
    defaults = _profile_defaults(character, story)
    profile = getattr(character, "performance_profile", None)
    voice = getattr(profile, "voice", None) if profile is not None else None
    npc_profile = getattr(character, "npc_profile", None)
    panel = getattr(character, "game_panel", None)
    panel_data = panel.model_dump() if hasattr(panel, "model_dump") else {}
    game_id = getattr(character, "game_id", "") or panel_data.get("game_id", "")
    game_story = _is_game_story_for_cards(story)
    identity = {
        "name": getattr(character, "name", ""),
        "role": getattr(character, "role", ""),
        "location": getattr(character, "location", ""),
    }
    if game_story:
        identity["game_id"] = game_id
    webnovel_profile = {
        "character_type": getattr(character, "character_type", "") or defaults.get("character_type", ""),
        "core_motivation": getattr(character, "core_motivation", "") or defaults.get("core_motivation", ""),
        "behavior_logic": getattr(character, "behavior_logic", "") or defaults.get("behavior_logic", ""),
        "interaction_mode": getattr(character, "interaction_mode", "") or defaults.get("interaction_mode", ""),
        "poison_points": list(getattr(character, "poison_points", []) or defaults.get("poison_points", [])),
    }
    dimensions = {
        "social": getattr(character, "social_profile", {}) or defaults.get("social_profile", {}),
        "psychological": getattr(character, "psychological_profile", {}) or defaults.get("psychological_profile", {}),
        "moral": getattr(character, "moral_profile", {}) or defaults.get("moral_profile", {}),
    }
    performance = {
        "speech_style": getattr(profile, "speech_style", "") if profile is not None else "",
        "action_style": getattr(profile, "action_style", "") if profile is not None else "",
        "risk_posture": getattr(profile, "risk_posture", "") if profile is not None else "",
        "emotional_triggers": list(getattr(profile, "emotional_triggers", []) if profile is not None else []),
        "decision_rules": list(getattr(profile, "decision_rules", []) if profile is not None else []),
        "reveal_limits": list(getattr(profile, "reveal_limits", []) if profile is not None else []),
        "voice": voice.model_dump() if hasattr(voice, "model_dump") else {},
    }
    npc_boundary = npc_profile.model_dump() if hasattr(npc_profile, "model_dump") else {}
    return {
        "name": getattr(character, "name", ""),
        "role": getattr(character, "role", ""),
        "identity": identity,
        "webnovel_profile": _clean_dict(webnovel_profile),
        "three_dimensions": _clean_dict(dimensions),
        "story_usage": _clean_dict(
            {
                "story_function": getattr(character, "story_function", "") or defaults.get("story_function", ""),
                "chapter_role": getattr(character, "chapter_role", "") or defaults.get("chapter_role", ""),
                "goals": list(getattr(character, "goals", [])),
                "current_emotion": getattr(character, "current_emotion", ""),
                "this_chapter_usage": {
                    "status": getattr(character, "current_emotion", "") or "neutral",
                    "drive": getattr(character, "core_motivation", "") or defaults.get("core_motivation", ""),
                    "function": getattr(character, "chapter_role", "") or defaults.get("chapter_role", ""),
                    "speech_tendency": getattr(profile, "speech_style", "") if profile is not None else defaults.get("interaction_mode", ""),
                },
            }
        ),
        "voice_and_action": _clean_dict(performance),
        "personality_portrait": character.personality_portrait.model_dump(),
        "continuity_locks": _clean_dict(
            {
                "memory": list(getattr(character, "memory", [])),
                "secrets": list(getattr(character, "secrets", [])),
                "relationships": {
                    key: value.model_dump() for key, value in getattr(character, "relationships", {}).items()
                },
                **({"game_panel": _clean_dict(panel_data)} if game_story else {}),
                "npc_boundary": _clean_dict(npc_boundary),
            }
        ),
    }


def build_character_cards(story: StoryState) -> list[dict]:
    return [_character_card(character, story) for character in story.characters]


def build_foreshadowing(story: StoryState, chapter_number: int) -> list[dict]:
    if not story.foreshadowing:
        return [
            {
                "text": _generic_foreshadowing_text(chapter_number),
                "first_chapter": chapter_number,
                "status": "open",
            }
        ]
    return [item.model_dump() for item in story.foreshadowing]
