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
        "session_revision_conflict",
    }:
        return str(exc)
    return "continuation_analysis_failed"


def _load_progress(
    progress: dict[str, Any], chapters: list[ContinuationChapter]
) -> list[ChapterAnalysis]:
    chapters_by_id = {chapter.chapter_id: chapter for chapter in chapters}
    raw_results = progress.get("chapter_results", [])
    if not isinstance(raw_results, list):
        return []
    valid_by_id: dict[str, ChapterAnalysis] = {}
    for raw in raw_results:
        try:
            result = ChapterAnalysis.model_validate(raw)
        except (TypeError, ValidationError):
            continue
        if result.chapter_id not in chapters_by_id or result.chapter_id in valid_by_id:
            continue
        valid_by_id[result.chapter_id] = _normalize_chapter_result(result, chapters_by_id)
    return [valid_by_id[chapter.chapter_id] for chapter in chapters if chapter.chapter_id in valid_by_id]


def run_continuation_analysis(
    store: ContinuationSessionStore,
    session_id: str,
    analyzer: ContinuationAnalyzer,
    batch_size: int = 10,
) -> ContinuationAnalysis:
    if batch_size <= 0:
        raise ValueError("invalid_batch_size")

    session = store.get(session_id)
    if session.status == "ready":
        return ContinuationAnalysis.model_validate(session.analysis)
    if session.status == "cancelled":
        raise ValueError("continuation_analysis_cancelled")
    if session.status not in {"parsed", "failed", "analyzing"}:
        raise ValueError("continuation_analysis_invalid_status")

    chapters = list(session.chapters)
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

    session = store.update(session_id, begin, expected_revision=session.revision)
    revision = session.revision
    completed_by_id = {result.chapter_id: result for result in completed}

    try:
        pending = [chapter for chapter in chapters if chapter.chapter_id not in completed_by_id]
        for offset in range(0, len(pending), batch_size):
            batch = pending[offset : offset + batch_size]
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


class LLMContinuationAnalyzer:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
    ) -> None:
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver

    def _call(self, prompt_context: dict[str, Any], system_prompt: str) -> dict[str, Any]:
        try:
            runtime = self._runtime_resolver("planner")
            if runtime.provider != "codexcli" and not runtime.api_key:
                raise ValueError("runtime_unavailable")
            payload = {
                "model": runtime.model,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {
                        "role": "user",
                        "content": json.dumps(prompt_context, ensure_ascii=False),
                    },
                ],
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
        context = {
            "chapters": [
                {
                    "chapter_id": chapter.chapter_id,
                    "number": chapter.number,
                    "title": chapter.title,
                    "body": chapter.body,
                }
                for chapter in chapters
            ],
            "output_schema": _ChapterBatchResponse.model_json_schema(),
            "rules": [
                "Return exactly one analysis for each supplied chapter_id.",
                "Use offsets into that chapter body for evidence.",
                "Mark confirmed only when valid evidence is present.",
            ],
        }
        parsed = self._call(
            context,
            "Analyze only the supplied Chinese novel chapters. Return JSON only and follow output_schema exactly. Do not invent facts.",
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
        context = {
            "chapter_results": [item.model_dump(mode="json") for item in chapter_results],
            "recent_chapters": [
                {
                    "chapter_id": chapter.chapter_id,
                    "number": chapter.number,
                    "title": chapter.title,
                    "body": chapter.body,
                }
                for chapter in recent_chapters
            ],
            "output_schema": ContinuationAnalysis.model_json_schema(),
            "rules": [
                "Synthesize analysis only; do not write continuation prose.",
                "Do not invent facts without valid evidence.",
                "Use recent_chapters only to locate the continuation point.",
            ],
        }
        parsed = self._call(
            context,
            "Merge the supplied chapter analyses into a continuation brief. Return JSON only. Do not continue the novel and do not invent unsupported facts.",
        )
        try:
            return ContinuationAnalysis.model_validate(parsed)
        except ValidationError as exc:
            raise ValueError("continuation_analysis_invalid_response") from exc
