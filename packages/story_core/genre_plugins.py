from __future__ import annotations

from copy import deepcopy
import json
import re

from packages.story_core.models import NovelProject
from packages.story_core.novel_type_catalog import has_explicit_non_game_type, normalize_novel_type_ids
from packages.story_core.novel_type_library import (
    list_novel_types,
    novel_type_record_to_genre_plugin,
)
from packages.story_core.genre_types import (
    EASTERN_FANTASY,
    EASTERN_FANTASY_SIMULATION_BLUEPRINT,
    GAME_WEBNOVEL,
    GAME_WEBNOVEL_SIMULATION_BLUEPRINT,
    GENERIC_WEBNOVEL,
    ROMANCE,
    RULEBOOK_FIELDS,
    RULES_MYSTERY,
    SUSPENSE,
    URBAN,
    XIANXIA,
    XUANHUAN,
    GenrePlugin,
)


PLUGIN_REGISTRY: tuple[GenrePlugin, ...] = (
    GAME_WEBNOVEL,
    XUANHUAN,
    XIANXIA,
    URBAN,
    ROMANCE,
    SUSPENSE,
    RULES_MYSTERY,
)


def _with_shared_genre_plugins(
    plugins: list[GenrePlugin], plugin_by_id: dict[str, GenrePlugin]
) -> list[GenrePlugin]:
    generic = plugin_by_id.get("generic_webnovel") or GENERIC_WEBNOVEL
    result: list[GenrePlugin] = [generic]
    for plugin in plugins:
        if plugin.plugin_id in {"xuanhuan", "xianxia"} and EASTERN_FANTASY not in result:
            result.append(EASTERN_FANTASY)
        if plugin not in result:
            result.append(plugin)
    return result


def _project_text(project: NovelProject) -> str:
    return " ".join(
        [
            project.title,
            project.seed_outline,
            project.world_summary,
            project.current_focus,
            " ".join(project.author_constraints),
            json.dumps(project.world_blueprint, ensure_ascii=False),
        ]
    )


def select_genre_plugins(project: NovelProject, *, max_plugins: int = 2, min_score: int = 2) -> list[GenrePlugin]:
    records = list_novel_types()
    plugin_by_id = {
        record.id: novel_type_record_to_genre_plugin(record) for record in records
    }
    text = _project_text(project)
    explicit_ids = project.world_blueprint.get("genre_plugin_ids") if isinstance(project.world_blueprint, dict) else None
    selected: list[GenrePlugin] = []
    normalized_explicit_ids = normalize_novel_type_ids(explicit_ids)
    raw_explicit_ids = (
        explicit_ids
        if isinstance(explicit_ids, list)
        else [explicit_ids]
        if isinstance(explicit_ids, str)
        else []
    )
    for raw_id in raw_explicit_ids:
        candidate = str(raw_id or "").strip()
        if candidate and candidate not in normalized_explicit_ids and candidate in plugin_by_id:
            normalized_explicit_ids.append(candidate)
    if normalized_explicit_ids:
        for plugin_id in normalized_explicit_ids:
            if plugin_id == "generic_webnovel":
                continue
            match = plugin_by_id.get(plugin_id)
            if match and match not in selected:
                selected.append(match)
            if len(selected) >= max_plugins:
                break
        return _with_shared_genre_plugins(selected, plugin_by_id)

    if len(selected) < max_plugins:
        scored: list[tuple[int, GenrePlugin]] = []
        for record in records:
            if record.id == "generic_webnovel":
                continue
            plugin = plugin_by_id[record.id]
            score = sum(1 for keyword in plugin.keywords if keyword and keyword in text)
            if score >= min_score:
                scored.append((score, plugin))
        for _, plugin in sorted(scored, key=lambda item: item[0], reverse=True):
            if plugin not in selected:
                selected.append(plugin)
            if len(selected) >= max_plugins:
                break

    return _with_shared_genre_plugins(selected, plugin_by_id)


