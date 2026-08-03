from __future__ import annotations

import json
import os
import re
import hashlib
import stat
from contextlib import contextmanager
from pathlib import Path
from pathlib import PurePosixPath
from typing import Any, Callable, Literal
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.story_core.continuation_analysis import ContinuationAnalysis
from packages.story_core.continuation_import import ContinuationChapter
from packages.story_core.continuation_sessions import (
    ContinuationImportSession,
    ContinuationSourceSnapshot,
    secure_named_file_lock,
)
from packages.story_core.file_project_creation import (
    CreatedFileProject,
    write_file_project_atomically,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.novel_type_catalog import (
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.project_outline import normalize_project_outline
from packages.story_core.relationship_graph import relationship_edge_id


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
    generate_outline: bool = True
    outline_chapters: int = Field(default=10, ge=0, le=30)
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


def _snapshot_relative_path(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    windows = Path(value)
    if (
        not value
        or "\\" in value
        or relative.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or any(part in {"", ".", ".."} for part in relative.parts)
        or relative.as_posix() != value
    ):
        raise ValueError("source_snapshot_invalid")
    return relative


def _validated_source_snapshot(
    session: ContinuationImportSession,
    source_snapshot: ContinuationSourceSnapshot,
) -> ContinuationSourceSnapshot:
    snapshot = ContinuationSourceSnapshot.model_validate(
        source_snapshot.model_dump(mode="python")
        if isinstance(source_snapshot, ContinuationSourceSnapshot)
        else source_snapshot
    )
    if (
        snapshot.source_fingerprint != session.source_fingerprint
        or snapshot.encoding != session.encoding
        or not snapshot.files
    ):
        raise ValueError("source_snapshot_invalid")
    seen: set[str] = set()
    for item in snapshot.files:
        _snapshot_relative_path(item.relative_path)
        if item.relative_path in seen:
            raise ValueError("source_snapshot_invalid")
        seen.add(item.relative_path)
        if hashlib.sha256(item.payload).hexdigest() != item.fingerprint:
            raise ValueError("source_snapshot_invalid")
    if snapshot.source_kind == "file":
        calculated = snapshot.files[0].fingerprint if len(snapshot.files) == 1 else ""
    else:
        combined = hashlib.sha256()
        for item in sorted(snapshot.files, key=lambda value: value.relative_path):
            combined.update(item.relative_path.encode("utf-8"))
            combined.update(b"\0")
            combined.update(item.fingerprint.encode("ascii"))
            combined.update(b"\n")
        calculated = combined.hexdigest()
    if calculated != snapshot.source_fingerprint:
        raise ValueError("source_snapshot_invalid")
    return snapshot


def _before_conversion_lock_open(path: Path) -> None:
    return None


@contextmanager
def _conversion_lease(export_root: Path, session_id: str):
    digest = hashlib.sha256(session_id.encode("utf-8")).hexdigest()
    with secure_named_file_lock(
        export_root,
        directory_name=".continuation-conversion-locks",
        lock_name=f"{digest}.lock",
        error_code="invalid_conversion_lock_path",
        before_open=_before_conversion_lock_open,
    ):
        yield


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
    summary = str(item.summary or "").strip()
    identity_match = re.search(r"\*\*身份\*\*[：:]\s*([^；\n]+)", summary)
    age_match = re.search(r"\*\*年龄\*\*[：:]\s*(\d+)\s*岁?", summary)
    cleaned_summary = re.sub(r"^#+\s*[^；\n]*[；\n]?\s*", "", summary)
    cleaned_summary = re.sub(r"(?:^|[；\n])\s*-\s*", "；", cleaned_summary)
    cleaned_summary = cleaned_summary.replace("**", "").strip("； \n")
    memories = [cleaned_summary] if cleaned_summary else []
    current_state: dict[str, Any] = {}
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
    for state in item.states:
        if (
            state.confidence != "confirmed"
            or not _included_at_branch(
                state,
                accepted_ids,
                branch_excludes_source=branch_excludes_source,
            )
        ):
            continue
        realm_match = re.search(
            r"(?:当前)?(?:修为|境界)\s*[：:]\s*([^；，。\n]+)",
            state.claim,
        )
        if realm_match:
            current_state["realm"] = realm_match.group(1).strip()
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
    character = {
        "name": item.name,
        "role": item.role or "supporting",
        "character_tier": "protagonist" if item.role == "protagonist" else "supporting",
        "memory": memories,
    }
    if identity_match or age_match:
        character["identity_profile"] = {
            "current_identity": identity_match.group(1).strip() if identity_match else "",
            "age": int(age_match.group(1)) if age_match else None,
        }
    if current_state:
        character["real_state"] = {"current": current_state, "recent_changes": []}
    return character


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


def _evidence_chapter_number(
    item: Any, chapter_numbers_by_id: dict[str, int], fallback: int
) -> int:
    for evidence in getattr(item, "evidence", []) or []:
        number = chapter_numbers_by_id.get(evidence.chapter_id)
        if number is not None:
            return number
    return fallback


def _relationship_graph(
    analysis: ContinuationAnalysis,
    chapter_numbers_by_id: dict[str, int],
    fallback_chapter: int,
) -> list[dict[str, Any]]:
    names = [character.name for character in analysis.characters]
    edges: list[dict[str, Any]] = []
    for character in analysis.characters:
        if character.confidence != "confirmed":
            continue
        for relation in character.relationships:
            if relation.confidence != "confirmed":
                continue
            target = next(
                (
                    name
                    for name in names
                    if name != character.name and name in relation.claim
                ),
                "",
            )
            if not target:
                match = re.search(r"(?:与|和)([^，。；;、]{1,24})", relation.claim)
                target = match.group(1).strip() if match else ""
            if not target or target == character.name:
                continue
            chapter_number = _evidence_chapter_number(
                relation, chapter_numbers_by_id, fallback_chapter
            )
            edges.append(
                {
                    "id": relationship_edge_id(character.name, target),
                    "source": character.name,
                    "target": target,
                    "relation_type": relation.claim,
                    "bond": relation.claim,
                    "current_state": relation.claim,
                    "first_chapter": chapter_number,
                    "last_changed_chapter": chapter_number,
                    "private_notes": [
                        json.dumps(
                            evidence.model_dump(mode="json"), ensure_ascii=False
                        )
                        for evidence in relation.evidence
                    ],
                }
            )
    return edges


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
    chapter_numbers_by_id = {
        chapter.chapter_id: chapter.number for chapter in accepted
    }
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
                "chapter_number": _evidence_chapter_number(
                    item, chapter_numbers_by_id, settings.start_after_chapter
                ),
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


_FACTION_SUFFIXES = (
    "\u5b97",
    "\u9601",
    "\u6559",
    "\u8054\u76df",
    "\u5546\u4f1a",
    "\u4e16\u5bb6",
    "\u5bb6",
    "\u65cf",
    "\u95e8",
    "\u5bab",
    "\u5bfa",
    "\u5e2e",
    "\u4f1a",
)
_LOCATION_SUFFIXES = (
    "\u8c37",
    "\u57ce",
    "\u5c71",
    "\u5cf0",
    "\u6d77",
    "\u5dde",
    "\u57df",
    "\u754c",
    "\u6d32",
    "\u6751",
    "\u9547",
    "\u5e9c",
    "\u9662",
    "\u5893",
    "\u603b\u90e8",
)


def _world_entities(
    claims: list[str],
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    locations: list[dict[str, str]] = []
    factions: list[dict[str, str]] = []
    seen_locations: set[str] = set()
    seen_factions: set[str] = set()
    for claim in claims:
        parts = re.split(r"[:\uff1a]", claim, maxsplit=1)
        if len(parts) != 2:
            continue
        name, description = (part.strip() for part in parts)
        if not name or not description or len(name) > 40:
            continue
        if name.endswith(_FACTION_SUFFIXES) and name not in seen_factions:
            factions.append({"name": name, "description": description})
            seen_factions.add(name)
        if name.endswith(_LOCATION_SUFFIXES) and name not in seen_locations:
            locations.append({"name": name, "description": description})
            seen_locations.add(name)
    return locations, factions


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
    confirmed_world = [
        item.claim.strip()
        for item in analysis.world
        if item.confidence == "confirmed"
        and item.claim.strip()
        and _included_at_branch(
            item,
            accepted_ids,
            branch_excludes_source=branch_excludes_source,
        )
    ]
    confirmed_power = [
        item.claim.strip()
        for item in analysis.power_system
        if item.confidence == "confirmed"
        and item.claim.strip()
        and _included_at_branch(
            item,
            accepted_ids,
            branch_excludes_source=branch_excludes_source,
        )
    ]
    locations, factions = _world_entities(confirmed_world)
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
    chapter_numbers_by_id = {
        chapter.chapter_id: chapter.number for chapter in accepted
    }
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
        "world_summary": "\n".join(confirmed_world) or overview,
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
        "relationship_graph": _relationship_graph(
            analysis, chapter_numbers_by_id, settings.start_after_chapter
        ),
        "enabled_skill_ids": [],
        "world_blueprint": {
            "genre_plugin_ids": [settings.novel_type_id],
            "premise": confirmed_world[0] if confirmed_world else overview,
            "current_arc": analysis.continuation_start.situation or direction,
            "world_rules": confirmed_world,
            "power_system": confirmed_power,
            "locations": locations,
            "factions": factions,
        },
        "current_chapter": settings.start_after_chapter,
        "status": "draft",
        "pipeline_stage": "imported",
        "active_story_id": f"file:{project_id}",
        "continuation": continuation,
    }


_CONTINUATION_STAGES = (
    "接住余波",
    "追索线索",
    "试探阻力",
    "逼近真相",
    "遭遇反制",
    "调整布局",
    "撬开缺口",
    "兑现成长",
    "正面碰撞",
    "留下新局",
)


def _continuation_outline(
    analysis: ContinuationAnalysis,
    settings: ContinuationSettings,
) -> dict[str, Any]:
    if not settings.generate_outline:
        return normalize_project_outline({})

    start = settings.start_after_chapter + 1
    end = settings.start_after_chapter + settings.outline_chapters
    genre = runtime_novel_type(settings.novel_type_id)
    trope_ids = [
        str(item.get("id") or "").strip()
        for item in novel_type_prompt_context(genre).get("genre_trope_templates", [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ] if genre is not None else []
    primary_trope_id = (
        "chapter_hook_escalation"
        if "chapter_hook_escalation" in trope_ids
        else (trope_ids[0] if trope_ids else None)
    )
    direction = (
        settings.direction.strip()
        or analysis.continuation_start.guidance.strip()
        or analysis.continuation_start.situation.strip()
        or "延续当前主线"
    )
    situation = analysis.continuation_start.situation.strip() or direction
    hooks = [
        item.text.strip()
        for item in analysis.open_hooks
        if item.confidence == "confirmed"
        and item.status != "resolved"
        and item.text.strip()
    ]
    protagonist = next(
        (
            item.name.strip()
            for item in analysis.characters
            if item.confidence == "confirmed"
            and item.role.strip().lower() in {"protagonist", "主角"}
            and item.name.strip()
        ),
        next(
            (
                item.name.strip()
                for item in analysis.characters
                if item.confidence == "confirmed" and item.name.strip()
            ),
            "主角",
        ),
    )
    growth_items: list[str] = []
    growth_chars = 0
    for item in analysis.power_system:
        claim = item.claim.strip()
        if item.confidence != "confirmed" or not claim:
            continue
        separator_chars = 1 if growth_items else 0
        if growth_chars + separator_chars + len(claim) > 500:
            break
        growth_items.append(claim)
        growth_chars += separator_chars + len(claim)
    growth = "；".join(growth_items)
    focuses = hooks or [direction]
    arcs: list[dict[str, Any]] = []
    if settings.start_after_chapter > 0:
        arcs.append(
            {
                "id": f"imported-history-1-{settings.start_after_chapter}",
                "title": "原著已发生",
                "start_chapter": 1,
                "end_chapter": settings.start_after_chapter,
                "goal": analysis.story_overview.strip() or "承接原著既有主线",
                "obstacle": situation,
                "payoff": f"原著推进至第{settings.start_after_chapter}章的既定状态。",
                "end_state": situation,
            }
        )
    arcs.append(
        {
            "id": f"continuation-{start}-{end}",
            "title": f"续写阶段：{direction[:18]}",
            "start_chapter": start,
            "end_chapter": end,
            "goal": direction,
            "obstacle": situation,
            "payoff": f"完成从第{settings.start_after_chapter}章遗留局势到下一阶段的推进。",
            "trope_id": primary_trope_id,
            "end_state": "当前冲突获得阶段性结果，并建立新的明确目标。",
        }
    )
    chapters: list[dict[str, Any]] = []
    for offset in range(settings.outline_chapters):
        number = start + offset
        focus = focuses[offset % len(focuses)]
        stage = _CONTINUATION_STAGES[offset % len(_CONTINUATION_STAGES)]
        cycle = offset // len(_CONTINUATION_STAGES) + 1
        title = f"{stage}：{focus[:12]}"
        if cycle > 1:
            title = f"{title}（{cycle}）"
        next_focus = focuses[(offset + 1) % len(focuses)]
        chapters.append(
            {
                "chapter_number": number,
                "title": title,
                "goal": focus,
                "obstacle": situation,
                "action": f"{protagonist}围绕“{focus}”采取具体行动并验证判断。",
                "turn": f"行动暴露新的限制，使“{direction}”进入下一阶段。",
                "payoff": f"推进“{focus}”，并形成可见的关系、信息或实力变化。",
                "ending_hook": (
                    f"将矛盾转向“{next_focus}”。"
                    if offset + 1 < settings.outline_chapters
                    else "本段目标暂时兑现，同时留下下一阶段的新问题。"
                ),
                "cast": [protagonist],
            }
        )

    return normalize_project_outline(
        {
            "overall": {
                "story": analysis.story_overview.strip() or situation,
                "protagonist_goal": direction,
                "main_conflict": situation,
                "growth_path": growth,
                "ending_direction": direction,
                "primary_trope_id": primary_trope_id,
                "core_ending_chapter": end,
                "extension_ceiling_chapter": end,
                "current_strategy": "observe",
                "ending_contract": direction,
            },
            "arcs": arcs,
            "chapters": chapters,
        }
    )


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
        item["summary"] = ""
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
    source_snapshot: ContinuationSourceSnapshot,
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
        "source/original",
    ):
        (root / relative).mkdir(parents=True, exist_ok=True)

    active_analysis = ContinuationAnalysis.model_validate(
        _active_analysis_payload(analysis, accepted, excluded, settings)
    )
    project = _project_payload(
        project_id, session, active_analysis, accepted, excluded, settings
    )
    state = _state_payload(
        project_id,
        active_analysis,
        accepted,
        settings,
        branch_excludes_source=bool(excluded),
    )
    _write_json(root / ".webnovel/project.json", project)
    _write_json(root / ".webnovel/state.json", state)
    _write_json(
        root / ".webnovel/outline.json",
        _continuation_outline(active_analysis, settings),
    )
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
        active_analysis.model_dump(mode="json"),
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
            "source_kind": source_snapshot.source_kind,
            "files": [
                {
                    "relative_path": item.relative_path,
                    "fingerprint": item.fingerprint,
                    "bytes": len(item.payload),
                }
                for item in source_snapshot.files
            ],
        },
    )

    for item in source_snapshot.files:
        relative = _snapshot_relative_path(item.relative_path)
        target = (root / "source" / "original").joinpath(*relative.parts)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("wb") as handle:
            handle.write(item.payload)
            handle.flush()
            os.fsync(handle.fileno())

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
    source_snapshot: ContinuationSourceSnapshot,
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

    manifest = json.loads((root / "source/manifest.json").read_text(encoding="utf-8"))
    expected_files = [
        {
            "relative_path": item.relative_path,
            "fingerprint": item.fingerprint,
            "bytes": len(item.payload),
        }
        for item in source_snapshot.files
    ]
    if (
        manifest.get("source_fingerprint") != source_snapshot.source_fingerprint
        or manifest.get("source_kind") != source_snapshot.source_kind
        or manifest.get("files") != expected_files
    ):
        raise ValueError("invalid_source_manifest")
    original_root = (root / "source/original").resolve(strict=True)
    for item in source_snapshot.files:
        relative = _snapshot_relative_path(item.relative_path)
        path = original_root.joinpath(*relative.parts)
        if path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path):
            raise ValueError("invalid_source_backup")
        resolved = path.resolve(strict=True)
        try:
            resolved.relative_to(original_root)
        except ValueError:
            raise ValueError("invalid_source_backup") from None
        if hashlib.sha256(resolved.read_bytes()).hexdigest() != item.fingerprint:
            raise ValueError("invalid_source_backup")


def _seal_source_originals(
    root: Path, source_snapshot: ContinuationSourceSnapshot
) -> None:
    original_root = (root / "source/original").resolve(strict=True)
    for item in source_snapshot.files:
        relative = _snapshot_relative_path(item.relative_path)
        path = original_root.joinpath(*relative.parts).resolve(strict=True)
        try:
            path.relative_to(original_root)
        except ValueError:
            raise ValueError("invalid_source_backup") from None
        os.chmod(path, stat.S_IREAD)
        if path.stat().st_mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH):
            raise ValueError("source_backup_not_readonly")


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
    source_snapshot: ContinuationSourceSnapshot,
    project_id_factory: Callable[[], str] | None = None,
    allow_unconfirmed_analysis: bool = False,
) -> CreatedFileProject:
    session = ContinuationImportSession.model_validate(session)
    settings = ContinuationSettings.model_validate(settings)
    if session.status != "ready" or not session.analysis:
        raise ValueError("continuation_session_not_ready")
    if (
        not allow_unconfirmed_analysis
        and session.analysis_progress.get("analysis_confirmed") is not True
    ):
        raise ValueError("continuation_analysis_not_confirmed")
    analysis = ContinuationAnalysis.model_validate(session.analysis)
    if analysis.needs_confirmation:
        raise ValueError("continuation_analysis_needs_confirmation")
    snapshot = _validated_source_snapshot(session, source_snapshot)

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
    accepted_source_text = "\n".join(
        f"{chapter.title}\n{chapter.body}" for chapter in accepted
    )
    accepted_ids = {chapter.chapter_id for chapter in accepted}
    branch_excludes_source = bool(excluded)
    for character in analysis.characters:
        if character.confidence != "confirmed" or not _included_at_branch(
            character,
            accepted_ids,
            branch_excludes_source=branch_excludes_source,
        ):
            continue
        character_name = character.name.strip()
        if character_name and character_name not in accepted_source_text:
            raise ValueError(
                f"continuation_character_missing_from_source:{character_name}"
            )

    export_path = Path(export_root)
    export_path.mkdir(parents=True, exist_ok=True)
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
            snapshot,
        )
        _validate_continuation_project(
            root,
            project_id,
            [chapter.number for chapter in accepted],
            snapshot,
        )
        _seal_source_originals(root, snapshot)

    with _conversion_lease(export_path, session.session_id):
        _assert_session_not_converted(export_path, session.session_id)
        final_root = write_file_project_atomically(export_path, project_id, writer)
    route_id = quote(f"file:{project_id}", safe="")
    return CreatedFileProject(
        project_id=project_id,
        root=final_root,
        next_path=f"/projects/{route_id}/outline",
    )
