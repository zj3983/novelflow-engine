"""Bounded input/output contracts for WorldBuild model tasks."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from copy import deepcopy
import hashlib
import json
from typing import Any

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.build_graph.contracts import BuildDiagnostic
from packages.story_core.models import NovelProject
from packages.story_core.novel_type_catalog import normalize_novel_type_ids

from .definition import WorldBuildGraph, WorldBuildTaskSpec


def bounded_json_projection(value: Any, *, chars: int = 360, items: int = 12, depth: int = 4) -> Any:
    """Create a JSON-safe, bounded projection for prompts and run metadata."""

    if isinstance(value, str):
        return value.strip()[: max(1, chars)]
    if value is None or isinstance(value, (bool, int, float)):
        return value
    if depth <= 0:
        return ""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in list(value.items())[: max(1, items)]:
            key = str(raw_key).strip()[:80]
            if key:
                result[key] = bounded_json_projection(
                    raw_value,
                    chars=chars,
                    items=items,
                    depth=depth - 1,
                )
        return result
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [
            bounded_json_projection(item, chars=chars, items=items, depth=depth - 1)
            for item in list(value)[: max(1, items)]
        ]
    return str(value)[: max(1, chars)]


def _json_text(value: Any) -> str:
    return json.dumps(
        bounded_json_projection(value, chars=480, items=16, depth=5),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _nonempty(value: Any) -> bool:
    return value not in (None, "", [], {})


def canonical_world_input(
    project: NovelProject,
    *,
    store: Any | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Return only bounded author/setup inputs, never generated graph output."""

    return bounded_json_projection(
        world_input_revision_payload(project, store=store, previous=previous),
        chars=720,
        items=20,
        depth=5,
    )


