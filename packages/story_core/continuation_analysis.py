from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from typing import Any, Literal, Protocol

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.continuation_import import ContinuationChapter
from packages.story_core.continuation_sessions import ContinuationSessionStore
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.runtime_config import StageRuntimeSettings, resolve_stage_runtime


Confidence = Literal["confirmed", "inferred"]

CONTINUATION_BATCH_BODY_CHAR_BUDGET = 60_000
CONTINUATION_CHAPTER_MAX_CHARS = 50_000
CONTINUATION_ANALYSIS_PROMPT_CHAR_BUDGET = 80_000
CONTINUATION_MERGE_CHAR_BUDGET = 80_000
CONTINUATION_RECENT_BODY_CHAR_BUDGET = 30_000
_RECENT_TAIL_MARKER = "[TRUNCATED_TO_RECENT_TAIL]"
_COMPACT_VALUE_MARKER = "[TRUNCATED]"
_ANALYSIS_BODY_MARKER = "[TRUNCATED_MIDDLE]"
_ANALYSIS_TITLE_MAX_CHARS = 160


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvidenceRef(_StrictModel):
    chapter_id: str = Field(min_length=1)
    excerpt_start: int
    excerpt_end: int
    quote: str = ""

    @model_validator(mode="after")
    def _valid_range(self) -> "EvidenceRef":
        if self.excerpt_start < 0 or self.excerpt_end <= self.excerpt_start:
            raise ValueError("invalid_evidence_range")
        return self


class ClaimItem(_StrictModel):
    claim: str = Field(min_length=1)
    confidence: Confidence = "inferred"
    evidence: list[EvidenceRef] = Field(default_factory=list)


class CharacterAnalysis(_StrictModel):
    name: str = Field(min_length=1)
    role: str = ""
    summary: str = ""
    confidence: Confidence = "inferred"
    evidence: list[EvidenceRef] = Field(default_factory=list)
    states: list[ClaimItem] = Field(default_factory=list)
    relationships: list[ClaimItem] = Field(default_factory=list)


class TimelineEvent(_StrictModel):
    text: str = Field(min_length=1)
    sequence: str = ""
    confidence: Confidence = "inferred"
    evidence: list[EvidenceRef] = Field(default_factory=list)


class HookAnalysis(_StrictModel):
    text: str = Field(min_length=1)
    status: Literal["open", "resolved", "uncertain"] = "open"
    confidence: Confidence = "inferred"
    evidence: list[EvidenceRef] = Field(default_factory=list)


class StyleProfile(_StrictModel):
    narrative_voice: str = ""
    point_of_view: str = ""
    tense: str = ""
    pacing: str = ""
    dialogue_style: str = ""
    prose_features: list[str] = Field(default_factory=list)


class ContinuationStart(_StrictModel):
    chapter_id: str = ""
    situation: str = ""
    guidance: str = ""
    constraints: list[ClaimItem] = Field(default_factory=list)


class NeedsConfirmation(_StrictModel):
    claim: str
    source: str
    reason: str = "invalid_or_missing_evidence"


class ChapterAnalysis(_StrictModel):
    chapter_id: str = Field(min_length=1)
    summary: str = ""
    characters: list[CharacterAnalysis] = Field(default_factory=list)
    facts: list[ClaimItem] = Field(default_factory=list)
    locations: list[ClaimItem] = Field(default_factory=list)
    timeline_events: list[TimelineEvent] = Field(default_factory=list)
    power_changes: list[ClaimItem] = Field(default_factory=list)
    hooks: list[HookAnalysis] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    needs_confirmation: list[NeedsConfirmation] = Field(default_factory=list)


class ContinuationAnalysis(_StrictModel):
    story_overview: str = ""
    characters: list[CharacterAnalysis] = Field(default_factory=list)
    world: list[ClaimItem] = Field(default_factory=list)
    power_system: list[ClaimItem] = Field(default_factory=list)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    open_hooks: list[HookAnalysis] = Field(default_factory=list)
    style_profile: StyleProfile = Field(default_factory=StyleProfile)
    continuation_start: ContinuationStart = Field(default_factory=ContinuationStart)
    evidence_index: dict[str, list[EvidenceRef]] = Field(default_factory=dict)
    needs_confirmation: list[NeedsConfirmation] = Field(default_factory=list)