def is_game_genre(text: str) -> bool:
    haystack = str(text or "")
    if re.search(r"(?<![A-Za-z0-9_])game_webnovel(?![A-Za-z0-9_])", haystack, re.IGNORECASE):
        return True
    if has_explicit_non_game_type(haystack):
        return False
    strong_tokens = (
        "《天启之门》",
        "网游",
        "VRMMO",
        "游戏ID",
        "交易行",
        "爆率",
        "铜币",
        "灰烬村",
        "game_webnovel",
    )
    weak_tokens = ("游戏", "系统", "等级", "面板", "背包", "NPC", "玩家", "公会")
    if any(token in haystack for token in strong_tokens):
        return True
    return sum(1 for token in weak_tokens if token in haystack) >= 2


def _context_genre_ids(context: Any) -> list[str]:
    if hasattr(context, "model_dump"):
        context = context.model_dump(mode="json")
    if isinstance(context, dict):
        result: list[str] = []
        for key, value in context.items():
            if key in {"genre_plugin_ids", "novel_type", "novel_type_id", "genre"}:
                candidates = normalize_novel_type_ids(value)
            elif isinstance(value, (dict, list, tuple, set)):
                candidates = _context_genre_ids(value)
            else:
                candidates = []
            for candidate in candidates:
                if candidate not in result:
                    result.append(candidate)
        return result
    if isinstance(context, (list, tuple, set)):
        result = normalize_novel_type_ids(list(context))
        for value in context:
            if isinstance(value, (dict, list, tuple, set)):
                for candidate in _context_genre_ids(value):
                    if candidate not in result:
                        result.append(candidate)
        return result
    return normalize_novel_type_ids(context)


def is_game_genre_context(body: str, context: Any = None) -> bool:
    """Resolve game genre from prose plus optional project/review metadata."""

    if context is None:
        return is_game_genre(body)
    genre_ids = _context_genre_ids(context)
    if "game_webnovel" in genre_ids:
        return True
    if genre_ids:
        return False
    context_text = json.dumps(context, ensure_ascii=False, default=str)
    return is_game_genre(f"{context_text}\n{body}")


def merge_plugin_rulebooks(plugins: list[GenrePlugin]) -> dict[str, list[str]]:
    merged: dict[str, list[str]] = {field: [] for field in RULEBOOK_FIELDS}
    for plugin in plugins:
        for field in RULEBOOK_FIELDS:
            for rule in plugin.rulebook.get(field, ()):
                if rule not in merged[field]:
                    merged[field].append(rule)
    return merged


def _plugin_trope_templates(plugins: list[GenrePlugin]) -> list[dict[str, object]]:
    templates: list[dict[str, object]] = []
    seen: set[str] = set()
    for plugin in plugins:
        for template in plugin.trope_templates:
            template_id = str(template.get("id") or "")
            if not template_id or template_id in seen:
                continue
            seen.add(template_id)
            templates.append(deepcopy(template))
    return templates


def plugin_simulation_blueprint(plugins: list[GenrePlugin]) -> dict[str, object]:
    plugin_ids = {plugin.plugin_id for plugin in plugins}
    for subtype in ("xuanhuan", "xianxia"):
        if subtype in plugin_ids:
            blueprint = deepcopy(EASTERN_FANTASY_SIMULATION_BLUEPRINT)
            blueprint["plugin_id"] = subtype
            blueprint["trope_templates"] = _plugin_trope_templates(plugins)
            return blueprint
    if "game_webnovel" in plugin_ids:
        blueprint = deepcopy(GAME_WEBNOVEL_SIMULATION_BLUEPRINT)
        blueprint["trope_templates"] = _plugin_trope_templates(plugins)
        return blueprint
    templates = _plugin_trope_templates(plugins)
    return {"trope_templates": templates} if templates else {}


def plugin_prompt_guide(plugins: list[GenrePlugin]) -> str:
    payload = [
        {
            "id": plugin.plugin_id,
            "name": plugin.name,
            "core_promises": list(plugin.core_promises),
            "ledger_fields": list(plugin.ledger_fields),
            "rulebook": {
                field: list(rules) for field, rules in plugin.rulebook.items()
            },
            "quality_checks": list(plugin.quality_checks),
            "trope_templates": deepcopy(list(plugin.trope_templates)),
        }
        for plugin in plugins
    ]
    return json.dumps(payload, ensure_ascii=False)
