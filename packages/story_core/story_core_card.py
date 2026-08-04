from __future__ import annotations

from copy import deepcopy
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _StoryCoreModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    @field_validator("*", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class CoreAdvantage(_StoryCoreModel):
    name: str = Field(default="", max_length=500)
    type: str = Field(default="", max_length=500)
    ability: str = Field(default="", max_length=1000)
    growth_rule: str = Field(default="", max_length=1000)
    limits: str = Field(default="", max_length=1000)
    early_payoff: str = Field(default="", max_length=1000)


class CentralMystery(_StoryCoreModel):
    surface_anomaly: str = Field(default="", max_length=1000)
    hidden_truth: str = Field(default="", max_length=2000)
    reality_impact: str = Field(default="", max_length=1000)
    reveal_path: list[str] = Field(default_factory=list, max_length=20)


class InitialDrive(_StoryCoreModel):
    immediate_need: str = Field(default="", max_length=1000)
    trigger: str = Field(default="", max_length=1000)
    short_term_goal: str = Field(default="", max_length=1000)
    failure_stakes: str = Field(default="", max_length=1000)
    long_term_transition: str = Field(default="", max_length=1000)


class StoryCoreCard(_StoryCoreModel):

    schema_version: Literal["story-core/v1"] = "story-core/v1"
    title: str = Field(default="", max_length=120)
    logline: str = Field(default="", max_length=1000)
    protagonist_profile: str = Field(default="", max_length=1000)
    inciting_incident: str = Field(default="", max_length=1000)
    protagonist_goal: str = Field(default="", max_length=1000)
    main_conflict: str = Field(default="", max_length=1000)
    failure_stakes: str = Field(default="", max_length=1000)
    growth_path: str = Field(default="", max_length=1000)
    excitement_point: str = Field(default="", max_length=1000)
    target_audience: str = Field(default="", max_length=1000)
    reader_promise: str = Field(default="", max_length=1000)
    ending_direction: str = Field(default="", max_length=1000)
    core_advantage: CoreAdvantage = Field(default_factory=CoreAdvantage)
    central_mystery: CentralMystery = Field(default_factory=CentralMystery)
    initial_drive: InitialDrive = Field(default_factory=InitialDrive)
    source_direction_id: str = Field(default="", max_length=120)


StoryCoreStage = Literal["character", "world", "outline", "planning", "writing"]

_STAGE_FIELDS: dict[StoryCoreStage, tuple[str, ...]] = {
    "character": (
        "protagonist_profile",
        "protagonist_goal",
        "failure_stakes",
        "growth_path",
        "main_conflict",
        "core_advantage",
        "initial_drive",
    ),
    "world": (
        "inciting_incident",
        "main_conflict",
        "excitement_point",
        "core_advantage",
        "central_mystery",
    ),
    "outline": tuple(
        field_name
        for field_name in StoryCoreCard.model_fields
        if field_name != "schema_version"
    ),
    "planning": (
        "logline",
        "reader_promise",
        "core_advantage",
        "central_mystery",
        "initial_drive",
    ),
    "writing": ("logline", "reader_promise", "core_advantage", "initial_drive"),
}


def _model_payload(value: BaseModel) -> dict[str, Any]:
    return {
        key: item
        for key, item in value.model_dump(mode="json").items()
        if item not in ("", [], {}, None)
    }


def story_core_projection(card: StoryCoreCard, stage: StoryCoreStage) -> dict[str, Any]:
    projection: dict[str, Any] = {}
    for field_name in _STAGE_FIELDS[stage]:
        value = getattr(card, field_name)
        if isinstance(value, BaseModel):
            nested = _model_payload(value)
            if field_name == "central_mystery" and stage == "planning":
                nested = {
                    key: nested[key]
                    for key in ("surface_anomaly", "reality_impact")
                    if key in nested
                }
            if nested:
                projection[field_name] = nested
            continue
        if str(value).strip():
            projection[field_name] = value
    return projection


def story_core_from_direction(direction: Any) -> StoryCoreCard:
    payload = (
        direction.model_dump(mode="json")
        if isinstance(direction, BaseModel)
        else dict(direction or {})
    )
    return StoryCoreCard(
        title=str(payload.get("title") or ""),
        logline=str(payload.get("logline") or payload.get("hook") or ""),
        protagonist_profile=str(payload.get("protagonist_profile") or ""),
        inciting_incident=str(payload.get("inciting_incident") or ""),
        protagonist_goal=str(payload.get("protagonist_goal") or ""),
        main_conflict=str(payload.get("main_conflict") or ""),
        failure_stakes=str(payload.get("failure_stakes") or ""),
        growth_path=str(payload.get("growth_path") or ""),
        excitement_point=str(payload.get("excitement_point") or ""),
        target_audience=str(payload.get("target_audience") or ""),
        reader_promise=str(
            payload.get("reader_promise") or payload.get("opening_promise") or ""
        ),
        ending_direction=str(payload.get("ending_direction") or ""),
        core_advantage=payload.get("core_advantage") or {},
        central_mystery=payload.get("central_mystery") or {},
        initial_drive=payload.get("initial_drive") or {},
        source_direction_id=str(payload.get("id") or payload.get("source_direction_id") or ""),
    )


def story_core_from_legacy(
    *,
    selected_direction: dict[str, Any] | None,
    outline: dict[str, Any] | None,
    title: str,
) -> StoryCoreCard:
    direction = dict(selected_direction or {})
    overall = dict((outline or {}).get("overall") or {})
    return StoryCoreCard(
        title=str(direction.get("title") or title or ""),
        logline=str(direction.get("logline") or direction.get("hook") or overall.get("story") or ""),
        protagonist_profile=str(direction.get("protagonist_profile") or ""),
        inciting_incident=str(direction.get("inciting_incident") or ""),
        protagonist_goal=str(direction.get("protagonist_goal") or overall.get("protagonist_goal") or overall.get("book_objective") or ""),
        main_conflict=str(direction.get("main_conflict") or overall.get("main_conflict") or ""),
        failure_stakes=str(direction.get("failure_stakes") or ""),
        growth_path=str(direction.get("growth_path") or overall.get("growth_path") or ""),
        excitement_point=str(direction.get("excitement_point") or ""),
        target_audience=str(direction.get("target_audience") or ""),
        reader_promise=str(direction.get("reader_promise") or direction.get("opening_promise") or ""),
        ending_direction=str(direction.get("ending_direction") or overall.get("ending_direction") or ""),
        core_advantage=direction.get("core_advantage") or {},
        central_mystery=direction.get("central_mystery") or {},
        initial_drive=direction.get("initial_drive") or {},
        source_direction_id=str(direction.get("id") or ""),
    )


def story_core_from_overall(
    overall: dict[str, Any] | None,
    *,
    title: str = "",
) -> StoryCoreCard:
    payload = dict(overall or {})
    positioning = dict(payload.get("positioning") or {})
    drive = dict(payload.get("protagonist_drive") or {})
    return StoryCoreCard(
        title=title,
        logline=str(payload.get("story") or ""),
        protagonist_profile=str(positioning.get("protagonist_profile") or ""),
        inciting_incident=str(positioning.get("inciting_incident") or ""),
        protagonist_goal=str(payload.get("protagonist_goal") or payload.get("book_objective") or ""),
        main_conflict=str(payload.get("main_conflict") or ""),
        failure_stakes=str(positioning.get("failure_stakes") or drive.get("failure_stakes") or ""),
        growth_path=str(payload.get("growth_path") or ""),
        excitement_point=str(positioning.get("excitement_point") or payload.get("core_selling_point") or ""),
        target_audience=str(positioning.get("target_audience") or ""),
        reader_promise=str(positioning.get("reader_promise") or ""),
        ending_direction=str(payload.get("ending_direction") or payload.get("ending_contract") or ""),
        core_advantage=payload.get("core_advantage") or {},
        central_mystery=payload.get("central_mystery") or {},
        initial_drive=drive,
    )


def merge_story_core_into_overall(
    overall: dict[str, Any] | None,
    core: StoryCoreCard | dict[str, Any],
    *,
    overwrite: bool = False,
) -> dict[str, Any]:
    merged = deepcopy(dict(overall or {}))
    card = core if isinstance(core, StoryCoreCard) else StoryCoreCard.model_validate(core)

    def assign(target: dict[str, Any], key: str, value: Any) -> None:
        if value in (None, "", [], {}):
            return
        if overwrite or target.get(key) in (None, "", [], {}):
            target[key] = deepcopy(value)

    assign(merged, "story", card.logline)
    assign(merged, "protagonist_goal", card.protagonist_goal)
    assign(merged, "main_conflict", card.main_conflict)
    assign(merged, "growth_path", card.growth_path)
    assign(merged, "ending_direction", card.ending_direction)

    positioning = dict(merged.get("positioning") or {})
    for key in (
        "protagonist_profile",
        "inciting_incident",
        "failure_stakes",
        "excitement_point",
        "target_audience",
        "reader_promise",
    ):
        assign(positioning, key, getattr(card, key))
    merged["positioning"] = positioning

    drive = dict(merged.get("protagonist_drive") or {})
    for key, value in card.initial_drive.model_dump(mode="json").items():
        assign(drive, key, value)
    merged["protagonist_drive"] = drive

    advantage = dict(merged.get("core_advantage") or {})
    for key, value in card.core_advantage.model_dump(mode="json").items():
        assign(advantage, key, value)
    merged["core_advantage"] = advantage

    mystery = dict(merged.get("central_mystery") or {})
    for key, value in card.central_mystery.model_dump(mode="json").items():
        assign(mystery, key, value)
    merged["central_mystery"] = mystery
    return merged


def outline_seed_from_story_core(
    card: StoryCoreCard,
    *,
    primary_trope_id: str | None = None,
) -> dict[str, Any]:
    return {
        "overall": merge_story_core_into_overall({
            "story": card.logline,
            "book_objective": card.protagonist_goal,
            "protagonist_goal": card.protagonist_goal,
            "main_conflict": card.main_conflict,
            "growth_path": card.growth_path,
            "ending_direction": card.ending_direction,
            "ending_image": card.ending_direction,
            "core_selling_point": card.excitement_point or card.reader_promise,
            "primary_trope_id": primary_trope_id,
        }, card, overwrite=True),
        "arcs": [],
        "chapters": [],
    }
