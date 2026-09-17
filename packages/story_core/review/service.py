"""Hard-gate and soft-review orchestration backed by canonical contracts.

`ReviewService` is the single runtime entry point that runs deterministic
chapter reviewers, converts their pass/issues-style output into structured
`ReviewFinding` objects, and produces a `ReviewResult` that downstream code
uses to make save, rewrite, and display decisions.

Hard-gate sources cover verifiable chapter-contract failures such as length,
continuity, fragments, world-event consistency, and the hard subset of
critical prose rules. Critical prose reviewers may also emit soft findings;
those remain advisory. Genre-profile findings are advisory by default because
type feel and payoff strength are editorial judgments, but a structured genre
finding can explicitly opt into blocking when it represents a real contract
violation.

Subclasses (typically test doubles) can override the individual ``_run_*``
hooks; the public ``run_hard_gate`` / ``run_soft_review`` / ``combine``
methods are the stable contract.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Iterable

from .contracts import ReviewFinding, ReviewResult, ReviewStatus


# Reviewer sources executed during the hard-gate pass. Individual adapters can
# still emit advisory findings when a layered reviewer reports a soft concern.
# Order is preserved in the recorded call list so tests can assert the exact
# dispatch sequence.
HARD_SOURCES: tuple[str, ...] = (
    "continuity",
    "fragments",
    "consistency",
    "critical",
    "genre",
)

# Soft-review reviewer sources. Order is preserved in the recorded call list.
SOFT_SOURCES: tuple[str, ...] = (
    "style",
    "prose_quality",
    "adversarial_cut",
    "ai_flavor",
    "reader_feel",
    "cold_reader",
    "plot_spine",
)


@dataclass
class ReviewService:
    """Orchestrate hard-gate and soft-review reviewers into a ReviewResult."""

    # Hard-gate dependencies ----------------------------------------------------
    length_check: Callable[[str], ReviewResult] | None = None
    review_continuity: Callable[..., dict[str, Any]] | None = None
    review_fragments: Callable[[str], list[str]] | None = None
    review_consistency: Callable[..., dict[str, Any]] | None = None
    review_critical_rules: Callable[..., dict[str, Any]] | None = None
    profile_for: Callable[[Any], Any] | None = None
    min_chars: int = 0
    max_chars: int = 0
    char_tolerance: int = 0
    hard_max_chars: int = 0

    # Soft-review dependencies --------------------------------------------------
    review_style: Callable[..., dict[str, Any]] | None = None
    review_prose_quality: Callable[..., dict[str, Any]] | None = None
    review_adversarial_cuts: Callable[..., dict[str, Any]] | None = None
    review_ai_flavor: Callable[..., dict[str, Any]] | None = None
    review_reader_feel: Callable[..., dict[str, Any]] | None = None
    review_cold_reader: Callable[..., dict[str, Any]] | None = None
    review_plot_spine: Callable[..., dict[str, Any]] | None = None

    # Diagnostics capture -------------------------------------------------------
    diagnostics: dict[str, Any] = field(default_factory=dict)
    call_log: list[str] = field(default_factory=list)

    # --- Public API ------------------------------------------------------------

    def run_hard_gate(self, *, body: str, context: dict[str, Any]) -> ReviewResult:
        findings: list[ReviewFinding] = []
        diagnostics: dict[str, Any] = {}
        raw: dict[str, Any] = {}

        length_result, length_raw = self._run_length_check(body=body, context=context)
        if length_result is not None:
            findings.extend(length_result.findings)
            diagnostics["length"] = length_result.diagnostics
        raw["length"] = length_raw

        continuity_result, continuity_raw = self._run_continuity(body=body, context=context)
        if continuity_result is not None:
            findings.extend(continuity_result.findings)
            diagnostics["continuity"] = continuity_result.diagnostics
        raw["continuity"] = continuity_raw

        fragments_result, fragments_raw = self._run_fragments(body=body, context=context)
        if fragments_result is not None:
            findings.extend(fragments_result.findings)
            diagnostics["fragments"] = fragments_result.diagnostics
        raw["fragments"] = fragments_raw

        consistency_result, consistency_raw = self._run_consistency(body=body, context=context)
        if consistency_result is not None:
            findings.extend(consistency_result.findings)
            diagnostics["consistency"] = consistency_result.diagnostics
        raw["consistency"] = consistency_raw

        critical_result, critical_raw = self._run_critical(body=body, context=context)
        if critical_result is not None:
            findings.extend(critical_result.findings)
            diagnostics["critical"] = critical_result.diagnostics
        raw["critical"] = critical_raw

        genre_result, genre_raw = self._run_genre(body=body, context=context)
        if genre_result is not None:
            findings.extend(genre_result.findings)
            diagnostics["genre"] = genre_result.diagnostics
        raw["genre"] = genre_raw

        diagnostics["raw_reports"] = raw
        result = ReviewResult.from_findings(findings, diagnostics=diagnostics)
        self.call_log.extend(["continuity", "fragments", "consistency", "critical", "genre"])
        return result

    def run_soft_review(self, *, body: str, context: dict[str, Any]) -> ReviewResult:
        findings: list[ReviewFinding] = []
        diagnostics: dict[str, Any] = {}
        raw: dict[str, Any] = {}

        for source in SOFT_SOURCES:
            sub, sub_raw = self._run_soft_source(source=source, body=body, context=context)
            if sub is None:
                continue
            findings.extend(sub.findings)
            diagnostics[source] = sub.diagnostics
            raw[source] = sub_raw

        diagnostics["raw_reports"] = raw
        result = ReviewResult.from_findings(findings, diagnostics=diagnostics)
        self.call_log.extend(list(SOFT_SOURCES))
        return result

    def combine(self, hard: ReviewResult, soft: ReviewResult) -> ReviewResult:
        hard_diag = dict(hard.diagnostics or {})
        soft_diag = dict(soft.diagnostics or {})
        hard_raw = hard_diag.pop("raw_reports", {}) or {}
        soft_raw = soft_diag.pop("raw_reports", {}) or {}
        merged_diagnostics: dict[str, Any] = {}
        for key, value in hard_diag.items():
            merged_diagnostics[key] = value
        for key, value in soft_diag.items():
            merged_diagnostics[key] = value
        merged_diagnostics["raw_reports"] = {**hard_raw, **soft_raw}
        return ReviewResult.from_findings(
            [*hard.findings, *soft.findings],
            diagnostics=merged_diagnostics,
        )

    # --- Internal hooks (overridable for tests) -------------------------------

    def _run_length_check(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if not self.min_chars:
            return None, {"compact_chars": len("".join(str(body or "").split()))}
        compact = "".join(str(body or "").split())
        if not compact:
            return (
                ReviewResult.from_findings(
                    [
                        ReviewFinding(
                            code="length.out_of_range",
                            category="hard",
                            blocking=True,
                            message="正文为空。",
                            suggestion="重写章节，保证篇幅。",
                            source="length",
                        )
                    ]
                ),
                {"compact_chars": 0},
            )
        low = self.min_chars - self.char_tolerance
        if len(compact) < low:
            return (
                ReviewResult.from_findings(
                    [
                        ReviewFinding(
                            code="length.out_of_range",
                            category="hard",
                            blocking=True,
                            message=f"章节篇幅{len(compact)}字，少于下限{low}字。",
                            suggestion=f"扩写到{self.min_chars}字以上。",
                            source="length",
                        )
                    ]
                ),
                {"compact_chars": len(compact)},
            )
        if self.hard_max_chars and len(compact) > self.hard_max_chars:
            return (
                ReviewResult.from_findings(
                    [
                        ReviewFinding(
                            code="length.out_of_range",
                            category="hard",
                            blocking=True,
                            message=f"章节篇幅{len(compact)}字，超过硬上限{self.hard_max_chars}字。",
                            suggestion=f"压缩到{self.hard_max_chars}字以内。",
                            source="length",
                        )
                    ]
                ),
                {"compact_chars": len(compact)},
            )
        return ReviewResult.from_findings([]), {"compact_chars": len(compact)}

    def _run_continuity(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_continuity is None:
            return None, None
        report = self.review_continuity(body, context.get("continuity_interface"))
        return _adapt_report(report, source="continuity", default_blocking=True), report

    def _run_fragments(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_fragments is None:
            return None, None
        issues = list(self.review_fragments(body) or [])
        result = ReviewResult.from_findings(
            [
                ReviewFinding(
                    code="continuity.fragments",
                    category="hard",
                    blocking=True,
                    message=str(text),
                    suggestion="补全该句的谓语、宾语或明确指代，不要用压缩短语代替完整中文。",
                    source="fragments",
                )
                for text in issues
                if str(text).strip()
            ]
        )
        return result, list(issues)

    def _run_consistency(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_consistency is None:
            return None, None
        report = self.review_consistency(
            body,
            world_events=context.get("world_events", []),
            scene_cards=context.get("scene_cards", []),
            chapter_number=context.get("chapter_number"),
            genre_context=context.get("genre_context"),
        )
        return _adapt_report(report, source="consistency", default_blocking=True), report

    def _run_critical(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_critical_rules is None:
            return None, None
        report = self.review_critical_rules(
            body,
            protagonist_names=context.get("protagonist_aliases") or (),
        )
        return _adapt_critical_report(report), report

    def _run_genre(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.profile_for is None:
            return None, None
        genre_context = context.get("genre_context")
        try:
            profile = self.profile_for(genre_context)
        except Exception:
            return None, None
        review = getattr(profile, "review_chapter", None)
        if not callable(review):
            return None, None
        try:
            report = review(context=_build_genre_context(context, body))
        except Exception:
            return None, None
        return _adapt_genre_report(report), report

    def _run_soft_source(self, *, source: str, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        runner = getattr(self, f"_run_soft_{source}", None)
        if runner is None:
            return None, None
        return runner(body=body, context=context)

    def _run_soft_style(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_style is None:
            return None, None
        report = self.review_style(body, genre_context=context.get("genre_context"))
        return _adapt_report(report, source="style", default_blocking=False), report

    def _run_soft_prose_quality(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_prose_quality is None:
            return None, None
        report = self.review_prose_quality(body)
        return _adapt_report(report, source="prose_quality", default_blocking=False), report

    def _run_soft_adversarial_cut(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_adversarial_cuts is None:
            return None, None
        report = self.review_adversarial_cuts(body)
        return _adapt_report(report, source="adversarial_cut", default_blocking=False), report

    def _run_soft_ai_flavor(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_ai_flavor is None:
            return None, None
        report = self.review_ai_flavor(body)
        return _adapt_report(report, source="ai_flavor", default_blocking=False), report

    def _run_soft_reader_feel(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_reader_feel is None:
            return None, None
        report = self.review_reader_feel(body)
        return _adapt_report(report, source="reader_feel", default_blocking=False), report

    def _run_soft_cold_reader(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_cold_reader is None:
            return None, None
        report = self.review_cold_reader(
            body,
            previous_summary=context.get("previous_summary", ""),
            genre_context=context.get("genre_context"),
        )
        return _adapt_report(report, source="cold_reader", default_blocking=False), report

    def _run_soft_plot_spine(self, *, body: str, context: dict[str, Any]) -> tuple[ReviewResult | None, Any]:
        if self.review_plot_spine is None:
            return None, None
        report = self.review_plot_spine(body, context.get("simulation_plan") or {})
        return _adapt_plot_spine_report(report), report


# --- Adapters ----------------------------------------------------------------


def _build_genre_context(context: dict[str, Any], body: str) -> dict[str, Any]:
    return {
        "chapter_number": context.get("chapter_number"),
        "body": body,
        "event_plan": context.get("event_plan", {}),
        "world_facts": context.get("world_facts", []),
        "simulation_plan": context.get("simulation_plan", {}),
        "protagonist_aliases": context.get("protagonist_aliases", ()),
        "character_names": context.get("character_names", ()),
    }


def _category_for_source(source: str) -> str:
    if source in {"continuity", "fragments", "consistency", "critical", "length"}:
        return "hard"
    if source in {"ai_flavor", "style", "adversarial_cut"}:
        return "ai_flavor"
    if source in {"reader_feel", "cold_reader", "prose_quality", "plot_spine"}:
        return "prose"
    return "prose"


def _adapt_report(
    report: Any,
    *,
    source: str,
    default_blocking: bool,
    category: str | None = None,
) -> ReviewResult:
    if not isinstance(report, dict):
        return ReviewResult.from_findings([])
    diagnostics = {key: value for key, value in report.items() if key not in {"issues", "revision_plan", "scores"}}
    category_name = category or _category_for_source(source)
    issues = list(report.get("issues") or [])
    plan_items = list(report.get("revision_plan") or [])
    findings: list[ReviewFinding] = []
    for index, issue in enumerate(issues):
        message, suggestion, evidence, explicit_blocking = _normalize_issue(issue)
        if not message:
            continue
        # Pair the i-th ``revision_plan`` entry with the i-th issue when
        # the reviewer exposes a top-level action list. This gives legacy
        # reviewers (and any future structured adapter) a way to attach
        # an explicit fix instruction without stuffing it into the issue
        # dict. Items without a paired plan keep the issue's own
        # suggestion.
        if index < len(plan_items):
            plan_text = str(plan_items[index] or "").strip()
            if plan_text:
                suggestion = plan_text
        blocking = explicit_blocking if explicit_blocking is not None else default_blocking
        findings.append(
            ReviewFinding(
                code=f"{source}.{_slugify(message)}",
                category=category_name,
                blocking=blocking,
                message=message,
                suggestion=suggestion,
                source=source,
                evidence=evidence,
            )
        )
    return ReviewResult.from_findings(findings, diagnostics=diagnostics)


def _adapt_critical_report(report: Any) -> ReviewResult:
    """Preserve the critical prose reviewer's own hard/soft classification.

    ``review_critical_prose_rules`` already separates factual/contract-breaking
    failures (POV leakage, planning metadata, role-boundary violations, etc.)
    from subjective craft concerns such as paragraph texture or metaphor
    density. Treating every returned issue as blocking discards that distinction
    and can make automatic revision chase stylistic thresholds indefinitely.

    Legacy critical reviewers that do not expose ``hard_issues`` / ``soft_issues``
    keep the previous fail-closed behavior.
    """
    if not isinstance(report, dict):
        return ReviewResult.from_findings([])

    has_layered_classification = "hard_issues" in report or "soft_issues" in report
    if not has_layered_classification:
        return _adapt_report(report, source="critical", default_blocking=True)

    diagnostics = {key: value for key, value in report.items() if key not in {"issues", "revision_plan", "scores"}}
    issues = list(report.get("issues") or [])
    plan_items = list(report.get("revision_plan") or [])
    hard_messages = {str(item).strip() for item in (report.get("hard_issues") or []) if str(item).strip()}
    findings: list[ReviewFinding] = []

    for index, issue in enumerate(issues):
        message, suggestion, evidence, explicit_blocking = _normalize_issue(issue)
        if not message:
            continue
        if index < len(plan_items):
            plan_text = str(plan_items[index] or "").strip()
            if plan_text:
                suggestion = plan_text
        blocking = bool(explicit_blocking) if explicit_blocking is not None else message in hard_messages
        findings.append(
            ReviewFinding(
                code=f"critical.{_slugify(message)}",
                category="hard" if blocking else "prose",
                blocking=blocking,
                message=message,
                suggestion=suggestion,
                source="critical",
                evidence=evidence,
            )
        )

    return ReviewResult.from_findings(findings, diagnostics=diagnostics)


_LEGACY_GENRE_HARD_PREFIXES: tuple[str, ...] = (
    "低等级越级：",
    "Lv.1越级：",
    "经验账本不清：",
)


def _genre_hard_messages(report: dict[str, Any]) -> set[str]:
    """Collect only objective legacy genre findings that may block.

    New/structured genre reviewers should emit ``blocking`` on an issue or
    expose ``hard_issues``. The game-webnovel reviewer still returns a legacy
    flat ``issues`` list, so keep a deliberately narrow bridge for established
    level/progression mechanics and for the dedicated numeric-consistency
    subreview. Editorial opening/pacing/payoff/style findings stay advisory.
    """
    hard_messages: set[str] = set()
    for item in report.get("hard_issues") or []:
        message, _, _, _ = _normalize_issue(item)
        if message:
            hard_messages.add(message)

    active = report.get("active_genre_reviews")
    if isinstance(active, dict):
        numeric = active.get("numeric_consistency_review")
        if isinstance(numeric, dict):
            for item in numeric.get("issues") or []:
                message, _, _, _ = _normalize_issue(item)
                if message:
                    hard_messages.add(message)

    for item in report.get("issues") or []:
        message, _, _, _ = _normalize_issue(item)
        if message and message.startswith(_LEGACY_GENRE_HARD_PREFIXES):
            hard_messages.add(message)
    return hard_messages


def _adapt_genre_report(report: Any) -> ReviewResult:
    if not isinstance(report, dict):
        return ReviewResult.from_findings([])
    diagnostics = {key: value for key, value in report.items() if key not in {"issues", "revision_plan", "scores", "active_genre_reviews"}}
    active = report.get("active_genre_reviews")
    if isinstance(active, dict):
        diagnostics["active_genre_reviews"] = active
    issues = list(report.get("issues") or [])
    plan_items = list(report.get("revision_plan") or [])
    hard_messages = _genre_hard_messages(report)
    findings: list[ReviewFinding] = []
    for index, issue in enumerate(issues):
        message, suggestion, evidence, explicit_blocking = _normalize_issue(issue)
        if not message:
            continue
        # Pair revision_plan[i] with issues[i] so the writer gets the
        # fix instruction even when genre reviewers do not embed it
        # in the issue dict.
        if index < len(plan_items):
            plan_text = str(plan_items[index] or "").strip()
            if plan_text:
                suggestion = plan_text
        # Genre fit, payoff strength, trope coverage and similar findings are
        # editorial judgments. A report-level ``pass: false`` must not turn all
        # of them into hard blockers. Structured genre findings can still opt
        # into blocking explicitly; the narrow legacy bridge above preserves
        # objective level/progression/numeric contradictions until those
        # reviewers emit structured disposition themselves.
        blocking = (
            bool(explicit_blocking)
            if explicit_blocking is not None
            else message in hard_messages
        )
        findings.append(
            ReviewFinding(
                code=f"genre.{_slugify(message)}",
                category="hard" if blocking else "prose",
                blocking=blocking,
                message=message,
                suggestion=suggestion,
                source="genre",
                evidence=evidence,
            )
        )
    return ReviewResult.from_findings(findings, diagnostics=diagnostics)


def _adapt_plot_spine_report(report: Any) -> ReviewResult:
    if not isinstance(report, dict):
        return ReviewResult.from_findings([])
    diagnostics = {key: value for key, value in report.items() if key not in {"issues", "revision_plan", "scores"}}
    issues = list(report.get("issues") or [])
    plan_items = list(report.get("revision_plan") or [])
    findings: list[ReviewFinding] = []
    for index, issue in enumerate(issues):
        message, suggestion, evidence, explicit_blocking = _normalize_issue(issue)
        if not message:
            continue
        if index < len(plan_items):
            plan_text = str(plan_items[index] or "").strip()
            if plan_text:
                suggestion = plan_text
        blocking = bool(explicit_blocking) if explicit_blocking is not None else False
        findings.append(
            ReviewFinding(
                code=f"plot_spine.{_slugify(message)}",
                category="hard" if blocking else "prose",
                blocking=blocking,
                message=message,
                suggestion=suggestion,
                source="plot_spine",
                evidence=evidence,
            )
        )
    return ReviewResult.from_findings(findings, diagnostics=diagnostics)


def _normalize_issue(issue: Any) -> tuple[str, str, str, bool | None]:
    if isinstance(issue, str):
        return issue.strip(), "", "", None
    if isinstance(issue, dict):
        for key in ("reason", "message", "issue", "type"):
            text = str(issue.get(key) or "").strip()
            if text:
                suggestion = str(issue.get("suggestion") or "").strip()
                evidence = str(issue.get("evidence") or "").strip()
                blocking = issue.get("blocking")
                if blocking is None and "severity" in issue:
                    blocking = str(issue.get("severity") or "").strip().lower() == "blocking"
                return text, suggestion, evidence, blocking
    return "", "", "", None


def _slugify(text: str) -> str:
    normalized = "".join(ch for ch in str(text) if ch.isalnum() or ch in {"_", "-"})
    return normalized[:40] or "issue"