class ContinuationAnalyzer(Protocol):
    def analyze_chapters(
        self, chapters: list[ContinuationChapter]
    ) -> list[ChapterAnalysis]: ...

    def merge(
        self,
        chapter_results: list[ChapterAnalysis],
        recent_chapters: list[ContinuationChapter],
    ) -> ContinuationAnalysis: ...


class _ChapterBatchResponse(_StrictModel):
    chapters: list[ChapterAnalysis]


def _valid_evidence(
    evidence: Iterable[EvidenceRef], chapters_by_id: dict[str, ContinuationChapter]
) -> list[EvidenceRef]:
    valid: list[EvidenceRef] = []
    for item in evidence:
        chapter = chapters_by_id.get(item.chapter_id)
        if chapter is None or item.excerpt_end > len(chapter.body):
            continue
        if item.quote and chapter.body[item.excerpt_start : item.excerpt_end] != item.quote:
            continue
        valid.append(item)
    return valid


def _claim_text(item: CharacterAnalysis | ClaimItem | TimelineEvent | HookAnalysis) -> str:
    if isinstance(item, ClaimItem):
        return item.claim
    if isinstance(item, TimelineEvent | HookAnalysis):
        return item.text
    return item.summary or item.name


def _chapter_claims(result: ChapterAnalysis) -> Iterable[tuple[str, Any]]:
    for field_name in ("facts", "locations", "timeline_events", "power_changes", "hooks"):
        for index, item in enumerate(getattr(result, field_name)):
            yield f"chapter.{result.chapter_id}.{field_name}.{index}", item
    for index, character in enumerate(result.characters):
        yield f"chapter.{result.chapter_id}.characters.{index}", character
        for field_name in ("states", "relationships"):
            for sub_index, item in enumerate(getattr(character, field_name)):
                yield (
                    f"chapter.{result.chapter_id}.characters.{index}.{field_name}.{sub_index}",
                    item,
                )


def _analysis_claims(analysis: ContinuationAnalysis) -> Iterable[tuple[str, Any]]:
    for field_name in ("world", "power_system", "timeline", "open_hooks"):
        for index, item in enumerate(getattr(analysis, field_name)):
            yield f"{field_name}.{index}", item
    for index, character in enumerate(analysis.characters):
        yield f"characters.{index}", character
        for field_name in ("states", "relationships"):
            for sub_index, item in enumerate(getattr(character, field_name)):
                yield f"characters.{index}.{field_name}.{sub_index}", item
    for index, item in enumerate(analysis.continuation_start.constraints):
        yield f"continuation_start.constraints.{index}", item


def _normalize_claims(
    claims: Iterable[tuple[str, Any]],
    chapters_by_id: dict[str, ContinuationChapter],
    needs_confirmation: list[NeedsConfirmation] | None = None,
    evidence_index: dict[str, list[EvidenceRef]] | None = None,
) -> None:
    for path, item in claims:
        had_evidence = bool(item.evidence)
        was_confirmed = item.confidence == "confirmed"
        item.evidence = _valid_evidence(item.evidence, chapters_by_id)
        if item.evidence and evidence_index is not None:
            evidence_index[path] = list(item.evidence)
        if item.confidence == "confirmed" and not item.evidence:
            item.confidence = "inferred"
        if (
            needs_confirmation is not None
            and not item.evidence
            and (had_evidence or was_confirmed)
        ):
            needs_confirmation.append(
                NeedsConfirmation(claim=_claim_text(item), source=path)
            )


def _normalize_chapter_result(
    result: ChapterAnalysis, chapters_by_id: dict[str, ContinuationChapter]
) -> ChapterAnalysis:
    normalized = result.model_copy(deep=True)
    normalized.evidence = _valid_evidence(normalized.evidence, chapters_by_id)
    confirmations = list(normalized.needs_confirmation)
    _normalize_claims(
        _chapter_claims(normalized), chapters_by_id, confirmations
    )
    normalized.needs_confirmation = list(
        {
            (item.claim, item.source): item
            for item in confirmations
        }.values()
    )
    return normalized


