from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from packages.story_core.outline_rolling import rolling_chapter_to_outline_entry
from packages.story_core.outline_rolling_store import RollingOutlineStore
from packages.story_core.persistence.project_locking import (
    with_project_update_lock as _with_project_update_lock,
)
from packages.story_core.quality import validate_bundle
from packages.story_core.review.contracts import ReviewFinding, ReviewResult
from packages.story_core.simplified_review import build_simplified_review
from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
    skill_module_key,
    skill_pack_prompt_context,
)


def _slugify_text(text: str) -> str:
    """Mirror the service-layer slugifier so finding codes stay
    consistent with the canonical review-result/v2 contract."""
    normalized = "".join(ch for ch in str(text or "") if ch.isalnum() or ch in {"_", "-"})
    return normalized[:40] or "issue"


def _project_legacy_review(payload: dict[str, Any]) -> dict[str, Any]:
    """Ensure a v1 review payload also exposes the canonical v2 fields.

    Persisted historical chapter data was saved before the v2 schema
    existed. The legacy v1 ``build_simplified_review`` shape is preserved
    under ``simplified_review`` (still useful for the front-end
    fall-back), and a fresh ``review_result`` is synthesized as a real
    ``review-result/v2`` payload — never reusing the v1 simplified dict
    as the v2 contract. Synthesizing rather than copying keeps the
    field names (``status``, ``categories``, ``diagnostics``,
    per-issue ``code``/``category``/``blocking``) consistent with what
    the auto generation path and the file-project write path emit.
    """
    if not isinstance(payload, dict):
        return payload
    projected = dict(payload)
    explicit = projected.get("review_result")
    if isinstance(explicit, dict) and explicit.get("schema_version") == "review-result/v2":
        projected.setdefault("simplified_review", explicit)
        return projected
    simplified = build_simplified_review(projected)
    if not isinstance(simplified, dict):
        return projected
    projected["simplified_review"] = simplified
    projected["review_result"] = _synthesize_v2_review_result(simplified)
    projected["ok"] = projected.get("ok", simplified.get("pass", True))
    return projected


def _synthesize_v2_review_result(simplified: dict[str, Any]) -> dict[str, Any]:
    """Build a canonical ``review-result/v2`` dict from a legacy v1
    simplified-review payload.

    The v1 shape carries issues as plain strings (or
    ``{"reason": ...}`` dicts from the legacy agents) plus coarse
    boolean flags (``has_hard_errors``, ``has_blocking_dialogue``,
    ``needs_revision``, ``pass``). We map those into ``ReviewFinding``
    objects so the v2 contract stays uniform with what the auto
    generation path emits. Anything v1 did not express explicitly
    (e.g. a per-issue ``blocking`` flag) inherits the report-level
    ``has_hard_errors`` flag, matching the v1 save/display semantics.
    """
    has_hard_errors = bool(simplified.get("has_hard_errors", False))
    has_blocking_dialogue = bool(simplified.get("has_blocking_dialogue", False))
    needs_revision = bool(simplified.get("needs_revision", has_hard_errors))
    revision_plan_items: list[str] = []
    for item in simplified.get("revision_plan") or []:
        text = str(item).strip()
        if text and text not in revision_plan_items:
            revision_plan_items.append(text)
    findings: list[ReviewFinding] = []
    issues = simplified.get("issues") or []
    for index, issue in enumerate(issues):
        if isinstance(issue, str):
            message = issue.strip()
            suggestion = ""
        elif isinstance(issue, dict):
            message = str(issue.get("reason") or issue.get("message") or "").strip()
            suggestion = str(issue.get("suggestion") or "").strip()
        else:
            continue
        if not message:
            continue
        # Pair revision_plan[i] with issues[i] so the writer sees the
        # matched fix instruction rather than the report-level
        # aggregate plan.
        suggestion = suggestion or (
            revision_plan_items[index] if index < len(revision_plan_items) else ""
        )
        # Treat the issue as blocking when the v1 report flagged any
        # hard error; otherwise it's advisory. Per-issue ``blocking``
        # keys from the v1 dict win when present.
        explicit_blocking = None
        if isinstance(issue, dict) and "blocking" in issue:
            explicit_blocking = bool(issue.get("blocking"))
        blocking = explicit_blocking if explicit_blocking is not None else has_hard_errors
        category = "hard" if blocking else "prose"
        findings.append(
            ReviewFinding(
                code=f"legacy.{_slugify_text(message)}",
                category=category,
                blocking=blocking,
                message=message,
                suggestion=suggestion,
                source="legacy_v1_projection",
            )
        )
    result = ReviewResult.from_findings(findings)
    payload = result.to_dict()
    # Carry the v1 report-level booleans through so callers that read
    # them directly (front-end fallback, downstream checks) keep
    # working.
    payload["pass"] = bool(simplified.get("pass", not has_hard_errors))
    payload["has_hard_errors"] = has_hard_errors
    payload["needs_revision"] = needs_revision
    if has_blocking_dialogue and "blocking_dialogue" not in (payload.get("diagnostics") or {}):
        diagnostics = dict(payload.get("diagnostics") or {})
        diagnostics["blocking_dialogue"] = True
        payload["diagnostics"] = diagnostics
    return payload


