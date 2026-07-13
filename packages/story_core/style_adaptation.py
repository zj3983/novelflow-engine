from __future__ import annotations

from collections import Counter
import json
import re
from typing import Any

from packages.story_core.web_game_author_craft import plain_writer_phrase


def _compact_context(text: str, limit: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) <= limit:
        return cleaned
    separator = " ... "
    if limit <= len(separator) + 2:
        return cleaned[:limit]
    half = max(1, (limit - len(separator)) // 2)
    tail_len = max(1, limit - len(separator) - half)
    return f"{cleaned[:half]}{separator}{cleaned[-tail_len:]}"


def _plain_prompt_value(value: Any) -> Any:
    if isinstance(value, str):
        return _compact_context(plain_writer_phrase(value), 180)
    if isinstance(value, list):
        return [_compact_context(plain_writer_phrase(str(item)), 160) for item in value if str(item).strip()][:6]
    if isinstance(value, dict):
        return {str(key): _plain_prompt_value(item) for key, item in value.items() if item not in (None, "", [], {})}
    return value


def _style_brief(plan: dict[str, Any]) -> dict[str, Any]:
    """Extract only the voice fields needed by the whole-chapter style pass."""
    plan = plan if isinstance(plan, dict) else {}
    craft = plan.get("craft_pack")
    if not isinstance(craft, dict):
        sim = plan.get("simulation_plan")
        craft = sim.get("craft_pack") if isinstance(sim, dict) else {}
    if not isinstance(craft, dict):
        craft = {}

    show_tell = craft.get("show_vs_tell") if isinstance(craft.get("show_vs_tell"), dict) else {}
    sentence_craft = craft.get("sentence_craft") if isinstance(craft.get("sentence_craft"), dict) else {}
    paragraph_rhythm = craft.get("paragraph_rhythm") if isinstance(craft.get("paragraph_rhythm"), dict) else {}
    transition_limits = craft.get("transition_crutch_limits") if isinstance(craft.get("transition_crutch_limits"), dict) else {}

    voices: list[dict[str, Any]] = []
    protagonist = plan.get("protagonist") if isinstance(plan.get("protagonist"), dict) else None
    if protagonist:
        voice = protagonist.get("voice") if isinstance(protagonist.get("voice"), dict) else None
        if voice:
            voices.append({"name": protagonist.get("name") or "主角", "voice": voice})
    for card in plan.get("character_cards") if isinstance(plan.get("character_cards"), list) else []:
        if not isinstance(card, dict):
            continue
        voice = card.get("voice") if isinstance(card.get("voice"), dict) else None
        if voice:
            voices.append({"name": card.get("name") or "?", "voice": voice})
        if len(voices) >= 3:
            break

    brief = {
        "show_vs_tell_conversions": show_tell.get("conversions", []),
        "sentence_craft": sentence_craft,
        "paragraph_rhythm": paragraph_rhythm,
        "transition_crutch_limits": transition_limits,
        "voice_guidance": voices,
    }
    return {key: value for key, value in brief.items() if value not in (None, "", [], {})}


def build_style_adapt_prompt(body: str, plan: dict[str, Any]) -> str:
    """Build the facts-frozen whole-chapter style adaptation prompt."""
    brief_json = json.dumps(_plain_prompt_value(_style_brief(plan)), ensure_ascii=False, separators=(",", ":"))
    return "\n".join(
        [
            "请对下面这章中文网文正文做风格适配，不改事实。",
            "",
            "唯一目的：把模板腔、说明腔、机械腔改成可读场面，不动任何事实。",
            "允许：把判断改成动作，把解释改成场面，把连续相同的段首改成动作、物件或对话开头。",
            "保留一两个自然比喻，不堆比喻；关键反应前后补连续动作，不要用总结代替过程。",
            "硬禁止：改名字、地名、ID、职业、装备、技能、道具、NPC名；改数字、改面板数据、货币、库存、价格；改NPC台词的事实内容；改事件顺序、场景顺序或主角决策；删除或新增完整场景。",
            "能不改就不改。如果原章已经通顺，可以原样输出。",
            f"风格参考：{brief_json}",
            "",
            "原章正文：",
            body,
            "",
            "只输出适配后的完整正文，不要说明、标题、前言或评论。",
        ]
    )


_NUMBER_PATTERN = re.compile(r"\d+")
_PANEL_TAG_PATTERN = re.compile(r"【[^】]{1,40}】")


def style_adapt_safety_check(original: str, candidate: str) -> dict[str, Any]:
    """Reject style rewrites that change hard numeric or panel facts."""
    if not candidate or not candidate.strip():
        return {"accept": False, "reason": "candidate_empty"}

    orig_compact_len = len("".join(original.split()))
    cand_compact_len = len("".join(candidate.split()))
    if cand_compact_len < orig_compact_len * 0.7:
        return {"accept": False, "reason": "candidate_too_short", "mismatch": {"original_chars": orig_compact_len, "candidate_chars": cand_compact_len}}
    if cand_compact_len > orig_compact_len * 1.4:
        return {"accept": False, "reason": "candidate_too_long", "mismatch": {"original_chars": orig_compact_len, "candidate_chars": cand_compact_len}}

    orig_numbers = _NUMBER_PATTERN.findall(original)
    cand_numbers = _NUMBER_PATTERN.findall(candidate)
    orig_number_counts = Counter(orig_numbers)
    cand_number_counts = Counter(cand_numbers)
    invented = sorted((cand_number_counts - orig_number_counts).elements())
    missing = sorted((orig_number_counts - cand_number_counts).elements())
    if invented:
        return {"accept": False, "reason": "invented_numbers", "mismatch": {"invented": invented[:8]}}
    if missing:
        return {"accept": False, "reason": "deleted_numbers", "mismatch": {"missing": missing[:8]}}

    orig_tags = sorted(_PANEL_TAG_PATTERN.findall(original))
    cand_tags = sorted(_PANEL_TAG_PATTERN.findall(candidate))
    if orig_tags and orig_tags != cand_tags:
        return {
            "accept": False,
            "reason": "panel_tags_changed",
            "mismatch": {"original_tag_count": len(orig_tags), "candidate_tag_count": len(cand_tags)},
        }

    return {
        "accept": True,
        "reason": "ok",
        "stats": {
            "original_chars": orig_compact_len,
            "candidate_chars": cand_compact_len,
            "panel_tag_count": len(orig_tags),
            "number_count": len(orig_numbers),
        },
    }