def _normalize_analysis(
    analysis: ContinuationAnalysis,
    chapters: list[ContinuationChapter],
    chapter_results: list[ChapterAnalysis],
) -> ContinuationAnalysis:
    normalized = analysis.model_copy(deep=True)
    chapters_by_id = {chapter.chapter_id: chapter for chapter in chapters}
    confirmations = [
        confirmation
        for result in chapter_results
        for confirmation in result.needs_confirmation
    ]
    confirmations.extend(normalized.needs_confirmation)
    evidence_index: dict[str, list[EvidenceRef]] = {}
    for result in chapter_results:
        _normalize_claims(
            _chapter_claims(result),
            chapters_by_id,
            confirmations,
            evidence_index,
        )
    _normalize_claims(
        _analysis_claims(normalized),
        chapters_by_id,
        confirmations,
        evidence_index,
    )
    deduplicated: list[NeedsConfirmation] = []
    seen: set[tuple[str, str]] = set()
    for item in confirmations:
        key = (item.claim, item.source)
        if key not in seen:
            seen.add(key)
            deduplicated.append(item)
    normalized.needs_confirmation = deduplicated
    normalized.evidence_index = evidence_index
    return normalized


def _safe_error(exc: BaseException) -> str:
    if isinstance(exc, ValueError) and str(exc) in {
        "invalid_chapter_analysis",
        "continuation_analysis_invalid_response",
        "continuation_chapter_too_large",
        "continuation_analysis_prompt_budget_too_small",
        "session_revision_conflict",
    }:
        return str(exc)
    return "continuation_analysis_failed"


def _load_progress(
    progress: dict[str, Any], chapters: list[ContinuationChapter]
) -> list[ChapterAnalysis]:
    chapters_by_id = {chapter.chapter_id: chapter for chapter in chapters}
    raw_results = progress.get("chapter_results", [])
    raw_completed = progress.get("completed_chapter_ids", [])
    raw_signatures = progress.get("chapter_signatures", {})
    raw_order = progress.get("chapter_order", [])
    if (
        not isinstance(raw_results, list)
        or not isinstance(raw_completed, list)
        or not isinstance(raw_signatures, dict)
        or not isinstance(raw_order, list)
    ):
        return []
    completed_ids = {item for item in raw_completed if isinstance(item, str)}
    valid_by_id: dict[str, ChapterAnalysis] = {}
    for raw in raw_results:
        try:
            result = ChapterAnalysis.model_validate(raw)
        except (TypeError, ValidationError):
            continue
        chapter = chapters_by_id.get(result.chapter_id)
        if (
            chapter is None
            or result.chapter_id not in completed_ids
            or raw_signatures.get(result.chapter_id) != _chapter_signature(chapter)
            or result.chapter_id in valid_by_id
        ):
            continue
        valid_by_id[result.chapter_id] = _normalize_chapter_result(result, chapters_by_id)
    return [valid_by_id[chapter.chapter_id] for chapter in chapters if chapter.chapter_id in valid_by_id]


def _chapter_signature(chapter: ContinuationChapter) -> dict[str, Any]:
    return {
        "chapter_id": chapter.chapter_id,
        "number": chapter.number,
        "title": chapter.title,
        "fingerprint": chapter.fingerprint,
    }


def _progress_matches_chapters(
    progress: dict[str, Any], chapters: list[ContinuationChapter]
) -> bool:
    current_order = [chapter.chapter_id for chapter in chapters]
    current_signatures = {
        chapter.chapter_id: _chapter_signature(chapter) for chapter in chapters
    }
    return (
        progress.get("chapter_order") == current_order
        and progress.get("completed_chapter_ids") == current_order
        and progress.get("chapter_signatures") == current_signatures
    )


