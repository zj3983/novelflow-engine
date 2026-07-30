"""Small, bounded assets used to prepare a story for publishing."""

from __future__ import annotations

from collections.abc import Iterable
from itertools import chain
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


_TEXT_SCALARS = (str, int, float, bool)
MAX_SYNOPSIS_TAG_CHARS = 32
MAX_VISUAL_HOOK_CHARS = 240
_MAX_TITLE_CHARS = 120
_MAX_NOVEL_TYPE_CHARS = 120
_MAX_OPENING_IDEA_CHARS = 1_000
_MAX_WORLD_SUMMARY_CHARS = 2_000
_MAX_CHARACTER_NAME_CHARS = 80
_MAX_CHARACTER_ROLE_CHARS = 80
_MAX_CHARACTER_GOAL_CHARS = 240
_MAX_OUTLINE_ARCS = 5
_OUTLINE_OVERALL_FIELDS = (
    "story",
    "summary",
    "premise",
    "main_conflict",
    "theme",
    "overall_arc",
)
_MAX_SERIALIZED_CONTEXT_CHARS = 11_999


def _bounded_text(value: Any, limit: int) -> str:
    """Return a compact scalar string without recursing into arbitrary data."""
    if not isinstance(value, _TEXT_SCALARS):
        return ""
    return str(value).strip()[:limit]


def _first_bounded_text(limit: int, *values: Any) -> str:
    for value in values:
        text = _bounded_text(value, limit)
        if text:
            return text
    return ""


