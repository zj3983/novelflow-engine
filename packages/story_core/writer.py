from __future__ import annotations

from packages.story_core.models import StoryState
from packages.story_core.planner import build_chapter_title


def _resolve_chapter_title(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None,
    chapter_title_override: str | None = None,
) -> str:
    if chapter_title_override:
        return chapter_title_override

    for summary in story.chapter_summaries:
        if summary.chapter_number == chapter_number and summary.chapter_title:
            return summary.chapter_title

    latest_focus = story.chapter_summaries[-1].next_focus if story.chapter_summaries else ""
    return build_chapter_title(chapter_number, conflict_summary, latest_focus, genre=story.genre)


def _tempo_label(cadence: str | None) -> str:
    if cadence == "urgent":
        return "紧绷"
    if cadence == "breathing":
        return "舒张"
    return "稳压"


def _lead(story: StoryState):
    return story.characters[0] if story.characters else None


def _first_goal(character) -> str:
    if not character or not character.goals:
        return "稳住当前局面"
    return character.goals[0]


def _is_game_novel(story: StoryState, event_plan: dict | None) -> bool:
    haystack = " ".join(
        [
            story.genre,
            story.style,
            story.outline,
            str((event_plan or {}).get("pivot", "")),
            str((event_plan or {}).get("collision", "")),
        ]
    )
    return any(token in haystack for token in ("网游", "游戏", "新手村", "副本", "公会", "登录", "升级", "VRMMO"))


def _world_anchor(story: StoryState, memory_constraints: dict | None) -> str:
    if memory_constraints:
        facts = memory_constraints.get("must_keep_facts", [])
        if isinstance(facts, list) and facts:
            return str(facts[0]).strip()
    if story.world_facts:
        return story.world_facts[-1]
    return ""


def _pick_named_actions(event_plan: dict | None) -> list[dict]:
    if not event_plan:
        return []
    actions = event_plan.get("ordered_actions", [])
    if not isinstance(actions, list):
        return []
    cleaned: list[dict] = []
    for item in actions[:4]:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        cleaned.append(
            {
                "name": name,
                "goal": str(item.get("goal", "")).strip(),
                "action": str(item.get("action", "")).strip(),
            }
        )
    return cleaned


def _opening_paragraph(
    story: StoryState,
    conflict_summary: dict | None,
    event_plan: dict | None,
    memory_constraints: dict | None,
) -> str:
    lead = _lead(story)
    lead_name = lead.name if lead else "主角"
    goal = _first_goal(lead)
    pivot = str((event_plan or {}).get("pivot", "")).strip()
    collision = str((event_plan or {}).get("collision", "")).strip()
    anchor = _world_anchor(story, memory_constraints)

    if _is_game_novel(story, event_plan):
        parts = [
            f"{lead_name}重新上线的时候，天启之门的晨雾还没从新手村外散干净。",
            f"他先确认了一遍今天最不能拖的事：{goal}。",
        ]
        if anchor:
            parts.append(f"可真正让他不敢放松的，不是经验条涨得慢，而是那条已经摆在眼前的硬事实：{anchor}。")
        if pivot:
            parts.append(f"也正因为这样，原本该是平稳发育的一天，被{pivot}硬生生拽进了台前。")
        elif collision:
            parts.append(f"也正因为这样，局势很快顺着{collision}的方向压了过来。")
        return "".join(parts)

    parts = [f"{lead_name}一开始只是想先把手头最要紧的事处理掉：{goal}。"]
    if anchor:
        parts.append(f"可眼下最不容忽视的事实只有一个：{anchor}。")
    if pivot:
        parts.append(f"局面真正拧紧的地方，也正是{pivot}。")
    return "".join(parts)


def _stakes_paragraph(conflict_summary: dict | None) -> str:
    stakes = str((conflict_summary or {}).get("stakes", "")).strip()
    if not stakes:
        return ""
    return f"苏叶心里很清楚，这一章真正危险的地方不在眼前谁赢谁输，而在于{stakes}。"


