"""Plan a closing volume in memory, then commit all outline projections together."""
from __future__ import annotations

import hashlib
import json
import logging
from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from packages.story_core.elastic_outline import completed_closing_volume, validate_outline_for_project
from packages.story_core.outline_planning_generation import (
    OutlinePlanningBrief, _compact_historical_chapter_summaries,
)
from packages.story_core.outline_rolling import validate_rolling_batch
from packages.story_core.outline_rolling_store import RollingOutlineStore
from packages.story_core.persistence.project_locking import project_update_lock
from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.project_outline import ArcOutline, ChapterPlan, normalize_project_outline


class EndingBlueprint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    closing_route: str = Field(min_length=1)
    ending_contract: str = Field(min_length=1)
    volume: ArcOutline

    @field_validator("closing_route", "ending_contract", mode="before")
    @classmethod
    def trim_text(cls, value):
        return value.strip() if isinstance(value, str) else value


def _validate_blueprint(blueprint: EndingBlueprint, constraints: dict) -> None:
    arc = blueprint.volume
    start, end = constraints["required_start_chapter"], arc.end_chapter
    if (arc.start_chapter != start or end < start or end - start + 1 > 30
            or (constraints["fixed_end_chapter"] is not None and end != constraints["fixed_end_chapter"])):
        raise ValueError("ending_planning_invalid_range")
    if not arc.is_final_arc or arc.next_arc_entry.strip():
        raise ValueError("ending_planning_not_final")
    if not all(getattr(arc, key).strip() for key in ("goal", "obstacle", "climax", "payoff", "end_state")):
        raise ValueError("ending_planning_invalid_volume_content")
    expected = start
    for node in arc.story_nodes:
        if (node.start_chapter != expected or node.end_chapter < node.start_chapter
                or node.end_chapter - node.start_chapter + 1 > 15
                or not all(str(getattr(node, key)).strip() for key in ("objective", "pressure", "turn", "payoff", "next_effect"))):
            raise ValueError(f"ending_planning_invalid_story_nodes:{node.start_chapter}")
        expected = node.end_chapter + 1
    if expected != end + 1:
        raise ValueError("ending_planning_invalid_story_nodes")


def _context_version(store: Any) -> str:
    # Include prose, snapshots and summaries: an outline-only token would miss a
    # concurrent chapter confirmation or edit while the planner is running.
    paths = {
        store.webnovel_dir / name for name in ("project.json", "state.json", "outline.json")
    }
    paths.update({store.story_system_dir / "outline.json", RollingOutlineStore(store.root)._rolling_path()})
    for directory in (store.root / "chapters", store.story_system_dir / "chapters",
                      store.story_system_dir / "continuity"):
        paths.update(path for path in directory.rglob("*") if path.is_file())
    paths.add(store.story_system_dir / "MASTER_SETTING.json")
    digest = hashlib.sha256()
    for path in sorted(paths):
        digest.update(str(path.relative_to(store.root)).encode())
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
    return digest.hexdigest()


