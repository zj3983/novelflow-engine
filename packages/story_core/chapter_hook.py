"""Reading Power Taxonomy: structured chapter-end hooks.

Inspired by webnovel-writer v5.5's ``reading-power-taxonomy.md``. The director
historically emitted ``explicit_chapter_end_hook`` as a single free-form
string. This module upgrades it to a structured triple ``{type, strength,
content}`` and adds a reviewer that grades the hook against the active
``GenreProfile``:

  * **type** must be one of the 5 canonical hook types.
  * **strength** is graded on a 3-step ladder so a weak hook in a
    strong-baseline genre (xianxia / suspense) raises a soft warning.
  * **content** must visibly land in the last 20 % of the body — otherwise
    the chapter promises a hook that the reader cannot see, which counts as
    a hard violation.

The module preserves backward compatibility: callers that still pass strings
get a dict back with type/strength inferred heuristically. Structured dicts
are passed through.
"""
from __future__ import annotations

import re
from typing import Any

from packages.story_core.genre_profile import GenreProfile


HOOK_TYPES: tuple[str, ...] = ("危机钩", "悬念钩", "渴望钩", "情绪钩", "选择钩")
HOOK_STRENGTHS: tuple[str, ...] = ("strong", "medium", "weak")


# Heuristic keyword → type lookup for backwards-compat parsing of plain strings.
# Order matters: we walk the dict in declaration order and stop at first hit,
# so place the more decisive markers first.
_HOOK_TYPE_KEYWORDS: dict[str, tuple[str, ...]] = {
    "危机钩": (
        "追杀", "围攻", "陷阱", "围捕", "追兵", "倒计时", "限时", "病危",
        "逼近", "迫近", "断裂", "失控", "断粮", "围堵", "敌人", "杀机", "刀架",
    ),
    "情绪钩": (
        "背叛", "误会", "心动", "心疼", "羞耻", "愤怒", "羞辱", "不甘",
        "心碎", "动情", "原谅", "心头", "眼眶", "苦笑", "委屈", "不爽",
    ),
    "选择钩": (
        "两难", "二选一", "抉择", "决定", "去还是留", "走还是留",
        "信不信", "救还是不救", "代价", "谁先", "或……或", "要不要",
    ),
    "悬念钩": (
        "未知", "未解", "失踪", "线索", "谜", "谁是", "为什么",
        "证据", "下落", "影子", "伏笔", "未公开", "异常", "不对劲",
        "看不懂", "记不起", "认不出",
    ),
    "渴望钩": (
        "即将", "在即", "突破", "宝物", "丹药", "奖励", "晋升", "兑现",
        "成就", "靠近", "重获", "回家", "翻盘", "升级", "解锁", "靠岸",
    ),
}

_STRONG_MARKERS: tuple[str, ...] = (
    "立刻", "马上", "即将", "在即", "倒计时", "限时", "迫近",
    "逼近", "！", "刀架", "杀机", "倒数", "瞬间", "下一秒",
)
_WEAK_MARKERS: tuple[str, ...] = (
    "可能", "大概", "也许", "或许", "之后再", "等以后", "不一定",
    "随后再说", "迟早", "总有一天",
)


def _strip_label_prefix(text: str) -> str:
    """Drop accidental field-name prefixes such as
    ``explicit_chapter_end_hook: ...`` that director LLMs sometimes emit."""
    return re.sub(r"^[\w_-]{3,40}\s*[:：]\s*", "", text.strip())


def _infer_hook_type(text: str) -> str | None:
    if not text:
        return None
    for hook_type, keywords in _HOOK_TYPE_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            return hook_type
    return None


def _infer_hook_strength(text: str) -> str:
    if not text:
        return "medium"
    if any(marker in text for marker in _STRONG_MARKERS):
        return "strong"
    if any(marker in text for marker in _WEAK_MARKERS):
        return "weak"
    return "medium"


def parse_chapter_end_hook(value: Any) -> dict[str, Any]:
    """Normalize any incoming hook value into a structured triple.

    Accepts:
      * ``None`` / empty → ``{"type": None, "strength": None, "content": ""}``
      * ``str`` → strip prefix, infer type and strength heuristically
      * ``dict`` with subset of ``{type, strength, content, text}`` → pass-through;
        missing fields are inferred from ``content``/``text`` when possible
    """
    if value is None:
        return {"type": None, "strength": None, "content": ""}
    if isinstance(value, dict):
        content = str(value.get("content") or value.get("text") or "").strip()
        hook_type = str(value.get("type") or "").strip() or None
        hook_strength = str(value.get("strength") or "").strip().lower() or None
        if hook_type is not None and hook_type not in HOOK_TYPES:
            hook_type = _infer_hook_type(content)
        if hook_strength not in HOOK_STRENGTHS:
            hook_strength = _infer_hook_strength(content) if content else None
        if hook_type is None and content:
            hook_type = _infer_hook_type(content)
        return {"type": hook_type, "strength": hook_strength, "content": content}

    text = _strip_label_prefix(str(value))
    if not text:
        return {"type": None, "strength": None, "content": ""}
    return {
        "type": _infer_hook_type(text),
        "strength": _infer_hook_strength(text),
        "content": text,
    }