def _build_scene_paragraphs(story: StoryState, event_plan: dict | None) -> list[str]:
    actions = _pick_named_actions(event_plan)
    if not actions:
        return []

    lead_name = _lead(story).name if _lead(story) else ""
    others = [item for item in actions if item["name"] != lead_name]
    paragraphs: list[str] = []

    if _is_game_novel(story, event_plan):
        if others:
            first = others[0]
            paragraphs.append(
                f"最先找上门的是{first['name']}。对方没有把话说得太透，可那种一步步把人往墙角逼的劲道却很明显，"
                f"摆明了是冲着“{first['goal'] or first['action']}”来的。"
            )
        if lead_name:
            paragraphs.append(
                f"{lead_name}没有立刻翻脸，只是一边顺着任务面板和周围玩家的动静往下看，一边在心里重新摆正顺序。"
                f"他知道，眼下每多说一句废话，都可能把本该属于自己的节奏拱手让出去。"
            )
        if len(others) > 1:
            second = others[1]
            paragraphs.append(
                f"偏偏侧面也没有空出来。{second['name']}像是早就盯住了这条线，"
                f"明里暗里都在给局面加压，逼得整件事越来越不像一次普通接触，反而更像试探后手的前哨。"
            )
        return paragraphs

    for item in others[:2]:
        paragraphs.append(
            f"{item['name']}先动了。对方表面上还算克制，真正的力道却都藏在后手里，"
            f"显然是想借着“{item['goal'] or item['action']}”把场面一点点拧紧。"
        )
    return paragraphs


def _constraint_paragraphs(memory_constraints: dict | None) -> list[str]:
    if not memory_constraints:
        return []

    paragraphs: list[str] = []
    unresolved = memory_constraints.get("unresolved_threads", [])
    if isinstance(unresolved, list) and unresolved:
        paragraphs.append(f"更麻烦的是，那条还没真正收束的暗线始终压在众人头顶：{unresolved[0]}。")

    foreshadowing = memory_constraints.get("protected_foreshadowing", [])
    if isinstance(foreshadowing, list) and foreshadowing:
        first = foreshadowing[0]
        if isinstance(first, dict):
            text = str(first.get("text", "")).strip()
            if text:
                paragraphs.append(f"那一点若有若无的预兆并没有消失，反而在这时候显得更刺眼：{text}。")

    author_constraints = memory_constraints.get("author_constraints", [])
    if isinstance(author_constraints, list):
        cleaned = [str(item).strip() for item in author_constraints[:2] if str(item).strip()]
        if cleaned:
            paragraphs.append(
                f"所以这一局没有侥幸，也没有天降答案。苏叶只能沿着既定规则一点点往前拱，"
                f"每一步都得自己扛住：{'；'.join(cleaned)}。"
            )

    return paragraphs


def _pivot_paragraph(event_beat: dict | None, event_plan: dict | None) -> str:
    pivot = str((event_plan or {}).get("pivot", "")).strip() or str((event_beat or {}).get("pivot", "")).strip()
    collision = str((event_plan or {}).get("collision", "")).strip()
    if pivot and collision:
        return f"等到场面真正撞响的时候，所有人都看明白了：{pivot}，而这背后牵出来的，正是{collision}。"
    if pivot:
        return f"真正把局面推到明处的，还是{pivot}。"
    return ""


def _closing_paragraph(story: StoryState, event_plan: dict | None) -> str:
    next_focus = str((event_plan or {}).get("next_focus", "")).strip()
    if not next_focus and story.chapter_summaries:
        next_focus = story.chapter_summaries[-1].next_focus

    if next_focus:
        return f"这一章收住时，局面并没有真正落定。新的压力已经顺着缝隙渗出来，下一步绕不开的，正是{next_focus}。"
    return "这一章收住时，表面上风平浪静，真正的变化却已经在水面下换了方向。"


def write_chapter_body(
    story: StoryState,
    chapter_number: int,
    conflict_summary: dict | None = None,
    event_beat: dict | None = None,
    cadence: str | None = None,
    chapter_title_override: str | None = None,
    event_plan: dict | None = None,
    memory_constraints: dict | None = None,
) -> str:
    chapter_title = _resolve_chapter_title(story, chapter_number, conflict_summary, chapter_title_override)
    tempo_label = _tempo_label(cadence)

    paragraphs: list[str] = [
        f"第{chapter_number}章《{chapter_title}》",
        f"（节奏：{tempo_label}）",
        "",
        _opening_paragraph(story, conflict_summary, event_plan, memory_constraints),
    ]

    stakes = _stakes_paragraph(conflict_summary)
    if stakes:
        paragraphs.append(stakes)

    paragraphs.extend(_build_scene_paragraphs(story, event_plan))
    paragraphs.extend(_constraint_paragraphs(memory_constraints))

    pivot = _pivot_paragraph(event_beat, event_plan)
    if pivot:
        paragraphs.append(pivot)

    paragraphs.append(_closing_paragraph(story, event_plan))
    return "\n\n".join(part for part in paragraphs if part).strip()
