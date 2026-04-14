from __future__ import annotations

from packages.story_core.models import StoryState
from packages.story_core.planner import build_chapter_title


# ── genre-agnostic detail sentences ──────────────────────────

_DETAIL_POOL = [
    "空气里多了一种说不清的味道，像是某种被刻意隐瞒的东西终于露出了边角。",
    "脚步声在远处停了停，又继续走远了。没有人回头。",
    "桌上的茶已经凉透，可没人有空去换一杯。",
    "窗外的光渐渐暗下来，屋里的影子被拉得很长。",
    "有人在门后站了一会儿，最后还是什么也没说就离开了。",
    "一个不该出现在这里的东西，安静地躺在它不该出现的位置上。",
    "风从缝隙里钻进来，吹动了一张没人注意到的纸。",
    "沉默持续得太久，久到连呼吸都变得小心翼翼。",
    "某个角落传来一声极轻的响动，像是有什么东西被轻轻推开了。",
    "他低头看了一眼自己的手，手心里多了一道不知道什么时候留下的痕迹。",
]


def _detail_sentence(story: StoryState, chapter_number: int) -> str:
    return _DETAIL_POOL[chapter_number % len(_DETAIL_POOL)]


# ── goal direction ───────────────────────────────────────────

def _goal_direction(goals: list[str]) -> str:
    goal_text = " ".join(goals).lower()
    if any(word in goal_text for word in ("protect", "save", "guard", "help", "hide")):
        return "cooperative"
    if any(word in goal_text for word in ("expose", "find", "accuse", "hunt")):
        return "adversarial"
    return "uncertain"


# ── relationship sentence ────────────────────────────────────

def _relationship_sentence(story: StoryState) -> str:
    if not story.characters or not story.characters[0].relationships:
        return "局面还没有给出答案，空气里只剩下层层逼近的压力。"

    lead = story.characters[0]
    relation = next(iter(lead.relationships.values()))
    direction = _goal_direction(lead.goals)
    if direction == "adversarial" or relation.tension >= 0.8:
        return f"{lead.name}与{relation.target}的每一次交锋，都在把这段脆弱同盟推向决裂。"
    if direction == "cooperative" or (relation.trust >= 0.5 and relation.tension <= 0.5):
        return f"{lead.name}与{relation.target}勉强维持着同步，连沉默都像一种试探后的信任。"
    return f"{lead.name}谨慎地观察着{relation.target}，还拿不准这段关系会倒向哪一边。"


# ── continuity sentence ──────────────────────────────────────

def _continuity_sentence(story: StoryState) -> str:
    parts: list[str] = []

    if story.world_facts:
        parts.append(f"上一章留下的事实仍在发酵：{story.world_facts[-1]}。")
    if story.foreshadowing:
        parts.append(f"先前埋下的暗线仍未熄灭：{story.foreshadowing[0].text}。")

    return "".join(parts)


# ── next focus sentence ──────────────────────────────────────

def _next_focus_sentence(story: StoryState) -> str:
    if not story.chapter_summaries:
        return ""

    next_focus = story.chapter_summaries[-1].next_focus
    if not next_focus:
        return ""

    return f"而这一章过后，新的焦点也已经浮出水面：{next_focus}。"


# ── opening hook sentence ────────────────────────────────────

def _opening_hook_sentence(story: StoryState) -> str:
    if not story.chapter_summaries:
        return ""

    next_focus = story.chapter_summaries[-1].next_focus
    if not next_focus:
        return ""

    return f"这一章一开场，所有目光都先被拉向了{next_focus}。"


# ── conflict participant count ───────────────────────────────

def _conflict_participant_count(conflict_summary: dict | None) -> int:
    if not conflict_summary:
        return 0

    primary = conflict_summary.get("primary_conflict", {})
    names = {primary.get("lead"), primary.get("opposition")} - {None, "", "circumstance"}
    secondary = conflict_summary.get("secondary_conflict", {})
    for participant in secondary.get("participants", []) or []:
        if isinstance(participant, dict):
            name = participant.get("name", "")
        else:
            name = str(participant)
        if name:
            names.add(name)
    return len(names)


# ── tempo ────────────────────────────────────────────────────

def _tempo(
    story: StoryState,
    conflict_summary: dict | None,
    event_beat: dict | None,
    cadence: str | None = None,
) -> str:
    if cadence in {"urgent", "measured", "breathing"}:
        return cadence

    style_text = (story.style or "").lower()
    genre_text = (story.genre or "").lower()

    score = 0
    participants = _conflict_participant_count(conflict_summary)
    score += 2 if participants >= 3 else 1 if participants == 2 else 0
    if conflict_summary and conflict_summary.get("stakes"):
        score += 1
    if conflict_summary and (conflict_summary.get("secondary_conflict") or {}).get("pressure") == "time":
        score += 1
    if event_beat and event_beat.get("turn"):
        score += 1

    if "tense" in style_text or "suspense" in style_text or "noir" in style_text:
        score += 2
    if "mystery" in genre_text:
        score += 1

    if score >= 5:
        return "urgent"
    if score >= 3:
        return "measured"
    return "breathing"


