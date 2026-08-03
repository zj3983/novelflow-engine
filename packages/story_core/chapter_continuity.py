from __future__ import annotations

import re
from typing import Any


FACT_PRIORITY = ["已发生剧情", "本章计划", "静态人物设定", "后续旧稿"]
_DEPARTURE_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fff]{2,6})(?:已经|已|紧随其后)?(?:离开|前往|踏入)[^。！？!?]{0,40}"
)
_RETURN_MARKERS = ("返回", "返程", "赶回", "回到", "抵达", "重新进入", "回援")
_PRESENCE_MARKERS = (
    "落在",
    "站在",
    "走到",
    "来到",
    "进入",
    "出现在",
    "挡在",
    "扶住",
    "抬手",
    "开口",
    "说道",
    "问道",
    "看着",
)
_CHINESE_FRAGMENT_PATTERNS = (
    re.compile(r"[我你他她]只要[我你他她]看(?:[。！？!?]|$)"),
    re.compile(r"(?:[我你他她]|[\u4e00-\u9fff]{2,4})的意思实打实(?:[。！？!?]|$)"),
    re.compile(r"(?:这|那)一次[^。！？!?\n]{0,20}(?:自己)?做出的选择(?:[。！？!?]|$)"),
    re.compile(r"(?:^|[。！？!?\n])\s*[修看做试走说问]，便是在"),
)


def _chapter_number(chapter: dict[str, Any] | None) -> int | None:
    if not isinstance(chapter, dict):
        return None
    try:
        number = int(chapter.get("chapter_number") or 0)
    except (TypeError, ValueError):
        return None
    return number if number > 0 else None


def _body_slice(chapter: dict[str, Any] | None, *, limit: int, tail: bool) -> str:
    if not isinstance(chapter, dict):
        return ""
    body = str(chapter.get("body") or "").strip()
    if not body:
        return ""
    if len(body) <= limit:
        return body
    return body[-limit:] if tail else body[:limit]


def _summary_items(chapter: dict[str, Any] | None, key: str, *, limit: int) -> list[str]:
    if not isinstance(chapter, dict):
        return []
    summary = chapter.get("chapter_summary")
    if not isinstance(summary, dict):
        return []
    values = summary.get(key)
    if not isinstance(values, list):
        return []
    result: list[str] = []
    for value in values:
        text = " ".join(str(value or "").split()).strip()
        if text and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def build_continuity_interface(
    target_chapter: int,
    *,
    previous: dict[str, Any] | None,
    next_chapter: dict[str, Any] | None,
) -> dict[str, Any]:
    """Build transient adjacent-chapter context for one generation run."""

    if target_chapter < 1:
        raise ValueError("target_chapter_must_be_positive")

    result: dict[str, Any] = {}
    previous_number = _chapter_number(previous)
    previous_tail = _body_slice(previous, limit=1000, tail=True)
    previous_facts = _summary_items(previous, "facts", limit=10)
    previous_threads = _summary_items(previous, "unresolved_threads", limit=6)
    if previous_number is not None:
        result["previous_chapter_number"] = previous_number
    if previous_tail:
        result["previous_tail"] = previous_tail
    if previous_facts:
        result["previous_facts"] = previous_facts
    if previous_threads:
        result["previous_threads"] = previous_threads

    next_number = _chapter_number(next_chapter)
    next_opening = _body_slice(next_chapter, limit=700, tail=False)
    if next_number is not None:
        result["next_chapter_number"] = next_number
    if next_opening:
        result["next_opening"] = next_opening

    if result:
        result["fact_priority"] = list(FACT_PRIORITY)
    return result


def departed_character_facts(interface: Any) -> dict[str, str]:
    if not isinstance(interface, dict):
        return {}
    facts = interface.get("previous_facts")
    sources = [str(item or "").strip() for item in facts] if isinstance(facts, list) else []
    previous_tail = str(interface.get("previous_tail") or "").strip()
    if previous_tail:
        sources.extend(part for part in re.split(r"(?<=[。！？!?])", previous_tail) if part.strip())
    result: dict[str, str] = {}
    for text in sources:
        for match in _DEPARTURE_RE.finditer(text):
            name = match.group("name")
            if name:
                result.setdefault(name, text)
    return result


def has_return_transition(name: str, text: Any) -> bool:
    action = str(text or "")
    if not name or name not in action:
        return False
    return any(marker in action for marker in _RETURN_MARKERS)


def _first_presence_index(text: str, name: str) -> int | None:
    for match in re.finditer(re.escape(name), text):
        window = text[match.start() : match.start() + 40]
        if any(marker in window for marker in _PRESENCE_MARKERS):
            return match.start()
        line_end = text.find("\n", match.end())
        if line_end < 0:
            line_end = min(len(text), match.end() + 80)
        line = text[match.start() : line_end]
        if "“" in line or '"' in line:
            return match.start()
    return None


def _returned_before_presence(text: str, name: str, presence_index: int) -> bool:
    boundary = min(len(text), presence_index + 60)
    prefix = text[:boundary]
    return has_return_transition(name, prefix)


def review_chinese_fragments(body: Any) -> list[str]:
    text = str(body or "")
    issues: list[str] = []
    for pattern in _CHINESE_FRAGMENT_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        fragment = " ".join(match.group(0).split()).strip()
        issues.append(f"中文残句：‘{fragment}’句法或指代被压缩，读者无法直接理解。")
    return issues


def review_continuity_interface(body: Any, interface: Any) -> dict[str, Any]:
    text = str(body or "")
    context = interface if isinstance(interface, dict) else {}
    issues: list[str] = []
    revision_plan: list[str] = []
    departed = departed_character_facts(context)
    for name, fact in departed.items():
        presence_index = _first_presence_index(text, name)
        if presence_index is None or _returned_before_presence(text, name, presence_index):
            continue
        issues.append(f"连续性冲突：{name}上一章已经离场，本章却无过程返场并直接行动或说话。")
        revision_plan.append(f"按‘{fact}’处理{name}的位置；删除其现场行动，或先写清返场路径和时间。")

    downstream_required = False
    next_opening = str(context.get("next_opening") or "")
    if next_opening:
        for name in departed:
            presence_index = _first_presence_index(next_opening, name)
            if presence_index is None or _returned_before_presence(next_opening, name, presence_index):
                continue
            downstream_required = True
            break

    result: dict[str, Any] = {
        "pass": not issues,
        "hard_error": bool(issues),
        "issues": issues,
        "revision_plan": revision_plan,
        "downstream_rewrite_required": downstream_required,
    }
    if downstream_required and context.get("next_chapter_number"):
        result["downstream_chapter_number"] = context["next_chapter_number"]
    return result

def generic_revision_fact_lock() -> str:
    """Return revision facts shared by non-game stories."""

    return "人物身份、能力、伤势、持有物、关系、地点和各自知情范围保持不变"
