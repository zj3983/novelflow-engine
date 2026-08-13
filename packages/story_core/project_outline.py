from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _OutlineModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


OutlineStrategy = Literal["observe", "expand", "close"]


class ExtensionGate(_OutlineModel):
    continue_route: str = ""
    close_route: str = ""


class LongTermStoryLine(_OutlineModel):
    name: str = ""
    purpose: str = ""
    start_state: str = ""
    progression_steps: list[str] = Field(default_factory=list)
    final_payoff: str = ""


class StoryPositioning(_OutlineModel):
    protagonist_profile: str = ""
    inciting_incident: str = ""
    failure_stakes: str = ""
    excitement_point: str = ""
    target_audience: str = ""
    reader_promise: str = ""


class ProtagonistDrive(_OutlineModel):
    immediate_need: str = ""
    trigger: str = ""
    short_term_goal: str = ""
    failure_stakes: str = ""
    long_term_transition: str = ""


class OutlineCoreAdvantage(_OutlineModel):
    name: str = ""
    type: str = ""
    ability: str = ""
    growth_rule: str = ""
    limits: str = ""
    early_payoff: str = ""


class OutlineCentralMystery(_OutlineModel):
    surface_anomaly: str = ""
    hidden_truth: str = ""
    reality_impact: str = ""
    reveal_path: list[str] = Field(default_factory=list)


class OverallOutline(_OutlineModel):
    story: str = ""
    theme_statement: str = ""
    foreground_story: str = ""
    background_story: str = ""
    book_objective: str = ""
    ending_image: str = ""
    protagonist_goal: str = ""
    main_conflict: str = ""
    growth_path: str = ""
    ending_direction: str = ""
    primary_trope_id: str | None = None
    core_ending_chapter: int = Field(default=1, ge=1, strict=True)
    extension_ceiling_chapter: int = Field(default=1, ge=1, strict=True)
    current_strategy: OutlineStrategy = "observe"
    ending_contract: str = ""
    core_selling_point: str = ""
    long_term_lines: list[LongTermStoryLine] = Field(default_factory=list)
    planned_arc_count: int = Field(default=0, ge=0, strict=True)
    planned_length: int = Field(default=0, ge=0, strict=True)
    expansion_route: str = ""
    closing_route: str = ""
    positioning: StoryPositioning = Field(default_factory=StoryPositioning)
    protagonist_drive: ProtagonistDrive = Field(default_factory=ProtagonistDrive)
    core_advantage: OutlineCoreAdvantage = Field(default_factory=OutlineCoreAdvantage)
    central_mystery: OutlineCentralMystery = Field(default_factory=OutlineCentralMystery)


class StoryNode(_OutlineModel):
    start_chapter: int = Field(ge=1, strict=True)
    end_chapter: int = Field(ge=1, strict=True)
    objective: str = ""
    pressure: str = ""
    turn: str = ""
    payoff: str = ""
    next_effect: str = ""


class ArcOutline(_OutlineModel):
    id: str = Field(strict=True)
    title: str = ""
    start_chapter: int = Field(default=1, ge=1, strict=True)
    end_chapter: int = Field(default=1, ge=1, strict=True)
    pacing_stage_id: str = ""
    goal: str = ""
    obstacle: str = ""
    payoff: str = ""
    emotional_curve: str = ""
    key_results: list[str] = Field(default_factory=list)
    hook_plan: str = ""
    irreversible_change: str = ""
    trope_id: str | None = None
    end_state: str = ""
    stage_antagonist: str = ""
    long_term_antagonist_traces: list[str] = Field(default_factory=list)
    game_line_payoff: str = ""
    reality_line_payoff: str = ""
    extension_gate: ExtensionGate = Field(default_factory=ExtensionGate)
    active_long_term_lines: list[str] = Field(default_factory=list)
    core_loop: str = ""
    escalations: list[str] = Field(default_factory=list)
    midpoint_turn: str = ""
    climax: str = ""
    relationship_changes: list[str] = Field(default_factory=list)
    foreshadowing_in: list[str] = Field(default_factory=list)
    foreshadowing_out: list[str] = Field(default_factory=list)
    next_arc_entry: str = ""
    is_final_arc: bool = False
    story_nodes: list[StoryNode] = Field(default_factory=list)

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