def _tempo_label(tempo: str) -> str:
    if tempo == "urgent":
        return "紧绷"
    if tempo == "measured":
        return "稳压"
    return "舒张"


# ── closing sentence ─────────────────────────────────────────

def _closing_sentence(tempo: str) -> str:
    if tempo == "urgent":
        return "章节末尾像刀锋骤然落下，谁也来不及把话说完。"
    if tempo == "measured":
        return "章节在一口被按住的呼吸里收住，真正的变化却已经开始。"
    return "章节收束得很轻，可轻并不意味着风暴已经过去。"


# ── resolve chapter title ────────────────────────────────────

def _resolve_chapter_title(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None,
    chapter_title_override: str | None = None,
) -> str:
    # 1. Explicit override (e.g. from DirectorDecision)
    if chapter_title_override:
        return chapter_title_override

    # 2. Existing summary for this chapter
    for summary in story.chapter_summaries:
        if summary.chapter_number == chapter_number and summary.chapter_title:
            return summary.chapter_title

    # 3. Build from conflict/topic
    latest_next_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""
    return build_chapter_title(
        chapter_number,
        conflict_summary,
        latest_next_focus,
        genre=story.genre,
    )


# ── narrative sentence builders ──────────────────────────────

def _narrate_lead(story: StoryState, chapter_number: int) -> str:
    lead = story.characters[0] if story.characters else None
    if lead is None:
        return "主角继续向迷局深处推进。"
    lead_goal = lead.goals[0] if lead.goals else "掌控局面"
    location = lead.location if lead.location else "迷局深处"
    direction = _goal_direction(lead.goals)

    if direction == "adversarial":
        return f"{lead.name}踏入{location}，目标只有一个：{lead_goal}。"
    if direction == "cooperative":
        return f"{lead.name}在{location}稳住阵脚，心里盘算着如何{lead_goal}。"
    return f"{lead.name}继续向{location}推进，试图{lead_goal}。"


def _narrate_primary_conflict(conflict_summary: dict | None) -> str:
    if not conflict_summary:
        return ""
    summary = conflict_summary.get("summary", "")
    if not summary:
        return ""
    # Convert meta-description into narrative form
    return summary


def _narrate_stakes(stakes: str | None) -> str:
    if not stakes:
        return ""
    return stakes


def _narrate_secondary_pressure(detail: str | None) -> str:
    if not detail:
        return ""
    return detail


def _narrate_event_pivot(event_line: str | None) -> str:
    if not event_line:
        return ""
    return event_line


# ── main chapter body writer ─────────────────────────────────

def write_chapter_body(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None = None,
    event_beat: dict | None = None,
    cadence: str | None = None,
    chapter_title_override: str | None = None,
) -> str:
    chapter_title = _resolve_chapter_title(story, chapter_number, conflict_summary, chapter_title_override)
    tempo_value = _tempo(story, conflict_summary, event_beat, cadence=cadence)
    tempo_label = _tempo_label(tempo_value)

    opening_hook_line = _opening_hook_sentence(story)
    relation_line = _relationship_sentence(story)
    continuity_line = _continuity_sentence(story)
    next_focus_line = _next_focus_sentence(story)

    primary_conflict = _narrate_primary_conflict(conflict_summary)
    stakes = _narrate_stakes(conflict_summary.get("stakes", "") if conflict_summary else "")
    secondary_line = _narrate_secondary_pressure(
        conflict_summary.get("secondary_conflict", {}).get("detail", "")
        if conflict_summary
        else ""
    )
    event_line = _narrate_event_pivot(event_beat.get("pivot", "") if event_beat else "")
    detail_line = _detail_sentence(story, chapter_number)
    closing_line = _closing_sentence(tempo_value)

    lead_narrative = _narrate_lead(story, chapter_number)

    parts = [
        f"第{chapter_number}章《{chapter_title}》",
        f"（节奏：{tempo_label}）",
        opening_hook_line,
        lead_narrative,
        primary_conflict,
        stakes and f"这一局真正的代价在于：{stakes}",
        secondary_line and f"旁侧压力也在同步逼近：{secondary_line}",
        event_line,
        relation_line,
        continuity_line,
        detail_line,
        next_focus_line,
        closing_line,
    ]
    return " ".join(part for part in parts if part).strip()
