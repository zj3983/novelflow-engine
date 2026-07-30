"""Small, bounded assets used to prepare a story for publishing."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator


_TEXT_SCALARS = (str, int, float, bool)
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


class FanqieSynopsis(BaseModel):
    tags: list[str] = Field(min_length=4, max_length=8)
    body: str = Field(min_length=200, max_length=450)
    pattern: Literal["conflict", "contrast", "micro_scene"]
    visual_hook: str = ""

    @field_validator("body", mode="before")
    @classmethod
    def normalize_body(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("tags", mode="before")
    @classmethod
    def normalize_tags(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            return value
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


class PublishingContext(BaseModel):
    title: str = Field(max_length=120)
    novel_type: str = Field(default="", max_length=120)
    opening_idea: str = Field(default="", max_length=1000)
    world_summary: str = Field(default="", max_length=2000)
    protagonists: list[dict[str, str]] = Field(default_factory=list, max_length=8)
    outline_summary: dict[str, object] = Field(default_factory=dict)


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


def _enforce_serialized_budget(context: PublishingContext) -> PublishingContext:
    """Apply finite, deterministic reductions using the actual JSON size."""
    data = context.model_dump()
    for _ in range(16):
        compact = PublishingContext.model_validate(data)
        if len(compact.model_dump_json()) <= _MAX_SERIALIZED_CONTEXT_CHARS:
            return compact
        if not _halve_optional_text(data):
            break

    return PublishingContext(title=context.title)


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
        for raw_arc in arcs_source[:5]:
            if not isinstance(raw_arc, dict):
                continue
            arc: dict[str, str] = {}
            name = _bounded_text(raw_arc.get("name") or raw_arc.get("title"), 80)
            summary = _bounded_text(
                raw_arc.get("summary") or raw_arc.get("description") or raw_arc.get("story"), 260
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
    if not isinstance(profiles, list):
        profiles = []
    state_characters = state.get("characters")
    if isinstance(state_characters, list):
        profiles = [*profiles, *state_characters]

    characters: list[dict[str, str]] = []
    seen_names: set[str] = set()
    for raw_profile in profiles:
        if len(characters) >= 8 or not isinstance(raw_profile, dict):
            continue
        name = _bounded_text(raw_profile.get("name"), 80)
        if not name or name in seen_names:
            continue
        role = _bounded_text(raw_profile.get("role") or raw_profile.get("story_role"), 80)
        goal = _bounded_text(
            raw_profile.get("goal")
            or raw_profile.get("motivation")
            or raw_profile.get("core_motivation")
            or raw_profile.get("story_goal"),
            240,
        )
        if not goal and isinstance(raw_profile.get("goals"), list):
            goal = _bounded_text(next(iter(raw_profile["goals"]), ""), 240)
        character = {"name": name, "role": role, "goal": goal}
        characters.append(character)
        seen_names.add(name)
    return characters


def build_publishing_context(
    *, project: dict, state: dict, opening_brief: dict, outline: dict
) -> PublishingContext:
    """Build the compact, explicit context permitted for publishing generation."""
    project = project if isinstance(project, dict) else {}
    state = state if isinstance(state, dict) else {}
    opening_brief = opening_brief if isinstance(opening_brief, dict) else {}

    title = _bounded_text(project.get("title") or opening_brief.get("working_title"), 120) or "未命名作品"
    novel_type = _bounded_text(
        state.get("genre") or project.get("genre") or project.get("novel_type") or opening_brief.get("novel_type_id"),
        120,
    )
    context = PublishingContext(
        title=title,
        novel_type=novel_type,
        opening_idea=_bounded_text(opening_brief.get("idea"), 1000),
        world_summary=_bounded_text(project.get("world_summary"), 2000),
        protagonists=_bounded_characters(project, state),
        outline_summary=_bounded_outline_summary(outline),
    )
    return _enforce_serialized_budget(context)
