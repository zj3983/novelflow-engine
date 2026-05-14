"""Format a ``_review_chapter_body`` verdict as a human-readable markdown report.

This is the observability complement to the layered HARD/SOFT review system:
running review programmatically produces a structured dict; this module turns
that dict into a one-glance markdown snapshot that can be written next to a
chapter export so we can audit "what did the reviewer think" without having to
re-run the pipeline.

Pure formatter — no I/O, no orchestrator coupling. Test-friendly.
"""
from __future__ import annotations

from typing import Any


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _bullet_block(items: list[str], *, indent: str = "- ", empty_text: str = "（无）") -> str:
    """Render a bullet list, with a placeholder when empty."""
    if not items:
        return empty_text
    return "\n".join(f"{indent}{item}" for item in items)


def _check_mark(value: Any) -> str:
    if value is True:
        return "✓"
    if value is False:
        return "✗"
    return "—"


# ---------------------------------------------------------------------------
# Section formatters
# ---------------------------------------------------------------------------


def _format_header(
    review: dict[str, Any],
    *,
    chapter_number: int | None,
    body_chars: int | None,
) -> str:
    profile_id = review.get("genre_profile_id") or "?"
    passed = bool(review.get("pass"))
    issues_count = len(_as_list(review.get("issues")))
    critical = _as_dict(review.get("critical_review"))
    requires_revision = bool(critical.get("requires_revision"))
    chapter_label = f"第 {chapter_number} 章" if chapter_number is not None else "未指定章节"
    overall_label = "✅ 通过" if passed else "❌ 待修"
    revision_hint = "是" if requires_revision else "否"

    lines = [
        f"# {chapter_label} 审稿报告",
        "",
        f"- **Genre Profile**: `{profile_id}`",
    ]
    if body_chars is not None:
        lines.append(f"- **正文字数**: {body_chars:,}")
    lines.extend([
        f"- **整体评估**: {overall_label}（共 {issues_count} 条 issue）",
        f"- **触发改稿**: {revision_hint}",
    ])
    return "\n".join(lines)


def _format_severity_summary(review: dict[str, Any]) -> str:
    critical = _as_dict(review.get("critical_review"))
    sev = _as_dict(critical.get("severity_summary"))
    has_hard = sev.get("has_hard_violation", False)
    soft_count = int(sev.get("soft_violation_count", 0) or 0)
    threshold = int(sev.get("soft_threshold", 3) or 3)
    soft_triggers = soft_count >= threshold

    return "\n".join([
        "## 严重度汇总",
        "",
        "| 级别 | 数量 | 阈值 | 触发改稿 |",
        "|---|---|---|---|",
        f"| 🔴 HARD | {len(_as_list(critical.get('hard_issues')))} | 任一即触发 | {'是' if has_hard else '否'} |",
        f"| 🟡 SOFT | {soft_count} | ≥{threshold} 触发 | "
        f"{'是' if soft_triggers else f'否（差 {threshold - soft_count} 条）'} |",
    ])


def _format_hard_block(review: dict[str, Any]) -> str:
    critical = _as_dict(review.get("critical_review"))
    hard_issues = [str(item) for item in _as_list(critical.get("hard_issues")) if str(item).strip()]
    return "\n".join([
        "## 🔴 HARD 违规（必修）",
        "",
        _bullet_block(hard_issues, empty_text="（本章无 HARD 违规）"),
    ])


def _format_soft_block(review: dict[str, Any]) -> str:
    critical = _as_dict(review.get("critical_review"))
    soft_issues = [str(item) for item in _as_list(critical.get("soft_issues")) if str(item).strip()]
    return "\n".join([
        "## 🟡 SOFT 警告（累计达阈值才触发）",
        "",
        _bullet_block(soft_issues, empty_text="（本章无 SOFT 警告）"),
    ])


def _format_hook_section(review: dict[str, Any]) -> str:
    hook = _as_dict(review.get("hook_review"))
    if not hook:
        return ""
    meta = _as_dict(hook.get("hook_meta"))
    scores = _as_dict(hook.get("scores"))
    landed = scores.get("hook_landed") is None  # absent score → passed the landing check
    type_ok = scores.get("hook_type_match") is None
    strength_ok = scores.get("hook_strength") is None

    content = str(meta.get("content") or "").strip()
    content_excerpt = content[:60] + ("…" if len(content) > 60 else "")
    return "\n".join([
        "## 章末钩子（Reading Power Taxonomy）",
        "",
        "| 字段 | 值 |",
        "|---|---|",
        f"| 类型 | {meta.get('type') or '（未分类）'} |",
        f"| 强度 | {meta.get('strength') or '—'} |",
        f"| 末段落地 | {_check_mark(landed)} |",
        f"| 题材匹配 | {_check_mark(type_ok)} |",
        f"| 强度达标 | {_check_mark(strength_ok)} |",
        f"| 内容摘录 | {content_excerpt or '（空）'} |",
    ])


