"""The four-page author workspace, backed by existing services and admission gates."""
from __future__ import annotations

from copy import deepcopy
import re
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from apps.api.routes import file_projects as workbench
from apps.api.routes.creation_product import ProductRoute, Screen, _handler, _key
from apps.api.routes.file_project_candidates import _candidate_project_ids
from packages.story_core import longform_lifecycle as lifecycle
from packages.story_core import product_presentation as product
from packages.story_core.candidate_editing import assert_review_current, candidate_authority, save_edit
from packages.story_core.book_style import BOOK_STYLE_OPTIONS
from packages.story_core.prompt_templates import load_global_prompt_templates, save_global_prompt_template
from packages.story_core.skill_packs import (
    list_skill_packs,
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
)
from packages.story_core.file_project_creation import FileProjectCreateSpec
from packages.story_core.longform_presentation import book_details, genre_id, opening_content, project_content, text
from packages.story_core.models import NovelProject
from packages.story_core.opening_build import execution, runtime
from packages.story_core.persistence.project_locking import project_update_lock


class CommandRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    bookId: str | None = None
    token: str = Field(min_length=64, max_length=64, pattern=r"^[a-f0-9]+$")
    command: dict[str, Any]


def _character_profile_patch(values: dict[str, Any]) -> dict[str, Any]:
    submitted = values.get("profile")
    if not isinstance(submitted, dict):
        raise ValueError("invalid_character_profile")

    def strings(value: Any, *, maximum: int = 5000) -> str:
        if not isinstance(value, str) or len(value) > maximum:
            raise ValueError("invalid_character_profile")
        return value.strip()

    def string_list(value: Any, *, maximum_items: int = 40) -> list[str]:
        if not isinstance(value, list) or len(value) > maximum_items:
            raise ValueError("invalid_character_profile")
        result = []
        for item in value:
            if not isinstance(item, str) or len(item) > 1000:
                raise ValueError("invalid_character_profile")
            clean = item.strip()
            if clean and clean not in result:
                result.append(clean)
        return result

    sections = {
        "identityProfile": {
            "gender": "gender", "aliases": "aliases", "birthplace": "birthplace",
            "origin": "origin", "currentIdentity": "current_identity",
            "occupation": "occupation", "affiliation": "affiliation", "age": "age",
        },
        "backgroundProfile": {
            "family": "family", "upbringing": "upbringing",
            "educationOrTraining": "education_or_training",
            "formativeEvents": "formative_events", "arrivalReason": "arrival_reason",
        },
        "storyDrive": {
            "longTermGoal": "long_term_goal", "immediateGoal": "immediate_goal",
            "motivation": "motivation", "failureStakes": "failure_stakes",
            "hiddenMatters": "hidden_matters", "mainConflictReason": "main_conflict_reason",
        },
        "performanceProfile": {
            "speechStyle": "speech_style", "actionStyle": "action_style",
            "riskPosture": "risk_posture", "emotionalTriggers": "emotional_triggers",
            "decisionRules": "decision_rules", "revealLimits": "reveal_limits",
        },
    }
    if set(submitted) - {*sections, "dialogueExamples", "futurePlans"}:
        raise ValueError("invalid_character_profile")
    patch: dict[str, Any] = {}
    for section_name, field_map in sections.items():
        if section_name not in submitted:
            continue
        section = submitted[section_name]
        if not isinstance(section, dict) or set(section) - set(field_map):
            raise ValueError("invalid_character_profile")
        converted: dict[str, Any] = {}
        for ui_key, field_name in field_map.items():
            if ui_key not in section:
                continue
            raw = section[ui_key]
            if ui_key == "age":
                if raw is not None and (
                    not isinstance(raw, int) or isinstance(raw, bool) or not 0 <= raw <= 300
                ):
                    raise ValueError("invalid_character_profile")
                converted[field_name] = raw
            elif field_name in {
                "aliases", "formative_events", "hidden_matters", "emotional_triggers",
                "decision_rules", "reveal_limits",
            }:
                converted[field_name] = string_list(raw)
            else:
                converted[field_name] = strings(raw)
        patch[
            {
                "identityProfile": "identity_profile",
                "backgroundProfile": "background_profile",
                "storyDrive": "story_drive",
                "performanceProfile": "performance_profile",
            }[section_name]
        ] = converted
    for ui_key, profile_key in (("dialogueExamples", "dialogue_examples"), ("futurePlans", "future_plans")):
        if ui_key in submitted:
            patch[profile_key] = string_list(submitted[ui_key], maximum_items=30)
    if not patch:
        raise ValueError("invalid_character_profile")
    return patch


def _world_section_item(raw: Any, *, title: str, body: str, section_id: str) -> Any:
    if isinstance(raw, str):
        return body
    if not isinstance(raw, dict):
        raise ValueError("invalid_world_section_item")
    updated = deepcopy(raw)
    title_key = next((key for key in ("name", "title", "label") if key in updated), "name")
    body_key = next((key for key in ("description", "summary", "content", "rule", "overview", "text") if key in updated), None)
    if body_key is None:
        body_key = "description" if section_id in {"locations", "factions", "equipment", "monsters"} else "text"
    updated[title_key] = title
    updated[body_key] = body
    return updated


class PlanningScreen(Screen):
    """Retain this request's already-read details for the four-page projection."""
    def __init__(self, request, project_id):
        super().__init__(request, project_id)
        self.graph = {}
        self.details = {}

    def call(self, name, **kwargs):
        if name == "get_file_project_build_graph_task" and kwargs["task_id"] in self.details:
            return self.details[kwargs["task_id"]]
        value = super().call(name, **kwargs)
        if name == "get_file_project_build_graph":
            self.graph = value
            # The caller holds the project lock for this entire projection. Reuse
            # its validated graph snapshot instead of reconstructing and checking
            # the complete graph once per chapter just to read its text.
            self.details = {}
            if value.get("initialized"):
                definition = runtime.graph_for(self.store, NovelProject.model_validate(self.store.project()))
                build_store = self.store.build_graph_store()
                for task in value["tasks"]:
                    revision = task.get("artifact_revision")
                    artifact = build_store.read_artifact(task["task_id"], revision) if revision is not None else None
                    if revision is not None and artifact is None:
                        raise HTTPException(409, "build_graph_artifact_missing")
                    self.details[task["task_id"]] = {
                        **task,
                        "artifact": artifact.to_dict() if artifact else None,
                        "editable": definition.spec(task["task_id"]).kind == "model"
                            and artifact is not None and not value.get("opening_execution_started"),
                    }
        elif name == "get_file_project_build_graph_task":
            self.details[kwargs["task_id"]] = value
        return value