class AttributeAllocationDecision(_OutlineModel):
    mode: Literal["allocate", "carry"]
    allocations: dict[str, int] = Field(default_factory=dict)
    remaining: int = Field(default=0, ge=0, strict=True)
    reason: str = ""

    @field_validator("allocations", mode="before")
    @classmethod
    def validate_positive_integer_allocations(cls, value: Any) -> Any:
        if not isinstance(value, dict) or any(
            not isinstance(name, str)
            or not name.strip()
            or name != name.strip()
            or any(char in name for char in "、+；\r\n")
            or not isinstance(points, int)
            or isinstance(points, bool)
            or points <= 0
            for name, points in value.items()
        ):
            raise ValueError("invalid_attribute_allocation_decision")
        return value

    @field_validator("reason")
    @classmethod
    def normalize_single_line_reason(cls, value: str) -> str:
        if "\r" in value or "\n" in value:
            raise ValueError("invalid_attribute_allocation_decision")
        return value.strip()

    @model_validator(mode="after")
    def validate_mode_shape(self) -> "AttributeAllocationDecision":
        if self.mode == "allocate" and not self.allocations:
            raise ValueError("invalid_attribute_allocation_decision")
        if self.mode == "carry" and self.allocations:
            raise ValueError("invalid_attribute_allocation_decision")
        return self


class ChapterScenePlan(_OutlineModel):
    location: str = ""
    pov: str = ""
    goal: str = ""
    obstacle: str = ""
    action: str = ""
    change: str = ""
    next: str = ""
    state_delta: dict[str, Any] = Field(default_factory=dict)


class ChapterPayoffContract(_OutlineModel):
    need: str = Field(default="", max_length=500)
    pressure: str = Field(default="", max_length=500)
    hidden_advantage: str = Field(default="", max_length=500)
    concrete_reward: str = Field(default="", max_length=500)

    @field_validator("*", mode="before")
    @classmethod
    def trim_contract_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ChapterSop(_OutlineModel):
    opening_carry: str = Field(default="", max_length=500)
    mid_feedback: str = Field(default="", max_length=500)
    turn: str = Field(default="", max_length=500)
    ending_hook: str = Field(default="", max_length=500)

    @field_validator("*", mode="before")
    @classmethod
    def trim_sop_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class ChapterPlan(_OutlineModel):
    chapter_number: int = Field(ge=1, strict=True)
    title: str = ""
    goal: str = ""
    obstacle: str = ""
    action: str = ""
    turn: str = ""
    payoff: str = ""
    ending_hook: str = ""
    trope_beat: str | None = None
    cast: list[str] = Field(default_factory=list)
    level_target: str | int | None = None
    attribute_allocation_decision: AttributeAllocationDecision | None = None
    numeric_plan: dict[str, Any] = Field(default_factory=dict)
    opponent_response: str = ""
    emotional_change: str = ""
    gain_or_loss: str = ""
    must_include: list[str] = Field(default_factory=list)
    must_not_write: list[str] = Field(default_factory=list)
    scene_chain: list[ChapterScenePlan] = Field(default_factory=list)
    payoff_contract: ChapterPayoffContract | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )
    chapter_sop: ChapterSop | None = Field(
        default=None,
        exclude_if=lambda value: value is None,
    )

    @field_validator("chapter_number", mode="before")
    @classmethod
    def validate_chapter(cls, value: Any) -> Any:
        if isinstance(value, int) and not isinstance(value, bool) and value < 1:
            raise ValueError("invalid_chapter_number")
        return value

    @field_validator("level_target", mode="before")
    @classmethod
    def normalize_numeric_level_target(cls, value: Any) -> Any:
        if isinstance(value, str):
            normalized = value.strip()
            if normalized.isdigit():
                return int(normalized)
            return normalized
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
        if self.overall.extension_ceiling_chapter < self.overall.core_ending_chapter:
            raise ValueError("extension_ceiling_before_core_ending")
        if self.overall.extension_ceiling_chapter > self.overall.core_ending_chapter:
            for arc in self.arcs:
                if arc.end_chapter > self.overall.core_ending_chapter:
                    continue
                if (
                    not arc.extension_gate.continue_route.strip()
                    or not arc.extension_gate.close_route.strip()
                ):
                    raise ValueError(f"missing_arc_extension_route:{arc.id}")
        return self