class FanqieSynopsis(BaseModel):
    tags: list[Annotated[str, Field(max_length=MAX_SYNOPSIS_TAG_CHARS)]] = Field(min_length=4, max_length=8)
    body: str = Field(min_length=200, max_length=450)
    pattern: Literal["conflict", "contrast", "micro_scene"]
    visual_hook: str = Field(default="", max_length=MAX_VISUAL_HOOK_CHARS)

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("visual_hook", mode="before")
    @classmethod
    def normalize_visual_hook(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("tags_must_be_list")
        normalized: list[str] = []
        seen: set[str] = set()
        for tag in value:
            if not isinstance(tag, str):
                continue
            clean_tag = tag.strip()
            if clean_tag and clean_tag not in seen:
                normalized.append(clean_tag)
                seen.add(clean_tag)
        return normalized


class _PublishingCharacterSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=_MAX_CHARACTER_NAME_CHARS)
    role: str = Field(default="", max_length=_MAX_CHARACTER_ROLE_CHARS)
    goal: str = Field(default="", max_length=_MAX_CHARACTER_GOAL_CHARS)

    @field_validator("name", "role", "goal", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class _PublishingOutlineOverall(BaseModel):
    model_config = ConfigDict(extra="forbid")

    story: str = Field(default="", max_length=240)
    summary: str = Field(default="", max_length=240)
    premise: str = Field(default="", max_length=240)
    main_conflict: str = Field(default="", max_length=240)
    theme: str = Field(default="", max_length=240)
    overall_arc: str = Field(default="", max_length=240)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class _PublishingOutlineArc(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(default="", max_length=_MAX_CHARACTER_NAME_CHARS)
    summary: str = Field(default="", max_length=260)
    main_conflict: str = Field(default="", max_length=160)

    @field_validator("*", mode="before")
    @classmethod
    def normalize_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class _PublishingOutlineSummary(BaseModel):
    model_config = ConfigDict(extra="forbid")

    overall: _PublishingOutlineOverall | None = None
    arcs: list[_PublishingOutlineArc] = Field(default_factory=list, max_length=_MAX_OUTLINE_ARCS)


class PublishingContext(BaseModel):
    model_config = ConfigDict(extra="forbid", revalidate_instances="always")

    title: str = Field(max_length=_MAX_TITLE_CHARS)
    novel_type: str = Field(default="", max_length=_MAX_NOVEL_TYPE_CHARS)
    opening_idea: str = Field(default="", max_length=_MAX_OPENING_IDEA_CHARS)
    world_summary: str = Field(default="", max_length=_MAX_WORLD_SUMMARY_CHARS)
    protagonists: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    outline_summary: dict[str, object] = Field(default_factory=dict)

    @field_validator("title", mode="before")
    @classmethod
    def normalize_title(cls, value: Any) -> Any:
        if not isinstance(value, str):
            return value
        return value.strip() or "未命名作品"

    @field_validator("novel_type", "opening_idea", "world_summary", mode="before")
    @classmethod
    def normalize_top_level_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("protagonists", mode="before")
    @classmethod
    def validate_protagonists(cls, value: Any) -> Any:
        if not isinstance(value, list):
            raise ValueError("protagonists_must_be_list")
        return [_PublishingCharacterSummary.model_validate(item).model_dump() for item in value]

    @field_validator("outline_summary", mode="before")
    @classmethod
    def validate_outline_summary(cls, value: Any) -> Any:
        if not isinstance(value, dict):
            raise ValueError("outline_summary_must_be_dict")
        summary = _PublishingOutlineSummary.model_validate(value)
        return summary.model_dump(exclude_none=True, exclude_defaults=True)

    @model_validator(mode="after")
    def validate_serialized_budget(self) -> "PublishingContext":
        if len(self.model_dump_json()) > _MAX_SERIALIZED_CONTEXT_CHARS:
            raise ValueError("publishing_context_serialized_budget_exceeded")
        return self


def _halve_optional_text(data: dict[str, Any]) -> bool:
    """Reduce every optional text value once, preserving the required title."""
    changed = False

    def halve(mapping: dict[str, Any], key: str) -> None:
        nonlocal changed
        value = mapping.get(key)
        if isinstance(value, str) and value:
            mapping[key] = value[: len(value) // 2]
            changed = True

    for key in ("novel_type", "opening_idea", "world_summary"):
        halve(data, key)

    protagonists = data.get("protagonists")
    if isinstance(protagonists, list):
        for protagonist in protagonists:
            if isinstance(protagonist, dict):
                for key in ("goal", "role", "name"):
                    halve(protagonist, key)

    outline_summary = data.get("outline_summary")
    if isinstance(outline_summary, dict):
        overall = outline_summary.get("overall")
        if isinstance(overall, dict):
            for key in sorted(overall):
                halve(overall, key)
        arcs = outline_summary.get("arcs")
        if isinstance(arcs, list):
            for arc in arcs:
                if isinstance(arc, dict):
                    for key in ("main_conflict", "summary", "name"):
                        halve(arc, key)
    return changed


def _enforce_serialized_budget(data: dict[str, Any]) -> PublishingContext:
    """Apply finite, deterministic reductions using the actual JSON size."""
    for _ in range(16):
        compact = PublishingContext.model_construct(**data)
        if len(compact.model_dump_json()) <= _MAX_SERIALIZED_CONTEXT_CHARS:
            return PublishingContext.model_validate(data)
        if not _halve_optional_text(data):
            break

    return PublishingContext.model_validate({"title": data["title"]})


def _bounded_outline_summary(outline: dict) -> dict[str, object]:
    """Select compact marketing-relevant outline fields, never chapter content."""
    if not isinstance(outline, dict):
        return {}

    overall_source = outline.get("overall")
    overall_sources = [outline]
    if isinstance(overall_source, dict):
        overall_sources.append(overall_source)
    overall: dict[str, str] = {}
    for source in overall_sources:
        for field in _OUTLINE_OVERALL_FIELDS:
            text = _bounded_text(source.get(field), 240)
            if text:
                overall[field] = text

    arcs_source = outline.get("arcs")
    if not isinstance(arcs_source, list):
        arcs_source = outline.get("act_breaks")
    arcs: list[dict[str, str]] = []
    if isinstance(arcs_source, list):
        for raw_arc in arcs_source[:_MAX_OUTLINE_ARCS]:
            if not isinstance(raw_arc, dict):
                continue
            arc: dict[str, str] = {}
            name = _first_bounded_text(80, raw_arc.get("name"), raw_arc.get("title"))
            summary = _first_bounded_text(
                260, raw_arc.get("summary"), raw_arc.get("description"), raw_arc.get("story")
            )
            conflict = _bounded_text(raw_arc.get("main_conflict"), 160)
            if name:
                arc["name"] = name
            if summary:
                arc["summary"] = summary
            if conflict:
                arc["main_conflict"] = conflict
            if arc:
                arcs.append(arc)

    result: dict[str, object] = {}
    if overall:
        result["overall"] = overall
    if arcs:
        result["arcs"] = arcs
    return result


def _bounded_characters(project: dict, state: dict) -> list[dict[str, str]]:
    profiles = project.get("character_profiles")
    if not isinstance(profiles, Iterable) or isinstance(profiles, (str, bytes, dict)):
        profiles = ()
    state_characters = state.get("characters")
    if not isinstance(state_characters, Iterable) or isinstance(state_characters, (str, bytes, dict)):
        state_characters = ()

    characters: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for raw_profile in chain(profiles, state_characters):
        if not isinstance(raw_profile, dict):
            continue
        name = _bounded_text(raw_profile.get("name"), _MAX_CHARACTER_NAME_CHARS)
        if not name or name in seen_names:
            continue
        role = _first_bounded_text(
            _MAX_CHARACTER_ROLE_CHARS, raw_profile.get("role"), raw_profile.get("story_role")
        )
        goal = _first_bounded_text(
            _MAX_CHARACTER_GOAL_CHARS,
            raw_profile.get("goal"),
            raw_profile.get("motivation"),
            raw_profile.get("core_motivation"),
            raw_profile.get("story_goal"),
        )
        if not goal and isinstance(raw_profile.get("goals"), list):
            goal = _bounded_text(next(iter(raw_profile["goals"]), ""), _MAX_CHARACTER_GOAL_CHARS)
        character = {"name": name, "role": role, "goal": goal}
        characters.append(character)
        seen_names.add(name)
        if len(characters) == 8:
            break
    return characters


def build_publishing_context(
    *, project: dict, state: dict, opening_brief: dict, outline: dict
) -> PublishingContext:
    """Build the compact, explicit context permitted for publishing generation."""
    project = project if isinstance(project, dict) else {}
    state = state if isinstance(state, dict) else {}
    opening_brief = opening_brief if isinstance(opening_brief, dict) else {}

    title = _first_bounded_text(_MAX_TITLE_CHARS, project.get("title"), opening_brief.get("working_title")) or "未命名作品"
    novel_type = _first_bounded_text(
        _MAX_NOVEL_TYPE_CHARS,
        state.get("genre"),
        project.get("genre"),
        project.get("novel_type"),
        opening_brief.get("novel_type_id"),
    )
    world_blueprint = project.get("world_blueprint")
    blueprint_overview = world_blueprint.get("overview") if isinstance(world_blueprint, dict) else None
    data = {
        "title": title,
        "novel_type": novel_type,
        "opening_idea": _first_bounded_text(
            _MAX_OPENING_IDEA_CHARS, opening_brief.get("idea"), project.get("seed_outline"), state.get("outline")
        ),
        "world_summary": _first_bounded_text(
            _MAX_WORLD_SUMMARY_CHARS, project.get("world_summary"), blueprint_overview, state.get("world_summary")
        ),
        "protagonists": _bounded_characters(project, state),
        "outline_summary": _bounded_outline_summary(outline),
    }
    return _enforce_serialized_budget(data)