def _format_pacing_section(review: dict[str, Any]) -> str:
    pacing = _as_dict(review.get("pacing_review"))
    if not pacing:
        return ""
    diag = _as_dict(pacing.get("diagnostics"))
    scores = _as_dict(pacing.get("scores"))
    # Suppress section entirely when there is no usable diagnostic context
    # (e.g. CLI ran on a single exported chapter without history). An empty
    # table is worse than no table — the reviewer didn't actually run.
    window_size = diag.get("window_size")
    if not diag or not window_size:
        return ""
    rows = [
        ("停滞章数", "stagnation_run", "pacing_stagnation"),
        ("任务线独占", "quest_only_run", "pacing_quest_strand"),
        ("情感线断档", "emotion_gap", "pacing_emotion_gap"),
        ("过渡章连发", "transition_run", "pacing_transition_run"),
    ]
    table_lines = [
        "## 跨章节节奏",
        "",
        f"- **题材**: `{diag.get('profile_id', '?')}`，**窗口**: 最近 {diag.get('window_size', '?')} 章",
        "",
        "| 指标 | 当前 | 触发？ |",
        "|---|---|---|",
    ]
    for label, diag_key, score_key in rows:
        actual = diag.get(diag_key)
        triggered = score_key in scores
        actual_str = "—" if actual is None else str(actual)
        triggered_str = "🔴 是" if triggered and score_key == "pacing_stagnation" else (
            "🟡 是" if triggered else "—"
        )
        table_lines.append(f"| {label} | {actual_str} | {triggered_str} |")

    pacing_issues = [str(item) for item in _as_list(pacing.get("issues")) if str(item).strip()]
    if pacing_issues:
        table_lines.extend(["", "**节奏说明**：", "", _bullet_block(pacing_issues)])
    return "\n".join(table_lines)


def _format_beats_section(review: dict[str, Any]) -> str:
    beats = _as_dict(review.get("beats_review"))
    if not beats:
        return ""
    diag = _as_dict(beats.get("diagnostics"))
    total = diag.get("total_beats")
    if not total:
        return ""
    completion_pct = int((diag.get("completion") or 0) * 100)
    covered = diag.get("covered", 0)
    partial = diag.get("partial", 0)
    missing = diag.get("missing", 0)

    bar_filled = max(0, min(20, round((diag.get("completion") or 0) * 20)))
    bar = "█" * bar_filled + "░" * (20 - bar_filled)

    lines = [
        "## 节拍完成度（director 规划 vs 正文落地）",
        "",
        f"`{bar}` **{completion_pct}%** ({covered} 已覆盖 · {partial} 部分 · {missing} 缺失 / 共 {total})",
        "",
    ]
    missing_labels = diag.get("missing_labels") or []
    partial_labels = diag.get("partial_labels") or []
    if missing_labels:
        lines.append("**未落地的节拍**：")
        lines.append(_bullet_block([str(label) for label in missing_labels[:8]]))
        lines.append("")
    if partial_labels:
        lines.append("**仅部分覆盖的节拍**：")
        lines.append(_bullet_block([str(label) for label in partial_labels[:8]]))
    return "\n".join(lines).rstrip()


def _format_revision_plan(review: dict[str, Any], *, max_items: int = 10) -> str:
    plan_items = [str(item) for item in _as_list(review.get("revision_plan")) if str(item).strip()]
    plan_items = plan_items[:max_items]
    return "\n".join([
        "## 修订建议",
        "",
        _bullet_block(
            [f"**{i+1}.** {item}" for i, item in enumerate(plan_items)],
            indent="",
            empty_text="（本章无具体修订建议）",
        ),
    ])


def _format_score_table(review: dict[str, Any]) -> str:
    scores = _as_dict(review.get("scores"))
    if not scores:
        return ""
    # Group by reviewer source via score-key prefix.
    groups: dict[str, list[tuple[str, int]]] = {}
    prefix_label = {
        "web_game_": "网游审稿",
        "world_event_": "世界一致性",
        "prose_style_": "文风审稿",
        "critical_": "HARD/SOFT 综合",
    }
    fallback_group = "内联规则"
    for key, value in scores.items():
        bucket = fallback_group
        for prefix, label in prefix_label.items():
            if key.startswith(prefix):
                bucket = label
                break
        groups.setdefault(bucket, []).append((key, int(value)))

    lines = [
        "## 评分细则",
        "",
    ]
    for bucket in [fallback_group, "HARD/SOFT 综合", "网游审稿", "世界一致性", "文风审稿"]:
        items = groups.get(bucket)
        if not items:
            continue
        lines.append(f"### {bucket}")
        lines.append("")
        lines.append("| 检查项 | 分数 |")
        lines.append("|---|---|")
        for key, value in sorted(items):
            # Score conventions across reviewers: HARD failure ≤5, SOFT
            # failure / warning =6-7, pass ≥8.
            marker = "🔴" if value <= 5 else ("🟡" if value <= 7 else "✅")
            lines.append(f"| `{key}` | {marker} {value} |")
        lines.append("")
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------------
# Public entry
# ---------------------------------------------------------------------------


def format_review_report(
    review: dict[str, Any],
    *,
    chapter_number: int | None = None,
    body_chars: int | None = None,
) -> str:
    """Format a ``_review_chapter_body`` result as a human-readable markdown
    snapshot. Pure: no I/O, no side effects.

    Sections (in order):

      1. Header (chapter, profile, overall verdict, body chars, revision flag)
      2. Severity summary table (HARD count / SOFT count / triggers)
      3. HARD violations bullet list
      4. SOFT warnings bullet list
      5. Hook review (type / strength / landing / matches)
      6. Cross-chapter pacing diagnostics
      7. Revision plan (top 10)
      8. Per-reviewer score table grouped by source
    """
    sections = [
        _format_header(review, chapter_number=chapter_number, body_chars=body_chars),
        _format_severity_summary(review),
        _format_hard_block(review),
        _format_soft_block(review),
        _format_beats_section(review),
        _format_hook_section(review),
        _format_pacing_section(review),
        _format_revision_plan(review),
        _format_score_table(review),
    ]
    # Drop empty sections gracefully (hook/pacing optional).
    return "\n\n".join(section for section in sections if section).rstrip() + "\n"