def _with_elastic_defaults(payload: Any) -> Any:
    if payload is None or not isinstance(payload, dict):
        return payload
    prepared = deepcopy(payload)
    overall = prepared.setdefault("overall", {})
    if not isinstance(overall, dict):
        return prepared
    arcs = prepared.get("arcs") if isinstance(prepared.get("arcs"), list) else []
    chapters = (
        prepared.get("chapters")
        if isinstance(prepared.get("chapters"), list)
        else []
    )
    planned_ends = [
        item.get("end_chapter")
        for item in arcs
        if isinstance(item, dict)
        and isinstance(item.get("end_chapter"), int)
        and not isinstance(item.get("end_chapter"), bool)
    ]
    planned_chapters = [
        item.get("chapter_number")
        for item in chapters
        if isinstance(item, dict)
        and isinstance(item.get("chapter_number"), int)
        and not isinstance(item.get("chapter_number"), bool)
    ]
    legacy_end = max([*planned_ends, *planned_chapters, 1])
    overall.setdefault("core_ending_chapter", legacy_end)
    overall.setdefault("extension_ceiling_chapter", overall["core_ending_chapter"])
    overall.setdefault("current_strategy", "observe")
    overall.setdefault("ending_contract", overall.get("ending_direction", ""))
    overall.setdefault("theme_statement", "")
    overall.setdefault("foreground_story", str(overall.get("story") or ""))
    overall.setdefault("background_story", "")
    overall.setdefault(
        "book_objective",
        str(
            overall.get("ending_contract")
            or overall.get("ending_direction")
            or overall.get("protagonist_goal")
            or ""
        ),
    )
    overall.setdefault("ending_image", str(overall.get("ending_direction") or ""))
    overall.setdefault("core_selling_point", "")
    overall.setdefault("long_term_lines", [])
    overall.setdefault("planned_arc_count", len(arcs))
    overall.setdefault("planned_length", overall.get("core_ending_chapter", legacy_end))
    overall.setdefault("expansion_route", "")
    overall.setdefault("closing_route", str(overall.get("ending_contract") or ""))
    overall.setdefault("positioning", {})
    overall.setdefault("protagonist_drive", {})
    overall.setdefault("core_advantage", {})
    overall.setdefault("central_mystery", {})
    for arc in arcs:
        if not isinstance(arc, dict):
            continue
        arc.setdefault("emotional_curve", "")
        arc.setdefault("pacing_stage_id", "")
        fallback_results: list[str] = []
        for field in ("goal", "payoff", "end_state"):
            value = str(arc.get(field) or "").strip()
            if value and value not in fallback_results:
                fallback_results.append(value)
        arc.setdefault("key_results", fallback_results)
        traces = arc.get("long_term_antagonist_traces")
        arc.setdefault(
            "hook_plan",
            "、".join(str(item).strip() for item in traces if str(item).strip())
            if isinstance(traces, list)
            else "",
        )
        arc.setdefault("irreversible_change", str(arc.get("end_state") or ""))
        arc.setdefault("active_long_term_lines", [])
        arc.setdefault("core_loop", "")
        arc.setdefault("escalations", [])
        arc.setdefault("midpoint_turn", "")
        arc.setdefault("climax", str(arc.get("payoff") or ""))
        arc.setdefault("relationship_changes", [])
        arc.setdefault("foreshadowing_in", [])
        arc.setdefault("foreshadowing_out", [])
        arc.setdefault("next_arc_entry", "")
        arc.setdefault("is_final_arc", False)
        arc.setdefault("story_nodes", [])
    return prepared


