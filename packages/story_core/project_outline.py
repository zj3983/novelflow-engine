from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _OutlineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OverallOutline(_OutlineModel):
    story: str = ""
    protagonist_goal: str = ""
    main_conflict: str = ""
    growth_path: str = ""
    ending_direction: str = ""


class ArcOutline(_OutlineModel):
    id: str = Field(strict=True)
    title: str = ""
    start_chapter: int = Field(default=1, ge=1, strict=True)
    end_chapter: int = Field(default=1, ge=1, strict=True)
    goal: str = ""
    obstacle: str = ""
    payoff: str = ""
    end_state: str = ""

    @field_validator("id")
    @classmethod
    def validate_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("invalid_arc_id")
        return value

    @field_validator("start_chapter", "end_chapter", mode="before")
    @classmethod
    def validate_positive_boundary(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and value < 1:
            raise ValueError("invalid_arc_chapter_range")
        return value

    @model_validator(mode="after")
    def validate_range(self) -> "ArcOutline":
        if self.end_chapter < self.start_chapter:
            raise ValueError("invalid_arc_chapter_range")
        return self


class ChapterPlan(_OutlineModel):
    chapter_number: int = Field(ge=1, strict=True)
    title: str = ""
    goal: str = ""
    obstacle: str = ""
    action: str = ""
    turn: str = ""
    payoff: str = ""
    ending_hook: str = ""

    @field_validator("chapter_number", mode="before")
    @classmethod
    def validate_chapter(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and value < 1:
            raise ValueError("invalid_chapter_number")
        return value


class ProjectOutline(_OutlineModel):
    schema_version: Literal["project-outline/v1"] = "project-outline/v1"
    overall: OverallOutline = Field(default_factory=OverallOutline)
    arcs: list[ArcOutline] = Field(default_factory=list)
    chapters: list[ChapterPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids_and_chapters(self) -> "ProjectOutline":
        arc_ids = [arc.id for arc in self.arcs]
        if len(arc_ids) != len(set(arc_ids)):
            raise ValueError("duplicate_arc_id")
        chapter_numbers = [chapter.chapter_number for chapter in self.chapters]
        if len(chapter_numbers) != len(set(chapter_numbers)):
            raise ValueError("duplicate_chapter_outline")
        return self


def normalize_project_outline(payload: Any) -> dict[str, Any]:
    normalized = ProjectOutline.model_validate({} if payload is None else payload).model_dump()
    normalized["arcs"].sort(
        key=lambda arc: (arc["start_chapter"], arc["end_chapter"], arc["id"])
    )
    normalized["chapters"].sort(key=lambda chapter: chapter["chapter_number"])
    return normalized


def outline_from_legacy_project(project: dict[str, Any]) -> dict[str, Any]:
    blueprint = project.get("world_blueprint")
    if not isinstance(blueprint, dict):
        blueprint = {}

    opening = blueprint.get("opening_arc")
    if not isinstance(opening, dict):
        opening = {}

    beats = opening.get("chapter_beats")
    if not isinstance(beats, list):
        beats = []

    chapters: list[dict[str, Any]] = []
    for beat in beats:
        if not isinstance(beat, dict):
            continue
        try:
            chapter_number = int(beat.get("chapter") or 0)
        except (TypeError, ValueError):
            continue
        if chapter_number < 1:
            continue
        chapters.append(
            {
                "chapter_number": chapter_number,
                "title": str(beat.get("title") or ""),
                "payoff": str(beat.get("required_payoff") or beat.get("payoff") or ""),
                "ending_hook": str(beat.get("ending_hook") or beat.get("hook") or ""),
            }
        )

    current_arc = str(blueprint.get("current_arc") or "").strip()
    arcs = []
    if current_arc:
        arcs.append(
            {
                "id": "legacy-opening",
                "title": "当前阶段",
                "start_chapter": 1,
                "end_chapter": max(
                    [chapter["chapter_number"] for chapter in chapters] or [10]
                ),
                "goal": current_arc,
            }
        )

    return normalize_project_outline(
        {
            "overall": {"story": str(project.get("seed_outline") or "")},
            "arcs": arcs,
            "chapters": chapters,
        }
    )


def select_outline_context(
    outline: dict[str, Any],
    chapter_number: int,
) -> dict[str, Any]:
    normalized = normalize_project_outline(outline)
    matching_arcs = [
        arc
        for arc in normalized["arcs"]
        if arc["start_chapter"] <= chapter_number <= arc["end_chapter"]
    ]
    active_arc = min(
        matching_arcs,
        key=lambda arc: (
            -arc["start_chapter"],
            arc["end_chapter"] - arc["start_chapter"],
            arc["id"],
        ),
        default=None,
    )
    chapter = next(
        (
            chapter
            for chapter in normalized["chapters"]
            if chapter["chapter_number"] == chapter_number
        ),
        None,
    )
    return {
        "schema_version": "outline-context/v1",
        "overall": normalized["overall"],
        "active_arc": active_arc,
        "chapter": chapter,
    }