# ---------------------------------------------------------------------------
# Reviewer: chapter end hook quality vs genre profile
# ---------------------------------------------------------------------------


_STRENGTH_RANK: dict[str, int] = {"strong": 3, "medium": 2, "weak": 1}


_HOOK_CONTENT_STOP_TOKENS: tuple[str, ...] = (
    "主角", "继续", "推进", "下一", "本章", "已经",
    "他的", "她的", "现在", "知道", "什么", "怎么",
)


def _hook_landed_in_body(body: str, hook_content: str) -> bool:
    """Heuristic: at least one distinctive 2-char window from the hook content
    appears in the last 25% of the body.

    We use sliding 2-char windows rather than maximal CJK runs because director
    LLMs often paraphrase a hook between event_plan and prose ("倒计时三天，
    债主即将上门" vs body "倒计时还剩三天"). Sliding windows survive that
    paraphrasing as long as any meaningful 2-char fragment lands.

    Generic narrative connectives are stripped before window extraction so
    hooks like "主角继续推进" don't trip a false negative.
    """
    if not body or not hook_content:
        return True
    cleaned = re.sub(r"[^一-鿿]", "", hook_content)
    for token in _HOOK_CONTENT_STOP_TOKENS:
        cleaned = cleaned.replace(token, "")
    if len(cleaned) < 4:
        return True  # too little distinctive content to verify
    last_chunk = body[int(len(body) * 0.75):]
    windows = {cleaned[i : i + 2] for i in range(len(cleaned) - 1)}
    if not windows:
        return True
    return any(w in last_chunk for w in windows)


def review_chapter_hook(
    body: str,
    hook_meta: dict[str, Any] | None,
    profile: GenreProfile | None,
) -> dict[str, Any]:
    """Grade a chapter-end hook against the active genre profile.

    Returns a sub-review dict whose ``scores`` keys integrate with
    ``review_critical_prose_rules`` HARD/SOFT classification:

      * ``hook_landed`` (HARD): hook content must visibly land in last quarter
      * ``hook_type_match`` (SOFT): type should be in profile.preferred_types
      * ``hook_strength`` (SOFT): strength should reach profile.strength_baseline
    """
    issues: list[str] = []
    revision_plan: list[str] = []
    scores: dict[str, int] = {}

    if not hook_meta:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}

    hook_type = hook_meta.get("type")
    hook_strength = hook_meta.get("strength")
    hook_content = str(hook_meta.get("content") or "").strip()

    # Landed check (HARD)
    if hook_content and not _hook_landed_in_body(body, hook_content):
        scores["hook_landed"] = 5
        sample = hook_content[:30] + ("…" if len(hook_content) > 30 else "")
        issues.append(f"章末钩子未在正文末段落地：'{sample}' 在最后 25% 正文里没有任何对应词。")
        revision_plan.append(
            "把钩子的关键名词或动作写进章末场景：让读者在本章最后几段就能看见钩子，"
            "而不是仅在 event_plan 字段里描述。"
        )

    # Type vs profile (SOFT)
    if profile is not None and hook_type:
        preferred = list(profile.hook.preferred_types)
        if preferred and hook_type not in preferred:
            scores["hook_type_match"] = 6
            top_two = "/".join(preferred[:2])
            issues.append(
                f"章末钩子类型与题材偏好不符：本章为 '{hook_type}'，{profile.name} 偏好 {top_two}。"
            )
            revision_plan.append(
                f"保持事件不变，把章末收束改成 {preferred[0]}：调整悬念落点而非剧情。"
            )

    # Strength vs baseline (SOFT)
    if profile is not None and hook_strength in HOOK_STRENGTHS:
        baseline = profile.hook.strength_baseline
        if baseline in HOOK_STRENGTHS:
            actual = _STRENGTH_RANK[hook_strength]
            target = _STRENGTH_RANK[baseline]
            if actual < target:
                scores["hook_strength"] = 6
                issues.append(
                    f"章末钩子强度偏弱：本章 {hook_strength}，{profile.name} 期望 {baseline}。"
                )
                revision_plan.append(
                    "把章末诱饵从情绪闭环升级为具体下一章压力（时间限/数量缺/对方逼近/未拿到的钥匙）。"
                )

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "hook_meta": hook_meta,
        "profile_id": profile.profile_id if profile else None,
    }
