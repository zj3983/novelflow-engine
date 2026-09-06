from __future__ import annotations

import json
import re
from copy import deepcopy
from hashlib import sha256
from typing import Any

from packages.story_core.elastic_outline import outline_window_status
from packages.story_core.outline_extension_readiness import inspect_outline_extension_readiness
from packages.story_core.outline_generation_checkpoints import OutlineCheckpointStore
from packages.story_core.outline_planning import CHAPTER_SOP_MODULE_ID
from packages.story_core.outline_planning_generation import validate_next_volume
from packages.story_core.outline_rolling import validate_rolling_batch
from packages.story_core.outline_rolling_store import RollingOutlineStore
from packages.story_core.persistence.project_locking import with_project_update_lock
from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
)
from packages.story_core.volume_detail_checkpoints import VolumeDetailCheckpointStore
from packages.story_core.volume_outline import (
    find_volume_for_chapter,
    volume_detail_batches_for_missing,
)


class VolumeOutlineWorkflowMixin:
    """Volume planning, rolling detail generation, and prose readiness gates."""

    @staticmethod
    def _generated_detail_to_rolling_chapter(chapter: Any) -> dict[str, Any]:
        payload = (
            chapter.model_dump(mode="json")
            if hasattr(chapter, "model_dump")
            else dict(chapter)
        )
        cast = [
            {
                "name": str(name).strip(),
                "role": "character",
                "this_chapter_role": "participates in the chapter action",
            }
            for name in payload.get("cast", [])
            if str(name).strip()
        ]
        scenes = []
        for scene in payload.get("scene_chain", []):
            if not isinstance(scene, dict):
                continue
            result = str(
                scene.get("change") or scene.get("next") or ""
            ).strip()
            scenes.append(
                {
                    "location": str(scene.get("location") or "").strip(),
                    "action": str(scene.get("action") or "").strip(),
                    "result": result,
                }
            )
        rolling = {
            "chapter_number": int(payload["chapter_number"]),
            "title": str(payload.get("title") or "").strip(),
            "chapter_goal": str(payload.get("goal") or "").strip(),
            "core_conflict": str(payload.get("core_conflict") or "").strip(),
            "cast": cast,
            "scenes": scenes,
            "gain": str(payload.get("gain") or "").strip(),
            "cost": str(payload.get("cost") or "").strip(),
            "foreshadowing": list(payload.get("foreshadowing") or []),
            "hook": str(payload.get("ending_hook") or "").strip(),
            "state_delta": str(
                payload.get("state_delta_summary") or ""
            ).strip(),
        }
        for optional in ("payoff_contract", "chapter_sop"):
            if isinstance(payload.get(optional), dict):
                rolling[optional] = dict(payload[optional])
        return rolling

    @staticmethod
    def _validate_volume_detail_handoff(
        *,
        batch_id: str,
        chapter_numbers: list[int],
        generated_chapters: list[Any],
        previous_batch: dict[str, Any] | None,
        adjacent_chapters: list[dict[str, Any]],
        volume_range: tuple[int, int],
        previous_missing_batch: tuple[int, int] | None,
        next_missing_batch: tuple[int, int] | None,
    ) -> dict[str, Any]:
        def payload(item: Any) -> dict[str, Any]:
            if hasattr(item, "model_dump"):
                return item.model_dump(mode="json")
            return dict(item) if isinstance(item, dict) else {}

        def hook_and_delta(item: dict[str, Any]) -> tuple[str, str]:
            return (
                str(item.get("ending_hook") or item.get("hook") or "").strip(),
                str(
                    item.get("state_delta_summary")
                    or item.get("state_delta")
                    or ""
                ).strip(),
            )

        rows = [payload(item) for item in generated_chapters]
        actual = [int(item.get("chapter_number") or 0) for item in rows]
        invalid = actual != chapter_numbers or not rows
        if rows:
            first = rows[0]
            invalid = invalid or not str(
                first.get("goal") or first.get("chapter_goal") or ""
            ).strip()
            invalid = invalid or not str(first.get("core_conflict") or "").strip()
            ending_hook, ending_delta = hook_and_delta(rows[-1])
            invalid = invalid or not ending_hook or not ending_delta

        previous_ending: dict[str, Any] | None = None
        if previous_batch:
            previous_rows = previous_batch.get("chapters")
            if isinstance(previous_rows, list) and previous_rows:
                previous_ending = payload(previous_rows[-1])
                previous_number = int(previous_ending.get("chapter_number") or 0)
                if previous_number + 1 == chapter_numbers[0]:
                    previous_hook, previous_delta = hook_and_delta(previous_ending)
                    invalid = invalid or not previous_hook or not previous_delta

        adjacent_by_number = {
            int(item.get("chapter_number") or 0): dict(item)
            for item in adjacent_chapters
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) > 0
        }
        start, end = chapter_numbers[0], chapter_numbers[-1]
        volume_start, volume_end = volume_range
        previous_is_contiguous = bool(
            previous_missing_batch and previous_missing_batch[1] + 1 == start
        )
        next_is_contiguous = bool(
            next_missing_batch and end + 1 == next_missing_batch[0]
        )
        if start > volume_start and not previous_is_contiguous:
            invalid = invalid or start - 1 not in adjacent_by_number
        if end < volume_end and not next_is_contiguous:
            invalid = invalid or end + 1 not in adjacent_by_number
        if invalid:
            raise ValueError(f"volume_detail_continuity_invalid:{batch_id}")
        return {
            "previous_batch_ending": previous_ending,
            "adjacent_chapters": list(adjacent_by_number.values()),
        }

    @staticmethod
    def _volume_design_outline_hash(outline: dict[str, Any]) -> str:
        payload = deepcopy(outline)
        payload.pop("source", None)
        return sha256(
            json.dumps(
                payload,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()

    def volume_workflow_status(self, target_chapter: int) -> dict[str, Any]:
        """Return the stable plan/detail gate for one requested chapter."""

        if (
            not isinstance(target_chapter, int)
            or isinstance(target_chapter, bool)
            or target_chapter < 1
        ):
            raise ValueError("invalid_chapter_number")
        outline = dict(self.project_outline())
        outline.pop("source", None)
        volume = find_volume_for_chapter(outline.get("arcs", []), target_chapter)
        if volume is None:
            return {
                "schema_version": "volume-workflow/v1",
                "target_chapter": target_chapter,
                "status": "volume_missing",
                "detail_status": "volume_missing",
                "next_action": "design_next_volume",
                "volume_id": None,
                "volume_range": None,
            }

        start = int(volume["start_chapter"])
        end = int(volume["end_chapter"])
        detailed = {
            int(item["chapter_number"])
            for item in outline.get("chapters", [])
            if isinstance(item, dict)
            and isinstance(item.get("chapter_number"), int)
            and not isinstance(item.get("chapter_number"), bool)
            and start <= int(item["chapter_number"]) <= end
        }
        rolling = RollingOutlineStore(self.root).read_rolling_outline() or {}
        detailed.update(
            int(item["chapter_number"])
            for item in rolling.get("chapters", [])
            if isinstance(item, dict)
            and isinstance(item.get("chapter_number"), int)
            and not isinstance(item.get("chapter_number"), bool)
            and start <= int(item["chapter_number"]) <= end
        )
        expected = set(range(start, end + 1))
        if detailed == expected:
            status = "detail_complete"
            detail_status = "detail_complete"
            next_action = "generate_prose"
        elif detailed:
            status = "detail_partial"
            detail_status = "partial"
            next_action = "generate_volume_detail"
        else:
            status = "volume_plan_ready"
            detail_status = "missing"
            next_action = "generate_volume_detail"
        return {
            "schema_version": "volume-workflow/v1",
            "target_chapter": target_chapter,
            "status": status,
            "detail_status": detail_status,
            "next_action": next_action,
            "volume_id": str(volume["id"]),
            "volume_range": [start, end],
        }

    def require_volume_detail_for_prose(self, target_chapter: int) -> dict[str, Any]:
        """Require a complete volume detail outline before any prose model call."""

        workflow = self.volume_workflow_status(target_chapter)
        status = str(workflow.get("status") or "")
        volume_id = str(workflow.get("volume_id") or "").strip()
        if status == "detail_complete":
            return workflow
        if status == "volume_missing":
            raise ValueError(f"next_volume_required:{target_chapter}")
        if status == "volume_plan_ready":
            raise ValueError(f"volume_detail_required:{volume_id}")
        if status == "detail_partial":
            raise ValueError(f"volume_detail_incomplete:{volume_id}")
        raise ValueError(f"invalid_volume_workflow_status:{status or 'missing'}")

    @with_project_update_lock
    def design_next_volume(
        self,
        generator: Any,
        *,
        guidance: str = "",
    ) -> dict[str, Any]:
        """Append one successor volume, leaving chapter detail untouched.

        A brand-new project with zero arcs bootstraps the first volume
        instead of raising ``previous_volume_missing``; in that case the
        generator and validator receive ``previous_volume=None`` and
        ``target_chapter=1`` with the whole-book length floor relaxed.
        """

        if not hasattr(generator, "generate_next_volume"):
            raise ValueError("next_volume_generator_required")
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        current_chapter = int(state.get("current_chapter") or 0)
        target_chapter = current_chapter + 1
        original = dict(self.project_outline())
        original.pop("source", None)
        existing = find_volume_for_chapter(original.get("arcs", []), target_chapter)
        if existing is not None:
            return {
                "schema_version": "volume-design/v1",
                "status": "volume_plan_ready",
                "next_action": "generate_volume_detail",
                "volume_id": str(existing["id"]),
                "volume_range": [
                    int(existing["start_chapter"]),
                    int(existing["end_chapter"]),
                ],
                "created": False,
            }

        previous_candidates = [
            dict(arc)
            for arc in original.get("arcs", [])
            if isinstance(arc, dict)
            and int(arc.get("end_chapter") or 0) < target_chapter
        ]
        if previous_candidates:
            previous = max(
                previous_candidates, key=lambda arc: int(arc["end_chapter"])
            )
            if int(previous["end_chapter"]) + 1 != target_chapter:
                raise ValueError("next_volume_start_gap")
        else:
            previous = None

        version_before = self._volume_design_outline_hash(original)
        brief = self._planning_brief()
        generated = generator.generate_next_volume(
            brief,
            previous_volume=deepcopy(previous) if previous is not None else None,
            guidance=str(guidance or "").strip(),
        )
        overall = original.get("overall") if isinstance(original.get("overall"), dict) else {}
        allow_short_final = (
            str(overall.get("current_strategy") or "observe") == "close"
        )
        volume = validate_next_volume(
            generated,
            previous_volume=previous,
            allow_short_final=allow_short_final,
        )

        latest = dict(self.project_outline())
        latest.pop("source", None)
        if self._volume_design_outline_hash(latest) != version_before:
            raise ValueError("outline_changed_during_volume_design")

        updated = deepcopy(latest)
        arcs = [dict(arc) for arc in updated.get("arcs", [])]
        if any(str(arc.get("id") or "") == volume.id for arc in arcs):
            raise ValueError(f"duplicate_arc_id:{volume.id}")
        for arc in arcs:
            if arc.get("is_final_arc") is True:
                arc["is_final_arc"] = False
        arcs.append(volume.model_dump(mode="json"))
        updated["arcs"] = arcs
        updated_overall = dict(updated.get("overall") or {})
        if volume.is_final_arc:
            updated_overall["core_ending_chapter"] = volume.end_chapter
        else:
            updated_overall["core_ending_chapter"] = max(
                int(updated_overall.get("core_ending_chapter") or 1),
                volume.end_chapter,
            )
        updated_overall["extension_ceiling_chapter"] = max(
            int(updated_overall.get("extension_ceiling_chapter") or 1),
            int(updated_overall["core_ending_chapter"]),
            volume.end_chapter,
        )
        updated_overall["planned_arc_count"] = len(arcs)
        updated_overall["planned_length"] = max(
            int(updated_overall.get("planned_length") or 0),
            volume.end_chapter,
        )
        updated["overall"] = updated_overall
        saved = self.update_project_outline(updated)
        return {
            "schema_version": "volume-design/v1",
            "status": "volume_plan_ready",
            "next_action": "generate_volume_detail",
            "volume_id": volume.id,
            "volume_range": [volume.start_chapter, volume.end_chapter],
            "created": True,
            "outline": saved,
        }

    @with_project_update_lock
    def generate_volume_detail(
        self,
        generator: Any,
        *,
        volume_id: str,
        guidance: str = "",
    ) -> dict[str, Any]:
        """Generate every missing detail row in one volume, then publish once."""

        if not hasattr(generator, "generate_chapter_batch"):
            raise ValueError("volume_detail_generator_required")
        normalized_volume_id = str(volume_id or "").strip()
        outline = dict(self.project_outline())
        outline.pop("source", None)
        volume = next(
            (
                dict(arc)
                for arc in outline.get("arcs", [])
                if isinstance(arc, dict)
                and str(arc.get("id") or "").strip() == normalized_volume_id
            ),
            None,
        )
        if volume is None:
            raise ValueError(
                f"volume_detail_volume_missing:{normalized_volume_id or volume_id}"
            )
        start = int(volume["start_chapter"])
        end = int(volume["end_chapter"])
        volume_range = (start, end)

        legacy_chapter_map = {
            int(chapter["chapter_number"]): dict(chapter)
            for chapter in outline.get("chapters", [])
            if isinstance(chapter, dict)
            and isinstance(chapter.get("chapter_number"), int)
            and not isinstance(chapter.get("chapter_number"), bool)
            and start <= int(chapter["chapter_number"]) <= end
        }
        rolling_store = RollingOutlineStore(self.root)
        rolling_outline = rolling_store.read_rolling_outline() or {}
        rolling_chapter_map = {
            int(chapter["chapter_number"]): dict(chapter)
            for chapter in rolling_outline.get("chapters", [])
            if isinstance(chapter, dict)
            and isinstance(chapter.get("chapter_number"), int)
            and not isinstance(chapter.get("chapter_number"), bool)
            and start <= int(chapter["chapter_number"]) <= end
        }
        existing_chapter_map = {**legacy_chapter_map, **rolling_chapter_map}
        existing_numbers = set(existing_chapter_map)
        missing_batches = volume_detail_batches_for_missing(
            start,
            end,
            existing=sorted(existing_numbers),
        )
        total_chapters = end - start + 1
        if not missing_batches:
            return {
                "schema_version": "volume-detail-generation/v1",
                "volume_id": normalized_volume_id,
                "volume_range": [start, end],
                "detail_status": "complete",
                "completed_chapters": total_chapters,
                "total_chapters": total_chapters,
                "batches": [],
            }

        normalized_guidance = str(guidance or "").strip()
        volume_fingerprint = sha256(
            json.dumps(
                {
                    "volume": volume,
                    "guidance": normalized_guidance,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        roster_path = (
            self.story_system_dir
            / "volume-characters"
            / f"{normalized_volume_id}.json"
        )
        roster_payload = self._read_json(roster_path, {})
        has_cached_roster = (
            isinstance(roster_payload, dict)
            and roster_payload.get("schema_version") == "volume-character-roster/v1"
            and roster_payload.get("volume_fingerprint") == volume_fingerprint
            and isinstance(roster_payload.get("characters"), list)
        )
        if has_cached_roster:
            self._persist_volume_character_cards(
                list(roster_payload["characters"]),
                roster_path=roster_path,
                volume_id=normalized_volume_id,
                volume_fingerprint=volume_fingerprint,
            )
        elif hasattr(generator, "generate_volume_characters"):
            generated_characters = generator.generate_volume_characters(
                self._planning_brief(),
                volume=deepcopy(volume),
                guidance=normalized_guidance,
            )
            self._persist_volume_character_cards(
                list(generated_characters or []),
                roster_path=roster_path,
                volume_id=normalized_volume_id,
                volume_fingerprint=volume_fingerprint,
            )
        enabled_module_ids = resolve_enabled_skill_module_ids(
            self.project(), self.state()
        )
        enabled_skill_ids = resolve_enabled_skill_ids(self.project(), self.state())
        require_chapter_contracts = (
            enabled_module_ids is None
            and CHAPTER_SOP_MODULE_ID.split("::", 1)[0] in enabled_skill_ids
        ) or CHAPTER_SOP_MODULE_ID in {
            str(module_id).strip()
            for module_id in (enabled_module_ids or [])
        }
        outline_version = sha256(
            json.dumps(
                {
                    "overall": outline.get("overall", {}),
                    "arcs": outline.get("arcs", []),
                    "existing_chapter_numbers": sorted(existing_numbers),
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()
        checkpoints = VolumeDetailCheckpointStore(
            self.story_system_dir / "volume-detail"
        )
        manifest = checkpoints.prepare(
            volume_id=normalized_volume_id,
            batches=[[batch[0], batch[-1]] for batch in missing_batches],
            volume_range=[start, end],
            story_nodes=volume.get("story_nodes", []),
            existing_outline_version=outline_version,
            user_guidance=normalized_guidance,
        )
        completed_payloads = checkpoints.completed_payloads()
        invalidate_downstream = False
        invalid_upstream_id = ""
        for batch in manifest["batches"]:
            batch_id = str(batch["id"])
            payload = completed_payloads.get(batch_id)
            if invalidate_downstream:
                if payload is not None:
                    checkpoints.fail(
                        batch_id,
                        f"upstream_batch_invalid:{invalid_upstream_id}",
                    )
                    completed_payloads.pop(batch_id, None)
                continue
            if payload is None:
                continue
            chapter_numbers = list(
                range(batch["start_chapter"], batch["end_chapter"] + 1)
            )
            try:
                payload["chapters"] = validate_rolling_batch(
                    payload.get("chapters", []),
                    expected_chapter_numbers=chapter_numbers,
                    volume_range=volume_range,
                    require_chapter_contracts=require_chapter_contracts,
                )
            except Exception as exc:
                detail = re.sub(r"\s+", " ", str(exc)).strip()[:500]
                checkpoints.fail(
                    batch_id,
                    f"cached_payload_invalid:{type(exc).__name__}:"
                    f"{detail or 'no_detail'}",
                )
                completed_payloads.pop(batch_id, None)
                invalidate_downstream = True
                invalid_upstream_id = batch_id
        previous_batches = [
            completed_payloads[batch["id"]]
            for batch in manifest["batches"]
            if batch["id"] in completed_payloads
        ]
        brief = self._planning_brief()
        if rolling_outline and rolling_outline.get("chapters"):
            existing_outline_copy = deepcopy(brief.existing_outline)
            existing_chapters_by_num = {
                int(c["chapter_number"]): dict(c)
                for c in existing_outline_copy.get("chapters", [])
                if isinstance(c, dict) and isinstance(c.get("chapter_number"), int)
            }
            for c in rolling_outline.get("chapters", []):
                if isinstance(c, dict) and isinstance(c.get("chapter_number"), int):
                    num = int(c["chapter_number"])
                    if num not in existing_chapters_by_num:
                        existing_chapters_by_num[num] = dict(c)
            existing_outline_copy["chapters"] = [
                existing_chapters_by_num[num] for num in sorted(existing_chapters_by_num)
            ]
            brief = brief.model_copy(update={"existing_outline": existing_outline_copy})
        known_character_names = {
            str(name).strip()
            for name in brief.existing_character_names
            if str(name).strip()
        }
        first_appearance_by_name = {
            str(card.get("name") or "").strip(): int(
                card.get("first_appearance") or 0
            )
            for card in self.project().get("character_profiles", [])
            if isinstance(card, dict) and str(card.get("name") or "").strip()
        }
        committed_context = {
            "world_facts": deepcopy(brief.world_facts),
            "continuity_facts": deepcopy(brief.continuity_facts),
            "committed_facts": deepcopy(brief.committed_facts),
        }

        while True:
            batch = checkpoints.next_incomplete_batch()
            if batch is None:
                break
            batch_id = str(batch["id"])
            batch_index = next(
                index
                for index, item in enumerate(manifest["batches"])
                if item["id"] == batch_id
            )
            chapter_numbers = list(
                range(batch["start_chapter"], batch["end_chapter"] + 1)
            )
            adjacent_chapters = [
                deepcopy(existing_chapter_map[number])
                for number in (chapter_numbers[0] - 1, chapter_numbers[-1] + 1)
                if number in existing_chapter_map
            ]
            previous_manifest_batch = (
                manifest["batches"][batch_index - 1] if batch_index > 0 else None
            )
            next_manifest_batch = (
                manifest["batches"][batch_index + 1]
                if batch_index + 1 < len(manifest["batches"])
                else None
            )
            previous_payload = (
                completed_payloads.get(previous_manifest_batch["id"])
                if previous_manifest_batch
                else None
            )
            checkpoints.running(batch_id)
            try:
                cast_correction = ""
                generated_chapters: list[Any] = []
                for cast_attempt in range(2):
                    batch_guidance = normalized_guidance
                    if cast_correction:
                        batch_guidance = "\n".join(
                            item
                            for item in (
                                normalized_guidance,
                                "Correct this cast validation error without changing the fixed volume or story nodes: "
                                + cast_correction,
                            )
                            if item
                        )
                    generated = generator.generate_chapter_batch(
                        brief,
                        volume=deepcopy(volume),
                        chapter_numbers=chapter_numbers,
                        previous_batches=deepcopy(previous_batches),
                        adjacent_chapters=deepcopy(adjacent_chapters),
                        committed_context=deepcopy(committed_context),
                        guidance=batch_guidance,
                    )
                    generated_chapters = list(getattr(generated, "chapters", []))
                    actual_numbers = [
                        int(chapter.chapter_number)
                        for chapter in generated_chapters
                    ]
                    if actual_numbers != chapter_numbers:
                        raise ValueError("generated_chapters_do_not_match_target_batch")
                    try:
                        self._validate_volume_detail_cast(
                            generated_chapters,
                            known_character_names=known_character_names,
                            first_appearance_by_name=first_appearance_by_name,
                        )
                        break
                    except ValueError as exc:
                        detail = str(exc)
                        if cast_attempt == 0 and detail.startswith(
                            ("missing_character_card:", "character_appears_before_card:")
                        ):
                            cast_correction = detail
                            continue
                        raise
                handoff = self._validate_volume_detail_handoff(
                    batch_id=batch_id,
                    chapter_numbers=chapter_numbers,
                    generated_chapters=generated_chapters,
                    previous_batch=previous_payload,
                    adjacent_chapters=adjacent_chapters,
                    volume_range=volume_range,
                    previous_missing_batch=(
                        (
                            int(previous_manifest_batch["start_chapter"]),
                            int(previous_manifest_batch["end_chapter"]),
                        )
                        if previous_manifest_batch
                        else None
                    ),
                    next_missing_batch=(
                        (
                            int(next_manifest_batch["start_chapter"]),
                            int(next_manifest_batch["end_chapter"]),
                        )
                        if next_manifest_batch
                        else None
                    ),
                )
                payload = {
                    "chapters": [
                        self._generated_detail_to_rolling_chapter(chapter)
                        for chapter in generated_chapters
                    ],
                    "handoff_context": handoff,
                }
                payload["chapters"] = validate_rolling_batch(
                    payload["chapters"],
                    expected_chapter_numbers=chapter_numbers,
                    volume_range=volume_range,
                    require_chapter_contracts=require_chapter_contracts,
                )
                checkpoints.complete(batch_id, payload)
                completed_payloads[batch_id] = payload
                previous_batches.append(payload)
            except Exception as exc:
                detail = re.sub(r"\s+", " ", str(exc)).strip()[:500]
                checkpoints.fail(
                    batch_id,
                    f"{type(exc).__name__}:{detail or 'no_detail'}",
                )
                if detail.startswith("volume_detail_continuity_invalid:"):
                    raise ValueError(detail) from exc
                raise ValueError(
                    f"volume_detail_generation_failed:{batch_id}:"
                    f"{type(exc).__name__}:{detail or 'no_detail'}"
                ) from exc

        manifest = checkpoints.load(normalized_volume_id)
        completed_payloads = checkpoints.completed_payloads()
        generated_chapters: list[dict[str, Any]] = []
        expected_missing: list[int] = []
        previous_payload = None
        for batch_index, batch in enumerate(manifest["batches"]):
            payload = completed_payloads.get(batch["id"])
            if payload is None:
                raise ValueError(
                    f"volume_detail_checkpoint_incomplete:{batch['id']}"
                )
            expected_missing.extend(
                range(batch["start_chapter"], batch["end_chapter"] + 1)
            )
            handoff = payload.get("handoff_context")
            if not isinstance(handoff, dict):
                checkpoints.fail(
                    str(batch["id"]),
                    f"volume_detail_continuity_invalid:{batch['id']}",
                )
                raise ValueError(
                    f"volume_detail_continuity_invalid:{batch['id']}"
                )
            previous_manifest_batch = (
                manifest["batches"][batch_index - 1] if batch_index > 0 else None
            )
            next_manifest_batch = (
                manifest["batches"][batch_index + 1]
                if batch_index + 1 < len(manifest["batches"])
                else None
            )
            try:
                self._validate_volume_detail_cast(
                    list(payload.get("chapters") or []),
                    known_character_names=known_character_names,
                    first_appearance_by_name=first_appearance_by_name,
                )
                self._validate_volume_detail_handoff(
                    batch_id=str(batch["id"]),
                    chapter_numbers=list(
                        range(batch["start_chapter"], batch["end_chapter"] + 1)
                    ),
                    generated_chapters=list(payload["chapters"]),
                    previous_batch=previous_payload,
                    adjacent_chapters=list(handoff.get("adjacent_chapters") or []),
                    volume_range=volume_range,
                    previous_missing_batch=(
                        (
                            int(previous_manifest_batch["start_chapter"]),
                            int(previous_manifest_batch["end_chapter"]),
                        )
                        if previous_manifest_batch
                        else None
                    ),
                    next_missing_batch=(
                        (
                            int(next_manifest_batch["start_chapter"]),
                            int(next_manifest_batch["end_chapter"]),
                        )
                        if next_manifest_batch
                        else None
                    ),
                )
            except ValueError as exc:
                checkpoints.fail(str(batch["id"]), str(exc))
                raise
            generated_chapters.extend(payload["chapters"])
            previous_payload = payload
        actual_missing = [
            int(chapter.get("chapter_number") or 0)
            for chapter in generated_chapters
        ]
        if (
            actual_missing != expected_missing
            or len(actual_missing) != len(set(actual_missing))
            or any(number < start or number > end for number in actual_missing)
        ):
            raise ValueError("volume_detail_publish_validation_failed")

        rolling_store.apply_rolling_batch(
            chapters=generated_chapters,
            expected_chapter_numbers=expected_missing,
            volume_range=volume_range,
            require_chapter_contracts=require_chapter_contracts,
        )
        return {
            "schema_version": "volume-detail-generation/v1",
            "volume_id": normalized_volume_id,
            "volume_range": [start, end],
            "detail_status": "complete",
            "completed_chapters": total_chapters,
            "total_chapters": total_chapters,
            "batches": manifest["batches"],
        }

    def outline_extension_readiness(self) -> dict[str, Any]:
        outline = dict(
            self._read_json(self.webnovel_dir / "outline.json", {})
            or self.project_outline()
        )
        outline.pop("source", None)
        readiness = inspect_outline_extension_readiness(
            project=dict(self.project()),
            state=dict(self._read_json(self.webnovel_dir / "state.json", {}) or {}),
            outline=outline,
        )
        raw_arcs = outline.get("arcs") if isinstance(outline.get("arcs"), list) else []
        has_actionable_arc = any(
            isinstance(arc, dict)
            and all(str(arc.get(field) or "").strip() for field in ("goal", "obstacle", "payoff"))
            for arc in raw_arcs
        )
        if not has_actionable_arc and not any(
            item.get("code") == "stage_arc_required"
            for item in readiness.get("blockers", [])
            if isinstance(item, dict)
        ):
            readiness.setdefault("blockers", []).append(
                {
                    "code": "stage_arc_required",
                    "message": "阶段大纲缺少可执行的目标、阻力和兑现。",
                    "section": "arcs",
                }
            )
            readiness["ready"] = False
        window = outline_window_status(
            outline,
            current_chapter=int(readiness.get("current_chapter") or 0),
        )
        detail_batches = window.get("detail_batches") or []
        readiness["next_chapter_numbers"] = (
            list(detail_batches[0])
            if detail_batches
            else list(
                range(
                    int(readiness.get("current_chapter") or 0) + 1,
                    int(readiness.get("current_chapter") or 0) + 16,
                )
            )
        )
        return readiness

    def outline_generation_checkpoints(self) -> dict[str, Any]:
        checkpoints = OutlineCheckpointStore(
            self.story_system_dir / "outline-generation"
        )
        status = checkpoints.status()
        payloads = checkpoints.completed_payloads()
        for phase in status.get("phases", []):
            if not isinstance(phase, dict):
                continue
            payload = payloads.get(str(phase.get("id") or ""))
            phase["has_payload"] = payload is not None
            if payload is not None:
                phase["payload"] = payload
        return status
