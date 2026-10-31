"""Persist a manual scene outline and its compatibility views together."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import logging
from uuid import uuid4

from packages.story_core.outline_rolling import rolling_chapter_to_outline_entry, validate_rolling_chapter
from packages.story_core.outline_rolling_store import RollingOutlineStore, _utc_timestamp
from packages.story_core.persistence.project_locking import project_update_lock
from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.project_outline import ChapterPlan, ChapterScenePlan

EDIT_FIELDS = {
    "title", "chapter_goal", "core_conflict", "cast", "scenes", "gain", "cost",
    "foreshadowing", "hook", "state_delta",
}


def chapter_edit_version(chapter: dict) -> str:
    return sha256(json.dumps(chapter, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def edit_scene_outline(store, number: int, payload: dict, assert_allowed=lambda: None) -> dict:
    with project_update_lock(store.root):
        assert_allowed()
        rolling_store = RollingOutlineStore(store.root)
        rolling = rolling_store.read_rolling_outline()
        if not rolling:
            raise ValueError("rolling_outline_missing")
        old = next((c for c in rolling["chapters"] if c["chapter_number"] == number), None)
        if old is None:
            raise ValueError(f"rolling_chapter_not_found:{number}")
        if payload.get("base_version") and payload["base_version"] != chapter_edit_version(old):
            raise ValueError("rolling_chapter_changed")
        if set(payload) - EDIT_FIELDS - {"base_version", "chapter_number"}:
            raise ValueError("rolling_chapter_unknown_field")
        if "chapter_number" in payload and payload["chapter_number"] != number:
            raise ValueError("rolling_chapter_number_mismatch")
        merged = {**old, **{k: deepcopy(v) for k, v in payload.items() if k in EDIT_FIELDS}}
        outline = store.project_outline()
        final = outline["overall"].get("current_strategy") == "close" and number == outline["overall"].get("core_ending_chapter")
        validation = {**merged, "hook": "全书完结。" if final and not merged.get("hook") else merged.get("hook")}
        validate_rolling_chapter(validation, expected_chapter_number=number, volume_range=(number, number))
        if any(not isinstance(member.get("name"), str) or not member["name"].strip() for member in merged["cast"]):
            raise ValueError("rolling_chapter_cast_invalid")
        if any(not isinstance(scene[field], str) for scene in merged["scenes"] for field in ("location", "action", "result")):
            raise ValueError("rolling_chapter_scene_field_blank")
        merged.update(source="manual", last_manual_edit_at=_utc_timestamp())
        rolling = {**rolling, "chapters": [merged if c["chapter_number"] == number else c for c in rolling["chapters"]]}
        previous = next((c for c in outline["chapters"] if c["chapter_number"] == number), {})
        adapted = rolling_chapter_to_outline_entry(merged, base_entry=previous)
        if merged["scenes"] == old["scenes"] and previous.get("scene_chain"):
            # The rolling view omits POV, goals and state deltas; an unchanged
            # scene submission must retain those original details.
            adapted["scene_chain"] = deepcopy(previous["scene_chain"])
        else:
            adapted["scene_chain"] = [
                ChapterScenePlan(
                    location=scene["location"], action=scene["action"], change=scene["result"],
                ).model_dump(mode="json")
                for scene in merged["scenes"]
            ]
        if "must_not_write" not in merged and "must_not_write" in previous:
            adapted["must_not_write"] = deepcopy(previous["must_not_write"])
        legacy = ChapterPlan.model_validate({
            **previous, **{k: v for k, v in adapted.items() if k in ChapterPlan.model_fields},
        }).model_dump(mode="json")
        outline.pop("source", None)
        outline["chapters"] = sorted([c for c in outline["chapters"] if c["chapter_number"] != number] + [legacy], key=lambda c: c["chapter_number"])
        canonical = store._read_json(store.story_system_dir / "outline.json", {}) or {}
        canonical["chapters"] = [c for c in canonical.get("chapters", []) if int(c.get("number") or c.get("chapter_number") or 0) != number] + [{**adapted, "number": number}]
        writer = SnapshotStore()
        targets = {store.webnovel_dir / "outline.json": outline, store.story_system_dir / "outline.json": canonical, rolling_store._rolling_path(): rolling}
        backup = store.story_system_dir / "outline-generation" / "backup" / f"manual-{uuid4().hex}"
        for index, path in enumerate(targets):
            if path.exists():
                writer.write_json_atomic(backup / f"{index}-{path.name}", writer.read_json(path))
        writer.replace_json_transaction(targets)
        try:
            from packages.story_core.outline_markdown_sync import export_outline_to_markdown
            export_outline_to_markdown(store.root, outline)
        except Exception:
            logging.getLogger(__name__).warning("Manual outline markdown export failed", exc_info=True)
        return {**merged, "edit_version": chapter_edit_version(merged)}