class AuthorScreen(Screen):
    def __init__(self, request, project_id):
        super().__init__(request, project_id)
        self.mode = "c"
        self.commands = {}

    def command(self, name, label, authority, callback, *, enabled=True, reason=None):
        action = self.action(name, label, authority, callback, enabled=enabled, reason=reason)
        action["command"] = name
        self.commands[name] = action
        return action

    def start_next(self, reservation=None, *, expected_plan=None):
        lifecycle.require_accepted_plan(self.store)
        return workbench.start_file_generation_job(self.project_id,
            workbench.FileProjectGenerationJobRequest(candidate_only=True, require_accepted_plan=True), reserved_job_id=reservation, expected_plan=expected_plan)

    def prepare(self):
        self.generation_job = workbench.read_file_generation_job_state(self.store) or {}
        self.build_screen = PlanningScreen(self.request, self.project_id)
        self.build_screen.prepare_build()
        # Read job ownership before taking the project lock. A failed next
        # chapter must stay recoverable even when the receipt still says queued.
        self.continuation_jobs = {}
        current_chapter = int(self.store.state().get("current_chapter") or 0)
        accepted_ids = _candidate_project_ids(self.store, self.project_id)
        for candidate in self.store.candidate_store.list():
            if candidate.status == "confirmed" and candidate.chapter_number == current_chapter and candidate.project_id in accepted_ids:
                intent = lifecycle.continuation_state(self.store, candidate.candidate_id)
                if intent and intent.get("job_id"):
                    self.continuation_jobs[intent["job_id"]] = workbench.read_file_generation_job_state(self.store, intent["job_id"])

    def view(self, chapter=None):
        store = self.store
        info, state = store.project(), store.state()
        confirmed = int(state.get("current_chapter") or 0)
        source = execution.source_fingerprint(store)
        accepted_ids = _candidate_project_ids(store, self.project_id)
        pending = [c for c in store.candidate_store.list() if c.project_id in accepted_ids and c.status == "pending"]
        candidate = max(pending, key=lambda c: c.chapter_number) if pending else None
        selected = chapter if chapter is not None else candidate.chapter_number if candidate else confirmed
        job = self.generation_job
        busy = job.get("status") in {"queued", "running"}
        continuous = workbench._continuous_job_store(store).load()
        if continuous:
            data = continuous.to_dict() if hasattr(continuous, "to_dict") else continuous
            busy = busy or data.get("status") in {"queued", "running", "stopping"}
        plan = lifecycle.plan_state(store)
        setup = opening_content(store)
        selected_direction = next((d for d in setup.get("directions", []) if d.get("id") == setup.get("selected_id")), {})
        future_intent = lifecycle.author_future_intent(store)
        content = project_content(store, future_intent=future_intent, selected_chapter=selected)
        details = book_details(store)
        authority = [source, info, plan["fingerprint"], job.get("job_id"), job.get("status")]
        result = {"id": self.project_id, "title": text(info.get("title")) or "未命名作品",
                  "genre": genre_id(info, state), "idea": text((setup.get("brief") or {}).get("idea")),
                  "targetWords": info.get("target_words"), "chapterWords": info.get("target_chapter_words"),
                  "requirements": "\n".join(info.get("author_constraints") or []),
                  "direction": text(selected_direction.get("title")), "planAdopted": plan["accepted"],
                  "directions": [{"id": _key("direction", self.project_id, d.get("id")), "text": text(d.get("title")), "label": text(d.get("logline")) or text(d.get("hook"))} for d in setup.get("directions", [])],
                  "chapters": [], "notice": "正在处理，请稍候。" if busy else "", "busy": busy,
                  "bookDetails": details, "lifecycleLabel": details["lifecycleLabel"],
                  "canRetry": job.get("status") in {"failed", "interrupted", "conflicted"},
                  "nextVolume": False, "archived": False, **content}
        result["future"] = future_intent if isinstance(future_intent, str) else content["future"]
        if not result["direction"] and (confirmed or content["plan"]):
            result["direction"] = content["plan"] or "沿用已有故事规划"

        profile_cards = info.get("character_profiles") if isinstance(info.get("character_profiles"), list) else []
        state_cards = state.get("characters") if isinstance(state.get("characters"), list) else []
        profile_by_name = {
            text(card.get("name")): card for card in profile_cards
            if isinstance(card, dict) and text(card.get("name"))
        }
        state_by_name = {
            text(card.get("name")): card for card in state_cards
            if isinstance(card, dict) and text(card.get("name"))
        }
        character_views = []
        for person in content.get("people", []):
            name = text(person.get("name"))
            profile_source = profile_by_name.get(name) or state_by_name.get(name)
            if not name or not isinstance(profile_source, dict):
                continue
            profile_version = store.character_profile_version(profile_source)
            profile_authority = [authority, "character-profile", name, profile_version]
            command_id = _key("character-profile", self.project_id, name)

            def save_character_profile(values, character_name=name, expected=profile_version):
                return store.update_character_profile(
                    character_name,
                    _character_profile_patch(values),
                    expected_version=expected,
                )

            def complete_character_profile(values, character_name=name, expected=profile_version):
                return store.complete_character_portrait(
                    character_name,
                    expected_version=expected,
                )

            save_action = self.command(
                "character-profile-save:" + command_id,
                "保存人物设定",
                profile_authority,
                save_character_profile,
                enabled=not busy,
            )
            complete_action = self.command(
                "character-profile-complete:" + command_id,
                "补全人物画像",
                profile_authority,
                complete_character_profile,
                enabled=not busy,
            )
            character_views.append({
                "name": name,
                "role": person.get("role"),
                "description": person.get("description"),
                "stableProfile": person.get("stableProfile", {}),
                "currentState": person.get("currentState", {}),
                "facts": person.get("facts", []),
                "performance": person.get("performance", []),
                "futurePlans": person.get("futurePlans", []),
                "editableProfile": person.get("editableProfile", {}),
                "actions": {"save": save_action, "completePortrait": complete_action},
            })
        result["characterCardsView"] = {"items": character_views}

        world_field_groups = {
            "background": ("world_background", "background", "world_model", "world_summary"),
            "rules": ("world_rules", "core_rules", "world_systems", "economy_rules", "faction_rules", "power_system_spec"),
            "locations": ("locations", "location_profiles"),
            "factions": ("factions", "faction_profiles"),
            "equipment": ("equipment_cards", "equipment_profiles", "equipment_catalog"),
            "monsters": ("monster_cards", "monster_profiles", "monster_catalog"),
        }
        blueprint = info.get("world_blueprint") if isinstance(info.get("world_blueprint"), dict) else {}
        world_section_views = []
        for section in content.get("worldSections", []):
            section_id = text(section.get("id"))
            source_entries = section.get("entries") if isinstance(section.get("entries"), list) else []
            field_group = world_field_groups.get(section_id, ())
            baseline_fields = {field: deepcopy(blueprint.get(field)) for field in field_group}
            source_by_id = {}
            display_entries = []
            for source_entry in source_entries:
                field = text(source_entry.get("sourceField"))
                owner = text(source_entry.get("sourceOwner"))
                index = source_entry.get("sourceIndex")
                if field == "@project.world_summary":
                    original = info.get("world_summary")
                else:
                    values_for_field = baseline_fields.get(field) if owner == "project" else state.get(field)
                    values_for_field = values_for_field if isinstance(values_for_field, list) else [values_for_field]
                    original = values_for_field[index] if isinstance(index, int) and 0 <= index < len(values_for_field) else None
                entry_key = _key(
                    "world-entry", self.project_id, section_id, field, index,
                    source_entry.get("title"), source_entry.get("text"),
                )
                source_by_id[entry_key] = {
                    "field": field, "index": index, "owner": owner,
                    "title": text(source_entry.get("title")),
                    "text": text(source_entry.get("text")),
                    "raw": deepcopy(original),
                }
                display_entries.append({
                    "id": entry_key,
                    "title": text(source_entry.get("title")),
                    "text": text(source_entry.get("text")),
                    "editable": owner == "project",
                })
            section_authority = [authority, "world-section", section_id, baseline_fields, info.get("world_summary") if section_id == "background" else None]

            def save_world_section(values, *, section_id=section_id, field_group=field_group,
                                   baseline_fields=baseline_fields, source_by_id=source_by_id,
                                   expected_summary=info.get("world_summary")):
                submitted = values.get("entries")
                if not isinstance(submitted, list) or len(submitted) > 500:
                    raise ValueError("invalid_world_section")
                submitted_by_id = {}
                new_items = []
                for item in submitted:
                    if not isinstance(item, dict) or set(item) - {"id", "title", "text", "editable"}:
                        raise ValueError("invalid_world_section")
                    title_value, body_value = item.get("title"), item.get("text")
                    if not isinstance(title_value, str) or len(title_value) > 500:
                        raise ValueError("invalid_world_section")
                    if not isinstance(body_value, str) or len(body_value) > 10_000:
                        raise ValueError("invalid_world_section")
                    clean_item = {"title": title_value.strip(), "text": body_value.strip()}
                    entry_id = item.get("id")
                    if entry_id is None:
                        if not clean_item["title"] and not clean_item["text"]:
                            continue
                        new_items.append(clean_item)
                        continue
                    if not isinstance(entry_id, str) or entry_id not in source_by_id or entry_id in submitted_by_id:
                        raise ValueError("invalid_world_section")
                    original = source_by_id[entry_id]
                    if original["owner"] == "state" and clean_item != {"title": original["title"], "text": original["text"]}:
                        raise ValueError("confirmed_world_fact_read_only")
                    submitted_by_id[entry_id] = clean_item

                added_field = {
                    "rules": "world_rules", "locations": "locations", "factions": "factions",
                    "equipment": "equipment_cards", "monsters": "monster_cards",
                }.get(section_id)
                if new_items and section_id in {"equipment", "monsters"}:
                    raise ValueError("world_catalog_create_requires_structured_fields")
                if new_items and section_id == "background":
                    summary_additions = new_items
                else:
                    summary_additions = []

                with project_update_lock(store.root):
                    current_project = store.project()
                    current_blueprint = current_project.get("world_blueprint") if isinstance(current_project.get("world_blueprint"), dict) else {}
                    for field, expected_value in baseline_fields.items():
                        if current_blueprint.get(field) != expected_value:
                            raise ValueError("world_section_revision_conflict")
                    if section_id == "background" and text(current_project.get("world_summary")) != text(expected_summary):
                        raise ValueError("world_section_revision_conflict")

                    blueprint_patch = {}
                    summary_patch = None
                    for field in field_group:
                        field_sources = [
                            (entry_id, source)
                            for entry_id, source in source_by_id.items()
                            if source["owner"] == "project" and source["field"] == field
                        ]
                        if not field_sources:
                            continue
                        original_value = baseline_fields.get(field)
                        old_items = original_value if isinstance(original_value, list) else ([] if original_value is None else [original_value])
                        changes = {
                            source["index"]: (entry_id, submitted_by_id.get(entry_id))
                            for entry_id, source in field_sources
                        }
                        updated_items = []
                        for index, raw_item in enumerate(old_items):
                            change = changes.get(index)
                            if change is None:
                                updated_items.append(deepcopy(raw_item))
                                continue
                            entry_id, edited = change
                            if edited is None:
                                continue
                            updated_items.append(_world_section_item(
                                raw_item,
                                title=(edited["title"] or original["title"])
                                if section_id == "rules" else edited["title"],
                                body=edited["text"], section_id=section_id,
                            ))
                        if isinstance(original_value, list) or original_value is None:
                            blueprint_patch[field] = updated_items
                        elif not updated_items:
                            blueprint_patch[field] = {} if isinstance(original_value, dict) else ""
                        else:
                            blueprint_patch[field] = updated_items[0]

                    summary_source = next((
                        (entry_id, source) for entry_id, source in source_by_id.items()
                        if source["owner"] == "project" and source["field"] == "@project.world_summary"
                    ), None)
                    if summary_source is not None:
                        entry_id, source = summary_source
                        edited_summary = submitted_by_id.get(entry_id)
                        summary_patch = edited_summary["text"] if edited_summary is not None else ""
                    if summary_additions:
                        addition = "\n\n".join(item["text"] for item in summary_additions)
                        summary_patch = "\n\n".join(part for part in (text(summary_patch if summary_patch is not None else current_project.get("world_summary")), addition) if part)
                    if new_items and added_field:
                        baseline_added = baseline_fields.get(added_field)
                        if added_field in field_group and baseline_added is not None:
                            added_list = list(baseline_added) if isinstance(baseline_added, list) else [baseline_added]
                        else:
                            added_list = current_blueprint.get(added_field)
                            added_list = list(added_list) if isinstance(added_list, list) else ([] if added_list is None else [added_list])
                        added_list.extend(
                            item["text"] if section_id == "rules" else {"name": item["title"], "description": item["text"]}
                            for item in new_items
                        )
                        blueprint_patch[added_field] = added_list
                    patch = {}
                    if blueprint_patch:
                        patch["world_blueprint"] = blueprint_patch
                    if summary_patch is not None:
                        patch["world_summary"] = summary_patch
                    if patch:
                        store.update_project(patch)
                return {"message": "世界设定已保存。"}

            section_action = self.command(
                "world-section:" + section_id,
                "保存" + text(section.get("title")),
                section_authority,
                save_world_section,
                enabled=not busy,
            )
            world_section_views.append({
                "id": section_id,
                "title": text(section.get("title")),
                "entries": display_entries,
                "save": section_action,
            })
        result["worldSections"] = world_section_views
        if any(text(section.get("id")) in {"equipment", "monsters"} for section in content.get("worldSections", [])):
            equipment = blueprint.get("equipment_cards")
            monsters = blueprint.get("monster_profiles")
            if not isinstance(equipment, list):
                equipment = state.get("equipment_cards") if isinstance(state.get("equipment_cards"), list) else []
            if not isinstance(monsters, list):
                monsters = state.get("monster_profiles") if isinstance(state.get("monster_profiles"), list) else []
            result["worldCatalogs"] = {
                "equipment_cards": deepcopy(equipment),
                "monster_profiles": deepcopy(monsters),
            }

        normalized_project_id = workbench._strip_file_prefix(self.project_id)
        active_job_id = workbench._active_world_build_jobs.get(normalized_project_id)
        world_job = workbench._world_build_jobs.get(active_job_id) if active_job_id else None
        if world_job is None:
            persisted_job = store.snapshot_store.read_json(store.story_system_dir / "world-build-jobs" / "latest.json", {})
            world_job = persisted_job if isinstance(persisted_job, dict) else None
        raw_world_status = text((world_job or {}).get("status"))
        if raw_world_status in {"queued", "running"} and not active_job_id:
            raw_world_status = "interrupted"
        world_status = {
            "queued": ("等待补全", "世界观补全已排队。"),
            "running": ("正在补全", "世界观正在补全，当前设定仍可查看。"),
            "completed": ("补全完成", "世界观补全已完成，可检查并编辑设定。"),
            "interrupted": ("上次补全已中断", "上次补全未完成，现有设定仍保留。"),
            "conflicted": ("设定已有修改", "补全期间设定发生变化，已保留你的修改。"),
            "failed": ("上次补全未完成", "上次补全未完成，检查当前设定后可以重试。"),
        }.get(raw_world_status, ("尚未补全", "可以按需让 AI 补全世界观。"))
        world_build_active = raw_world_status in {"queued", "running"}

        def start_world_enrichment(values):
            self.call("start_file_project_world_build_job")
            return {"_product_response": {
                "statusLabel": "补全已开始",
                "message": "世界观补全已开始，现有设定仍保留；完成后请检查变更。",
            }}

        start_enrichment_action = self.command("enrich-world", "补全世界观", [authority, "world-enrichment", raw_world_status],
            start_world_enrichment, enabled=not busy and not world_build_active)
        result["worldEnrichment"] = {
            "statusLabel": world_status[0],
            "message": world_status[1],
            "canStart": start_enrichment_action["enabled"],
            "action": start_enrichment_action,
            "manualEditsRemainAuthoritative": True,
        }
        for number in store.chapter_numbers():
            data = store.snapshot_store.read_json(store.story_system_dir / "chapters" / f"{number:04d}.json", {})
            body = store.chapter(number).get("body", "") if number == selected else ""
            result["chapters"].append({"number": number, "title": data.get("chapter_title") or f"第 {number} 章", "body": body})
        if result["canRetry"]:
            result["notice"] = product.problem(job.get("error") or job.get("error_code"))["message"]

        def directions(values):
            return workbench.start_opening_direction_job(self.project_id, expected_source=source, guidance=text(values.get("text")))

        def choose(values):
            direction = next((d for d in setup.get("directions", []) if _key("direction", self.project_id, d.get("id")) == values.get("id")), None)
            if direction is None:
                raise ValueError("direction_not_found")
            with project_update_lock(store.root):
                if execution.source_fingerprint(store) != source or opening_content(store) != setup:
                    raise ValueError("candidate_source_changed")
                return self.call("select_opening_direction", direction_id=direction["id"])

        self.command("prepare-directions", "准备故事方向", authority, directions,
            enabled=not busy and confirmed == 0 and not setup.get("selected_id"))
        self.command("direction", "选择这个方向", [authority, setup], choose, enabled=not busy and confirmed == 0 and bool(setup.get("directions")))
        self.command("adopt", "采纳当前规划", authority,
            lambda values: lifecycle.accept_plan(store, plan["fingerprint"]), enabled=not busy and plan["ready"])
        self.command("generate", "生成候选" if confirmed == 0 else "继续写作", authority,
            lambda values: self.start_next(expected_plan=plan["fingerprint"]), enabled=not busy and not pending and plan["accepted"] and plan["ready"],
            reason=None if plan["accepted"] else "请先完成并采纳当前规划。")
        self.command("requirements", "保存作者要求", authority,
            lambda values: lifecycle.save_author_requirements(store, requirements=text(values.get("text")).splitlines(), expected_source=source), enabled=not busy)
        self.command("trash", "移入回收站", authority,
            lambda values: self.call("trash_file_project"), enabled=not busy)

        def save_plan(values, key):
            outline = deepcopy(store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {}))
            outline.setdefault("overall", {})[key] = text(values.get("text"))
            return lifecycle.save_future_plan(store, payload=outline, expected_source=source)

        edit_reason = "请在下方相应规划部分修改；已被正文采用的内容不能覆盖。" if runtime.enabled(store) else None
        self.command("future", "保存后续创作想法", authority,
            lambda values: lifecycle.save_future_intent(store, text(values.get("text")), expected_source=source), enabled=not busy)
        self.command("plan", "保存全书方向", authority, lambda values: save_plan(values, "story"),
            enabled=not busy and not runtime.enabled(store), reason=edit_reason)
        self.command("archive", "归档作品", authority, lambda values: self.call("archive_file_project"), enabled=not busy)

        blueprint = info.get("world_blueprint") if isinstance(info.get("world_blueprint"), dict) else {}
        selected_type = genre_id(info, state)
        selected_style = text(blueprint.get("writing_style") or blueprint.get("style"))
        type_options = _handler(self.request, "list_registered_novel_types")

        def save_book_type(values):
            next_type = text(values.get("novelTypeId"))
            allowed_types = {text(item.get("id")) for item in type_options if isinstance(item, dict)}
            if next_type and next_type not in allowed_types:
                raise ValueError("invalid_novel_type")
            with project_update_lock(store.root):
                current_project = store.project()
                current_state = store.state()
                if genre_id(current_project, current_state) != selected_type:
                    raise ValueError("revision_conflict")
                store.update_project({"world_blueprint": {"genre_plugin_ids": [next_type] if next_type else []}})
            return {"message": "作品类型已保存。"}

        def save_book_style(values):
            next_style = text(values.get("writingStyle"))
            if next_style and next_style not in BOOK_STYLE_OPTIONS:
                raise ValueError("invalid_writing_style")
            with project_update_lock(store.root):
                current_project = store.project()
                current_blueprint = current_project.get("world_blueprint") if isinstance(current_project.get("world_blueprint"), dict) else {}
                current_style = text(current_blueprint.get("writing_style") or current_blueprint.get("style"))
                if current_style != selected_style:
                    raise ValueError("revision_conflict")
                store.update_project({"world_blueprint": {"writing_style": next_style}})
            return {"message": "文风已保存。"}

        save_type_action = self.command("book-type", "保存作品类型", [authority, selected_type], save_book_type,
            enabled=not busy)
        save_style_action = self.command("book-style", "保存文风", [authority, selected_style], save_book_style,
            enabled=not busy)
        result["bookDetails"]["novelTypeOptions"] = [
            {"id": text(item.get("id")), "label": text(item.get("name"))}
            for item in type_options if isinstance(item, dict) and text(item.get("id"))
        ]
        publishing_assets = store.publishing_assets()
        synopsis_snapshot = publishing_assets.get("synopsis")
        cover_snapshot = publishing_assets.get("cover")
        synopsis_version = workbench._publishing_asset_version(synopsis_snapshot)
        cover_version = workbench._publishing_asset_version(cover_snapshot)
        title_snapshot = text(info.get("title"))

        def save_synopsis(values):
            try:
                payload = workbench.SynopsisUpdateRequest.model_validate({
                    "tags": values.get("tags"),
                    "body": values.get("body"),
                    "expected_version": synopsis_version,
                })
            except ValidationError as exc:
                raise HTTPException(status_code=422, detail="synopsis_invalid") from exc
            with project_update_lock(store.root):
                current = store.publishing_assets().get("synopsis")
                if current != synopsis_snapshot:
                    raise ValueError("publishing_asset_stale_synopsis")
                return _handler(
                    self.request,
                    "update_file_project_synopsis",
                    project_id=self.project_id,
                    payload=payload,
                )

        def generate_synopsis(values):
            with project_update_lock(store.root):
                if store.publishing_assets().get("synopsis") != synopsis_snapshot:
                    raise ValueError("publishing_asset_stale_synopsis")
            payload = workbench.PublishingGenerationRequest.model_validate({
                "guidance": values.get("guidance", ""),
                "expected_synopsis_version": synopsis_version,
            })
            return _handler(
                self.request,
                "generate_file_project_synopsis",
                project_id=self.project_id,
                payload=payload,
            )

        def generate_cover(values):
            with project_update_lock(store.root):
                if (
                    store.publishing_assets().get("cover") != cover_snapshot
                    or text(store.project().get("title")) != title_snapshot
                ):
                    raise ValueError("publishing_asset_stale_cover")
            payload = workbench.PublishingGenerationRequest.model_validate({
                "guidance": values.get("guidance", ""),
                "expected_cover_version": cover_version,
                "expected_cover_title": title_snapshot,
            })
            return _handler(
                self.request,
                "generate_file_project_cover",
                project_id=self.project_id,
                payload=payload,
            )

        result["bookDetails"]["synopsisStatusLabel"] = "已有简介" if text(synopsis_snapshot.get("body") if isinstance(synopsis_snapshot, dict) else "") else "尚无简介"
        result["bookDetails"]["coverStatusLabel"] = "封面已生成" if result["bookDetails"].get("coverAvailable") else "尚无封面"
        result["bookDetails"]["actions"] = {
            "saveType": save_type_action,
            "saveStyle": save_style_action,
            "saveSynopsis": self.command("synopsis-save", "保存作品简介", [authority, "synopsis", synopsis_version], save_synopsis, enabled=not busy),
            "generateSynopsis": self.command("synopsis-generate", "生成作品简介", [authority, "synopsis", synopsis_version], generate_synopsis, enabled=not busy),
            "generateCover": self.command("cover-generate", "生成作品封面", [authority, "cover", cover_version, title_snapshot], generate_cover, enabled=not busy),
        }

        raw_graph = info.get("relationship_graph") if isinstance(info.get("relationship_graph"), list) else []
        relationship_people = set()
        for card in [*(info.get("character_profiles") or []), *(state.get("characters") or [])]:
            if isinstance(card, dict) and text(card.get("name")):
                relationship_people.add(text(card.get("name")))
        relation_authority = [authority, "relationship-graph", raw_graph, sorted(relationship_people)]

        def pair_key(edge):
            return tuple(sorted((text(edge.get("source")), text(edge.get("target")))))

        def save_relationships(values):
            submitted = values.get("items")
            if not isinstance(submitted, list) or len(submitted) > 500:
                raise ValueError("invalid_relationship_graph")
            incoming_pairs = set()
            normalized = []
            previous_by_pair = {pair_key(edge): deepcopy(edge) for edge in raw_graph if isinstance(edge, dict)}
            for item in submitted:
                if not isinstance(item, dict):
                    raise ValueError("invalid_relationship_graph")
                source, target = text(item.get("source")), text(item.get("target"))
                pair = tuple(sorted((source, target)))
                if not source or not target or source == target or source not in relationship_people or target not in relationship_people or pair in incoming_pairs:
                    raise ValueError("invalid_relationship_graph_endpoint")
                incoming_pairs.add(pair)
                previous = previous_by_pair.get(pair)
                submitted_origin = text(item.get("origin"))
                if previous is not None and "origin" in item and submitted_origin != text(previous.get("origin")):
                    raise ValueError("relationship_origin_immutable")
                edge = deepcopy(previous) if previous is not None else {"source": source, "target": target}
                edge["source"], edge["target"] = source, target
                for key in ("relation_type", "current_state", "shared_interest_or_conflict"):
                    value = text(item.get(key))
                    if len(value) > 2000:
                        raise ValueError("invalid_relationship_graph")
                    edge[key] = value
                edge["bond"] = text(item.get("relation_type"))
                for key in ("trust", "tension"):
                    score = item.get(key)
                    if not isinstance(score, (int, float)) or isinstance(score, bool) or not 0 <= score <= 100:
                        raise ValueError("invalid_relationship_graph")
                    edge[key] = score
                if previous is None:
                    edge["origin"] = text(item.get("origin"))[:2000]
                    edge["first_chapter"] = 0
                    edge["last_changed_chapter"] = 0
                    edge["status"] = "active"
                normalized.append(edge)
            for pair, previous in previous_by_pair.items():
                if pair in incoming_pairs:
                    continue
                has_confirmed_history = bool(
                    int(previous.get("last_changed_chapter") or 0) > 0
                    or int(previous.get("first_chapter") or 0) > 0
                    or previous.get("changes")
                )
                if has_confirmed_history:
                    raise ValueError("confirmed_relationship_cannot_be_removed")
            with project_update_lock(store.root):
                current_project = store.project()
                current_graph = current_project.get("relationship_graph") if isinstance(current_project.get("relationship_graph"), list) else []
                current_people = set()
                current_state = store.state()
                for card in [*(current_project.get("character_profiles") or []), *(current_state.get("characters") or [])]:
                    if isinstance(card, dict) and text(card.get("name")):
                        current_people.add(text(card.get("name")))
                if current_graph != raw_graph or current_people != relationship_people:
                    raise ValueError("revision_conflict")
                store.update_project({"relationship_graph": normalized})
            return {"message": "人物关系已保存。"}

        relationship_action = self.command("relationships", "保存人物关系", relation_authority,
            save_relationships, enabled=not busy)
        result["relationshipView"] = {"items": content["relationships"], "save": relationship_action}

        ledger = store.foreshadowing_ledger()
        ledger_version = store.foreshadowing_version(ledger)
        confirmed_chapters = {number for number in store.chapter_numbers() if number <= confirmed}
        stale_state = store.snapshot_store.read_json(store.story_system_dir / "continuity" / "stale.json", {}) or {}
        unavailable_chapters = set(number for number in stale_state.get("chapters", []) if isinstance(number, int))
        valid_chapters = confirmed_chapters - unavailable_chapters

        def save_foreshadowing(values):
            submitted = values.get("items")
            if not isinstance(submitted, list) or len(submitted) > 500:
                raise ValueError("invalid_foreshadowing_ledger")
            status_by_label = {"待回应": "open", "已强化": "reinforced", "已回收": "resolved", "已过期": "expired"}
            parsed = []
            for item in submitted:
                if not isinstance(item, dict):
                    raise ValueError("invalid_foreshadowing_ledger")
                status = status_by_label.get(text(item.get("statusLabel")))
                if status is None:
                    raise ValueError("invalid_foreshadowing_status")
                parsed.append(workbench.ForeshadowingLedgerItemRequest.model_validate({
                    "text": item.get("text"),
                    "first_chapter": 0 if item.get("firstChapter") is None else item.get("firstChapter"),
                    "last_touched_chapter": item.get("lastTouchedChapter"),
                    "status": status,
                    "payoff_plan": item.get("payoffPlan", ""),
                    "resolved_chapter": item.get("resolvedChapter"),
                }))
            referenced = {
                chapter for item in parsed for chapter in
                (item.first_chapter, item.last_touched_chapter, item.resolved_chapter)
                if isinstance(chapter, int) and chapter > 0
            }
            if not referenced.issubset(valid_chapters):
                raise ValueError("foreshadowing_chapter_source_unavailable")
            with project_update_lock(store.root):
                current_ledger = store.foreshadowing_ledger()
                if store.foreshadowing_version(current_ledger) != ledger_version:
                    raise ValueError("foreshadowing_version_conflict")
                store.update_foreshadowing_ledger(
                    [item.to_domain() for item in parsed], expected_version=ledger_version
                )
            return {"message": "伏笔已保存。"}

        foreshadowing_action = self.command("foreshadowing", "保存伏笔", [authority, "foreshadowing", ledger_version],
            save_foreshadowing, enabled=not busy)
        result["foreshadowingView"] = {
            "items": [
                {"key": _key("foreshadow", self.project_id, item.get("text")), **item}
                for item in content["foreshadowing"]
            ],
            "save": foreshadowing_action,
        }

        source_labels = {
            "global_default": "全局默认", "global_override": "全局设置", "project_override": "本书设置",
        }
        stage_labels = {"planning": "规划", "writing": "写作", "revision": "改稿"}
        applicability_labels = {"all": "适用于全部题材", "game_only": "仅适用于网游", "non_game_only": "适用于非网游"}
        placeholder_labels = {
            "chapter_number": "章节序号", "chapter_phase": "章节阶段", "project_snapshot": "作品背景",
            "chapter_seed": "本章连续性材料", "character_cards": "相关人物", "active_characters": "活跃人物",
            "output_section": "输出格式", "chapter_direction": "章节安排", "chapter_facts": "已确认事实",
            "character_context": "人物信息", "prose_method": "行文要求", "body_prompt": "正文写作要求",
            "revision_instructions": "本次修改要求", "source_body": "待修改正文", "target_chars": "目标篇幅",
            "expansion_focus": "扩写重点", "opening_line": "开头句", "compression_method": "压缩方法",
            "chapter_scope": "章节范围", "polish_focus": "润色重点",
        }
        global_templates = {item.key: item for item in load_global_prompt_templates()}
        template_views = []
        for template in store.prompt_templates():
            key = text(template.get("key"))
            global_template = global_templates.get(key)
            if not key or global_template is None:
                continue
            template_id = _key("template", self.project_id, key)
            effective_version = text(template.get("version"))
            global_version = global_template.version
            template_authority = [authority, "template", template_id, effective_version, global_version]
            save_project_type = f"template-project-{template_id}"
            save_global_type = f"template-global-{template_id}"
            restore_type = f"template-restore-{template_id}"
            check_type = f"template-check-{template_id}"
            deep_check_type = f"template-deep-check-{template_id}"

            def save_template_to_project(values, key=key, version=effective_version):
                content_value = values.get("content")
                if not isinstance(content_value, str) or not content_value.strip():
                    raise ValueError("content_required")
                if len(content_value) > 100_000:
                    raise ValueError("prompt_template_content_too_long")
                return store.set_prompt_template_override(key, content_value, expected_version=version)

            def save_template_globally(values, key=key, version=global_version):
                if values.get("confirm") is not True:
                    raise ValueError("global_prompt_confirmation_required")
                content_value = values.get("content")
                if not isinstance(content_value, str) or not content_value.strip():
                    raise ValueError("content_required")
                if len(content_value) > 100_000:
                    raise ValueError("prompt_template_content_too_long")
                save_global_prompt_template(key, content_value, expected_version=version)
                return {"message": "全局模板已更新；使用全局模板的其他作品会受到影响。"}

            def restore_template_to_global(values, key=key, version=effective_version):
                if values.get("confirm") is not True:
                    raise ValueError("prompt_template_restore_confirmation_required")
                return store.delete_prompt_template_override(key, expected_version=version)

            def check_template(values, key=key, variables=tuple(template.get("required_variables") or []), template_id=template_id):
                content_value = values.get("content")
                if not isinstance(content_value, str):
                    raise ValueError("content_required")
                from apps.api.routes.prompt_audit import PromptAuditRequest

                report = _handler(self.request, "run_prompt_audit", payload=PromptAuditRequest(
                    mode="template", content=content_value, template_key=key, required_variables=list(variables)
                ))
                binding = _key("prompt-audit", self.project_id, template_id, content_value)
                return {"_product_response": product.prompt_audit_result(report, binding_token=binding)}

            def deep_check_template(values, key=key, variables=tuple(template.get("required_variables") or []), template_id=template_id):
                content_value = values.get("content")
                if not isinstance(content_value, str):
                    raise ValueError("content_required")
                from apps.api.routes.prompt_audit import PromptAuditRequest, DeepPromptAuditRequest

                local_result = _handler(self.request, "run_prompt_audit", payload=PromptAuditRequest(
                    mode="template", content=content_value, template_key=key, required_variables=list(variables)
                ))
                report = _handler(self.request, "run_deep_prompt_audit", payload=DeepPromptAuditRequest(
                    mode="template", content=content_value, template_key=key,
                    required_variables=list(variables), local_result=local_result,
                ))
                binding = _key("prompt-audit", self.project_id, template_id, content_value)
                return {"_product_response": product.prompt_audit_result(report, binding_token=binding)}

            project_action = self.command(save_project_type, "保存为本书设置", template_authority,
                save_template_to_project, enabled=not busy)
            global_action = self.command(save_global_type, "更新全局模板", template_authority,
                save_template_globally, enabled=not busy)
            global_action["requiresConfirmation"] = True
            restore_action = None
            if template.get("source") == "project_override":
                restore_action = self.command(restore_type, "恢复使用全局模板", template_authority,
                    restore_template_to_global, enabled=not busy)
                restore_action["requiresConfirmation"] = True
            check_action = self.command(check_type, "普通检查", template_authority, check_template, enabled=not busy)
            deep_action = self.command(deep_check_type, "深度检查", template_authority, deep_check_template, enabled=not busy)
            template_views.append({
                "id": template_id,
                "title": text(template.get("title")),
                "purpose": stage_labels.get(text(template.get("stage")), "写作模板"),
                "applicabilityLabel": applicability_labels.get(text(template.get("applicability")), "适用范围待检查"),
                "activeForBook": bool(template.get("active_for_project", True)),
                "content": text(template.get("content")),
                "placeholders": [
                    {"syntax": "{{" + str(variable) + "}}", "label": placeholder_labels.get(str(variable), "模板变量")}
                    for variable in template.get("required_variables", []) if isinstance(variable, str)
                ],
                "sourceLabel": source_labels.get(text(template.get("source")), "模板来源"),
                "usesBookOverride": template.get("source") == "project_override",
                "actions": {
                    "saveProject": project_action,
                    "saveGlobal": global_action,
                    "restoreGlobal": restore_action,
                    "check": check_action,
                    "deepCheck": deep_action,
                },
            })
        result["writingTemplatesView"] = {"templates": template_views}

        packs = list_skill_packs()
        installed_by_id = {pack.skill_id: pack for pack in packs}
        selected_pack_ids = resolve_enabled_skill_ids(info, state)
        selected_module_ids = resolve_enabled_skill_module_ids(info, state)
        legacy_all_modules = selected_module_ids is None
        enabled_modules = set(selected_module_ids or [])
        known_pack_ids = set(installed_by_id)
        unknown_selected = [item for item in selected_pack_ids if item not in known_pack_ids]
        ability_packs = []
        for pack in packs:
            included = pack.skill_id in selected_pack_ids
            ability_packs.append({
                "id": pack.skill_id,
                "name": pack.name,
                "description": pack.description,
                "available": True,
                "selected": included,
                "modules": [
                    {
                        "id": "root",
                        "title": "根写作能力",
                        "purpose": "包的总入口说明",
                        "selected": included and (legacy_all_modules or f"{pack.skill_id}::root" in enabled_modules),
                    },
                    *[
                        {
                            "id": module.module_id,
                            "title": module.title,
                            "purpose": module.description or module.summary or "写作辅助",
                            "selected": included and (legacy_all_modules or f"{pack.skill_id}::{module.module_id}" in enabled_modules),
                        }
                        for module in pack.modules
                    ],
                ],
            })
        for missing_id in unknown_selected:
            ability_packs.append({"id": missing_id, "name": "能力包已不可用", "description": "请重新选择可用能力。", "available": False, "selected": True, "modules": []})
        ability_authority = [authority, selected_pack_ids, selected_module_ids, sorted(known_pack_ids)]

        def save_writing_abilities(values):
            next_pack_ids = values.get("packIds")
            next_module_ids = values.get("moduleIds")
            if not isinstance(next_pack_ids, list) or not isinstance(next_module_ids, list):
                raise ValueError("invalid_skill_selection")
            if any(not isinstance(item, str) for item in [*next_pack_ids, *next_module_ids]):
                raise ValueError("invalid_skill_selection")
            next_pack_ids = list(dict.fromkeys(item.strip() for item in next_pack_ids if item.strip()))
            next_module_ids = list(dict.fromkeys(item.strip() for item in next_module_ids if item.strip()))
            with project_update_lock(store.root):
                current_project, current_state = store.project(), store.state()
                if (resolve_enabled_skill_ids(current_project, current_state) != selected_pack_ids
                    or resolve_enabled_skill_module_ids(current_project, current_state) != selected_module_ids):
                    raise ValueError("revision_conflict")
                current_packs = {pack.skill_id: pack for pack in list_skill_packs()}
                if any(skill_id not in current_packs for skill_id in next_pack_ids):
                    raise ValueError("skill_selection_pack_unavailable")
                module_pack_ids = {
                    module_id: skill_id
                    for skill_id, pack in current_packs.items()
                    for module_id in [
                        f"{skill_id}::root",
                        *(f"{skill_id}::{module.module_id}" for module in pack.modules),
                    ]
                }
                if not set(next_module_ids).issubset(module_pack_ids):
                    raise ValueError("skill_selection_module_unavailable")
                derived_pack_ids = list(dict.fromkeys(module_pack_ids[module_id] for module_id in next_module_ids))
                if next_pack_ids != derived_pack_ids:
                    raise ValueError("skill_selection_pack_module_mismatch")
                store.update_project({
                    "enabled_skill_ids": next_pack_ids,
                    "enabled_skill_module_ids": next_module_ids,
                })
            return {"message": "本书写作能力已保存。"}

        ability_save = self.command("writing-abilities", "保存本书写作能力",
            ability_authority, save_writing_abilities, enabled=not busy)
        result["writingAbilitiesView"] = {
            "packs": ability_packs,
            "selectionModeLabel": "旧项目默认启用包内全部模块" if legacy_all_modules else "按模块选择",
            "save": ability_save,
            "managementLabel": "管理写作能力库",
        }

        selected_chapter_row = next((item for item in result["chapters"] if item["number"] == selected), None)
        selected_body = text(selected_chapter_row.get("body")) if selected_chapter_row else ""
        can_inspect_chapter = bool(selected_chapter_row and 0 < selected <= confirmed and selected_body)

        def inspect_project_chapter(values):
            current = store.chapter(selected)
            if text(current.get("body")) != selected_body or int(store.state().get("current_chapter") or 0) < selected:
                raise ValueError("dissection_source_changed")
            report = _handler(self.request, "dissect_file_project_chapter", project_id=self.project_id,
                payload=workbench.BookDissectionChapterRequest(chapter_number=selected, body=selected_body))
            return {"_product_response": {
                "modeLabel": "本书章节体检",
                "sourceChapter": selected,
                "sourceToken": _key("dissection-source", self.project_id, selected, selected_body, source),
                "report": product.book_dissection_result(report),
            }}

        def inspect_reference(values):
            reference_text = values.get("text")
            if not isinstance(reference_text, str) or not reference_text.strip():
                raise ValueError("text_required")
            if len(reference_text) > 50_000:
                raise ValueError("text_too_long")
            report = _handler(self.request, "dissect_book_reference",
                payload=workbench.BookDissectionReferenceRequest(
                    text=reference_text,
                    genre=text(values.get("genre")),
                    focus=text(values.get("focus")),
                ))
            return {"_product_response": {
                "modeLabel": "参考书拆解",
                "sourceToken": _key("reference-dissection", self.project_id, reference_text),
                "report": product.book_dissection_result(report),
            }}

        inspect_action = self.command("dissection-chapter", "体检当前确认章节",
            [authority, selected, _key("chapter-body", self.project_id, selected_body)],
            inspect_project_chapter, enabled=not busy and can_inspect_chapter,
            reason=None if can_inspect_chapter else "选择一章已确认且正文可用的章节后再体检。")
        reference_action = self.command("dissection-reference", "拆解参考书片段",
            [authority, "reference-dissection"], inspect_reference, enabled=not busy)
        result["dissectionView"] = {
            "modeLabel": "本书章节体检",
            "selectedChapter": selected if selected_chapter_row else None,
            "statusLabel": "尚未生成报告",
            "report": None,
            "actions": {"inspectChapter": inspect_action, "inspectReference": reference_action},
            "reportIsReadOnly": True,
        }

        if not pending:
            last = next((c for c in store.candidate_store.list() if c.project_id in accepted_ids
                         and c.status == "confirmed" and c.chapter_number == confirmed), None)
            intent = lifecycle.continuation_state(store, last.candidate_id) if last else None
            next_job = self.continuation_jobs.get(intent.get("job_id")) if intent else None
            interrupted = intent and (intent.get("state") in {"failed", "launching"}
                or (next_job or {}).get("status") in {"failed", "interrupted", "conflicted"}
                or intent.get("state") in {"queued", "running"} and not next_job)
            if interrupted:
                result["notice"] = "本章已保存，下一章尚未开始。完成规划后可以继续。"
                self.command("retry-next", "继续准备下一章", [authority, intent],
                    lambda values: lifecycle.confirm_and_continue(store, last.candidate_id, expected_candidate=None,
                        accept_quality_warnings=False, start_next=self.start_next, retry=True,
                        read_job=lambda job_id: workbench.read_file_generation_job_state(store, job_id)),
                    enabled=not busy and plan["accepted"] and plan["ready"])

        if candidate:
            review, issues, blocked, warning = product.candidate_review(candidate, store=store)
            if runtime.enabled(store):
                try:
                    execution.verify(store, candidate.submission_payload.get("opening_authority"))
                except ValueError as exc:
                    blocked = True
                    issues = [product.problem(exc), *issues]
            expected = candidate_authority(candidate)
            ref = [authority, expected]
            editable = candidate.operation == "generate" and candidate.chapter_number == confirmed + 1
            needs_check = bool(candidate.review_binding) and candidate.review_binding.get("state") != "checked"
            try:
                assert_review_current(store, candidate)
            except ValueError:
                needs_check = True
            result["candidate"] = {"key": _key("candidate", candidate.candidate_id), "number": candidate.chapter_number,
                "title": candidate.chapter_title, "body": candidate.body, "label": review["message"],
                "needsCheck": needs_check, "checking": busy and job.get("operation") in {"candidate_review", "candidate_revise"},
                "canConfirm": not busy and not blocked and not warning, "canAcceptSuggestion": not busy and not blocked and warning,
                "concerns": issues, "concern": issues[0] if issues else None, "pastDrafts": []}
            for entry in candidate.revision_history[-20:]:
                old_id = entry.get("candidate_id") if isinstance(entry, dict) else entry
                if not isinstance(old_id, str) or not re.fullmatch(r"cd-[a-f0-9]+", old_id):
                    continue
                old = store.candidate_store.get(old_id)
                if old and old.project_id in accepted_ids:
                    result["candidate"]["pastDrafts"].append({"body": old.body, "label": "先前保存的稿件"})
            self.command("save-draft", "保存改稿", ref,
                lambda values: save_edit(store, candidate.candidate_id, body=text(values.get("text")), expected=expected, expected_source=source), enabled=editable and not busy)
            self.command("review", "重新检查", ref,
                lambda values: workbench.start_candidate_review_job(self.project_id, candidate.candidate_id, expected=expected), enabled=editable and not busy)
            self.command("ai-edit", "让 AI 修改", ref,
                lambda values: workbench.start_candidate_review_job(self.project_id, candidate.candidate_id, expected=expected, guidance=text(values.get("instruction"))), enabled=editable and not busy)
            self.command("discard", "放弃当前候选", ref,
                lambda values: self.call("discard_file_project_candidate", candidate_id=candidate.candidate_id), enabled=not busy)
            def confirm(values, allow_warning=False):
                workbench._assert_candidate_mutation_allowed(store)
                if values.get("continue") is True:
                    return lifecycle.confirm_and_continue(store, candidate.candidate_id, expected_candidate=expected,
                        accept_quality_warnings=allow_warning, start_next=self.start_next,
                        read_job=lambda job_id: workbench.read_file_generation_job_state(store, job_id))
                with project_update_lock(store.root):
                    current = store.candidate_store.get(candidate.candidate_id)
                    if current is None or candidate_authority(current) != expected:
                        raise ValueError("candidate_revision_conflict")
                    lifecycle.require_accepted_plan(store)
                    # Final body/check/source admission and the confirmation
                    # transaction share the lock. There is no model call here.
                    return store.confirm_candidate(candidate.candidate_id, accept_quality_warnings=allow_warning)
            self.command("confirm", "确认本章", ref, confirm, enabled=not busy and not blocked and not warning)
            self.command("accept-suggestion", "保留原文并确认本章（接受提醒）", ref,
                lambda values: confirm(values, True), enabled=not busy and not blocked and warning)

        # Reuse each existing build callback, including its commit-time protections.
        build = self.build_screen
        with project_update_lock(store.root):
            planning = build.build(all_actions=True)
        if planning.get("refresh_after_ms"):
            result["busy"] = True
            result["notice"] = "正在准备故事规划。"
        known = {"开始准备故事": "prepare-plan", "更新创作想法": "sync-plan", "生成规划": "prepare-plan",
                 "更新受影响的内容": "refresh-plan", "继续下一部分": "continue-plan", "规划下一卷": "next-volume", "完善本卷规划": "complete-volume"}
        for action in planning.get("actions", []):
            name = known.get(action["label"])
            if name and action.get("token") in build.actions:
                self.command(name, action["label"], [authority, action["token"]], build.actions[action["token"]], enabled=action["enabled"] and not busy)
                if name == "next-volume":
                    result["nextVolume"] = action["enabled"]
        if result["busy"]:
            for action in self.commands.values():
                action["enabled"] = False
                action["reason"] = "请等待当前创作完成。"
        result["actions"] = self.commands
        return result


