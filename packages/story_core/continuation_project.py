from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.story_core.continuation_analysis import ContinuationAnalysis
from packages.story_core.continuation_import import ContinuationChapter
from packages.story_core.continuation_sessions import ContinuationImportSession
from packages.story_core.file_project_creation import (
    CreatedFileProject,
    write_file_project_atomically,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.novel_type_catalog import runtime_novel_type
from packages.story_core.project_outline import normalize_project_outline


_WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{number}" for number in range(1, 10)),
    *(f"LPT{number}" for number in range(1, 10)),
}


class ContinuationSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    start_after_chapter: int = Field(ge=1)
    fidelity: Literal["faithful", "adaptive"] = "faithful"
    target_chars: int = Field(default=4500, ge=1000, le=20_000)
    direction: str = Field(default="", max_length=1000)
    planned_chapters: int = Field(default=0, ge=0, le=10_000)
    must_preserve: list[str] = Field(default_factory=list, max_length=100)
    forbidden_content: list[str] = Field(default_factory=list, max_length=100)
    generate_outline: bool = False
    outline_chapters: int = Field(default=0, ge=0, le=30)
    novel_type_id: str = "generic_webnovel"

    @field_validator("direction", "novel_type_id", mode="before")
    @classmethod
    def _trim_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("must_preserve", "forbidden_content")
    @classmethod
    def _clean_rules(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for value in values:
            item = " ".join(value.split()).strip()
            if item and item not in cleaned:
                cleaned.append(item)
        return cleaned

    @model_validator(mode="after")
    def _validate_outline_settings(self) -> "ContinuationSettings":
        if runtime_novel_type(self.novel_type_id) is None:
            raise ValueError("invalid_novel_type")
        if self.generate_outline and not 5 <= self.outline_chapters <= 30:
            raise ValueError("invalid_outline_chapter_count")
        if not self.generate_outline and self.outline_chapters != 0:
            raise ValueError("unexpected_outline_chapter_count")
        return self


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _safe_chapter_filename(chapter: ContinuationChapter) -> str:
    title = re.sub(r'[\\/:*?"<>|\x00-\x1f]+', "", chapter.title).strip(" .")
    title = " ".join(title.split())[:80].rstrip(" .")
    if not title:
        title = f"Chapter {chapter.number}"
    if title.upper() in _WINDOWS_RESERVED_NAMES:
        title = f"_{title}"
    return f"{chapter.number:04d}-{title}.md"


def _included_at_branch(
    item: Any,
    accepted_ids: set[str],
    *,
    branch_excludes_source: bool,
) -> bool:
    if not branch_excludes_source:
        return True
    evidence = list(getattr(item, "evidence", []) or [])
    return bool(evidence) and all(ref.chapter_id in accepted_ids for ref in evidence)


def _analysis_style(
    analysis: ContinuationAnalysis,
    accepted_ids: set[str],
    *,
    branch_excludes_source: bool,
) -> str:
    profile = analysis.style_profile
    if profile.confidence != "confirmed" or not _included_at_branch(
        profile,
        accepted_ids,
        branch_excludes_source=branch_excludes_source,
    ):
        return "通俗网文"
    values = [
        profile.narrative_voice,
        profile.point_of_view,
        profile.tense,
        profile.pacing,
        profile.dialogue_style,
        *profile.prose_features,
    ]
    return "；".join(value.strip() for value in values if value.strip()) or "通俗网文"


def _character_state(
    item: Any,
    accepted_ids: set[str],
    *,
    branch_excludes_source: bool,
) -> dict[str, Any]:
    memories = [item.summary] if item.summary else []
    memories.extend(
        state.claim
        for state in item.states
        if state.claim
        and state.confidence == "confirmed"
        and _included_at_branch(
            state,
            accepted_ids,
            branch_excludes_source=branch_excludes_source,
        )
    )
    memories.extend(
        relation.claim
        for relation in item.relationships
        if relation.claim
        and relation.confidence == "confirmed"
        and _included_at_branch(
            relation,
            accepted_ids,
            branch_excludes_source=branch_excludes_source,
        )
    )
    return {
        "name": item.name,
        "role": item.role or "supporting",
        "character_tier": "protagonist" if item.role == "protagonist" else "supporting",
        "memory": memories,
    }


def _chapter_summary(chapter: ContinuationChapter) -> dict[str, Any]:
    compact = " ".join(chapter.body.split())
    return {
        "chapter_number": chapter.number,
        "chapter_title": chapter.title,
        "cadence": "measured",
        "summary": compact[:320] or chapter.title,
        "facts": [],
        "unresolved_threads": [],
        "next_focus": "continue",
    }


def _branch_overview(
    analysis: ContinuationAnalysis,
    accepted: list[ContinuationChapter],
    *,
    branch_excludes_source: bool,
) -> str:
    if not branch_excludes_source:
        return analysis.story_overview
    return "\n".join(
        f"第{chapter.number}章 {chapter.title}：{' '.join(chapter.body.split())[:240]}"
        for chapter in accepted
    )


def _state_payload(
    project_id: str,
    analysis: ContinuationAnalysis,
    accepted: list[ContinuationChapter],
    settings: ContinuationSettings,
    *,
    branch_excludes_source: bool,
) -> dict[str, Any]:
    novel_type = runtime_novel_type(settings.novel_type_id)
    if novel_type is None:
        raise ValueError("invalid_novel_type")
    constraints = [
        *settings.must_preserve,
        *(f"禁止：{item}" for item in settings.forbidden_content),
    ]
    accepted_ids = {chapter.chapter_id for chapter in accepted}
    state = StoryState(
        story_id=f"file:{project_id}",
        outline=_branch_overview(
            analysis,
            accepted,
            branch_excludes_source=branch_excludes_source,
        ),
        genre=novel_type.name,
        genre_plugin_ids=[novel_type.id],
        style=_analysis_style(
            analysis,
            accepted_ids,
            branch_excludes_source=branch_excludes_source,
        ),
        current_chapter=settings.start_after_chapter,
        author_constraints=constraints,
        characters=[
            _character_state(
                item,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
            for item in analysis.characters
            if item.confidence == "confirmed"
            and _included_at_branch(
                item,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
        ],
        world_facts=[
            item.claim
            for item in analysis.world
            if item.claim
            and item.confidence == "confirmed"
            and _included_at_branch(
                item,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
        ]
        + [
            item.claim
            for item in analysis.power_system
            if item.claim
            and item.confidence == "confirmed"
            and _included_at_branch(
                item,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
        ],
        progression_ledger={
            "source": "continuation_analysis",
            "power_system": [
                item.model_dump(mode="json")
                for item in analysis.power_system
                if item.confidence == "confirmed"
                and _included_at_branch(
                    item,
                    accepted_ids,
                    branch_excludes_source=branch_excludes_source,
                )
            ],
        },
        timeline=[
            {
                "chapter_number": settings.start_after_chapter,
                "summary": item.text,
                "impact": item.sequence or item.text,
            }
            for item in analysis.timeline
            if item.confidence == "confirmed"
            and _included_at_branch(
                item,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
        ],
        foreshadowing=[
            {
                "text": item.text,
                "first_chapter": settings.start_after_chapter,
                "status": "resolved" if item.status == "resolved" else "open",
            }
            for item in analysis.open_hooks
            if item.confidence == "confirmed"
            and _included_at_branch(
                item,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
        ],
        chapter_summaries=[_chapter_summary(chapter) for chapter in accepted],
        memory_index=[
            {
                "chapter_number": chapter.number,
                "chapter_title": chapter.title,
                "summary": _chapter_summary(chapter)["summary"],
            }
            for chapter in accepted
        ],
    )
    return state.model_dump(mode="json")


def _project_payload(
    project_id: str,
    session: ContinuationImportSession,
    analysis: ContinuationAnalysis,
    accepted: list[ContinuationChapter],
    excluded: list[ContinuationChapter],
    settings: ContinuationSettings,
) -> dict[str, Any]:
    title = Path(session.source_path).stem.strip() or "续写项目"
    accepted_ids = {chapter.chapter_id for chapter in accepted}
    branch_excludes_source = bool(excluded)
    analysis_direction_allowed = (
        not branch_excludes_source
        or analysis.continuation_start.chapter_id in accepted_ids
    )
    direction = (
        settings.direction
        or (
            analysis.continuation_start.guidance
            if analysis_direction_allowed
            else ""
        )
        or (
            analysis.continuation_start.situation
            if analysis_direction_allowed
            else ""
        )
    )
    overview = _branch_overview(
        analysis,
        accepted,
        branch_excludes_source=branch_excludes_source,
    )
    continuation = {
        **settings.model_dump(mode="json"),
        "schema_version": "continuation-project/v1",
        "session_id": session.session_id,
        "session_revision": session.revision,
        "source_path": session.source_path,
        "source_fingerprint": session.source_fingerprint,
        "branch_point": settings.start_after_chapter,
        "imported_source_chapters": [chapter.number for chapter in accepted],
        "excluded_source_chapters": [chapter.number for chapter in excluded],
        "excluded_source_chapter_ids": [chapter.chapter_id for chapter in excluded],
        "analysis_continuation_start": analysis.continuation_start.model_dump(mode="json"),
    }
    return {
        "project_id": project_id,
        "title": title,
        "source_path": session.source_path,
        "seed_outline": overview,
        "world_summary": overview,
        "current_focus": direction,
        "author_constraints": [
            *settings.must_preserve,
            *(f"禁止：{item}" for item in settings.forbidden_content),
        ],
        "character_profiles": [
            item.model_dump(mode="json")
            for item in analysis.characters
            if item.confidence == "confirmed"
            and _included_at_branch(
                item,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
        ],
        "relationship_graph": [],
        "enabled_skill_ids": [],
        "world_blueprint": {
            "genre_plugin_ids": [settings.novel_type_id],
            "power_system": [
                item.model_dump(mode="json")
                for item in analysis.power_system
                if item.confidence == "confirmed"
                and _included_at_branch(
                    item,
                    accepted_ids,
                    branch_excludes_source=branch_excludes_source,
                )
            ],
        },
        "current_chapter": settings.start_after_chapter,
        "status": "draft",
        "pipeline_stage": "imported",
        "active_story_id": f"file:{project_id}",
        "continuation": continuation,
    }


def _source_index(
    session: ContinuationImportSession,
    settings: ContinuationSettings,
) -> dict[str, Any]:
    return {
        "schema_version": "continuation-source-index/v1",
        "session_id": session.session_id,
        "source_path": session.source_path,
        "source_fingerprint": session.source_fingerprint,
        "encoding": session.encoding,
        "branch_point": settings.start_after_chapter,
        "chapters": [
            {
                "chapter_id": chapter.chapter_id,
                "number": chapter.number,
                "title": chapter.title,
                "source_name": chapter.source_name,
                "source_start": chapter.source_start,
                "source_end": chapter.source_end,
                "fingerprint": chapter.fingerprint,
                "body_chars": len(chapter.body),
                "reference_path": f"source/chapters/{_safe_chapter_filename(chapter)}",
                "status": (
                    "imported"
                    if chapter.number <= settings.start_after_chapter
                    else "excluded_after_branch"
                ),
            }
            for chapter in session.chapters
        ],
    }


def _active_analysis_payload(
    analysis: ContinuationAnalysis,
    accepted: list[ContinuationChapter],
    excluded: list[ContinuationChapter],
    settings: ContinuationSettings,
) -> dict[str, Any]:
    if not excluded:
        return analysis.model_dump(mode="json")

    accepted_ids = {chapter.chapter_id for chapter in accepted}

    def included(item: Any) -> bool:
        return _included_at_branch(
            item, accepted_ids, branch_excludes_source=True
        )

    payload = analysis.model_dump(mode="json")
    payload["story_overview"] = _branch_overview(
        analysis, accepted, branch_excludes_source=True
    )
    payload["characters"] = []
    for character in analysis.characters:
        if not included(character):
            continue
        item = character.model_dump(mode="json")
        item["states"] = [
            state.model_dump(mode="json") for state in character.states if included(state)
        ]
        item["relationships"] = [
            relation.model_dump(mode="json")
            for relation in character.relationships
            if included(relation)
        ]
        payload["characters"].append(item)
    for field_name in ("world", "power_system", "timeline", "open_hooks"):
        payload[field_name] = [
            item.model_dump(mode="json")
            for item in getattr(analysis, field_name)
            if included(item)
        ]
    if not included(analysis.style_profile):
        payload["style_profile"] = analysis.style_profile.model_copy(
            update={
                "narrative_voice": "",
                "point_of_view": "",
                "tense": "",
                "pacing": "",
                "dialogue_style": "",
                "prose_features": [],
                "confidence": "inferred",
                "evidence": [],
            }
        ).model_dump(mode="json")
    if analysis.continuation_start.chapter_id not in accepted_ids:
        payload["continuation_start"] = {
            "chapter_id": accepted[-1].chapter_id,
            "situation": f"从第{accepted[-1].number}章《{accepted[-1].title}》之后续写",
            "guidance": settings.direction,
            "constraints": [],
        }
    payload["evidence_index"] = {
        key: [
            ref.model_dump(mode="json")
            for ref in refs
            if ref.chapter_id in accepted_ids
        ]
        for key, refs in analysis.evidence_index.items()
        if any(ref.chapter_id in accepted_ids for ref in refs)
    }
    return ContinuationAnalysis.model_validate(payload).model_dump(mode="json")


def _write_continuation_project(
    root: Path,
    project_id: str,
    session: ContinuationImportSession,
    analysis: ContinuationAnalysis,
    accepted: list[ContinuationChapter],
    excluded: list[ContinuationChapter],
    settings: ContinuationSettings,
) -> None:
    for relative in (
        ".story-system/chapters",
        ".story-system/reviews",
        ".webnovel",
        "chapters",
        "commits",
        "reviews",
        "source",
        "source/chapters",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    project = _project_payload(
        project_id, session, analysis, accepted, excluded, settings
    )
    state = _state_payload(
        project_id,
        analysis,
        accepted,
        settings,
        branch_excludes_source=bool(excluded),
    )
    _write_json(root / ".webnovel/project.json", project)
    _write_json(root / ".webnovel/state.json", state)
    _write_json(root / ".webnovel/outline.json", normalize_project_outline({}))
    _write_json(
        root / ".story-system/MASTER_SETTING.json",
        {
            "schema_version": "story-system-master-setting/v1",
            "project": project,
            "state": state,
        },
    )
    _write_json(
        root / ".story-system/continuation-analysis.json",
        _active_analysis_payload(analysis, accepted, excluded, settings),
    )
    _write_json(root / "source/analysis.json", analysis.model_dump(mode="json"))
    source_index = _source_index(session, settings)
    _write_json(root / ".story-system/source-index.json", source_index)
    _write_json(
        root / "source/manifest.json",
        {
            "schema_version": "continuation-project-source-manifest/v1",
            "session_id": session.session_id,
            "source_path": session.source_path,
            "source_fingerprint": session.source_fingerprint,
            "encoding": session.encoding,
            "chapter_count": len(session.chapters),
        },
    )

    for chapter in session.chapters:
        _write_text(
            root / "source/chapters" / _safe_chapter_filename(chapter),
            chapter.body,
        )

    for chapter in accepted:
        summary = _chapter_summary(chapter)
        chapter_payload = {
            "schema_version": "imported-continuation-chapter/v1",
            "chapter_number": chapter.number,
            "chapter_title": chapter.title,
            "body": chapter.body,
            "cadence": "measured",
            "next_outline": "continue",
            "chapter_summary": summary,
            "source_import": {
                "chapter_id": chapter.chapter_id,
                "source_name": chapter.source_name,
                "source_start": chapter.source_start,
                "source_end": chapter.source_end,
                "fingerprint": chapter.fingerprint,
            },
        }
        _write_json(
            root / ".story-system/chapters" / f"{chapter.number:04d}.json",
            chapter_payload,
        )
        _write_text(root / "chapters" / _safe_chapter_filename(chapter), chapter.body)


def _validate_continuation_project(
    root: Path,
    project_id: str,
    expected_chapter_numbers: list[int],
) -> None:
    for path in root.rglob("*.json"):
        payload = json.loads(path.read_text(encoding="utf-8"))
        if json.loads(json.dumps(payload, ensure_ascii=False)) != payload:
            raise ValueError("invalid_json_roundtrip")

    raw_state = json.loads((root / ".webnovel/state.json").read_text(encoding="utf-8"))
    validated_state = StoryState.model_validate(raw_state).model_dump(mode="json")
    if validated_state != raw_state:
        raise ValueError("invalid_story_state")

    store = FileProjectStore(root)
    if not store.exists():
        raise ValueError("unreadable_file_project")
    if store.chapter_numbers() != expected_chapter_numbers:
        raise ValueError("invalid_imported_chapters")
    if store.project().get("project_id") != project_id:
        raise ValueError("invalid_project_payload")
    if int(store.state().get("current_chapter") or 0) != expected_chapter_numbers[-1]:
        raise ValueError("invalid_current_chapter")


def _assert_session_not_converted(export_root: Path, session_id: str) -> None:
    if not export_root.is_dir():
        return
    for project_file in export_root.glob("*/.webnovel/project.json"):
        try:
            project = json.loads(project_file.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            continue
        continuation = project.get("continuation")
        if isinstance(continuation, dict) and continuation.get("session_id") == session_id:
            raise FileExistsError("continuation_session_already_converted")


def create_continuation_project(
    export_root: str | Path,
    session: ContinuationImportSession,
    settings: ContinuationSettings,
    *,
    project_id_factory: Callable[[], str] | None = None,
) -> CreatedFileProject:
    session = ContinuationImportSession.model_validate(session)
    settings = ContinuationSettings.model_validate(settings)
    if session.status != "ready" or not session.analysis:
        raise ValueError("continuation_session_not_ready")
    if session.analysis_progress.get("analysis_confirmed") is not True:
        raise ValueError("continuation_analysis_not_confirmed")
    analysis = ContinuationAnalysis.model_validate(session.analysis)
    if analysis.needs_confirmation:
        raise ValueError("continuation_analysis_needs_confirmation")

    chapter_numbers = [chapter.number for chapter in session.chapters]
    if settings.start_after_chapter not in chapter_numbers:
        raise ValueError("invalid_continuation_point")
    accepted = [
        chapter
        for chapter in session.chapters
        if chapter.number <= settings.start_after_chapter
    ]
    excluded = [
        chapter
        for chapter in session.chapters
        if chapter.number > settings.start_after_chapter
    ]
    if not accepted or accepted[-1].number != settings.start_after_chapter:
        raise ValueError("invalid_continuation_point")

    export_path = Path(export_root)
    _assert_session_not_converted(export_path, session.session_id)
    project_id = (project_id_factory or (lambda: f"p-{uuid4().hex}"))()

    def writer(root: Path) -> None:
        _write_continuation_project(
            root,
            project_id,
            session,
            analysis,
            accepted,
            excluded,
            settings,
        )
        _validate_continuation_project(
            root, project_id, [chapter.number for chapter in accepted]
        )

    final_root = write_file_project_atomically(export_path, project_id, writer)
    route_id = quote(f"file:{project_id}", safe="")
    return CreatedFileProject(
        project_id=project_id,
        root=final_root,
        next_path=f"/projects/{route_id}/outline",
    )
