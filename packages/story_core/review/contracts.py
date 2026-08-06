"""Canonical chapter review contracts.

Defines the structured `ReviewFinding` and `ReviewResult` types that act as
the single source of truth for chapter-level review decisions at runtime.
Legacy v1 reports are projected to this schema via
`packages.story_core.review.legacy_adapter`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


ReviewCategory = Literal["hard", "dialogue", "ai_flavor", "prose"]
ReviewStatus = Literal["passed", "warning", "blocked"]


_CATEGORY_ORDER = {"hard": 0, "dialogue": 1, "ai_flavor": 2, "prose": 3}


@dataclass(frozen=True)
class ReviewFinding:
    code: str
    category: ReviewCategory
    blocking: bool
    message: str
    suggestion: str
    source: str
    evidence: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "category": self.category,
            "severity": "blocking" if self.blocking else "advisory",
            "blocking": self.blocking,
            "message": self.message,
            "suggestion": self.suggestion,
            "source": self.source,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class ReviewResult:
    status: ReviewStatus
    findings: tuple[ReviewFinding, ...] = ()
    diagnostics: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_findings(
        cls,
        findings: list[ReviewFinding],
        *,
        diagnostics: dict[str, Any] | None = None,
    ) -> "ReviewResult":
        deduplicated: dict[tuple[str, str], ReviewFinding] = {}
        for finding in findings:
            key = (
                finding.code,
                "".join(finding.message.split()).rstrip("。；;！!"),
            )
            deduplicated.setdefault(key, finding)
        ordered = sorted(
            deduplicated.values(),
            key=lambda item: (
                not item.blocking,
                _CATEGORY_ORDER[item.category],
            ),
        )
        status: ReviewStatus = (
            "blocked"
            if any(item.blocking for item in ordered)
            else ("warning" if ordered else "passed")
        )
        return cls(
            status=status,
            findings=tuple(ordered),
            diagnostics=diagnostics or {},
        )

    @property
    def has_hard_errors(self) -> bool:
        return any(item.blocking for item in self.findings)

    @property
    def needs_revision(self) -> bool:
        return self.has_hard_errors

    @property
    def revision_plan(self) -> list[str]:
        return [
            item.suggestion
            for item in self.findings
            if item.blocking and item.suggestion
        ][:3]

    def to_dict(self, *, issue_limit: int = 3) -> dict[str, Any]:
        selected = self.findings[:issue_limit]
        counts = {category: 0 for category in ("hard", "dialogue", "ai_flavor", "prose")}
        for finding in self.findings:
            counts[finding.category] += 1
        return {
            "schema_version": "review-result/v2",
            "status": self.status,
            "pass": not self.has_hard_errors,
            "has_hard_errors": self.has_hard_errors,
            "needs_revision": self.needs_revision,
            "issues": [item.to_dict() for item in selected],
            "revision_plan": self.revision_plan,
            "total_issues": len(self.findings),
            "categories": {
                "hard": {"label": "硬伤", "count": counts["hard"]},
                "dialogue": {"label": "对话", "count": counts["dialogue"]},
                "ai_flavor": {"label": "AI味", "count": counts["ai_flavor"]},
                "prose": {"label": "正文", "count": counts["prose"]},
            },
            "diagnostics": self.diagnostics,
        }