def _workspace(request, book_id=None, chapter=None):
    books = []
    recycle_bin = []
    selected = None
    genres = _handler(request, "list_registered_novel_types")
    genre_names = {g["id"]: g["name"] for g in genres}
    for store in workbench._stores(lifecycle="active"):
        project_id = workbench._public_project_id(store)
        screen = AuthorScreen(request, project_id)
        screen.prepare()
        with project_update_lock(store.root):
            book = screen.view(chapter if project_id == book_id else None)
        book["genre"] = genre_names.get(book["genre"], "未设置")
        book["lifecycleLabel"] = "创作中"
        for rule in book.get("world", []):
            # Legacy seed facts contain the machine genre ID. Translate that
            # exact system-created sentence without changing authored prose.
            for genre, label in genre_names.items():
                if rule.get("text") == f"小说类型：{genre}":
                    rule["text"] = f"小说类型：{label}"
                    break
        books.append(book)
        if project_id == book_id or selected is None and book_id is None:
            selected = screen
    for store in workbench._stores(lifecycle="archived"):
        info = store.project()
        project_id = workbench._public_project_id(store)
        token = _key("restore", project_id, info)
        books.append({"id": project_id, "title": text(info.get("title")), "genre": genre_names.get(genre_id(info), "未设置"),
                      "idea": "", "requirements": "", "future": "", "plan": "", "planAdopted": False,
                      "planningVolume": 1, "chapters": [], "archived": True, "notice": "作品已归档。", "busy": False,
                      "bookDetails": book_details(store), "lifecycleLabel": "已归档",
                      "canRetry": False, "nextVolume": False, "actions": {"archive": {"token": token, "label": "恢复作品", "enabled": True}}})
    for store in workbench._stores(lifecycle="trashed"):
        info = store.project()
        project_id = workbench._public_project_id(store)
        recycle_bin.append({
            "id": project_id,
            "title": text(info.get("title")) or "未命名作品",
            "bookDetails": book_details(store),
            "actions": {
                "restore-trashed": {"token": _key("restore-trashed", project_id, info), "label": "恢复作品", "enabled": True},
                "delete-trashed": {"token": _key("delete-trashed", project_id, info), "label": "彻底删除", "enabled": True, "requiresFullTitle": True},
            },
        })
    return {"books": books, "bookId": book_id or (selected.project_id if selected else ""), "page": "books", "selectedChapter": chapter,
            "recycleBin": recycle_bin,
            "showNew": False, "storyTab": "人物", "person": "", "storageWarning": "",
            "genres": [{"value": g["id"], "label": g["name"]} for g in genres],
            "actions": {"create": {"token": _key("create-author-book"), "label": "开始创作", "enabled": True}},
            "links": {"settings": "/config", "import": "/projects?import=1"}}, selected