def normalize_project_outline(payload: Any) -> dict[str, Any]:
    prepared = {} if payload is None else payload
    normalized = ProjectOutline.model_validate(_with_elastic_defaults(prepared)).model_dump()
    normalized["arcs"].sort(
        key=lambda arc: (arc["start_chapter"], arc["end_chapter"], arc["id"])
    )
    for arc in normalized["arcs"]:
        if not str(arc.get("pacing_stage_id") or "").strip():
            arc.pop("pacing_stage_id", None)
    normalized["chapters"].sort(key=lambda chapter: chapter["chapter_number"])
    for chapter in normalized["chapters"]:
        if chapter.get("level_target") is None:
            chapter.pop("level_target", None)
        if chapter.get("attribute_allocation_decision") is None:
            chapter.pop("attribute_allocation_decision", None)
        if chapter.get("payoff_contract") is None:
            chapter.pop("payoff_contract", None)
        if chapter.get("chapter_sop") is None:
            chapter.pop("chapter_sop", None)
    return normalized


def normalize_outline_for_story_type(
    payload: Any,
    *,
    is_game_story: bool,
) -> dict[str, Any]:
    normalized = normalize_project_outline(payload)
    if not is_game_story:
        for arc in normalized["arcs"]:
            arc["game_line_payoff"] = ""
            arc["reality_line_payoff"] = ""
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
    overall_context = {
        key: normalized["overall"][key]
        for key in (
            "story",
            "theme_statement",
            "foreground_story",
            "background_story",
            "book_objective",
            "ending_image",
            "protagonist_goal",
            "main_conflict",
            "growth_path",
            "ending_direction",
            "primary_trope_id",
            "current_strategy",
            "ending_contract",
            "core_selling_point",
            "long_term_lines",
            "planned_arc_count",
            "planned_length",
            "expansion_route",
            "closing_route",
            "positioning",
            "protagonist_drive",
            "core_advantage",
            "central_mystery",
        )
    }
    mystery = overall_context.get("central_mystery")
    if isinstance(mystery, dict):
        overall_context["central_mystery"] = {
            key: mystery.get(key, "")
            for key in ("surface_anomaly", "reality_impact")
            if str(mystery.get(key) or "").strip()
        }
    active_arc_context = (
        {
            key: active_arc[key]
            for key in (
                "id",
                "title",
                "start_chapter",
                "end_chapter",
                "goal",
                "obstacle",
                "payoff",
                "emotional_curve",
                "key_results",
                "hook_plan",
                "irreversible_change",
                "trope_id",
                "game_line_payoff",
                "reality_line_payoff",
                "end_state",
                "stage_antagonist",
                "long_term_antagonist_traces",
                "active_long_term_lines",
                "core_loop",
                "escalations",
                "midpoint_turn",
                "climax",
                "relationship_changes",
                "foreshadowing_in",
                "foreshadowing_out",
                "next_arc_entry",
            )
        }
        if active_arc is not None
        else None
    )
    if active_arc_context is not None and active_arc is not None:
        pacing_stage_id = str(active_arc.get("pacing_stage_id") or "").strip()
        if pacing_stage_id:
            active_arc_context["pacing_stage_id"] = pacing_stage_id
    return {
        "schema_version": "outline-context/v1",
        "overall": overall_context,
        "active_arc": active_arc_context,
        "chapter": chapter,
    }
