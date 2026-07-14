from __future__ import annotations

from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field, model_validator


class OverallOutline(BaseModel):
    story: str = ""
    protagonist_goal: str = ""
    main_conflict: str = ""
    growth_path: str = ""
    ending_direction: str = ""


class ArcOutline(BaseModel):
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    title: str = ""
    start_chapter: int = 1
    end_chapter: int = 1
    goal: str = ""
    obstacle: str = ""
    payoff: str = ""
    end_state: str = ""

    @model_validator(mode="after")
    def validate_range(self) -> "ArcOutline":
        if self.start_chapter < 1 or self.end_chapter < self.start_chapter:
            raise ValueError("invalid_arc_chapter_range")
        return self


class ChapterPlan(BaseModel):
    chapter_number: int
    title: str = ""
    goal: str = ""
    obstacle: str = ""
    action: str = ""
    turn: str = ""
    payoff: str = ""
    ending_hook: str = ""

    @model_validator(mode="after")
    def validate_chapter(self) -> "ChapterPlan":
        if self.chapter_number < 1:
            raise ValueError("invalid_chapter_number")
        return self


class ProjectOutline(BaseModel):
    schema_version: str = "project-outline/v1"
    overall: OverallOutline = Field(default_factory=OverallOutline)
    arcs: list[ArcOutline] = Field(default_factory=list)
    chapters: list[ChapterPlan] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_and_sort(self) -> "ProjectOutline":
        chapter_numbers = [chapter.chapter_number for chapter in self.chapters]
        if len(chapter_numbers) != len(set(chapter_numbers)):
            raise ValueError("duplicate_chapter_outline")
        self.arcs.sort(key=lambda arc: (arc.start_chapter, arc.end_chapter))
        self.chapters.sort(key=lambda chapter: chapter.chapter_number)
        return self


def normalize_project_outline(payload: Any) -> dict[str, Any]:
    return ProjectOutline.model_validate(payload or {}).model_dump()


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
    active_arc = max(
        matching_arcs,
        key=lambda arc: arc["start_chapter"],
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
