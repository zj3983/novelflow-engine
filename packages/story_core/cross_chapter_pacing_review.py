"""Cross-chapter pacing reviewer.

Inspired by webnovel-writer v5.5's HARD-003 "节奏灾难" check. Reads the last
N chapter summaries from ``StoryState.history`` and applies four red-line
checks against the active ``GenreProfile``:

  1. **Stagnation** (HARD): consecutive no-progress chapters >= profile
     ``stagnation_threshold``. Triggers HARD-003 equivalent.
  2. **Quest strand exclusivity** (SOFT): too many consecutive chapters on
     quest strand without touching emotion or world strands.
  3. **Emotion strand gap** (SOFT): too many chapters since the last beat
     on the emotion strand. Romance / dog-blood profiles are strict (gap_max
     = 2); web-game profiles are lax (gap_max = 20).
  4. **Transition chapter run** (SOFT): too many consecutive transition
     chapters in a row. Stories that pile up filler arcs lose readers.

Score keys:

  * ``pacing_stagnation`` (HARD)
  * ``pacing_quest_strand`` (SOFT)
  * ``pacing_emotion_gap`` (SOFT)
  * ``pacing_transition_run`` (SOFT)
"""
from __future__ import annotations

from typing import Any

from packages.story_core.genre_profile import GenreProfile


# ---------------------------------------------------------------------------
# Strand classification — heuristic token lookup over chapter facts/summary
# ---------------------------------------------------------------------------

_QUEST_TOKENS: tuple[str, ...] = (
    "任务", "委托", "材料", "挂单", "成交", "兑现", "收益", "职业",
    "试炼", "副本", "通关", "升级", "经验", "等级", "刷怪", "击杀",
    "金币", "铜币", "银币", "灵石", "贡献",
)
_EMOTION_TOKENS: tuple[str, ...] = (
    "信任", "试探", "承诺", "告白", "隔阂", "和好", "对话", "眼神",
    "心意", "误会", "亲密", "靠近", "吃醋", "心疼", "心动", "拥抱",
    "牵手", "情绪", "心结", "原谅",
)
_WORLD_TOKENS: tuple[str, ...] = (
    "公会", "势力", "宗门", "规则", "秘境", "线索", "真相", "组织",
    "幕后", "档案", "古卷", "传闻", "阵营", "家族", "国度", "禁地",
    "圣域", "议会", "联盟",
)
_TRANSITION_TOKENS: tuple[str, ...] = (
    "过渡", "铺垫", "休整", "路上", "赶路", "等待", "回程", "夜幕",
    "晨光", "无事", "平静", "暂歇", "短暂",
)


def _bundle_field(bundle: Any, field: str, default: Any = "") -> Any:
    """Read a field from a ChapterBundle-like object, working with both
    pydantic models and plain dicts."""
    if isinstance(bundle, dict):
        return bundle.get(field, default)
    return getattr(bundle, field, default)


def _summary_dict(bundle: Any) -> dict[str, Any]:
    summary = _bundle_field(bundle, "chapter_summary", {})
    if hasattr(summary, "model_dump"):
        summary = summary.model_dump()
    if not isinstance(summary, dict):
        return {}
    return summary


def _chapter_text(bundle: Any) -> str:
    summary = _summary_dict(bundle)
    parts = [
        str(_bundle_field(bundle, "chapter_title", "") or ""),
        str(_bundle_field(bundle, "next_outline", "") or ""),
        str(summary.get("summary", "") or ""),
        " ".join(str(item) for item in summary.get("facts", []) or []),
        " ".join(str(item) for item in summary.get("unresolved_threads", []) or []),
    ]
    return " ".join(part for part in parts if part)


def _classify_strands(bundle: Any) -> set[str]:
    text = _chapter_text(bundle)
    strands: set[str] = set()
    if any(token in text for token in _QUEST_TOKENS):
        strands.add("quest")
    if any(token in text for token in _EMOTION_TOKENS):
        strands.add("emotion")
    if any(token in text for token in _WORLD_TOKENS):
        strands.add("world")
    return strands


def _is_transition(bundle: Any) -> bool:
    text = _chapter_text(bundle)
    if any(token in text for token in _TRANSITION_TOKENS):
        return True
    summary = _summary_dict(bundle)
    event_beat = summary.get("event_beat", {}) or {}
    if isinstance(event_beat, dict) and not (
        event_beat.get("turn") or event_beat.get("pivot") or event_beat.get("landing")
    ):
        return True
    return False


def _progress_score(bundle: Any, prev_bundle: Any | None) -> float:
    """Heuristic 0-1 progress score. < 0.4 is treated as no-progress."""
    score = 0.5
    summary = _summary_dict(bundle)
    event_beat = summary.get("event_beat", {}) or {}
    if isinstance(event_beat, dict) and (
        event_beat.get("turn") or event_beat.get("pivot") or event_beat.get("landing")
    ):
        score += 0.3

    cur_focus = str(summary.get("next_focus", "") or "").strip()
    prev_focus = ""
    if prev_bundle is not None:
        prev_focus = str(_summary_dict(prev_bundle).get("next_focus", "") or "").strip()
    if cur_focus and prev_focus and cur_focus[:30] == prev_focus[:30]:
        score -= 0.4  # next_focus repeated verbatim → stagnation

    facts = summary.get("facts", []) or []
    if not facts:
        score -= 0.2
    elif len(facts) >= 4:
        score += 0.1

    unresolved = summary.get("unresolved_threads", []) or []
    if unresolved:
        score += 0.1

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Reviewer
# ---------------------------------------------------------------------------