def _ending_input(store: Any, draft: dict[str, Any] | None) -> tuple[dict, OutlinePlanningBrief, dict]:
    outline = deepcopy(draft or store.project_outline())
    outline.pop("source", None)
    outline = normalize_project_outline(outline)
    current = int(store.state().get("current_chapter") or 0)
    if current < 1:
        raise ValueError("ending_planning_requires_written_chapter")
    closing = completed_closing_volume(outline, current_chapter=current)
    base = int(closing["start_chapter"]) - 1 if closing else current
    fixed_end = int(closing["end_chapter"]) if closing else None
    if fixed_end is not None and fixed_end - base > 30:
        raise ValueError("ending_planning_range_too_large")
    if base != current:
        snapshot = store._read_json(store.story_system_dir / "continuity" / "snapshots" / f"{base:04d}.json", {})
        state = snapshot.get("state_after") if isinstance(snapshot, dict) else None
        if not isinstance(state, dict) or int(state.get("current_chapter") or 0) != base:
            state = store._chapter_snapshot_state(base, store.state())
        if not isinstance(state, dict) or int(state.get("current_chapter") or 0) != base:
            raise ValueError("ending_planning_base_snapshot_missing")
    else:
        state = store.state()
    brief = store._planning_brief()
    histories, recent = [], []
    for path in sorted((store.story_system_dir / "chapters").glob("*.json")):
        row = store._read_json(path, {})
        number = row.get("chapter_number", 0)
        if not isinstance(number, int) or not 1 <= number <= base:
            continue
        summary = row.get("chapter_summary") or {}
        histories.append({"chapter_number": number, "title": row.get("chapter_title", ""),
                          "summary": str(summary.get("summary", ""))[:700]})
        if number > base - 5:
            recent.append({"chapter_number": number, **deepcopy(summary)})
    known_outline = deepcopy(outline)
    known_outline["chapters"] = [row for row in outline["chapters"] if row["chapter_number"] <= base]
    # The old tail is a draft intention, not evidence of events that already happened.
    known_outline["arcs"] = [row for row in outline["arcs"] if row["end_chapter"] <= base]
    characters = [deepcopy(row) for row in state.get("characters", []) if isinstance(row, dict)]
    updates = {
        "current_chapter": base, "existing_outline": known_outline,
        "recent_chapter_summaries": recent,
        "historical_chapter_summaries": _compact_historical_chapter_summaries(histories),
        "continuation_start_chapter": base,
        "existing_characters": characters,
        "existing_character_names": [str(row["name"]) for row in characters if row.get("name")],
        "character_current_states": characters,
        "world_facts": deepcopy(state.get("world_facts", [])),
        "continuity_facts": deepcopy(state.get("continuity_facts", [])),
        "committed_facts": deepcopy(state.get("committed_facts", [])),
        "unresolved_foreshadowing": [deepcopy(row) for row in state.get("foreshadowing", [])
                                   if isinstance(row, dict) and row.get("status", "open") in {"open", "reinforced"}],
    }
    brief = OutlinePlanningBrief.model_validate({**brief.model_dump(), **updates})
    bodies = []
    for path in sorted((store.root / "chapters").glob("*.md")):
        try:
            number = int(path.name.split("-", 1)[0])
        except ValueError:
            continue
        if base - 3 < number <= base:
            bodies.append({"chapter_number": number, "text": path.read_text(encoding="utf-8-sig")[-9000:]})
    constraints = {
        "base_chapter": base, "required_start_chapter": base + 1,
        "fixed_end_chapter": fixed_end, "maximum_chapter_count": 30,
        "recent_prose": bodies,
        "existing_ending_intention": {key: outline["overall"].get(key, "")
                                     for key in ("closing_route", "ending_contract", "ending_direction", "ending_image")},
    }
    return outline, brief, constraints