def world_input_revision_payload(
    project: NovelProject,
    *,
    store: Any | None = None,
    previous: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build the shared root-input definition used for graph and job revisions.

    This intentionally returns the pre-projection payload.  Callers that put
    it into a model prompt should use :func:`canonical_world_input`; callers
    computing a project revision may canonicalize the same payload without
    maintaining a second field list.
    """

    blueprint = project.world_blueprint if isinstance(project.world_blueprint, Mapping) else {}
    previous_payload = dict(previous or {})
    story_core: Mapping[str, Any] = {}
    if store is not None and hasattr(store, "story_core_context"):
        try:
            candidate = store.story_core_context("world")
            if isinstance(candidate, Mapping):
                story_core = candidate
        except Exception:
            story_core = {}
    if not story_core and isinstance(project.story_core_context, Mapping):
        story_core = project.story_core_context

    raw_ids = blueprint.get("genre_plugin_ids")
    genre_ids = normalize_novel_type_ids(raw_ids)
    explicit_source_premise = blueprint.get("source_premise") or blueprint.get("imported_premise")
    current_premise = blueprint.get("premise") or ""
    previous_source_premise = previous_payload.get("source_premise")
    generated_premise = ""
    if store is not None and hasattr(store, "build_artifact"):
        try:
            core_artifact = store.build_artifact("world_core_rules")
            core_payload = core_artifact.get("payload") if isinstance(core_artifact, Mapping) else None
            if isinstance(core_payload, Mapping):
                generated_premise = str(core_payload.get("premise") or "").strip()
        except Exception:
            generated_premise = ""
    if _nonempty(explicit_source_premise):
        # An explicit imported/source field is always an author/setup input,
        # including when it changes after the graph was materialized.
        source_premise = explicit_source_premise
    elif previous_payload:
        # A generated core-rules premise must not become a new root input on
        # every resume.  Conversely, if the persisted project premise no
        # longer matches the root snapshot, treat that difference as an
        # author edit instead of silently reusing the old input revision.
        baseline_premise = str(previous_source_premise or generated_premise or "").strip()
        if _nonempty(current_premise) and str(current_premise).strip() != baseline_premise:
            source_premise = current_premise
        else:
            source_premise = previous_source_premise
    elif not previous_payload:
        # On first bootstrap an existing premise may be author input.  Once a
        # graph exists, an empty root snapshot stays empty while the generated
        # core-rules premise remains a downstream artifact.
        source_premise = current_premise
    else:
        source_premise = ""

    current_focus = str(project.current_focus or "").strip()
    if (
        previous_payload
        and "current_focus" in previous_payload
        and current_focus
        and current_focus == str(blueprint.get("current_arc") or "").strip()
    ):
        # ``_merge_enrichment`` may derive current_focus from the generated
        # story-engine compatibility artifact.  Keep that derived value from
        # looking like a new author input on the next resume.
        current_focus = str(previous_payload.get("current_focus") or "").strip()

    payload = {
        "title": str(project.title or "").strip(),
        "seed_outline": str(project.seed_outline or "").strip(),
        "source_premise": str(source_premise or "").strip(),
        "story_core": deepcopy(dict(story_core)),
        "author_constraints": list(project.author_constraints or [])[:16],
        "current_focus": current_focus,
        "genre_plugin_ids": genre_ids,
        "novel_type_id": genre_ids[0] if genre_ids else "generic_webnovel",
    }
    return payload


def task_payload_from_project(project: NovelProject, task_id: str) -> dict[str, Any]:
    """Extract only fields that a task is allowed to import from the project."""

    blueprint = project.world_blueprint if isinstance(project.world_blueprint, Mapping) else {}
    if task_id == "world_input":
        return {}
    if task_id == "world_core_rules":
        values = {
            "premise": blueprint.get("premise") or project.world_summary,
            "world_rules": blueprint.get("world_rules"),
            "constraints": blueprint.get("constraints"),
        }
        return {key: deepcopy(value) for key, value in values.items() if _nonempty(value)}
    if task_id == "power_system_foundation":
        spec = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
        return {key: deepcopy(spec[key]) for key in ("name", "origin") if _nonempty(spec.get(key))}
    if task_id == "power_system_attributes":
        spec = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
        return {"attributes": deepcopy(spec.get("attributes"))} if _nonempty(spec.get("attributes")) else {}
    if task_id == "power_system_paths":
        spec = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
        return {"paths": deepcopy(spec.get("paths"))} if _nonempty(spec.get("paths")) else {}
    if task_id == "power_system_stages":
        spec = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
        return {"stages": deepcopy(spec.get("stages"))} if _nonempty(spec.get("stages")) else {}
    if task_id == "power_system_resources":
        spec = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
        fields = ("skills", "equipment", "resources", "advancement")
        return {key: deepcopy(spec[key]) for key in fields if _nonempty(spec.get(key))}
    if task_id == "power_system_constraints":
        spec = blueprint.get("power_system_spec") if isinstance(blueprint.get("power_system_spec"), Mapping) else {}
        fields = (
            "costs",
            "counters",
            "boundaries",
            "social_impact",
            "visibility",
            "continuity_ledger",
            "attribute_allocation",
            "class_advancement_tiers",
        )
        return {key: deepcopy(spec[key]) for key in fields if _nonempty(spec.get(key))}
    if task_id == "power_system_final":
        spec = blueprint.get("power_system_spec")
        if not isinstance(spec, Mapping):
            return {}
        return {
            "power_system_spec": deepcopy(dict(spec)),
            "power_system": deepcopy(blueprint.get("power_system") or []),
        }

    task_fields = {
        "world_economy": ("economy_rules",),
        "world_locations": ("locations",),
        "world_factions": ("factions",),
        "world_society": ("world_systems", "living_world", "faction_rules"),
        "game_ecology": ("quest_rules", "panel_rules", "npc_system", "quest_network", "server_runtime", "map_ecology"),
        "story_engine_compat": (
            "current_arc",
            "progression_rules",
            "chapter_formula",
            "forbidden_breaks",
            "opening_arc",
            "volume_plan",
            "longform_framework",
            "progression_ledger",
        ),
    }
    fields = task_fields.get(task_id, ())
    return {key: deepcopy(blueprint[key]) for key in fields if _nonempty(blueprint.get(key))}


def build_input_contract(
    project: NovelProject,
    graph: WorldBuildGraph,
    service: Any,
    task_id: str,
) -> dict[str, Any]:
    spec = graph.spec(task_id)
    ancestors: list[str] = []

    def visit(candidate_id: str) -> None:
        for dependency in graph.spec(candidate_id).task.dependencies:
            if dependency not in ancestors:
                ancestors.append(dependency)
                visit(dependency)

    visit(task_id)
    # The full ancestor revision map is deliberately retained for provenance
    # and race detection.  It is not the model context: model input is built
    # strictly from the task's declared read paths below.
    revisions: dict[str, int] = {}
    for dependency in ancestors:
        artifact = service.inspect_artifact(dependency)
        if artifact is None:
            continue
        revisions[dependency] = artifact.revision

    def owner_for_read(path: str) -> tuple[str, str] | None:
        candidates: list[tuple[int, str, str]] = []
        for owner_id in graph.definition.ordered_task_ids:
            owner = graph.spec(owner_id)
            for owned_path in owner.task.owns:
                if path == owned_path or path.startswith(f"{owned_path}."):
                    candidates.append((len(owned_path), owner_id, owned_path))
        if not candidates:
            return None
        _, owner_id, owned_path = max(candidates)
        return owner_id, owned_path

    def read_value(payload: Any, owned_path: str, read_path: str) -> Any:
        if not isinstance(payload, Mapping):
            return None
        # Domain-owned tasks often own several dotted paths but return a
        # flat task payload.  Prefer the leaf field for an exact read so a
        # declared world_systems read cannot leak living_world/faction_rules.
        leaf = owned_path.rsplit(".", 1)[-1]
        value: Any = payload.get(leaf, payload)
        suffix = read_path[len(owned_path):].lstrip(".")
        if suffix:
            for token in suffix.split("."):
                if not isinstance(value, Mapping):
                    return None
                value = value.get(token)
        return value

    reads: list[dict[str, Any]] = []
    declared_values: dict[str, Any] = {}
    read_revisions: dict[str, int] = {}
    for read_path in spec.task.reads:
        owner_info = owner_for_read(read_path)
        if owner_info is None:
            continue
        owner_id, owned_path = owner_info
        artifact = service.inspect_artifact(owner_id)
        if artifact is None:
            continue
        value = bounded_json_projection(
            read_value(artifact.payload, owned_path, read_path),
            chars=480,
            items=16,
            depth=5,
        )
        reads.append(
            {
                "path": read_path,
                "task_id": owner_id,
                "revision": artifact.revision,
                "value": value,
            }
        )
        declared_values[read_path] = value
        read_revisions[read_path] = artifact.revision
    plugin_template: Any = None
    if graph.structured_power and task_id.startswith("power_system_"):
        plugin = graph.plugin_id
        plugin_template = {"novel_type_id": plugin}
    contract = {
        "schema_version": "world-build-input/v1",
        "task_id": task_id,
        "read_paths": list(spec.task.reads),
        "write_paths": list(spec.task.owns),
        "forbidden_writes": list(spec.task.forbidden_writes),
        "reads": reads,
        # Keep this compatibility-shaped field bounded and declared-read
        # only.  Older callers can still inspect ``dependencies`` without
        # receiving the ancestor closure.
        "dependencies": declared_values,
        "read_revisions": read_revisions,
        "dependency_revisions": revisions,
        "existing_candidate": bounded_json_projection(
            task_payload_from_project(project, task_id),
            chars=480,
            items=16,
            depth=5,
        ),
        "novel_type": plugin_template,
        "output_schema": deepcopy(dict(spec.output_schema or {})),
    }
    return bounded_json_projection(contract, chars=720, items=20, depth=6)


def input_fingerprint(contract: Mapping[str, Any]) -> str:
    return hashlib.sha256(_json_text(contract).encode("utf-8")).hexdigest()


def run_read_projection(graph: WorldBuildGraph, task_id: str, contract: Mapping[str, Any]) -> dict[str, Any]:
    spec = graph.spec(task_id)
    return {
        "schema_version": "world-build-read-projection/v1",
        "task_id": task_id,
        "read_paths": list(spec.task.reads),
        "reads": deepcopy(contract.get("reads") or []),
        "read_revisions": dict(contract.get("read_revisions") or {}),
        "dependency_revisions": dict(contract.get("dependency_revisions") or {}),
    }


def build_task_prompt(
    graph: WorldBuildGraph,
    task_id: str,
    contract: Mapping[str, Any],
    *,
    repair_candidate: Any | None = None,
    diagnostics: Sequence[BuildDiagnostic] = (),
) -> str:
    spec = graph.spec(task_id)
    lines = [
        "你是 NovelFlow 的受 ownership 约束的世界构建任务执行器。只返回 JSON，不要 Markdown，不要小说正文。",
        f"当前任务：{task_id} / {spec.task.title}",
        f"任务职责：{spec.instructions}",
        f"只允许写入：{', '.join(spec.task.owns)}",
        f"禁止写入：{', '.join(spec.task.forbidden_writes) or '无'}",
        f"输出契约：{_json_text(spec.output_schema or {})}",
        "输入只来自下面列出的已提交依赖 artifact；不得臆造未提供的事实。",
        f"bounded input contract: {_json_text(contract)}",
    ]
    if repair_candidate is not None or diagnostics:
        lines.extend(
            [
                "这是唯一一次 focused repair。只修复当前任务的结构化诊断，不重写其他任务，不补全整个项目。",
                f"当前候选：{_json_text(repair_candidate)}",
                "诊断：" + _json_text([item.to_dict() for item in diagnostics]),
            ]
        )
    return "\n".join(lines)


def parse_task_payload(text: str, allowed_fields: Sequence[str]) -> tuple[dict[str, Any] | None, tuple[BuildDiagnostic, ...]]:
    try:
        parsed = parse_json_message_content(
            {"choices": [{"message": {"content": str(text or "")}}]}
        )
    except Exception:
        parsed = None
    if isinstance(parsed, Mapping) and isinstance(parsed.get("world_blueprint"), Mapping):
        # Keep all fields inside a legacy wrapper so the task validator can
        # report an ownership violation.  Silently filtering an out-of-scope
        # field would make a model response look compliant when it was not.
        parsed = dict(parsed["world_blueprint"])
    if not isinstance(parsed, Mapping):
        return None, (
            BuildDiagnostic(
                "task.invalid_json",
                "payload",
                "model response was not a JSON object",
                "blocking",
            ),
        )
    return deepcopy(dict(parsed)), ()


__all__ = [
    "bounded_json_projection",
    "build_input_contract",
    "build_task_prompt",
    "canonical_world_input",
    "input_fingerprint",
    "parse_task_payload",
    "run_read_projection",
    "task_payload_from_project",
]
