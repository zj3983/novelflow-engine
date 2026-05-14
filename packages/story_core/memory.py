from __future__ import annotations

from packages.story_core.models import (
    ArcRecap,
    ChapterSummary,
    CharacterRelationship,
    ForeshadowingState,
    MemoryIndexEntry,
    StoryState,
    TimelineEvent,
)
from packages.story_core.planner import build_chapter_title


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
) -> None:
    fact = f"第{chapter_number}章确认调查仍在继续推进。"
    unresolved = f"第{chapter_number}章之后，谁会先掌控核心线索？"
    inherited_next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""

    participant_map = {character.name: character for character in story.characters}
    primary = (conflict_summary or {}).get("primary_conflict", {})
    secondary = (conflict_summary or {}).get("secondary_conflict", {})
    primary_names = {primary.get("lead"), primary.get("opposition")} - {None, ""}
    secondary_participants = [
        _normalize_participant(item) for item in secondary.get("participants", [])
    ]
    secondary_names = {item["name"] for item in secondary_participants}
    secondary_goals = {item["name"]: item.get("goal", "") for item in secondary_participants}

    for character in story.characters:
        if character.frozen:
            continue

        touched = False
        if character.name in primary_names:
            collision = primary.get("collision", "the main clash")
            character.memory.append(
                f'第{chapter_number}章中，{character.name}因自身利益被卷入"{_goal_topic(collision)}"冲突，下一步会按自己的底线和风险判断行动。'
            )
            _promote_goal(character, _primary_follow_up_intent(character.name, primary))
            character.current_emotion = "alert"
            touched = True
        elif character.name in secondary_names:
            detail = secondary.get("detail", "side pressure")
            goal = secondary_goals.get(character.name, "hold the line")
            character.memory.append(
                f'第{chapter_number}章中，{character.name}承受"{_goal_topic(detail)}"侧面压力，行动目标是{goal}。'
            )
            _promote_goal(character, _secondary_follow_up_intent(goal, secondary))
            character.current_emotion = "wary"
            touched = True

        if touched and not character.location:
            character.location = "迷局深处"

        if character.name == story.characters[0].name and character.relationships:
            key = next(iter(character.relationships))
            relation = character.relationships[key]
            trust_delta, tension_delta = _relationship_shift(character.goals)
            character.relationships[key] = CharacterRelationship(
                target=relation.target,
                trust=max(0.0, min(1.0, round(relation.trust + trust_delta, 2))),
                tension=max(0.0, min(1.0, round(relation.tension + tension_delta, 2))),
                bond=relation.bond,
            )

    story.world_facts.append(fact)
    story.timeline.append(
        TimelineEvent(
            chapter_number=chapter_number,
            summary=f"第{chapter_number}章把核心谜团继续向前推进。",
            impact="主要角色承受的整体压力继续上升",
        )
    )

    chapter_summary = ChapterSummary(
        chapter_number=chapter_number,
        chapter_title=build_chapter_title(
            chapter_number,
            conflict_summary or {},
            inherited_next_focus or _build_next_focus(chapter_number, primary, secondary, [unresolved]),
            genre=story.genre,
        ),
        summary=body,
        facts=[fact],
        unresolved_threads=[unresolved],
        next_focus=inherited_next_focus
        or _build_next_focus(chapter_number, primary, secondary, [unresolved]),
        primary_conflict=primary,
        secondary_conflict=secondary,
        event_beat=event_beat or {},
    )
    story.chapter_summaries.append(chapter_summary)
    add_chapter_memory_index(
        story,
        chapter_number=chapter_number,
        chapter_title=chapter_summary.chapter_title,
        summary=body,
        facts=chapter_summary.facts,
        unresolved_threads=chapter_summary.unresolved_threads,
    )

    # Genre-agnostic foreshadowing
    if not story.foreshadowing:
        story.foreshadowing.append(
            ForeshadowingState(
                text=_generic_foreshadowing_text(chapter_number),
                first_chapter=chapter_number,
                status="open",
            )
        )
    else:
        story.foreshadowing[0].status = "reinforced"


def build_character_cards(story: StoryState) -> list[dict]:
    return [
        {
            "name": c.name,
            "role": c.role,
            "memory": list(c.memory),
            "current_emotion": c.current_emotion,
            "location": c.location,
            "goals": list(c.goals),
            "relationships": {key: value.model_dump() for key, value in c.relationships.items()},
        }
        for c in story.characters
    ]


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