def plan_ending(store: Any, generator: Any, *, draft: dict | None = None,
                guidance: str = "", progress: Callable[[str], None] = lambda _: None,
                assert_mutation_allowed: Callable[[], None] = lambda: None,
                expected_version: str | None = None) -> dict:
    with project_update_lock(store.root):
        assert_mutation_allowed()
        if expected_version is not None and _context_version(store) != expected_version:
            raise ValueError("ending_planning_context_changed")
        original, brief, constraints = _ending_input(store, draft)
        version = _context_version(store)
    progress("正在整理已写剧情、人物现状和未回收伏笔，规划收束路线与结局契约。")
    blueprint_guidance = guidance
    for attempt in range(2):
        try:
            blueprint = EndingBlueprint.model_validate(generator.generate_ending_blueprint(
                brief, constraints=constraints, guidance=blueprint_guidance))
            _validate_blueprint(blueprint, constraints)
            break
        except (ValueError, ValidationError) as exc:
            repairable = isinstance(exc, ValidationError) or str(exc).startswith((
                "ending_planning_invalid_", "ending_planning_not_final", "invalid_ending_blueprint_json"))
            if attempt or not repairable:
                raise
            progress("结尾方案未通过完整性检查，正在自动修正章节范围和剧情节点。")
            blueprint_guidance = (guidance + "\n上一版结尾方案校验失败：" + str(exc)[:300]
                                  + "。请修正后返回完整方案，必填字段不得为空，严格按章节范围连续覆盖。")[:1000]
    arc = blueprint.volume
    start = constraints["required_start_chapter"]
    end = arc.end_chapter
    overall = deepcopy(original["overall"])
    overall.update(current_strategy="close", closing_route=blueprint.closing_route,
                   ending_contract=blueprint.ending_contract, core_ending_chapter=end,
                   extension_ceiling_chapter=end, planned_length=end)
    brief = brief.model_copy(update={"overall_context": overall})
    chapters, batches = [], []
    # Detailed scenes make closing chapters substantially larger than a blueprint.
    pending = [list(range(offset, min(offset + 3, end) + 1))
               for offset in range(start, end + 1, 4)]
    while pending:
        numbers = pending.pop(0)
        progress(f"正在生成第{numbers[0]}—{numbers[-1]}章细纲：场景、行动、冲突与结果。")
        try:
            batch = generator.generate_chapter_batch(
                brief, volume=arc.model_dump(mode="json"), chapter_numbers=numbers,
                previous_batches=batches,
                committed_context={"ending_contract": blueprint.ending_contract,
                                   "unresolved_foreshadowing": brief.unresolved_foreshadowing,
                                   "character_current_states": brief.character_current_states,
                                   "recent_prose": constraints["recent_prose"]},
                guidance=(guidance + "\n按结局契约收束。每章写具体场景、人物行动和可见结果，延续已有伤势，成本按计划照实记录，无新增代价时不追加损失；"
                          "每个场景填全location、pov、goal、obstacle、action、change，不得留空。"
                          f"第{end}章章尾写收尾画面，不留新危机或下一卷钩子。不要写验收清单、器材盘点或说教总结。")[:1000],
            )
        except ValueError as exc:
            if str(exc) != "invalid_chapter_batch_json" or len(numbers) == 1:
                raise
            middle = len(numbers) // 2
            pending[:0] = [numbers[:middle], numbers[middle:]]
            progress(f"第{numbers[0]}—{numbers[-1]}章细纲返回不完整，正在拆成更小批次重试。")
            continue
        rows = [row.model_dump(mode="json") if hasattr(row, "model_dump") else dict(row) for row in batch.chapters]
        if [row["chapter_number"] for row in rows] != numbers:
            raise ValueError("ending_planning_chapters_incomplete")
        for row in rows:
            if not row.get("scene_chain") or any(
                not str(scene.get(field) or "").strip()
                for scene in row["scene_chain"] for field in ("location", "pov", "goal", "obstacle", "action", "change")
            ):
                raise ValueError("ending_planning_scene_incomplete")
        chapters.extend(rows)
        batches.append({"chapters": rows})
    preserved_arcs = []
    for row in original["arcs"]:
        if row["start_chapter"] >= start:
            continue
        row = deepcopy(row)
        row["is_final_arc"] = False
        if row["end_chapter"] >= start:
            row["end_chapter"] = start - 1
            row["story_nodes"] = [{**node, "end_chapter": min(node["end_chapter"], start - 1)}
                                  for node in row.get("story_nodes", []) if node["start_chapter"] < start]
        preserved_arcs.append(row)
    if any(row["id"] == arc.id for row in preserved_arcs):
        raise ValueError("ending_planning_duplicate_arc")
    overall["planned_arc_count"] = len(preserved_arcs) + 1
    new_plans = [ChapterPlan.model_validate({key: value for key, value in row.items()
                                           if key in ChapterPlan.model_fields}).model_dump(mode="json") for row in chapters]
    updated = normalize_project_outline({**original, "overall": overall,
                                        "arcs": [*preserved_arcs, arc.model_dump(mode="json")],
                                        "chapters": [*[row for row in original["chapters"] if row["chapter_number"] < start], *new_plans]})
    updated = validate_outline_for_project(updated, current_chapter=int(store.state().get("current_chapter") or 0))
    rolling_rows = [store._generated_detail_to_rolling_chapter(row) for row in chapters]
    validate_rolling_batch(rolling_rows, expected_chapter_numbers=list(range(start, end + 1)), volume_range=(start, end))
    progress("细纲已生成，正在校验并保存总纲、结尾卷纲和章节细纲。")
    writer = SnapshotStore()
    with project_update_lock(store.root):
        assert_mutation_allowed()
        if _context_version(store) != version:
            raise ValueError("ending_planning_context_changed")
        rolling_store = RollingOutlineStore(store.root)
        rolling = rolling_store.read_rolling_outline() or {"schema_version": "rolling-outline/v1", "chapters": []}
        rolling = {**rolling, "chapters": [*[row for row in rolling.get("chapters", []) if row["chapter_number"] < start], *rolling_rows]}
        canonical = store._read_json(store.story_system_dir / "outline.json", {}) or {}
        canonical_rows = [row for row in canonical.get("chapters", []) if int(row.get("number") or row.get("chapter_number") or 0) < start]
        canonical = {**canonical, **{key: updated[key] for key in ("schema_version", "overall", "arcs")},
                     "chapters": [*canonical_rows, *[{**row, "number": row["chapter_number"],
                                                      "summary": row["goal"], "state_delta": row["payoff"]} for row in new_plans]]}
        payloads = {store.webnovel_dir / "outline.json": updated,
                    store.story_system_dir / "outline.json": canonical,
                    rolling_store._rolling_path(): rolling}
        backup = store.story_system_dir / "ending-plans" / "backups" / uuid4().hex
        for index, path in enumerate(payloads):
            writer.write_json_atomic(backup / f"{index}-{path.name}", writer.read_json(path))
        writer.replace_json_transaction(payloads)
        try:
            from packages.story_core.outline_markdown_sync import export_outline_to_markdown
            export_outline_to_markdown(store.root, updated)
        except Exception:
            logging.getLogger(__name__).warning("Ending outline markdown export failed", exc_info=True)
    return {"outline": {**updated, "source": "saved"}, "base_chapter": start - 1,
            "chapter_range": [start, end], "chapter_count": len(chapters)}