class ChapterReviewWorkflowMixin:
    """Read, run, and persist chapter review artifacts."""


    def review(self, chapter_number: int | None = None) -> dict[str, Any]:
        chapter = self.chapter(chapter_number)
        target = int(chapter.get("chapter_number") or chapter_number or 0)
        review = self._read_json(self.story_system_dir / "reviews" / f"{target:04d}.json")
        if isinstance(review, dict) and review:
            return _project_legacy_review(review)
        quality_report = chapter.get("quality_report")
        if isinstance(quality_report, dict) and quality_report:
            return _project_legacy_review(quality_report)
        return validate_bundle(chapter)

    def _candidate_artifacts_hash(self) -> str:
        digest = sha256()
        directory = self.candidate_store.directory
        if not directory.is_dir():
            return digest.hexdigest()
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            digest.update(str(path.relative_to(directory)).replace("\\", "/").encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    @staticmethod
    def _chapter_contracts(chapter: dict[str, Any], rolling_chapter: dict[str, Any]) -> dict[str, Any]:
        adapted = rolling_chapter_to_outline_entry(rolling_chapter)
        plan = adapted if isinstance(adapted, dict) else {}
        event_plan = chapter.get("event_plan") if isinstance(chapter.get("event_plan"), dict) else {}
        return {
            key: deepcopy(
                plan.get(key)
                or rolling_chapter.get(key)
                or chapter.get(key)
                or event_plan.get(key)
                or {}
            )
            for key in ("payoff_contract", "chapter_sop")
        }

    @_with_project_update_lock
    def _store_shuangwen_review(
        self,
        *,
        chapter_number: int,
        report: dict[str, Any],
        expected_artifact_hash: str,
        expected_body_hash: str,
        expected_candidate_hash: str,
    ) -> dict[str, Any]:
        chapter_path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
        if not chapter_path.is_file():
            raise FileNotFoundError(f"chapter_not_found:{chapter_number}")
        if sha256(chapter_path.read_bytes()).hexdigest() != expected_artifact_hash:
            raise ValueError("shuangwen_review_chapter_changed")
        raw_chapter = self._read_json(chapter_path, {}) or {}
        hydrated = self._hydrate_chapter_body(raw_chapter)
        body = str(hydrated.get("body") or "")
        if sha256(body.encode("utf-8")).hexdigest() != expected_body_hash:
            raise ValueError("shuangwen_review_body_changed")
        if self._candidate_artifacts_hash() != expected_candidate_hash:
            raise ValueError("shuangwen_review_candidate_changed")

        updated = dict(raw_chapter)
        quality_report = dict(updated.get("quality_report") or {})
        skill_reviews = dict(quality_report.get("skill_reviews") or {})
        skill_reviews["commercial-shuangwen"] = deepcopy(report)
        quality_report["skill_reviews"] = skill_reviews
        updated["quality_report"] = quality_report
        review_path = self.story_system_dir / "reviews" / f"{chapter_number:04d}.json"
        self._replace_json_transaction(
            {
                chapter_path: updated,
                review_path: deepcopy(quality_report),
            }
        )
        return deepcopy(report)

    def run_shuangwen_review(
        self,
        chapter_number: int,
        *,
        model_gateway: Any | None = None,
    ) -> dict[str, Any]:
        from packages.story_core.shuangwen_review import (
            ShuangwenReviewPreconditionError,
            review_shuangwen_chapter,
        )

        project = self.project()
        state = self.state()
        pack = self._review_skill_pack("commercial-shuangwen")
        if pack is None or not any(module.module_id == "review-checklist" for module in pack.modules):
            raise ValueError("commercial_shuangwen_skill_missing")
        if "commercial-shuangwen" not in resolve_enabled_skill_ids(project, state):
            raise ValueError("commercial_shuangwen_skill_disabled")
        enabled_modules = resolve_enabled_skill_module_ids(project, state)
        reviewer_key = skill_module_key("commercial-shuangwen", "review-checklist")
        if enabled_modules is not None and reviewer_key not in enabled_modules:
            raise ValueError("commercial_shuangwen_reviewer_disabled")
        if chapter_number < 1 or int(state.get("current_chapter") or 0) < chapter_number:
            raise ValueError(f"chapter_not_confirmed:{chapter_number}")

        chapter_path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
        if not chapter_path.is_file():
            raise FileNotFoundError(f"chapter_not_found:{chapter_number}")
        chapter = self.chapter(chapter_number)
        body = str(chapter.get("body") or "")
        if not body.strip():
            raise ShuangwenReviewPreconditionError(
                "shuangwen_review_confirmed_body_required"
            )
        artifact_hash = sha256(chapter_path.read_bytes()).hexdigest()
        body_hash = sha256(body.encode("utf-8")).hexdigest()
        candidate_hash = self._candidate_artifacts_hash()
        rolling_chapter = RollingOutlineStore(self.root).read_chapter(chapter_number) or {}
        genre_context = self._review_genre_context()
        genre_ids = genre_context.get("genre_plugin_ids") or []
        genre_id = str(genre_ids[0] if genre_ids else genre_context.get("genre") or "")
        skill_context = skill_pack_prompt_context(
            ["commercial-shuangwen"],
            enabled_module_ids=enabled_modules,
            purpose="reviewer",
            include_examples=True,
            genre_id=genre_id,
            max_chars_per_pack=2200,
            compact=True,
            max_serialized_chars=2600,
        )
        report = review_shuangwen_chapter(
            body=body,
            chapter_plan=self._chapter_contracts(chapter, rolling_chapter),
            skill_context=skill_context,
            model_gateway=model_gateway,
        )
        if sha256(body.encode("utf-8")).hexdigest() != body_hash:
            raise ValueError("shuangwen_review_body_changed")
        return self._store_shuangwen_review(
            chapter_number=chapter_number,
            report=report,
            expected_artifact_hash=artifact_hash,
            expected_body_hash=body_hash,
            expected_candidate_hash=candidate_hash,
        )
