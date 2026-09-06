from __future__ import annotations

from copy import deepcopy
import json
import re
from types import SimpleNamespace
from typing import Any, Callable

from pydantic import ValidationError

from packages.story_core.character_profiles import is_non_character_card
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.generation_quality import (
    chapter_outline_title as _chapter_outline_title,
    is_regeneration_continuity_failure as _is_regeneration_continuity_failure,
    promote_downstream_rewrite_status as _promote_downstream_rewrite_status,
    regeneration_quality_blocking as _regeneration_quality_blocking,
)
from packages.story_core.models import StoryState
from packages.story_core.outline_planning import CHAPTER_SOP_MODULE_ID
from packages.story_core.persistence.project_locking import (
    with_project_update_lock as _with_project_update_lock,
)
from packages.story_core.prompt_call_log import prompt_call_recording
from packages.story_core.prompt_templates import prompt_template_scope
from packages.story_core.quality import validate_bundle
from packages.story_core.skill_packs import (
    resolve_enabled_skill_ids,
    resolve_enabled_skill_module_ids,
)


class ChapterGenerationWorkflowMixin:
    def _commit_generated_bundle_canon(self, bundle: Any) -> dict[str, int]:
        """Commit the continuity delta of a directly persisted chapter.

        Candidate confirmation already applies this delta. The normal
        ``生成下一章`` path persists immediately, so it needs the same canon
        update after the chapter files have been written successfully.
        """
        from packages.story_core.continuity.delta import ContinuityDelta

        raw_delta = getattr(bundle, "continuity_delta", None)
        if raw_delta is None:
            return {}
        delta = (
            raw_delta
            if isinstance(raw_delta, ContinuityDelta)
            else ContinuityDelta.model_validate(raw_delta)
        )
        candidate_like = SimpleNamespace(continuity_delta=delta)
        counts = self._apply_candidate_canon_delta(candidate_like)
        self._sync_candidate_character_additions(candidate_like)
        return counts

    def _generation_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Reconcile accepted chapter bodies before planning another chapter."""

        reconciled = deepcopy(state)
        current_chapter = int(reconciled.get("current_chapter") or 0)
        for chapter_number in self.chapter_numbers():
            if current_chapter and chapter_number > current_chapter:
                break
            chapter_path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            chapter = self._read_json(chapter_path, {}) or {}
            if isinstance(chapter, dict) and str(chapter.get("body") or "").strip():
                self._sync_ledger_from_chapter_body(reconciled, deepcopy(chapter))
        return reconciled

    def _generation_state_for_target(
        self,
        current_state: dict[str, Any],
        target_chapter: int,
    ) -> dict[str, Any]:
        """Build the same chapter-start state for generation and prompt previews."""

        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        saved_current_chapter = max(latest_number, int(current_state.get("current_chapter") or 0))
        if target_chapter > saved_current_chapter:
            return self._generation_state(current_state)
        if target_chapter > 1:
            state = self._regeneration_base_state(target_chapter, current_state)
        else:
            state = self._conservative_regeneration_state(current_state)
        state["current_chapter"] = target_chapter - 1
        return state

    def generate_next_chapter(
        self,
        engine: Any | None = None,
        *,
        chapter_direction_id: str | None = None,
        commit_message: str | None = None,
        persist: bool = True,
        accept_quality_warnings: bool = False,
    ) -> dict[str, Any]:
        from packages.story_core.engine import StoryEngine

        state = self._generation_state(self.state())
        project = self.project()
        target_chapter = int(state.get("current_chapter") or 0) + 1
        self.require_volume_detail_for_prose(target_chapter)
        outline_status = self.rolling_fill_status(target_chapter)
        if outline_status.get("status") not in {"present", "legacy"}:
            raise ValueError(f"chapter_outline_required:{target_chapter}")
        chapter_direction = self._resolve_chapter_direction(state, project, target_chapter, chapter_direction_id)
        if chapter_direction:
            state = dict(state)
            ledger = dict(state.get("progression_ledger") or {})
            ledger["chapter_direction"] = chapter_direction
            state["progression_ledger"] = ledger
        story = StoryState.model_validate(self._story_state_payload_for_direction(state, project, target_chapter))
        # The workbench path: every project lives on disk under
        # ``self.root`` so the new modular pipeline can read
        # the legacy ``.webnovel/`` shape through
        # ``context.legacy_adapter``. The engine is constructed
        # per-call with ``use_modular_agents=True`` so the
        # Director / Writer / FactExtractor agents drive the
        # body generation; the legacy review / revision
        # controller is intentionally skipped because the new
        # pipeline's ``FocusedConsistencyAgent`` already surfaces
        # the deterministic contradictions during the writer
        # stage, and the user's confirmation gate is the final
        # safety net. The orchestrator's stored ``project_root``
        # is what the new pipeline reads, so the call site
        # does not need to forward ``project_root`` again —
        # keeping the call signature stable so existing
        # ``FakeEngine`` test doubles keep working.
        generator = engine or StoryEngine(
            use_modular_agents=True, project_root=self.root
        )
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source), prompt_call_recording(
            self.prompt_call_log()
        ):
            bundle = generator.generate_next_chapter(story)
        if not persist:
            project_id = str(
                project.get("project_id")
                or project.get("active_story_id")
                or state.get("story_id")
                or self.root.name
            )
            candidate = self._save_candidate_from_bundle(bundle, project_id=project_id)
            return {
                "schema_version": "file-project-candidate/v1",
                "root": str(self.root),
                "chapter_number": candidate.chapter_number,
                "chapter_title": candidate.chapter_title,
                "candidate": candidate.to_dict(),
            }
        persisted = self.persist_bundle(
            bundle,
            operation="generate",
            commit_message=commit_message,
            accept_quality_warnings=accept_quality_warnings,
        )
        persisted["canon_updates"] = self._commit_generated_bundle_canon(bundle)
        return {
            "schema_version": "file-project-generate-next/v1",
            "root": str(self.root),
            "chapter_number": persisted["chapter_number"],
            "chapter_title": persisted["chapter_title"],
            "chapter_direction": chapter_direction,
            "persisted": persisted,
        }

    @_with_project_update_lock
    def polish_chapter(
        self,
        chapter_number: int,
        *,
        orchestrator: Any | None = None,
    ) -> dict[str, Any]:
        """Adaptively polish one confirmed chapter into a pending candidate."""

        from packages.story_core.genre_stages.length_prompts import expansion_ending_anchor
        from packages.story_core.orchestrator import (
            MAX_CHAPTER_CHARS,
            MIN_CHAPTER_CHARS,
            StoryOrchestrator,
            _chapter_char_count,
            _chapter_polish_mode,
            _compressed_body_is_progress,
            _expanded_body_is_progress,
            _expansion_target_range,
            _postprocess_chapter_output,
            _render_compression_length_prompt,
            _render_expansion_length_prompt,
            _render_polish_length_prompt,
        )

        if chapter_number < 1:
            raise ValueError("chapter_number_must_be_positive")
        chapter = self.chapter(chapter_number)
        source_body = str(chapter.get("body") or "")
        if not source_body.strip():
            raise ValueError("chapter_body_required")

        current_state = dict(self.state())
        project = self.project()
        story = StoryState.model_validate(
            self._story_state_payload_for_direction(current_state, project, chapter_number)
        )
        event_plan = chapter.get("event_plan") if isinstance(chapter.get("event_plan"), dict) else {}
        world_facts = [str(item) for item in (story.world_facts or []) if str(item).strip()]
        source_chars = _chapter_char_count(source_body)
        mode = _chapter_polish_mode(source_body)
        allowed_polish_delta = max(300, source_chars // 10)
        if mode == "expand":
            target_min, target_max = _expansion_target_range(source_chars)
            prompt = _render_expansion_length_prompt(
                story,
                source_body=source_body,
                chapter_number=chapter_number,
                event_plan=event_plan,
                world_facts=world_facts,
                source_chars_override=source_chars,
            )
            max_tokens = min(6200, target_max + 300)
        elif mode == "shorten":
            target_min, target_max = MIN_CHAPTER_CHARS, MAX_CHAPTER_CHARS
            prompt = _render_compression_length_prompt(
                story,
                source_body=source_body,
                chapter_number=chapter_number,
                event_plan=event_plan,
                world_facts=world_facts,
                outline_anchor=(chapter.get("chapter_seed") or {}).get("outline_anchor")
                if isinstance(chapter.get("chapter_seed"), dict)
                else None,
                target_chars=f"调整到{target_min}到{target_max}字",
            )
            max_tokens = min(6200, source_chars + 300)
        else:
            target_min = max(MIN_CHAPTER_CHARS, source_chars - allowed_polish_delta)
            target_max = min(MAX_CHAPTER_CHARS, source_chars + allowed_polish_delta)
            prompt = _render_polish_length_prompt(
                story,
                source_body=source_body,
                chapter_number=chapter_number,
                event_plan=event_plan,
                world_facts=world_facts,
            )
            max_tokens = min(6200, source_chars + 500)

        runner = orchestrator or StoryOrchestrator(project_root=self.root)
        mode_label = {
            "expand": "自动扩写",
            "shorten": "自动缩短",
            "polish": "表达润色",
        }[mode]
        report_generation_progress(
            {
                "message": f"第{chapter_number}章润色：已选择{mode_label}",
                "status": "running",
                "stage": "revision",
                "source": "writer",
                "artifact": {
                    "reason": "adaptive_chapter_polish",
                    "inputs": {"chapter_number": chapter_number, "before_chars": source_chars},
                    "outputs": {
                        "polish_mode": mode,
                        "polish_mode_label": mode_label,
                        "target_min_chars": target_min,
                        "target_max_chars": target_max,
                    },
                },
            }
        )
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source), prompt_call_recording(
            self.prompt_call_log()
        ):
            candidate_body, error = runner._timed_chat(
                story,
                prompt,
                max_tokens=max_tokens,
                json_mode=False,
                agent="writer",
                stage=f"章节润色（{mode}） 第{chapter_number}章",
                timeout_seconds=720,
            )
        if error:
            raise ValueError(f"chapter_polish_failed:{error}")
        candidate_body = _postprocess_chapter_output(
            story,
            str(candidate_body or ""),
            chapter_number=chapter_number,
            scene_cards=list(chapter.get("scene_cards") or []),
            outline_anchor=(chapter.get("chapter_seed") or {}).get("outline_anchor")
            if isinstance(chapter.get("chapter_seed"), dict)
            else None,
        )
        if not candidate_body.strip():
            raise ValueError("chapter_polish_failed:empty_body")
        candidate_chars = _chapter_char_count(candidate_body)
        first_pass_chars = candidate_chars
        length_repair_applied = False
        if not target_min <= candidate_chars <= target_max:
            repair_mode = "shorten" if candidate_chars > target_max else "expand"
            report_generation_progress(
                {
                    "message": (
                        f"第{chapter_number}章润色：首稿{candidate_chars}字，"
                        f"超出目标{target_min}到{target_max}字，正在校正"
                    ),
                    "status": "running",
                    "stage": "revision",
                    "source": "writer",
                    "artifact": {
                        "reason": "adaptive_chapter_polish_length_repair",
                        "inputs": {
                            "chapter_number": chapter_number,
                            "first_pass_chars": candidate_chars,
                            "target_min_chars": target_min,
                            "target_max_chars": target_max,
                        },
                        "outputs": {"repair_mode": repair_mode},
                    },
                }
            )
            if repair_mode == "shorten":
                repair_prompt = _render_compression_length_prompt(
                    story,
                    source_body=candidate_body,
                    chapter_number=chapter_number,
                    event_plan=event_plan,
                    world_facts=world_facts,
                    outline_anchor=(chapter.get("chapter_seed") or {}).get("outline_anchor")
                    if isinstance(chapter.get("chapter_seed"), dict)
                    else None,
                    target_chars=f"调整到{target_min}到{target_max}字",
                    feedback="这是润色字数校正，只删冗余表达，不改变已确认事件、事实和结尾钩子。",
                )
                repair_max_tokens = min(6200, target_max + 300)
            else:
                repair_prompt = _render_expansion_length_prompt(
                    story,
                    source_body=candidate_body,
                    chapter_number=chapter_number,
                    event_plan=event_plan,
                    world_facts=world_facts,
                    source_chars_override=_chapter_char_count(candidate_body),
                )
                repair_max_tokens = min(6200, target_max + 300)
            with prompt_template_scope(
                self.prompt_template_object, self.prompt_template_source
            ), prompt_call_recording(self.prompt_call_log()):
                repaired_body, repair_error = runner._timed_chat(
                    story,
                    repair_prompt,
                    max_tokens=repair_max_tokens,
                    json_mode=False,
                    agent="writer",
                    stage=f"章节润色字数校正（{repair_mode}） 第{chapter_number}章",
                    timeout_seconds=720,
                )
            if repair_error:
                raise ValueError(f"chapter_polish_failed:length_repair:{repair_error}")
            candidate_body = _postprocess_chapter_output(
                story,
                str(repaired_body or ""),
                chapter_number=chapter_number,
                scene_cards=list(chapter.get("scene_cards") or []),
                outline_anchor=(chapter.get("chapter_seed") or {}).get("outline_anchor")
                if isinstance(chapter.get("chapter_seed"), dict)
                else None,
            )
            if not candidate_body.strip():
                raise ValueError("chapter_polish_failed:length_repair_empty_body")
            candidate_chars = _chapter_char_count(candidate_body)
            length_repair_applied = True
        if not target_min <= candidate_chars <= target_max:
            raise ValueError(f"chapter_polish_failed:length_out_of_range:{candidate_chars}")
        if mode == "expand" and not _expanded_body_is_progress(source_body, candidate_body):
            raise ValueError("chapter_polish_failed:no_expansion_progress")
        if mode == "shorten" and not _compressed_body_is_progress(source_body, candidate_body):
            raise ValueError("chapter_polish_failed:no_shorten_progress")
        if mode == "polish":
            if (
                candidate_body.strip() == source_body.strip()
                or abs(candidate_chars - source_chars) > allowed_polish_delta
            ):
                raise ValueError("chapter_polish_failed:no_polish_progress")

        updated_story_payload = chapter.get("updated_story")
        if isinstance(updated_story_payload, dict):
            try:
                updated_story = StoryState.model_validate(updated_story_payload)
            except ValidationError:
                updated_story = story.model_copy(update={"current_chapter": chapter_number})
        else:
            updated_story = story.model_copy(update={"current_chapter": chapter_number})

        bundle_payload = dict(chapter)
        bundle_payload.update(
            {
                "chapter_number": chapter_number,
                "chapter_title": str(chapter.get("chapter_title") or f"Chapter {chapter_number}"),
                "body": candidate_body,
                "updated_story": updated_story,
                "quality_report": {},
            }
        )
        validation_payload = dict(bundle_payload)
        validation_payload["updated_story"] = updated_story.model_dump(mode="json")
        validation_payload["enforce_target_chars"] = True
        quality_report = validate_bundle(validation_payload)
        ending_anchor = expansion_ending_anchor(source_body)
        if ending_anchor and not candidate_body.rstrip().endswith(ending_anchor):
            issues = quality_report.setdefault("issues", [])
            if "ending_hook_changed" not in issues:
                issues.append("ending_hook_changed")
            quality_report["ok"] = False

        bundle = SimpleNamespace(**bundle_payload)
        bundle.quality_report = quality_report
        project_id = str(
            project.get("project_id")
            or project.get("active_story_id")
            or current_state.get("story_id")
            or self.root.name
        )
        candidate = self._save_candidate_from_bundle(
            bundle,
            project_id=project_id,
            quality_report=quality_report,
            operation="regenerate",
        )
        report_generation_progress(
            {
                "message": f"第{chapter_number}章润色候选稿已生成，等待人工确认",
                "status": "done",
                "stage": "revision",
                "source": "writer",
                "artifact": {
                    "reason": "adaptive_chapter_polish_complete",
                    "inputs": {
                        "before_chars": source_chars,
                        "first_pass_chars": first_pass_chars,
                        "polish_mode": mode,
                        "polish_mode_label": mode_label,
                    },
                    "outputs": {
                        "after_chars": candidate_chars,
                        "candidate_id": candidate.candidate_id,
                        "length_repair_applied": length_repair_applied,
                    },
                },
            }
        )
        return {
            "schema_version": "file-project-candidate/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": candidate.chapter_title,
            "polish_mode": mode,
            "before_chars": source_chars,
            "after_chars": candidate_chars,
            "length_repair_applied": length_repair_applied,
            "candidate": candidate.to_dict(),
        }

    @_with_project_update_lock
    def expand_chapter(
        self,
        chapter_number: int,
        *,
        orchestrator: Any | None = None,
    ) -> dict[str, Any]:
        """Expand one confirmed chapter into a pending candidate."""

        from packages.story_core.orchestrator import (
            StoryOrchestrator,
            _chapter_char_count,
            _expanded_body_is_progress,
            _expansion_target_range,
            _postprocess_chapter_output,
            _render_expansion_length_prompt,
        )
        from packages.story_core.genre_stages.length_prompts import (
            expansion_ending_anchor,
        )

        if chapter_number < 1:
            raise ValueError("chapter_number_must_be_positive")
        chapter = self.chapter(chapter_number)
        source_body = str(chapter.get("body") or "")
        if not source_body.strip():
            raise ValueError("chapter_body_required")
        current_state = dict(self.state())
        project = self.project()
        state_payload = self._story_state_payload_for_direction(
            current_state,
            project,
            chapter_number,
        )
        story = StoryState.model_validate(state_payload)
        event_plan = chapter.get("event_plan") if isinstance(chapter.get("event_plan"), dict) else {}
        prompt = _render_expansion_length_prompt(
            story,
            source_body=source_body,
            chapter_number=chapter_number,
            event_plan=event_plan,
            world_facts=[str(item) for item in (story.world_facts or []) if str(item).strip()],
            source_chars_override=_chapter_char_count(source_body),
        )
        runner = orchestrator or StoryOrchestrator(project_root=self.root)
        report_generation_progress(f"第{chapter_number}章人工扩写：读取正文和章节上下文")
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source), prompt_call_recording(
            self.prompt_call_log()
        ):
            _, expansion_target_max = _expansion_target_range(
                _chapter_char_count(source_body)
            )
            candidate_body, error = runner._timed_chat(
                story,
                prompt,
                max_tokens=min(6200, expansion_target_max + 300),
                json_mode=False,
                agent="writer",
                stage=f"章节扩写 第{chapter_number}章",
                timeout_seconds=720,
            )
        if error:
            raise ValueError(f"chapter_expansion_failed:{error}")
        candidate_body = _postprocess_chapter_output(
            story,
            str(candidate_body or ""),
            chapter_number=chapter_number,
            scene_cards=list(chapter.get("scene_cards") or []),
            outline_anchor=(chapter.get("chapter_seed") or {}).get("outline_anchor")
            if isinstance(chapter.get("chapter_seed"), dict)
            else None,
        )
        if not candidate_body.strip():
            raise ValueError("chapter_expansion_failed:empty_body")
        if not _expanded_body_is_progress(source_body, candidate_body):
            raise ValueError("chapter_expansion_failed:no_progress")

        updated_story_payload = chapter.get("updated_story")
        if isinstance(updated_story_payload, dict):
            try:
                updated_story = StoryState.model_validate(updated_story_payload)
            except ValidationError:
                updated_story = story.model_copy(update={"current_chapter": chapter_number})
        else:
            updated_story = story.model_copy(update={"current_chapter": chapter_number})

        bundle_payload = dict(chapter)
        bundle_payload.update(
            {
                "chapter_number": chapter_number,
                "chapter_title": str(chapter.get("chapter_title") or f"Chapter {chapter_number}"),
                "body": candidate_body,
                "updated_story": updated_story,
                "quality_report": {},
            }
        )
        validation_payload = dict(bundle_payload)
        validation_payload["updated_story"] = updated_story.model_dump(mode="json")
        validation_payload["enforce_target_chars"] = True
        quality_report = validate_bundle(validation_payload)
        ending_anchor = expansion_ending_anchor(source_body)
        if ending_anchor and not candidate_body.rstrip().endswith(ending_anchor):
            issues = quality_report.setdefault("issues", [])
            if "ending_hook_changed" not in issues:
                issues.append("ending_hook_changed")
            quality_report["ok"] = False
        bundle = SimpleNamespace(**bundle_payload)
        bundle.quality_report = quality_report
        project_id = str(
            project.get("project_id")
            or project.get("active_story_id")
            or current_state.get("story_id")
            or self.root.name
        )
        candidate = self._save_candidate_from_bundle(
            bundle,
            project_id=project_id,
            quality_report=bundle.quality_report,
            operation="regenerate",
        )
        report_generation_progress(f"第{chapter_number}章扩写候选稿已生成，等待人工确认")
        return {
            "schema_version": "file-project-candidate/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": candidate.chapter_title,
            "candidate": candidate.to_dict(),
        }

    def _regeneration_variant(self, chapter_number: int) -> dict[str, Any]:
        variants = [
            {
                "id": "focus-conflict-cost",
                "axes": ["核心冲突", "人物付出的代价"],
                "avoid": [],
            },
            {
                "id": "focus-character-choice",
                "axes": ["人物选择", "关系变化"],
                "avoid": ["照搬上一版的行动顺序", "只替换措辞而不改变场面推进"],
            },
            {
                "id": "focus-payoff-hook",
                "axes": ["可见结果", "章末下一步"],
                "avoid": ["照搬上一版的行动顺序", "用说明代替人物行动"],
            },
        ]
        count = 0
        commits_dir = self.story_system_dir / "commits"
        if commits_dir.exists():
            for path in commits_dir.glob("*.json"):
                if path.name == "latest_commit.json":
                    continue
                try:
                    data = self._read_json(path, default={})
                except Exception:
                    continue
                if int(data.get("chapter_number") or 0) == chapter_number and str(data.get("operation") or "") in {
                    "generate",
                    "regenerate",
                    "rewrite",
                    "write",
                }:
                    count += 1
        return variants[count % len(variants)]

    def _regeneration_title_override(self, chapter_number: int, variant_id: str) -> str | None:
        return None

    @staticmethod
    def _global_author_constraints(raw_constraints: Any) -> list[str]:
        """Return reusable book rules; chapter beats belong to the outline."""

        constraints = raw_constraints if isinstance(raw_constraints, list) else []
        chapter_pattern = re.compile(r"第(?:\d+|[一二三四五六七八九十百]+)章")
        return [
            text
            for item in constraints
            if (text := str(item).strip())
            and not chapter_pattern.search(text)
        ]

    @staticmethod
    def _historical_character_profile(
        raw_profile: dict[str, Any],
        *,
        target_chapter: int,
    ) -> dict[str, Any]:
        """Keep stable characterization while removing facts learned later."""

        profile = deepcopy(raw_profile)
        identity = profile.get("identity_profile")
        if isinstance(identity, dict):
            profile["identity_profile"] = {
                key: value
                for key, value in identity.items()
                if key not in {"current_identity", "affiliation"}
            }
        current_life = profile.get("current_life_profile")
        if isinstance(current_life, dict):
            profile["current_life_profile"] = {
                key: value
                for key, value in current_life.items()
                if key not in {"economic_state", "immediate_problem"}
            }
        story_drive = profile.get("story_drive")
        if isinstance(story_drive, dict):
            profile["story_drive"] = {
                key: value
                for key, value in story_drive.items()
                if key != "immediate_goal"
            }
        background = profile.get("background_profile")
        if isinstance(background, dict) and isinstance(background.get("formative_events"), list):
            next_background = dict(background)
            next_background["formative_events"] = [
                event
                for event in background["formative_events"]
                if not re.search(r"第(?:\d+|[一二三四五六七八九十百]+)章|本章|当前章", str(event))
            ]
            profile["background_profile"] = next_background
        for field in (
            "game_panel",
            "game_state",
            "real_state",
            "memory",
            "location",
            "current_location",
            "current_emotion",
            "latest_chapter",
            "chapter_role",
        ):
            profile.pop(field, None)
        return profile

    def _current_outline_volume_range(
        self, target_chapter: int
    ) -> tuple[int, int]:
        """Return the current volume's chapter range from
        the on-disk ``.webnovel/outline.json``.

        The planner needs a volume range so it does not
        invent cross-volume chapters. The range comes
        from the outline's arcs: the arc whose
        ``start_chapter <= target <= end_chapter`` is
        the active volume. When no arc matches (a
        pre-migration outline without arcs), the function
        falls back to ``(1, target + window)`` so the
        planner still has a finite range.
        """
        outline_path = self.webnovel_dir / "outline.json"
        if outline_path.is_file():
            try:
                payload = json.loads(
                    outline_path.read_text(encoding="utf-8")
                )
            except (OSError, json.JSONDecodeError):
                payload = None
            if isinstance(payload, dict):
                arcs = [
                    arc
                    for arc in payload.get("arcs", [])
                    if isinstance(arc, dict)
                ]
                for arc in arcs:
                    try:
                        start = int(arc.get("start_chapter") or 0)
                        end = int(arc.get("end_chapter") or 0)
                    except (TypeError, ValueError):
                        continue
                    if start <= 0 or end <= 0 or end < start:
                        continue
                    if start <= target_chapter <= end:
                        return (start, end)
        return (1, max(target_chapter + 5, 10))
    def _conservative_regeneration_state(
        self,
        current_state: dict[str, Any],
    ) -> dict[str, Any]:
        project = self.project()
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        def static_character_cards(raw_characters: Any) -> list[dict[str, Any]]:
            if not isinstance(raw_characters, list):
                return []
            cards: list[dict[str, Any]] = []
            for raw_character in raw_characters:
                if not isinstance(raw_character, dict):
                    continue
                name = str(raw_character.get("name") or "").strip()
                role = str(raw_character.get("role") or "").strip()
                if not name or not role or is_non_character_card(raw_character):
                    continue
                character = {"name": name, "role": role}
                # Rewriting must discard chapter-specific runtime state without
                # erasing the stable portrait that tells the writer who this
                # person is and how they behave.
                for field in (
                    "character_tier",
                    "first_appearance",
                    "game_id",
                    "identity_profile",
                    "background_profile",
                    "current_life_profile",
                    "story_drive",
                    "performance_profile",
                    "dialogue_examples",
                    "relationship_notes",
                    "personality_portrait",
                    "character_type",
                    "core_motivation",
                    "behavior_logic",
                    "interaction_mode",
                    "poison_points",
                    "social_profile",
                    "psychological_profile",
                    "moral_profile",
                    "story_function",
                    "chapter_role",
                ):
                    if raw_character.get(field) not in (None, "", [], {}):
                        character[field] = deepcopy(raw_character[field])
                legacy_motivation = str(raw_character.get("motivation") or "").strip()
                legacy_personality = str(raw_character.get("personality") or "").strip()
                legacy_speech = str(raw_character.get("speech_style") or "").strip()
                legacy_goals = [
                    str(item).strip()
                    for item in raw_character.get("goals", [])
                    if str(item).strip()
                ] if isinstance(raw_character.get("goals"), list) else []
                if legacy_motivation and not character.get("core_motivation"):
                    character["core_motivation"] = legacy_motivation
                if legacy_personality and not character.get("behavior_logic"):
                    character["behavior_logic"] = legacy_personality
                if legacy_speech and not character.get("performance_profile"):
                    character["performance_profile"] = {"speech_style": legacy_speech}
                if not character.get("story_drive") and (legacy_motivation or legacy_goals):
                    character["story_drive"] = {
                        "immediate_goal": legacy_goals[0] if legacy_goals else legacy_motivation,
                        "long_term_goal": legacy_goals[-1] if len(legacy_goals) > 1 else "",
                        "motivation": legacy_motivation,
                    }
                game_id = str(character.get("game_id") or "").strip()
                if game_id:
                    character["game_panel"] = {"game_id": game_id}
                cards.append(character)
            return cards

        project_character_profiles = [
            self._historical_character_profile(card, target_chapter=1)
            for card in project.get("character_profiles", [])
            if isinstance(card, dict)
        ]
        static_characters = static_character_cards(project_character_profiles)
        if not static_characters:
            static_characters = static_character_cards(project.get("characters"))
        state_characters = static_character_cards(current_state.get("characters"))
        state_by_name = {
            str(character.get("name") or "").strip(): character
            for character in state_characters
            if str(character.get("name") or "").strip()
        }
        for index, character in enumerate(static_characters):
            current = state_by_name.get(str(character.get("name") or "").strip())
            if not isinstance(current, dict):
                continue
            merged = dict(character)
            merged.update(
                {
                    key: deepcopy(value)
                    for key, value in current.items()
                    if value not in (None, "", [], {})
                }
            )
            static_characters[index] = merged
        for character in static_characters:
            # The latest character card may contain results learned during the
            # book. A chapter-one rewrite needs the stable portrait, not the
            # character's later money problem, immediate goal, or chapter recap.
            identity = character.get("identity_profile")
            if isinstance(identity, dict):
                character["identity_profile"] = {
                    key: value
                    for key, value in identity.items()
                    if key not in {"current_identity", "affiliation"}
                }
            current_life = character.get("current_life_profile")
            if isinstance(current_life, dict):
                character["current_life_profile"] = {
                    key: value
                    for key, value in current_life.items()
                    if key not in {"economic_state", "immediate_problem"}
                }
            story_drive = character.get("story_drive")
            if isinstance(story_drive, dict):
                character["story_drive"] = {
                    key: value
                    for key, value in story_drive.items()
                    if key != "immediate_goal"
                }
            background = character.get("background_profile")
            if isinstance(background, dict) and isinstance(background.get("formative_events"), list):
                next_background = dict(background)
                next_background["formative_events"] = [
                    event
                    for event in background["formative_events"]
                    if not any(marker in str(event) for marker in ("第一章", "第1章", "本章", "当前章"))
                ]
                character["background_profile"] = next_background
            character.pop("chapter_role", None)

        baseline = {
            "story_id": str(
                current_state.get("story_id")
                or project.get("active_story_id")
                or project.get("project_id")
                or "file-project"
            ),
            "outline": str(
                current_state.get("outline")
                or project.get("seed_outline")
                or project.get("title")
                or ""
            ),
            "genre": str(current_state.get("genre") or project.get("genre") or ""),
            "genre_plugin_ids": deepcopy(
                current_state.get("genre_plugin_ids")
                or world_blueprint.get("genre_plugin_ids")
                or []
            ),
            "style": str(current_state.get("style") or project.get("style") or ""),
            "current_chapter": 0,
            "author_constraints": deepcopy(
                project.get("author_constraints")
                or current_state.get("author_constraints")
                or []
            ),
            "enabled_skill_ids": deepcopy(
                resolve_enabled_skill_ids(project, current_state)
            ),
            "enabled_skill_module_ids": deepcopy(
                resolve_enabled_skill_module_ids(project, current_state)
            ),
            "characters": static_characters,
            "monster_profiles": [],
            "world_facts": [],
            "progression_ledger": {},
            "timeline": [],
            "foreshadowing": [],
            "chapter_summaries": [],
            "memory_index": [],
            "arc_recaps": [],
        }
        master_state = self.master_setting().get("state")
        if isinstance(master_state, dict) and int(master_state.get("current_chapter") or 0) == 0:
            opening_state = deepcopy(master_state)
            # MASTER_SETTING.state is the immutable chapter-zero snapshot. Keep
            # its opening resources and time, while taking editable book-level
            # configuration and static character portraits from current files.
            for field in (
                "story_id",
                "outline",
                "genre",
                "genre_plugin_ids",
                "style",
                "author_constraints",
                "enabled_skill_ids",
                "enabled_skill_module_ids",
                "characters",
            ):
                opening_state[field] = deepcopy(baseline[field])
            opening_state["current_chapter"] = 0
            for field in (
                "progression_ledger",
                "timeline",
                "foreshadowing",
                "chapter_summaries",
                "memory_index",
                "arc_recaps",
                "world_facts",
                "monster_profiles",
            ):
                opening_state.setdefault(field, deepcopy(baseline[field]))
            baseline = opening_state
        for field in ("novel_type", "novel_type_id", "novel_type_ids"):
            if field in current_state:
                baseline[field] = deepcopy(current_state[field])
        return baseline

    def _chapter_snapshot_state(
        self,
        chapter_number: int,
        current_state: dict[str, Any],
    ) -> dict[str, Any] | None:
        try:
            chapter = self.chapter(chapter_number)
        except FileNotFoundError:
            return None
        updated_story = chapter.get("updated_story") if isinstance(chapter, dict) else None
        if not isinstance(updated_story, dict):
            return None
        try:
            snapshot_chapter = int(updated_story.get("current_chapter") or 0)
        except (TypeError, ValueError):
            return None
        if snapshot_chapter != chapter_number:
            return None
        hydrated_snapshot = self._conservative_regeneration_state(current_state)
        hydrated_snapshot.update(deepcopy(updated_story))
        usable = self._validated_runtime_state(hydrated_snapshot, current_state)
        return dict(usable) if usable is not None else None

    @staticmethod
    def _merge_regeneration_configuration(
        base_state: dict[str, Any],
        current_state: dict[str, Any],
    ) -> dict[str, Any]:
        merged = dict(base_state)
        for field in (
            "author_constraints",
            "enabled_skill_ids",
            "enabled_skill_module_ids",
            "genre",
            "genre_plugin_ids",
            "style",
        ):
            if field in current_state:
                merged[field] = deepcopy(current_state[field])
        return merged

    def _regeneration_base_state(
        self,
        chapter_number: int,
        current_state: dict[str, Any],
    ) -> dict[str, Any]:
        snapshot_number = 0
        base_state: dict[str, Any] | None = None
        for previous_number in range(chapter_number - 1, 0, -1):
            base_state = self._chapter_snapshot_state(previous_number, current_state)
            if base_state is not None:
                snapshot_number = previous_number
                break
        if base_state is None:
            base_state = self._conservative_regeneration_state(current_state)

        replay_numbers = [
            number
            for number in self.chapter_numbers()
            if snapshot_number < number < chapter_number
        ]
        for previous_number in replay_numbers:
            chapter = self.chapter(previous_number)
            base_state = self._sync_state_after_chapter(base_state, deepcopy(chapter))
            base_state = self._sync_ledger_from_chapter_body(base_state, deepcopy(chapter))

        base_state["current_chapter"] = chapter_number - 1
        return self._merge_regeneration_configuration(base_state, current_state)

    @_with_project_update_lock
    def regenerate_chapter(
        self,
        chapter_number: int,
        engine: Any | None = None,
        *,
        variant: str | None = None,
        guidance: str | None = None,
        commit_message: str | None = None,
        persist: bool = True,
    ) -> dict[str, Any]:
        # Model generation stays inside the per-project lock so a later rewrite
        # cannot be generated from state that another same-project rewrite replaces.
        # This intentionally blocks same-project edits; locks for other roots are independent.
        from packages.story_core.engine import StoryEngine

        if chapter_number < 1:
            raise ValueError("chapter_number_must_be_positive")
        self._assert_chapter_not_frozen(chapter_number, "regenerate")
        self._assert_opening_preflight(chapter_number)

        current_state = dict(self.state())
        if chapter_number > 1:
            base_state = self._regeneration_base_state(chapter_number, current_state)
        else:
            base_state = self._conservative_regeneration_state(current_state)

        base_state["current_chapter"] = chapter_number - 1
        ledger = dict(base_state.get("progression_ledger") or {})
        variant_payload = self._regeneration_variant(chapter_number)
        if variant:
            variant_payload = {**variant_payload, "id": variant}
            if variant == "progression-lead":
                variant_payload.setdefault("axes", ["把本书已有优势转化为可见成长和下一步机会"])
                variant_payload.setdefault(
                    "avoid",
                    ["公开解释隐藏优势", "擅自提前后续势力反应", "把账本说明写成正文高潮"],
                )
                variant_payload["skip_expansion"] = False
        variant_payload.setdefault("skip_expansion", False)
        guidance_text = self._compact_text(guidance, 1200)
        if guidance_text:
            variant_payload["rewrite_guidance"] = {"source": "book_dissection", "text": guidance_text}
        ledger["simulation_variant"] = variant_payload
        base_state["progression_ledger"] = ledger

        project = self.project()
        direction_payload = self._story_state_payload_for_direction(
            base_state,
            project,
            chapter_number,
        )
        story = StoryState.model_validate(direction_payload)
        generator = engine or StoryEngine(
            use_modular_agents=True, project_root=self.root
        )
        with prompt_template_scope(self.prompt_template_object, self.prompt_template_source), prompt_call_recording(
            self.prompt_call_log()
        ):
            bundle = generator.generate_next_chapter(story)
        if int(getattr(bundle, "chapter_number", 0) or 0) != chapter_number:
            raise ValueError(f"regenerated_wrong_chapter:{getattr(bundle, 'chapter_number', None)}")
        quality_report = getattr(bundle, "quality_report", None)
        writing_review = quality_report.get("writing_review") if isinstance(quality_report, dict) else None
        if isinstance(quality_report, dict):
            _promote_downstream_rewrite_status(quality_report)
        if (
            isinstance(quality_report, dict)
            and quality_report
            and not quality_report.get("regeneration_degraded")
            and quality_report.get("ok") is False
        ):
            issues = quality_report.get("issues") or []
            if isinstance(writing_review, dict):
                issues = [*issues, *(writing_review.get("issues") or [])]
            issue_text = "; ".join(str(item) for item in issues[:5] if str(item).strip())
            if _is_regeneration_continuity_failure(quality_report, writing_review if isinstance(writing_review, dict) else None):
                quality_report["regeneration_degraded"] = True
                quality_report["regeneration_quality_warning"] = [
                    str(item) for item in issues if str(item).strip()
                ][:10]
            elif not _regeneration_quality_blocking(
                quality_report,
                writing_review if isinstance(writing_review, dict) else None,
            ):
                quality_report["regeneration_quality_warning"] = [str(item) for item in issues if str(item).strip()][:10]
        title_override = _chapter_outline_title(
            direction_payload.get("outline_context"),
            chapter_number,
        ) or self._regeneration_title_override(chapter_number, str(variant_payload.get("id") or ""))
        if title_override:
            bundle.chapter_title = title_override
            if isinstance(getattr(bundle, "chapter_summary", None), dict):
                bundle.chapter_summary["chapter_title"] = title_override
        if not persist:
            project_id = str(
                project.get("project_id")
                or project.get("active_story_id")
                or current_state.get("story_id")
                or self.root.name
            )
            candidate = self._save_candidate_from_bundle(
                bundle,
                project_id=project_id,
                quality_report=quality_report if isinstance(quality_report, dict) else None,
                operation="regenerate",
            )
            return {
                "schema_version": "file-project-candidate/v1",
                "root": str(self.root),
                "chapter_number": candidate.chapter_number,
                "chapter_title": candidate.chapter_title,
                "candidate": candidate.to_dict(),
                "simulation_variant": variant_payload,
            }
        persisted = self.persist_bundle(
            bundle,
            operation="regenerate",
            commit_message=commit_message or f"regenerate chapter {chapter_number} ({variant_payload.get('id')})",
        )
        return {
            "schema_version": "file-project-regenerate/v1",
            "root": str(self.root),
            "chapter_number": persisted["chapter_number"],
            "chapter_title": persisted["chapter_title"],
            "simulation_variant": variant_payload,
            "persisted": persisted,
            "quality_warning": quality_report.get("regeneration_quality_warning")
            if isinstance(quality_report, dict)
            else None,
        }