def review_cross_chapter_pacing(
    history: list[Any],
    profile: GenreProfile | None,
    *,
    target_chapter: int,
    window: int = 12,
) -> dict[str, Any]:
    """Inspect last ``window`` chapter bundles for pacing red lines.

    ``history`` may include the chapter currently being reviewed; entries with
    ``chapter_number >= target_chapter`` are filtered out so we only look at
    truly-previous chapters.
    """
    if profile is None or not history:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}

    # Filter and sort previous chapters
    previous: list[Any] = []
    for bundle in history:
        n = _bundle_field(bundle, "chapter_number", None)
        if isinstance(n, int) and n < target_chapter:
            previous.append(bundle)
    previous.sort(key=lambda b: int(_bundle_field(b, "chapter_number", 0) or 0))
    if not previous:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}

    recent = previous[-window:]

    issues: list[str] = []
    revision_plan: list[str] = []
    scores: dict[str, int] = {}

    # ----- Check 1: stagnation run --------------------------------------
    stagnation_run = 0
    for i in range(len(recent) - 1, -1, -1):
        prev = recent[i - 1] if i > 0 else None
        if _progress_score(recent[i], prev) < 0.4:
            stagnation_run += 1
        else:
            break
    if stagnation_run >= profile.pacing.stagnation_threshold:
        scores["pacing_stagnation"] = 4  # HARD
        issues.append(
            f"节奏停滞：连续 {stagnation_run} 章无可见推进，"
            f"超过 {profile.name} 题材阈值（{profile.pacing.stagnation_threshold}）。"
            "持续无推进会让读者直接退出。"
        )
        revision_plan.append(
            "下一章必须形成至少一项可感知推进：能力突破、关系变化、新线索揭露、"
            "资源到手或代价兑现；不要再写无 turn/pivot 的过渡章。"
        )

    # ----- Check 2: quest-only strand run -------------------------------
    quest_only_run = 0
    for bundle in reversed(recent):
        strands = _classify_strands(bundle)
        if "quest" in strands and "emotion" not in strands and "world" not in strands:
            quest_only_run += 1
        else:
            break
    if quest_only_run > profile.pacing.strand_quest_max:
        scores["pacing_quest_strand"] = 6  # SOFT
        issues.append(
            f"主线/任务线连续 {quest_only_run} 章独占叙事，超过 {profile.name} 阈值"
            f"（{profile.pacing.strand_quest_max}）。情感线/世界线长时间空白会让节奏单一。"
        )
        revision_plan.append(
            "下一章在主线推进的同时，至少触一条情感关系或世界规则线：一段对话、"
            "一次试探、一条传闻、一个势力反应。"
        )

    # ----- Check 3: emotion strand gap ----------------------------------
    last_emotion_n: int | None = None
    for bundle in reversed(recent):
        if "emotion" in _classify_strands(bundle):
            n = _bundle_field(bundle, "chapter_number", None)
            if isinstance(n, int):
                last_emotion_n = n
                break
    last_prev = int(_bundle_field(recent[-1], "chapter_number", target_chapter - 1) or (target_chapter - 1))
    emotion_gap = (last_prev - last_emotion_n) if last_emotion_n is not None else (last_prev - 0)
    if emotion_gap > profile.pacing.strand_emotion_gap_max:
        scores["pacing_emotion_gap"] = 6  # SOFT
        issues.append(
            f"情感线断档：距上次情感推进已 {emotion_gap} 章，超过 {profile.name} 阈值"
            f"（{profile.pacing.strand_emotion_gap_max}）。"
        )
        revision_plan.append(
            "下一章补一段关系节拍：试探、承诺、靠近、误会、和解中任一；"
            "不需要长，半场对话或一次眼神交换即可。"
        )

    # ----- Check 4: transition chapter run ------------------------------
    transition_run = 0
    for bundle in reversed(recent):
        if _is_transition(bundle):
            transition_run += 1
        else:
            break
    if transition_run >= profile.pacing.transition_max_consecutive:
        scores["pacing_transition_run"] = 6  # SOFT
        issues.append(
            f"过渡章连发：连续 {transition_run} 章为过渡/铺垫，"
            f"超过 {profile.name} 阈值（{profile.pacing.transition_max_consecutive}）。"
        )
        revision_plan.append(
            "下一章必须给出一个具体事件 turn 或 pivot：冲突爆发、关键决定、"
            "信息揭露、关系转折等任一，不要再写赶路 / 等待 / 休整。"
        )

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "diagnostics": {
            "profile_id": profile.profile_id,
            "stagnation_run": stagnation_run,
            "quest_only_run": quest_only_run,
            "emotion_gap": emotion_gap,
            "transition_run": transition_run,
            "window_size": len(recent),
        },
    }