def init_longform_product_routes():
    router = APIRouter(route_class=ProductRoute)

    @router.get("/author-workspace")
    def author_workspace(request: Request, book_id: str | None = None, chapter: int | None = None):
        return _workspace(request, book_id, chapter)[0]

    @router.post("/author-workspace/commands")
    def author_command(request: Request, body: CommandRequest):
        command = body.command
        name = command.get("type")
        if name == "create":
            if body.token != _key("create-author-book"):
                raise HTTPException(409, "product_action_revision_expired")
            result = _handler(request, "create_new_file_project", payload=FileProjectCreateSpec(
                mode="inspiration", title=text(command.get("title")), novel_type_id=text(command.get("genre")), idea=text(command.get("idea")),
                target_words=command.get("targetWords", 900000), target_chapter_words=command.get("chapterWords", 3000),
                author_constraints=text(command.get("requirements")).splitlines()))
            return {"bookId": result["project_id"], "message": "作品已创建，请准备故事方向。"}
        if not body.bookId:
            raise HTTPException(422, "project_not_found")
        if name in {"restore-trashed", "delete-trashed"}:
            store = workbench._trashed_store_for(body.bookId)
            info = store.project()
            action_name = "restore-trashed" if name == "restore-trashed" else "delete-trashed"
            if body.token != _key(action_name, body.bookId, info):
                raise HTTPException(409, "product_action_revision_expired")
            if name == "restore-trashed":
                _handler(request, "restore_file_project", project_id=body.bookId)
                return {"bookId": body.bookId, "message": "作品已恢复。"}
            _handler(request, "delete_file_project", project_id=body.bookId,
                confirm_title=text(command.get("confirmTitle")))
            return {"bookId": body.bookId, "message": "作品已彻底删除。"}
        if name == "trash" and command.get("confirm") is not True:
            raise HTTPException(422, "trash_confirmation_required")
        if name == "archive" and command.get("archived") is False:
            store = workbench._store_for(body.bookId)
            if store.project().get("project_lifecycle") != "archived":
                raise HTTPException(409, "product_action_revision_expired")
            if body.token != _key("restore", body.bookId, store.project()):
                raise HTTPException(409, "product_action_revision_expired")
            _handler(request, "restore_file_project", project_id=body.bookId)
            return {"bookId": body.bookId, "message": "作品已恢复。"}
        screen = AuthorScreen(request, body.bookId)
        screen.prepare()
        with project_update_lock(screen.store.root):
            screen.view()
            action = screen.commands.get(name)
            if not action or not action["enabled"] or action["token"] != body.token:
                raise HTTPException(409, "product_action_revision_expired")
            callback = screen.actions[body.token]
        result = callback(command)
        message = "已保存。"
        if isinstance(result, dict) and isinstance(result.get("next"), dict):
            message = result["next"].get("message") or message
        response = {"bookId": body.bookId, "message": message}
        if isinstance(result, dict) and isinstance(result.get("_product_response"), dict):
            response["product"] = result["_product_response"]
        return response

    return router
