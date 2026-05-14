"""Reviewer that quantifies how much of ``simulation_plan.required_beats``
actually landed in the chapter body.

Closes the director→writer→review loop by giving a numeric "completion"
ratio: of N planned beats, how many have evidence in the prose? Each beat is
broken into a label (the prefix before "：") and a set of content terms
(2+ char CJK runs, minus instructional words). A beat is *covered* when at
least 50 % of its content terms appear somewhere in the body.

Score keys:

  * ``required_beats_critical`` (HARD): >50 % of beats missing entirely
  * ``required_beats_partial`` (SOFT): some beats missing or only partially
    covered; not severe enough to force a rewrite alone
"""
from __future__ import annotations

import re
from typing import Any


# Common instructional / connective tokens that appear in beat strings but
# don't represent the beat's actual content payload. Filtering these prevents
# a beat like "现实入口：说明主角现实职业..." from being trivially "covered"
# just because the body contains "说明" or "主角".
_BEAT_STOP_TERMS: frozenset[str] = frozenset({
    "必须", "应当", "应该", "需要", "不要", "禁止", "确保", "建议",
    "可以", "之前", "之后", "可能", "或者", "以及", "用于", "形成",
    "说明", "主角", "他", "她", "它", "本章", "下一章", "章节",
    "时候", "情况", "进行", "发生", "因为", "所以", "并且", "通过",
    "包括", "至少", "最多", "不只", "只是", "只要", "只有", "只能",
    "已经", "正在", "暂时", "始终", "一直", "继续", "出现", "做到",
    "不出现",
})

_BEAT_HEAD_PATTERN = re.compile(r"^([一-鿿0-9A-Za-z\s/]{2,16})\s*[：:]")
_CJK_RUN_PATTERN = re.compile(r"[一-鿿]{2,}")


def _beat_label(beat: str) -> str:
    """Return the short label of a beat — the prefix before '：' if present,
    otherwise the first 12 chars."""
    m = _BEAT_HEAD_PATTERN.match(beat.strip())
    if m:
        return m.group(1).strip()
    return beat.strip()[:12]


def _beat_run_groups(beat: str) -> list[list[str]]:
    """For each non-stopword maximal CJK run in the beat, return a list of
    candidate surface forms: the whole run plus its overlapping 2-char windows
    (windows themselves filtered against the stopword set).

    Grouping by run lets a beat be considered "hit" when ANY of the related
    surface forms appear in the body — which is critical because writers
    paraphrase: "登录建号" in the plan often shows up as "登录界面" in prose,
    so we accept any 2-char overlap such as "登录".
    """
    groups: list[list[str]] = []
    for run in _CJK_RUN_PATTERN.findall(beat):
        if run in _BEAT_STOP_TERMS:
            continue
        candidates: list[str] = [run]
        for i in range(len(run) - 1):
            window = run[i : i + 2]
            if window in _BEAT_STOP_TERMS or window in candidates:
                continue
            candidates.append(window)
        if candidates:
            groups.append(candidates)
    return groups


def _beat_content_terms(beat: str) -> set[str]:
    """Distinct surface forms (whole runs + 2-char sliding windows) from a
    beat, with stopwords filtered. Exposed mostly for tests/diagnostics."""
    terms: set[str] = set()
    for group in _beat_run_groups(beat):
        terms.update(group)
    return terms


def _beat_coverage(body: str, beat: str) -> float:
    """0.0 = no run-groups hit the body; 1.0 = every run-group has at least
    one surface form present. A run-group is "hit" when its whole run OR any
    of its 2-char windows appears as a substring of the body."""
    groups = _beat_run_groups(beat)
    if not groups:
        return 1.0  # nothing to verify; treat as covered (degenerate beat)
    hits = sum(1 for group in groups if any(candidate in body for candidate in group))
    return hits / len(groups)


def review_required_beats_completion(
    body: str,
    simulation_plan: dict[str, Any] | None,
    *,
    covered_threshold: float = 0.4,
    partial_threshold: float = 0.2,
    hard_missing_ratio: float = 0.5,
) -> dict[str, Any]:
    """Compare ``simulation_plan.required_beats`` against the chapter body.

    Returns a sub-review compatible with ``review_critical_prose_rules`` so it
    can be passed via ``extra_subreviews`` and routed through the same HARD/
    SOFT severity classifier.
    """
    if not isinstance(simulation_plan, dict):
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}
    beats = simulation_plan.get("required_beats")
    if not isinstance(beats, list) or not beats:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}

    covered: list[tuple[str, float]] = []
    partial: list[tuple[str, float]] = []
    missing: list[tuple[str, float]] = []
    for raw in beats:
        text = str(raw).strip()
        if not text:
            continue
        ratio = _beat_coverage(body, text)
        if ratio >= covered_threshold:
            covered.append((text, ratio))
        elif ratio >= partial_threshold:
            partial.append((text, ratio))
        else:
            missing.append((text, ratio))

    total = len(covered) + len(partial) + len(missing)
    if total == 0:
        return {"pass": True, "issues": [], "revision_plan": [], "scores": {}}

    completion = (len(covered) + 0.5 * len(partial)) / total

    issues: list[str] = []
    revision_plan: list[str] = []
    scores: dict[str, int] = {}
    diagnostics = {
        "total_beats": total,
        "covered": len(covered),
        "partial": len(partial),
        "missing": len(missing),
        "completion": round(completion, 2),
        "missing_labels": [_beat_label(beat) for beat, _ in missing[:8]],
        "partial_labels": [_beat_label(beat) for beat, _ in partial[:8]],
    }

    if missing and len(missing) / total > hard_missing_ratio:
        scores["required_beats_critical"] = 4  # HARD
        sample = "、".join(diagnostics["missing_labels"][:5])
        issues.append(
            f"required_beats 完成度严重不足：{len(missing)}/{total} 节拍未在正文落地"
            f"（{sample}）；正文与导演规划脱节。"
        )
        revision_plan.append(
            "把缺失的节拍写成具体场景：每个节拍至少需要 2-3 个内容关键词在正文出现，"
            "可以是动作、物件名、对话内容、面板提示或角色反应。"
        )
    elif missing or partial:
        scores["required_beats_partial"] = 6  # SOFT
        sample_missing = "、".join(diagnostics["missing_labels"][:3]) or "无"
        sample_partial = "、".join(diagnostics["partial_labels"][:3]) or "无"
        issues.append(
            f"required_beats 完成度 {int(completion * 100)}%："
            f"缺失 {len(missing)} 节拍（{sample_missing}），"
            f"部分覆盖 {len(partial)} 节拍（{sample_partial}）。"
        )
        revision_plan.append(
            "补足或加强未完成的节拍：缺失节拍要写成完整场景，半覆盖节拍要把关键事件、物件、对话写进具体动作或界面反馈。"
        )

    return {
        "pass": not issues,
        "issues": issues,
        "revision_plan": revision_plan,
        "scores": scores,
        "diagnostics": diagnostics,
    }