def _set_progress_identity(
    progress: dict[str, Any],
    completed: list[ChapterAnalysis],
    chapters: list[ContinuationChapter],
) -> None:
    chapters_by_id = {chapter.chapter_id: chapter for chapter in chapters}
    progress["chapter_fingerprints"] = {
        result.chapter_id: chapters_by_id[result.chapter_id].fingerprint
        for result in completed
    }
    progress["chapter_signatures"] = {
        result.chapter_id: _chapter_signature(chapters_by_id[result.chapter_id])
        for result in completed
    }
    progress["chapter_order"] = [chapter.chapter_id for chapter in chapters]


def _analysis_batches(
    chapters: list[ContinuationChapter],
    *,
    batch_size: int,
    body_char_budget: int,
    chapter_max_chars: int,
) -> Iterable[list[ContinuationChapter]]:
    batch: list[ContinuationChapter] = []
    batch_chars = 0
    for chapter in chapters:
        body_chars = len(chapter.body)
        if body_chars > chapter_max_chars or body_chars > body_char_budget:
            if batch:
                yield batch
            raise ValueError("continuation_chapter_too_large")
        if batch and (
            len(batch) >= batch_size or batch_chars + body_chars > body_char_budget
        ):
            yield batch
            batch = []
            batch_chars = 0
        batch.append(chapter)
        batch_chars += body_chars
    if batch:
        yield batch


def run_continuation_analysis(
    store: ContinuationSessionStore,
    session_id: str,
    analyzer: ContinuationAnalyzer,
    batch_size: int = 10,
    batch_body_char_budget: int = CONTINUATION_BATCH_BODY_CHAR_BUDGET,
    chapter_max_chars: int = CONTINUATION_CHAPTER_MAX_CHARS,
) -> ContinuationAnalysis:
    if batch_size <= 0:
        raise ValueError("invalid_batch_size")
    if batch_body_char_budget <= 0 or chapter_max_chars <= 0:
        raise ValueError("invalid_analysis_budget")

    session = store.get(session_id)
    chapters = list(session.chapters)
    if session.status == "ready" and _progress_matches_chapters(
        session.analysis_progress, chapters
    ):
        return ContinuationAnalysis.model_validate(session.analysis)
    if session.status == "cancelled":
        raise ValueError("continuation_analysis_cancelled")
    if session.status not in {"parsed", "failed", "analyzing", "ready"}:
        raise ValueError("continuation_analysis_invalid_status")

    chapters_by_id = {chapter.chapter_id: chapter for chapter in chapters}
    completed = _load_progress(session.analysis_progress, chapters)

    def begin(current) -> None:
        current.status = "analyzing"
        current.error = ""
        current.analysis = {}
        current.analysis_progress["completed_chapter_ids"] = [
            result.chapter_id for result in completed
        ]
        current.analysis_progress["chapter_results"] = [
            result.model_dump(mode="json") for result in completed
        ]
        _set_progress_identity(current.analysis_progress, completed, chapters)

    session = store.update(session_id, begin, expected_revision=session.revision)
    revision = session.revision
    completed_by_id = {result.chapter_id: result for result in completed}

    try:
        pending = [chapter for chapter in chapters if chapter.chapter_id not in completed_by_id]
        for batch in _analysis_batches(
            pending,
            batch_size=batch_size,
            body_char_budget=batch_body_char_budget,
            chapter_max_chars=chapter_max_chars,
        ):
            raw_results = analyzer.analyze_chapters(batch)
            try:
                results = [ChapterAnalysis.model_validate(item) for item in raw_results]
            except (TypeError, ValidationError):
                raise ValueError("invalid_chapter_analysis") from None
            expected_ids = [chapter.chapter_id for chapter in batch]
            result_ids = [result.chapter_id for result in results]
            if (
                len(result_ids) != len(expected_ids)
                or len(result_ids) != len(set(result_ids))
                or set(result_ids) != set(expected_ids)
            ):
                raise ValueError("invalid_chapter_analysis")
            by_id = {
                result.chapter_id: _normalize_chapter_result(result, chapters_by_id)
                for result in results
            }
            for chapter in batch:
                completed_by_id[chapter.chapter_id] = by_id[chapter.chapter_id]
            ordered = [completed_by_id[chapter.chapter_id] for chapter in chapters if chapter.chapter_id in completed_by_id]

            def checkpoint(current) -> None:
                current.analysis_progress["completed_chapter_ids"] = [
                    result.chapter_id for result in ordered
                ]
                current.analysis_progress["chapter_results"] = [
                    result.model_dump(mode="json") for result in ordered
                ]
                _set_progress_identity(current.analysis_progress, ordered, chapters)

            session = store.update(session_id, checkpoint, expected_revision=revision)
            revision = session.revision

        ordered = [completed_by_id[chapter.chapter_id] for chapter in chapters]
        recent_chapters = chapters[-min(10, len(chapters)) :]
        try:
            merged = ContinuationAnalysis.model_validate(
                analyzer.merge(ordered, recent_chapters)
            )
        except ValidationError:
            raise ValueError("continuation_analysis_invalid_response") from None
        merged = _normalize_analysis(merged, chapters, ordered)

        def finish(current) -> None:
            current.status = "ready"
            current.analysis = merged.model_dump(mode="json")
            current.error = ""

        store.update(session_id, finish, expected_revision=revision)
        return merged
    except BaseException as exc:
        if isinstance(exc, (KeyboardInterrupt, SystemExit)):
            raise
        error = _safe_error(exc)

        def fail(current) -> None:
            current.status = "failed"
            current.error = error
            current.analysis = {}

        try:
            store.update(session_id, fail, expected_revision=revision)
        except ValueError as conflict:
            if str(conflict) != "session_revision_conflict":
                raise
        raise


