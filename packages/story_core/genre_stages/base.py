from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


def review_placeholder_actor_names(moves: list[dict[str, Any]]) -> list[str]:
    suffixes = ("收购方", "管理员", "工作人员", "路人", "店员")
    for move in moves:
        name = str(move.get("name") or "").strip()
        if name.endswith(suffixes):
            return [f"角色“{name}”是岗位或占位称呼；删除该角色，或先使用已有具名角色卡。"]
    return []


class DirectorRenderer(Protocol):
    def __call__(
        self,
        *,
        story: Any,
        chapter_number: int,
        plan: Any,
        values: Any,
    ) -> str: ...


class WriterRenderer(Protocol):
    def __call__(self, *, context: Any) -> str: ...


class WriterContextPreparer(Protocol):
    def __call__(self, *, context: Any) -> Any: ...


class ChapterReviewer(Protocol):
    def __call__(self, *, context: Any) -> dict[str, Any]: ...


class RevisionRenderer(Protocol):
    def __call__(self, *, context: Any) -> str: ...


class LengthPromptRenderer(Protocol):
    def __call__(self, *, context: Any) -> str: ...


class BodyPostprocessor(Protocol):
    def __call__(self, *, context: Any) -> str: ...


class ChapterPhaseRenderer(Protocol):
    def __call__(self, chapter_number: int) -> str: ...


class DirectorPlanReviewer(Protocol):
    def __call__(self, *, context: Any) -> list[str]: ...


class SceneCardPreparer(Protocol):
    def __call__(self, *, context: Any) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class DirectorPlanReviewContext:
    story: Any
    moves: list[dict[str, Any]]
    plan: Any = None


@dataclass(frozen=True)
class SceneCardContext:
    story: Any
    chapter_number: int
    scene_cards: list[dict[str, Any]]
    world_facts: list[str]


@dataclass(frozen=True)
class GenreStageProfile:
    profile_id: str
    director_template_key: str
    render_director_prompt: DirectorRenderer
    render_writer_prompt: WriterRenderer
    review_chapter: ChapterReviewer
    render_revision_prompt: RevisionRenderer
    render_expansion_prompt: LengthPromptRenderer
    render_compression_prompt: LengthPromptRenderer
    postprocess_body: BodyPostprocessor
    chapter_phase: ChapterPhaseRenderer
    review_director_plan: DirectorPlanReviewer
    prepare_scene_cards: SceneCardPreparer
    prepare_writer_context: WriterContextPreparer
    stage_modules: dict[str, tuple[str, ...]]

    def modules_for(self, stage: str) -> tuple[str, ...]:
        return self.stage_modules.get(str(stage).strip(), ())