def _clipped(value: str, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    keep = max(0, limit - len(_COMPACT_VALUE_MARKER))
    return f"{text[:keep]}{_COMPACT_VALUE_MARKER}"


def _compact_evidence(evidence: list[EvidenceRef]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in evidence[:3]]


def _compact_claim(item: ClaimItem | TimelineEvent | HookAnalysis) -> dict[str, Any]:
    text = item.claim if isinstance(item, ClaimItem) else item.text
    return {
        "text": _clipped(text, 240),
        "confidence": item.confidence,
        "evidence": _compact_evidence(item.evidence),
    }


def _compact_chapter_result(result: ChapterAnalysis) -> dict[str, Any]:
    return {
        "chapter_id": result.chapter_id,
        "summary": _clipped(result.summary, 500),
        "characters": [
            {
                "name": _clipped(item.name, 80),
                "role": _clipped(item.role, 120),
                "summary": _clipped(item.summary, 240),
                "confidence": item.confidence,
                "evidence": _compact_evidence(item.evidence),
            }
            for item in result.characters[:8]
        ],
        "facts": [_compact_claim(item) for item in result.facts[:8]],
        "locations": [_compact_claim(item) for item in result.locations[:6]],
        "timeline_events": [
            _compact_claim(item) for item in result.timeline_events[:8]
        ],
        "power_changes": [
            _compact_claim(item) for item in result.power_changes[:8]
        ],
        "hooks": [_compact_claim(item) for item in result.hooks[:8]],
        "needs_confirmation": [
            {
                "claim": _clipped(item.claim, 240),
                "source": item.source,
                "reason": item.reason,
            }
            for item in result.needs_confirmation[:8]
        ],
        "compacted": True,
    }


def _summary_only_result(result: ChapterAnalysis) -> dict[str, Any]:
    return {
        "chapter_id": result.chapter_id,
        "summary": _clipped(result.summary, 240),
        "compacted": True,
        "omitted_fields": _COMPACT_VALUE_MARKER,
    }


def _recent_chapter_context(
    chapters: list[ContinuationChapter], body_char_budget: int
) -> list[dict[str, Any]]:
    remaining = body_char_budget
    selected: list[tuple[int, dict[str, Any]]] = []
    recent = chapters[-10:]
    for index in range(len(recent) - 1, -1, -1):
        if remaining <= 0:
            break
        chapter = recent[index]
        if len(chapter.body) <= remaining:
            excerpt = chapter.body
        else:
            tail_chars = max(0, remaining - len(_RECENT_TAIL_MARKER))
            tail = chapter.body[-tail_chars:] if tail_chars else ""
            excerpt = f"{_RECENT_TAIL_MARKER}{tail}"
            excerpt = excerpt[:remaining]
        selected.append(
            (
                index,
                {
                    "chapter_id": chapter.chapter_id,
                    "number": chapter.number,
                    "title": _clipped(chapter.title, 160),
                    "body_excerpt": excerpt,
                    "excerpt_kind": (
                        "full" if excerpt == chapter.body else "recent_tail"
                    ),
                },
            )
        )
        remaining -= len(excerpt)
    return [item for _, item in sorted(selected)]


def _merge_context(
    chapter_results: list[ChapterAnalysis],
    recent_chapters: list[ContinuationChapter],
    *,
    total_char_budget: int,
    recent_body_char_budget: int,
    system_prompt: str,
) -> dict[str, Any]:
    user_budget = total_char_budget - len(system_prompt)
    if user_budget <= 0:
        raise ValueError("continuation_analysis_invalid_response")

    output_schema = {
        "type": "ContinuationAnalysis",
        "required": [
            "story_overview",
            "characters",
            "world",
            "power_system",
            "timeline",
            "open_hooks",
            "style_profile",
            "continuation_start",
            "evidence_index",
            "needs_confirmation",
        ],
    }

    def build(
        included: list[tuple[int, dict[str, Any]]],
        recent: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "chapter_results": [item for _, item in sorted(included)],
            "recent_chapters": recent,
            "output_schema": output_schema,
            "rules": [
                "Synthesize analysis only; do not write continuation prose.",
                "Do not invent facts without valid evidence.",
                "Recent chapter excerpts retain the newest available text first.",
            ],
            "truncation": {
                "markers": [_COMPACT_VALUE_MARKER, _RECENT_TAIL_MARKER],
                "omitted_chapter_result_count": len(chapter_results) - len(included),
            },
        }

    recent_limit = min(recent_body_char_budget, max(0, user_budget // 2))
    recent = _recent_chapter_context(recent_chapters, recent_limit)
    context = build([], recent)
    while len(json.dumps(context, ensure_ascii=False, separators=(",", ":"))) > user_budget:
        if recent_limit == 0:
            raise ValueError("continuation_analysis_invalid_response")
        excess = len(json.dumps(context, ensure_ascii=False, separators=(",", ":"))) - user_budget
        recent_limit = max(0, recent_limit - excess - 32)
        recent = _recent_chapter_context(recent_chapters, recent_limit)
        context = build([], recent)

    included: list[tuple[int, dict[str, Any]]] = []
    for index in range(len(chapter_results) - 1, -1, -1):
        result = chapter_results[index]
        for compact in (_compact_chapter_result(result), _summary_only_result(result)):
            candidate = build([*included, (index, compact)], recent)
            serialized = json.dumps(
                candidate, ensure_ascii=False, separators=(",", ":")
            )
            if len(serialized) <= user_budget:
                included.append((index, compact))
                context = candidate
                break
    return context


_ANALYSIS_SYSTEM_PROMPT = (
    "Analyze only the supplied Chinese novel chapters. Return JSON only and "
    "follow output_schema exactly. Do not invent facts."
)


def _analysis_body_excerpt(body: str, limit: int) -> tuple[str, list[dict[str, int]]]:
    if limit >= len(body):
        return body, [{"excerpt_start": 0, "excerpt_end": len(body)}]
    usable = limit - len(_ANALYSIS_BODY_MARKER)
    if usable < 2:
        return "", []
    head_chars = usable // 2
    tail_chars = usable - head_chars
    tail_start = len(body) - tail_chars
    return (
        f"{body[:head_chars]}{_ANALYSIS_BODY_MARKER}{body[tail_start:]}",
        [
            {"excerpt_start": 0, "excerpt_end": head_chars},
            {"excerpt_start": tail_start, "excerpt_end": len(body)},
        ],
    )


def _body_limits(chapters: list[ContinuationChapter], total: int) -> list[int]:
    minimums = [
        min(len(chapter.body), len(_ANALYSIS_BODY_MARKER) + 2)
        for chapter in chapters
    ]
    limits = list(minimums)
    remaining = total - sum(limits)
    active = {index for index, chapter in enumerate(chapters) if limits[index] < len(chapter.body)}
    while remaining > 0 and active:
        share = max(1, remaining // len(active))
        progressed = False
        for index in sorted(active):
            capacity = len(chapters[index].body) - limits[index]
            added = min(capacity, share, remaining)
            limits[index] += added
            remaining -= added
            progressed = progressed or added > 0
            if limits[index] >= len(chapters[index].body):
                active.remove(index)
            if remaining == 0:
                break
        if not progressed:
            break
    return limits


def _analysis_context(
    chapters: list[ContinuationChapter], body_chars: int
) -> dict[str, Any]:
    limits = _body_limits(chapters, body_chars)
    chapter_payloads: list[dict[str, Any]] = []
    for chapter, limit in zip(chapters, limits, strict=True):
        body, segments = _analysis_body_excerpt(chapter.body, limit)
        chapter_payloads.append(
            {
                "chapter_id": chapter.chapter_id,
                "number": chapter.number,
                "title": _clipped(chapter.title, _ANALYSIS_TITLE_MAX_CHARS),
                "body": body,
                "body_truncated": body != chapter.body,
                "body_original_char_count": len(chapter.body),
                "body_segments": segments,
            }
        )
    return {
        "chapters": chapter_payloads,
        "body_char_count": sum(len(chapter.body) for chapter in chapters),
        "body_char_budget": body_chars,
        "output_schema": _ChapterBatchResponse.model_json_schema(),
        "rules": [
            "Return exactly one analysis for each supplied chapter_id.",
            "Evidence offsets are zero-based Python Unicode code point offsets into the original chapter body; a non-BMP character counts as one code point.",
            "When body_truncated is true, use body_segments to map visible text back to original offsets and do not cite the truncation marker.",
            "Mark confirmed only when valid evidence is present.",
        ],
    }


def _prompt_chars(system_prompt: str, context: dict[str, Any]) -> int:
    return len(system_prompt) + len(
        json.dumps(context, ensure_ascii=False, separators=(",", ":"))
    )


def _bounded_analysis_context(
    chapters: list[ContinuationChapter], total_char_budget: int
) -> dict[str, Any] | None:
    full_body_chars = sum(len(chapter.body) for chapter in chapters)
    full = _analysis_context(chapters, full_body_chars)
    if _prompt_chars(_ANALYSIS_SYSTEM_PROMPT, full) <= total_char_budget:
        return full

    minimum_body_chars = sum(
        min(len(chapter.body), len(_ANALYSIS_BODY_MARKER) + 2)
        for chapter in chapters
    )
    minimum = _analysis_context(chapters, minimum_body_chars)
    if _prompt_chars(_ANALYSIS_SYSTEM_PROMPT, minimum) > total_char_budget:
        return None

    low = minimum_body_chars
    high = full_body_chars
    best = minimum
    while low <= high:
        candidate_chars = (low + high) // 2
        candidate = _analysis_context(chapters, candidate_chars)
        if _prompt_chars(_ANALYSIS_SYSTEM_PROMPT, candidate) <= total_char_budget:
            best = candidate
            low = candidate_chars + 1
        else:
            high = candidate_chars - 1
    return best


class LLMContinuationAnalyzer:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
        batch_body_char_budget: int = CONTINUATION_BATCH_BODY_CHAR_BUDGET,
        chapter_max_chars: int = CONTINUATION_CHAPTER_MAX_CHARS,
        analysis_prompt_char_budget: int = CONTINUATION_ANALYSIS_PROMPT_CHAR_BUDGET,
        merge_char_budget: int = CONTINUATION_MERGE_CHAR_BUDGET,
        recent_body_char_budget: int = CONTINUATION_RECENT_BODY_CHAR_BUDGET,
    ) -> None:
        if min(
            batch_body_char_budget,
            chapter_max_chars,
            analysis_prompt_char_budget,
            merge_char_budget,
            recent_body_char_budget,
        ) <= 0:
            raise ValueError("invalid_analysis_budget")
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver
        self._batch_body_char_budget = batch_body_char_budget
        self._chapter_max_chars = chapter_max_chars
        self._analysis_prompt_char_budget = analysis_prompt_char_budget
        self._merge_char_budget = merge_char_budget
        self._recent_body_char_budget = recent_body_char_budget

    def _call(
        self,
        prompt_context: dict[str, Any],
        system_prompt: str,
        *,
        total_char_budget: int | None = None,
    ) -> dict[str, Any]:
        user_content = json.dumps(
            prompt_context, ensure_ascii=False, separators=(",", ":")
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]
        if total_char_budget is not None and sum(
            len(message["content"]) for message in messages
        ) > total_char_budget:
            raise ValueError("continuation_analysis_prompt_budget_too_small")
        try:
            runtime = self._runtime_resolver("planner")
            if runtime.provider != "codexcli" and not runtime.api_key:
                raise ValueError("runtime_unavailable")
            payload = {
                "model": runtime.model,
                "messages": messages,
                "response_format": {"type": "json_object"},
                "temperature": float(runtime.temperature),
                "max_tokens": 6000,
                "parameters": {"enable_thinking": False},
            }
            response = self._post_json(
                runtime.base_url,
                "/chat/completions",
                payload,
                runtime.api_key,
                provider=runtime.provider,
                codex_command=runtime.codex_command,
            )
            parsed = parse_json_message_content(response)
            if parsed is None:
                raise ValueError("invalid_json")
            return parsed
        except Exception as exc:
            raise ValueError("continuation_analysis_invalid_response") from exc

    def analyze_chapters(
        self, chapters: list[ContinuationChapter]
    ) -> list[ChapterAnalysis]:
        body_char_count = sum(len(chapter.body) for chapter in chapters)
        if (
            any(len(chapter.body) > self._chapter_max_chars for chapter in chapters)
            or body_char_count > self._batch_body_char_budget
        ):
            raise ValueError("continuation_chapter_too_large")
        return self._analyze_bounded_batch(chapters)

    def _analyze_bounded_batch(
        self, chapters: list[ContinuationChapter]
    ) -> list[ChapterAnalysis]:
        context = _bounded_analysis_context(
            chapters, self._analysis_prompt_char_budget
        )
        if context is None:
            if len(chapters) == 1:
                raise ValueError("continuation_analysis_prompt_budget_too_small")
            midpoint = len(chapters) // 2
            return [
                *self._analyze_bounded_batch(chapters[:midpoint]),
                *self._analyze_bounded_batch(chapters[midpoint:]),
            ]
        parsed = self._call(
            context,
            _ANALYSIS_SYSTEM_PROMPT,
            total_char_budget=self._analysis_prompt_char_budget,
        )
        try:
            return _ChapterBatchResponse.model_validate(parsed).chapters
        except ValidationError as exc:
            raise ValueError("continuation_analysis_invalid_response") from exc

    def merge(
        self,
        chapter_results: list[ChapterAnalysis],
        recent_chapters: list[ContinuationChapter],
    ) -> ContinuationAnalysis:
        system_prompt = (
            "Merge the supplied chapter analyses into a continuation brief. "
            "Return JSON only. Do not continue the novel and do not invent unsupported facts."
        )
        context = _merge_context(
            chapter_results,
            recent_chapters,
            total_char_budget=self._merge_char_budget,
            recent_body_char_budget=self._recent_body_char_budget,
            system_prompt=system_prompt,
        )
        parsed = self._call(
            context,
            system_prompt,
            total_char_budget=self._merge_char_budget,
        )
        try:
            return ContinuationAnalysis.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError("continuation_analysis_invalid_response") from exc
