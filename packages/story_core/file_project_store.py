from __future__ import annotations

import json
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any
from urllib.parse import quote

from packages.story_core.chapter_direction import build_chapter_direction_options
from packages.story_core.character_portraits import complete_character_portrait as complete_portrait
from packages.story_core.character_profiles import (
    merge_character_profile,
    normalize_character_profile,
)
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.cold_reader_review import review_cold_reader_experience
from packages.story_core.editor_agent import review_editor_agent
from packages.story_core.elastic_outline import outline_window_status, validate_outline_for_project
from packages.story_core.dual_state import (
    merge_state_change,
    normalize_dual_state,
    project_character_for_scene,
    scene_kind_for_cards,
)
from packages.story_core.genre_plugins import select_genre_plugins
from packages.story_core.models import CharacterState, NovelProject, StoryState
from packages.story_core.novel_type_catalog import (
    normalize_novel_type_ids,
    novel_type_id_from_metadata_fact,
    resolve_novel_type_id,
    runtime_novel_type,
)
from packages.story_core.opening_directions import OpeningBrief, OpeningDirectionSet
from packages.story_core.outline_planning import GeneratedOutlinePlan, validate_generated_opening_plan
from packages.story_core.outline_planning_generation import OutlinePlanningBrief
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.project_outline import normalize_project_outline, outline_from_legacy_project, select_outline_context
from packages.story_core.reader_feel_review import review_reader_feel
from packages.story_core.relationship_graph import (
    apply_relationship_updates,
    graph_from_character_cards,
    merge_relationship_graph,
    normalize_relationship_graph,
    select_relationship_subgraph,
)
from packages.story_core.quality import validate_bundle
from packages.story_core.reader_agent import review_reader_agent
from packages.story_core.reviewer_agent import review_reviewer_agent
from packages.story_core.workflow_telemetry import append_workflow_telemetry
from packages.story_core.writing_learning import learning_snapshot, lessons_from_quality_report, merge_writing_lessons
from packages.story_core.writing_packet import prose_renderer_contract
from packages.story_core.skill_packs import skill_pack_prompt_context
from packages.story_core.writing_taskbook import format_taskbook_brief_section


def _state_namespace_has_content(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    current = value.get("current")
    if isinstance(current, dict) and any(item not in (None, "", [], {}) for item in current.values()):
        return True
    recent_changes = value.get("recent_changes")
    return isinstance(recent_changes, list) and bool(recent_changes)


def _normalize_character_persistence_card(
    card: dict[str, Any],
    *,
    is_game_story: bool,
) -> dict[str, Any]:
    normalized = normalize_dual_state(card, is_game_story=is_game_story)
    if is_game_story:
        current = normalized.get("game_state", {}).get("current") if isinstance(normalized.get("game_state"), dict) else None
        if isinstance(current, dict):
            panel = dict(normalized.get("game_panel") or {})
            for field in (
                "game_id",
                "level",
                "class_path",
                "exp",
                "hp",
                "mp",
                "attributes",
                "skills",
                "equipment",
                "inventory",
                "currency",
                "quests",
                "risk",
            ):
                value = current.get(field)
                if value not in (None, "", [], {}):
                    panel[field] = value
            normalized["game_panel"] = panel
    for state_name in ("real_state", "game_state"):
        if not _state_namespace_has_content(normalized.get(state_name)):
            normalized.pop(state_name, None)
    return normalized


_GAME_STATE_FIELDS = (
    "game_id",
    "level",
    "class_path",
    "exp",
    "hp",
    "mp",
    "attributes",
    "skills",
    "equipment",
    "inventory",
    "currency",
    "quests",
    "risk",
    "backpack",
)


def _sync_game_panel_from_state(card: dict[str, Any]) -> dict[str, Any]:
    """Mirror structured game state into the legacy panel."""

    panel = dict(card.get("game_panel") or {})
    state = dict(card.get("game_state") or {})
    current = dict(state.get("current") or {}) if isinstance(state.get("current"), dict) else {}
    for field in _GAME_STATE_FIELDS:
        value = current.get(field)
        if value not in (None, "", [], {}):
            panel[field] = deepcopy(value)
    card["game_panel"] = panel
    return card


def _sync_game_state_mirror(card: dict[str, Any]) -> dict[str, Any]:
    """Materialize game state from a legacy panel without touching reality."""

    panel = dict(card.get("game_panel") or {})
    state = dict(card.get("game_state") or {})
    current = dict(state.get("current") or {}) if isinstance(state.get("current"), dict) else {}
    for field in _GAME_STATE_FIELDS:
        value = panel.get(field)
        if value not in (None, "", [], {}):
            current.setdefault(field, deepcopy(value))
    state["current"] = current
    state.setdefault("recent_changes", [])
    card["game_state"] = state
    return card


SOFT_REGENERATION_ISSUE_MARKERS = (
    "正文带出后台硬词",
    "战斗写成攻略说明",
    "比喻配额超标",
    "AI味",
    "段首主语单调",
    "段落形态",
    "推演事件未被正文场景化",
    "场景卡必写内容缺失",
    "Scene contract not consumed",
    "命名NPC出场缺少完整设定",
)


FILE_CHAPTER_MIN_CHARS = 3800
FILE_CHAPTER_MAX_CHARS = 5500


def _chapter_length_review(body: str) -> dict[str, Any]:
    body_chars = len("".join(str(body or "").split()))
    issues: list[str] = []
    if body_chars < FILE_CHAPTER_MIN_CHARS:
        issues.append(f"章节字数偏少：当前约{body_chars}字，最低要求{FILE_CHAPTER_MIN_CHARS}字。")
    elif body_chars > FILE_CHAPTER_MAX_CHARS:
        issues.append(f"章节字数超标：当前约{body_chars}字，建议不超过{FILE_CHAPTER_MAX_CHARS}字。")
    return {
        "pass": not issues,
        "body_chars": body_chars,
        "min_chars": FILE_CHAPTER_MIN_CHARS,
        "max_chars": FILE_CHAPTER_MAX_CHARS,
        "issues": issues,
    }


def _assert_auto_chapter_length(body: str, *, operation: str) -> None:
    """Reject generated chapters that cannot satisfy the file-project length gate."""

    length_review = _chapter_length_review(body)
    if length_review.get("pass", True):
        return
    body_chars = int(length_review.get("body_chars") or 0)
    min_chars = int(length_review.get("min_chars") or FILE_CHAPTER_MIN_CHARS)
    if body_chars < min_chars:
        issue = "; ".join(str(item) for item in length_review.get("issues", []) if str(item).strip())
        raise ValueError(f"{operation}_length_failed:{issue or f'body_chars {body_chars} < {min_chars}'}")


def _regeneration_quality_blocking(quality_report: dict[str, Any], writing_review: dict[str, Any] | None) -> bool:
    if not writing_review:
        return True
    critical = writing_review.get("critical_review") if isinstance(writing_review.get("critical_review"), dict) else {}
    severity = critical.get("severity_summary") if isinstance(critical.get("severity_summary"), dict) else {}
    if critical.get("hard_issues") or severity.get("has_hard_violation"):
        return True
    detailed_issues = [str(item) for item in (writing_review.get("issues") or []) if str(item).strip()]
    if not detailed_issues:
        detailed_issues = [str(item) for item in (quality_report.get("issues") or []) if str(item).strip()]
    for issue in detailed_issues:
        if issue == "writing_review":
            continue
        if not any(marker in issue for marker in SOFT_REGENERATION_ISSUE_MARKERS):
            return True
    return False


def _assert_auto_chapter_quality(
    quality_report: dict[str, Any],
    *,
    operation: str,
) -> None:
    if operation not in {"generate", "regenerate"}:
        return
    if not isinstance(quality_report, dict) or quality_report.get("ok") is not False:
        return
    writing_review = quality_report.get("writing_review") if isinstance(quality_report.get("writing_review"), dict) else None
    issues = list(quality_report.get("issues") or [])
    if isinstance(writing_review, dict):
        issues.extend(writing_review.get("issues") or [])
    issue_text = "; ".join(str(item) for item in issues[:6] if str(item).strip())
    if _regeneration_quality_blocking(quality_report, writing_review):
        raise ValueError(f"{operation}_quality_failed:{issue_text or 'quality_report_not_ok'}")


def _normalize_chapter_title(title: str, chapter_number: int) -> str:
    cleaned = str(title or "").strip()
    cleaned = re.sub(rf"^\s*第\s*{chapter_number}\s*章[：:\s、.-]*", "", cleaned).strip()
    cleaned = re.sub(r"^\s*第\s*[零一二三四五六七八九十百千万]+\s*章[：:\s、.-]*", "", cleaned).strip()
    return cleaned or str(title or "").strip() or f"Chapter {chapter_number}"


def _manual_chapter_quality_report(chapter: dict[str, Any]) -> dict[str, Any]:
    quality_report = validate_bundle(chapter)
    body = str(chapter.get("body") or "")
    length_review = _chapter_length_review(body)
    ai_flavor_review = review_ai_flavor(body)
    reader_feel_review = review_reader_feel(body)
    prose_style_review = review_prose_style(body)
    cold_reader_review = review_cold_reader_experience(
        body,
        previous_summary=str((chapter.get("event_plan") or {}).get("summary") or ""),
    )
    reader_agent_review = review_reader_agent(
        body,
        previous_summary=str((chapter.get("event_plan") or {}).get("summary") or ""),
        cold_reader_review=cold_reader_review,
    )
    editor_agent_review = review_editor_agent(
        body,
        prose_style_review=prose_style_review,
        ai_flavor_review=ai_flavor_review,
    )
    reviewer_agent_review = review_reviewer_agent(
        chapter_number=int(chapter.get("chapter_number") or 0),
        body=body,
        event_plan=chapter.get("event_plan") if isinstance(chapter.get("event_plan"), dict) else {},
        world_facts=[],
    )

    issues = [str(item) for item in quality_report.get("issues", []) if str(item).strip()]
    for issue in length_review.get("issues", []):
        text = str(issue).strip()
        if text and text not in issues:
            issues.append(text)
    quality_metrics = quality_report.setdefault("metrics", {})
    if isinstance(quality_metrics, dict):
        quality_metrics["body_chars"] = length_review["body_chars"]
        quality_metrics["target_min_chars"] = length_review["min_chars"]
        quality_metrics["target_max_chars"] = length_review["max_chars"]
        quality_metrics["target_range"] = f'{length_review["min_chars"]}-{length_review["max_chars"]}字'
    scores: dict[str, Any] = {}
    for prefix, report in (
        ("ai_flavor", ai_flavor_review),
        ("reader_feel", reader_feel_review),
        ("prose_style", prose_style_review),
        ("cold_reader", cold_reader_review),
    ):
        for key, score in (report.get("scores") or {}).items():
            scores[f"{prefix}_{key}"] = score
        for issue in report.get("issues", []):
            reason = issue.get("reason") if isinstance(issue, dict) else str(issue)
            if reason and reason not in issues:
                issues.append(reason)
    for agent_review in (reader_agent_review, editor_agent_review, reviewer_agent_review):
        for issue in agent_review.get("issues", []):
            text = str(issue).strip()
            if text and text not in issues:
                issues.append(text)

    pass_review = (
        bool(quality_report.get("ok"))
        and bool(length_review.get("pass", True))
        and bool(ai_flavor_review.get("pass", True))
        and bool(reader_feel_review.get("pass", True))
        and bool(prose_style_review.get("pass", True))
        and bool(cold_reader_review.get("pass", True))
        and bool(reader_agent_review.get("pass", True))
        and bool(editor_agent_review.get("pass", True))
        and bool(reviewer_agent_review.get("pass", True))
    )
    writing_review = {
        "pass": pass_review,
        "issues": issues,
        "scores": scores,
        "length_review": length_review,
        "ai_flavor_review": ai_flavor_review,
        "reader_feel_review": reader_feel_review,
        "prose_style_review": prose_style_review,
        "cold_reader_review": cold_reader_review,
        "reader_agent_review": reader_agent_review,
        "editor_agent_review": editor_agent_review,
        "reviewer_agent_review": reviewer_agent_review,
        "revision_plan": _merge_revision_plans(
            ai_flavor_review.get("revision_plan", []),
            reader_feel_review.get("revision_plan", []),
            prose_style_review.get("revision_plan", []),
            cold_reader_review.get("revision_plan", []),
            reader_agent_review.get("revision_plan", []),
            editor_agent_review.get("revision_plan", []),
            reviewer_agent_review.get("revision_plan", []),
        ),
    }
    report = {
        "schema_version": "file-writing-review/v2",
        "writing_review": writing_review,
        "quality_report": quality_report,
        "length_review": length_review,
        "ai_flavor_review": ai_flavor_review,
        "reader_feel_review": reader_feel_review,
        "prose_style_review": prose_style_review,
        "cold_reader_review": cold_reader_review,
        "reader_agent_review": reader_agent_review,
        "editor_agent_review": editor_agent_review,
        "reviewer_agent_review": reviewer_agent_review,
    }
    if not pass_review:
        quality_report["ok"] = False
        quality_report["issues"] = issues
        report["ok"] = False
        report["issues"] = issues
    else:
        report["ok"] = bool(quality_report.get("ok"))
        report["issues"] = issues
    return report


def _merge_revision_plans(*plans: Any) -> list[str]:
    merged: list[str] = []
    for plan in plans:
        for item in plan or []:
            text = str(item).strip()
            if text and text not in merged:
                merged.append(text)
    return merged


class FileProjectStore:
    """Read plugin-friendly story project files from a directory."""

    def __init__(self, root: str | Path):
        self.root = Path(root).resolve()
        self.story_system_dir = self.root / ".story-system"
        self.webnovel_dir = self.root / ".webnovel"
        self.chapters_dir = self.root / "chapters"

    def _read_json(self, path: Path, default: Any = None) -> Any:
        if not path.exists():
            return default
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def _write_json(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_json_atomic(self, path: Path, payload: Any) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        serialized = json.dumps(payload, ensure_ascii=False, indent=2)
        fd: int | None = None
        temp_path: Path | None = None
        try:
            fd, temp_name = tempfile.mkstemp(
                dir=str(path.parent),
                prefix=f".{path.name}.",
                suffix=".tmp",
            )
            temp_path = Path(temp_name)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                fd = None
                handle.write(serialized)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, path)
        finally:
            try:
                if fd is not None:
                    os.close(fd)
            finally:
                if temp_path is not None:
                    temp_path.unlink(missing_ok=True)

    def _replace_json_transaction(self, payloads: dict[Path, Any]) -> None:
        targets = [(Path(path), payload) for path, payload in payloads.items()]
        snapshots: dict[Path, bytes | None] = {
            path: path.read_bytes() if path.exists() else None for path, _ in targets
        }
        prepared: dict[Path, Path] = {}
        try:
            for path, payload in targets:
                path.parent.mkdir(parents=True, exist_ok=True)
                fd, temp_name = tempfile.mkstemp(
                    dir=str(path.parent),
                    prefix=f".{path.name}.",
                    suffix=".tmp",
                )
                temp_path = Path(temp_name)
                prepared[path] = temp_path
                with os.fdopen(fd, "w", encoding="utf-8") as handle:
                    handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
                    handle.flush()
                    os.fsync(handle.fileno())

            for path, _ in targets:
                os.replace(prepared[path], path)
        except Exception as exc:
            rollback_errors: list[Exception] = []
            for path, snapshot in snapshots.items():
                try:
                    if snapshot is None:
                        path.unlink(missing_ok=True)
                    else:
                        path.parent.mkdir(parents=True, exist_ok=True)
                        path.write_bytes(snapshot)
                except Exception as rollback_exc:  # pragma: no cover - catastrophic filesystem failure
                    rollback_errors.append(rollback_exc)
            if rollback_errors:
                raise RuntimeError("json_transaction_rollback_failed") from exc
            raise
        finally:
            for temp_path in prepared.values():
                temp_path.unlink(missing_ok=True)

    def _write_text(self, path: Path, text: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _chapter_markdown_name(self, chapter_number: int, title: str) -> str:
        cleaned = re.sub(r'[\\/:*?"<>|]+', "", str(title or "")).strip()
        suffix = f"-{cleaned}" if cleaned else ""
        return f"{chapter_number:04d}{suffix}.md"

    def _remove_chapter_markdowns(self, chapter_number: int) -> None:
        if not self.chapters_dir.exists():
            return
        prefix = f"{chapter_number:04d}"
        for path in self.chapters_dir.glob(f"{prefix}*.md"):
            path.unlink()

    def _chapter_paths(self, chapter_number: int, title: str) -> dict[str, Path]:
        return {
            "json": self.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            "review": self.story_system_dir / "reviews" / f"{chapter_number:04d}.json",
            "markdown": self.chapters_dir / self._chapter_markdown_name(chapter_number, title),
        }

    def _append_workflow_log(
        self,
        *,
        chapter_number: int,
        chapter_title: str,
        review: dict[str, Any],
        operation: str,
    ) -> None:
        if not isinstance(review, dict) or review.get("workflow_log_path"):
            return
        project = self.project()
        state = self.state()
        path = append_workflow_telemetry(
            chapter=chapter_number,
            chapter_title=chapter_title,
            operation=operation,
            quality_report=review,
            project_id=str(project.get("project_id") or ""),
            story_id=str(state.get("story_id") or project.get("active_story_id") or ""),
        )
        if path is not None:
            review["workflow_log_path"] = str(path)

    def _bundle_to_dict(self, bundle: Any) -> dict[str, Any]:
        if hasattr(bundle, "model_dump"):
            return bundle.model_dump(mode="json")
        if isinstance(bundle, dict):
            return dict(bundle)
        return {
            key: value
            for key, value in vars(bundle).items()
            if not key.startswith("_")
        }

    def _compact_text(self, value: Any, limit: int = 180) -> str:
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        if len(text) <= limit:
            return text
        return f"{text[:limit].rstrip()}..."

    def _merge_unique(self, current: list[Any], additions: list[Any], *, limit: int = 80) -> list[Any]:
        result: list[Any] = []
        seen: set[str] = set()
        for item in [*current, *additions]:
            if item in (None, ""):
                continue
            key = json.dumps(item, ensure_ascii=False, sort_keys=True) if isinstance(item, (dict, list)) else str(item)
            if key in seen:
                continue
            seen.add(key)
            result.append(item)
        return result[-limit:]

    def _coerce_summary_mapping(self, value: Any, *, label: str) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if value in (None, ""):
            return {}
        return {"note": self._compact_text(value, 220), "source": label}

    def _clean_state_fact_list(self, values: Any) -> list[Any]:
        if not isinstance(values, list):
            return []
        blocked_fragments = (
            "manual draft",
            "第2章事实：夜烬仍为Lv.1",
            "夜烬仍为Lv.1见习冒险者",
            "第2章事实：新手法杖9/10",
            "第2章事实：背包为粗糙狼皮×7",
        )
        return [
            item
            for item in values
            if not (isinstance(item, str) and any(fragment in item for fragment in blocked_fragments))
        ]

    def _clean_summary_mapping(self, value: Any, *, label: str) -> dict[str, Any]:
        mapping = self._coerce_summary_mapping(value, label=label)
        if not mapping:
            return {}
        meaningful_values = [item for key, item in mapping.items() if key != "source"]
        if not meaningful_values or all(self._is_placeholder_text(item) for item in meaningful_values):
            return {}
        return mapping

    def _is_placeholder_text(self, value: Any) -> bool:
        text = self._compact_text(value, 260).lower()
        if not text:
            return True
        return text in {
            "continue",
            "manual draft",
            "manual rewrite",
            "manual chapter",
            "chapter-progress",
        } or text.startswith("codex hand-written")

    def _first_mapping_text(self, value: Any, keys: tuple[str, ...], fallback: str = "") -> str:
        if isinstance(value, dict):
            for key in keys:
                text = self._compact_text(value.get(key), 260)
                if text and not self._is_placeholder_text(text):
                    return text
            note = self._compact_text(value.get("note"), 260)
            if note and not self._is_placeholder_text(note):
                return note
            return fallback
        text = self._compact_text(value, 260)
        if text and not self._is_placeholder_text(text):
            return text
        return fallback

    def _hydrate_chapter_display_fields(self, chapter: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
        """Backfill workbench insight cards for legacy/manual file chapters.

        Generated bundles already carry these fields. Older restored chapters and
        hand-written rewrites may only have a chapter summary, which made the UI
        show empty "not organized yet" cards even though enough chapter state
        existed to present a useful reading report.
        """

        hydrated = dict(chapter)
        summary = self._chapter_summary_payload(hydrated)
        summary_text = self._compact_text(summary.get("summary"), 260)
        next_focus = self._compact_text(summary.get("next_focus"), 220) or hydrated.get("next_outline") or "continue"

        if not isinstance(hydrated.get("chapter_intent"), dict) or not hydrated.get("chapter_intent"):
            primary = self._coerce_summary_mapping(summary.get("primary_conflict"), label="primary_conflict")
            secondary = self._coerce_summary_mapping(summary.get("secondary_conflict"), label="secondary_conflict")
            collision = self._first_mapping_text(primary, ("collision", "summary", "detail"), summary_text)
            hydrated["chapter_intent"] = {
                "chapter_title": summary.get("chapter_title"),
                "cadence": summary.get("cadence") or hydrated.get("cadence") or "measured",
                "next_focus": next_focus,
                "primary_conflict": primary | {"collision": collision},
                "secondary_conflict": secondary,
            }

        if not isinstance(hydrated.get("event_beat"), dict) or not hydrated.get("event_beat"):
            event_beat = self._coerce_summary_mapping(summary.get("event_beat"), label="event_beat")
            pivot = self._first_mapping_text(event_beat, ("pivot", "summary", "detail"), summary_text)
            hydrated["event_beat"] = {
                "turn": self._first_mapping_text(event_beat, ("turn",), "chapter-progress"),
                "pivot": pivot,
            }

        if not isinstance(hydrated.get("memory_constraints"), dict) or not hydrated.get("memory_constraints"):
            facts = [
                self._compact_text(item, 220)
                for item in (summary.get("facts") if isinstance(summary.get("facts"), list) else [])
                if str(item).strip() and not self._is_placeholder_text(item)
            ]
            hydrated["memory_constraints"] = {
                "must_keep_facts": facts[:8] or ([summary_text] if summary_text else []),
                "unresolved_threads": [
                    self._compact_text(item, 220)
                    for item in (
                        summary.get("unresolved_threads")
                        if isinstance(summary.get("unresolved_threads"), list)
                        else []
                    )
                    if str(item).strip()
                ][:8],
                "current_focus": next_focus,
            }

        if not isinstance(hydrated.get("character_moves"), list) or not hydrated.get("character_moves"):
            source_state = state if isinstance(state, dict) else self.state()
            names = self._character_names_in_chapter(source_state, hydrated)
            if not names:
                for character in source_state.get("characters", []) if isinstance(source_state.get("characters"), list) else []:
                    if isinstance(character, dict) and str(character.get("name") or "").strip():
                        names = [str(character["name"]).strip()]
                        break
            hydrated["character_moves"] = [
                {
                    "name": name,
                    "goal": next_focus,
                    "action": summary_text,
                    "priority": index + 1,
                }
                for index, name in enumerate(names[:4])
            ]

        if not hydrated.get("next_outline") and next_focus:
            hydrated["next_outline"] = next_focus

        return hydrated

    def _sanitize_story_state(self, state: dict[str, Any]) -> dict[str, Any]:
        sanitized = dict(state)
        ledger = sanitized.get("progression_ledger")
        if isinstance(ledger, dict):
            ledger = dict(ledger)
            economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
            if isinstance(economy.get("inventory"), dict):
                ledger.pop("inventory", None)
            if economy.get("game_currency") not in (None, "", [], {}):
                ledger.pop("currency", None)
            if isinstance(ledger.get("skills"), list):
                ledger["skills"] = [item for item in ledger["skills"] if "熟练度" not in str(item)]
                if not ledger["skills"]:
                    ledger.pop("skills", None)
            pressure = ledger.get("pressure") if isinstance(ledger.get("pressure"), dict) else {}
            next_pressure = pressure.get("next") if isinstance(pressure, dict) else None
            if isinstance(next_pressure, list):
                pressure = dict(pressure)
                pressure["next"] = [
                    "后坡探路前置已满足，但等级和补给仍压着风险"
                    if "熟练度" in str(item)
                    else item
                    for item in next_pressure
                ]
                ledger["pressure"] = pressure
            sanitized["progression_ledger"] = ledger
        sanitized["world_facts"] = self._clean_state_fact_list(sanitized.get("world_facts"))
        summaries: list[Any] = []
        changed = False
        for item in sanitized.get("chapter_summaries", []) if isinstance(sanitized.get("chapter_summaries"), list) else []:
            if not isinstance(item, dict):
                summaries.append(item)
                continue
            summary = dict(item)
            cleaned_facts = self._clean_state_fact_list(summary.get("facts"))
            if cleaned_facts != summary.get("facts"):
                summary["facts"] = cleaned_facts
                changed = True
            for field in ("primary_conflict", "secondary_conflict", "event_beat"):
                coerced = self._clean_summary_mapping(summary.get(field), label=field)
                if coerced != summary.get(field):
                    summary[field] = coerced
                    changed = True
            summaries.append(summary)
        deduped_summaries = self._dedupe_numbered_records(summaries)
        if changed or deduped_summaries != sanitized.get("chapter_summaries"):
            sanitized["chapter_summaries"] = deduped_summaries
        if isinstance(sanitized.get("timeline"), list):
            sanitized["timeline"] = self._dedupe_numbered_records(list(sanitized.get("timeline") or []))
        if isinstance(sanitized.get("memory_index"), list):
            memory_records = []
            for item in sanitized.get("memory_index") or []:
                if isinstance(item, dict):
                    record = dict(item)
                    record["facts"] = self._clean_state_fact_list(record.get("facts"))
                    memory_records.append(record)
                else:
                    memory_records.append(item)
            sanitized["memory_index"] = self._dedupe_numbered_records(memory_records)
        return sanitized

    def _strip_temporary_generation_fields(self, state: dict[str, Any]) -> dict[str, Any]:
        stripped = dict(state)
        ledger = stripped.get("progression_ledger")
        if not isinstance(ledger, dict):
            return stripped
        ledger = dict(ledger)
        variant = ledger.get("simulation_variant")
        if isinstance(variant, dict) and "rewrite_guidance" in variant:
            variant = dict(variant)
            variant.pop("rewrite_guidance", None)
            ledger["simulation_variant"] = variant
            stripped["progression_ledger"] = ledger
        return stripped

    def _usable_bundle_state(self, updated_story: Any, current_state: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(updated_story, dict) or not updated_story:
            return current_state
        if updated_story.get("story_id") != current_state.get("story_id"):
            return current_state
        has_runtime_state = any(
            isinstance(updated_story.get(key), expected_type)
            for key, expected_type in (
                ("progression_ledger", dict),
                ("characters", list),
                ("chapter_summaries", list),
                ("time_state", dict),
            )
        )
        if not has_runtime_state:
            return current_state
        usable = self._strip_temporary_generation_fields(dict(updated_story))
        if isinstance(current_state.get("characters"), list):
            usable["characters"] = list(current_state.get("characters") or [])
        return usable

    def _chapter_summary_payload(self, chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        summary = dict(chapter.get("chapter_summary") or {})
        title = str(chapter.get("chapter_title") or summary.get("chapter_title") or f"Chapter {chapter_number}")
        summary_text = self._compact_text(summary.get("summary") or chapter.get("next_outline") or chapter.get("body"), 320)
        raw_facts = summary.get("facts") if isinstance(summary.get("facts"), list) else []
        facts = [self._compact_text(item, 220) for item in raw_facts if str(item).strip()]
        if summary_text and not facts:
            facts = [summary_text]
        return {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "cadence": summary.get("cadence") or chapter.get("cadence") or "measured",
            "summary": summary_text or f"Chapter {chapter_number}.",
            "facts": facts[:8],
            "unresolved_threads": [
                self._compact_text(item, 220)
                for item in (summary.get("unresolved_threads") if isinstance(summary.get("unresolved_threads"), list) else [])
                if str(item).strip()
            ][:8],
            "next_focus": self._compact_text(
                summary.get("next_focus")
                or chapter.get("next_outline")
                or (chapter.get("event_plan") or {}).get("next_focus")
                or "continue",
                220,
            ),
            "primary_conflict": self._coerce_summary_mapping(
                summary.get("primary_conflict") or chapter.get("conflict_summary", {}).get("primary_conflict"),
                label="primary_conflict",
            ),
            "secondary_conflict": self._coerce_summary_mapping(
                summary.get("secondary_conflict") or chapter.get("conflict_summary", {}).get("secondary_conflict"),
                label="secondary_conflict",
            ),
            "event_beat": self._coerce_summary_mapping(
                summary.get("event_beat") or chapter.get("event_beat"),
                label="event_beat",
            ),
        }

    def _replace_by_chapter_number(self, items: list[Any], entry: dict[str, Any], *, limit: int = 120) -> list[Any]:
        chapter_number = entry.get("chapter_number")
        filtered = [
            item
            for item in items
            if not (
                (isinstance(item, dict) and item.get("chapter_number") == chapter_number)
                or (
                    isinstance(item, str)
                    and chapter_number is not None
                    and re.match(rf"^\s*chapter\s+{int(chapter_number)}\s*:", item, re.IGNORECASE)
                )
            )
        ]
        filtered.append(entry)
        filtered.sort(key=lambda item: int(item.get("chapter_number") or 0) if isinstance(item, dict) else 0)
        return filtered[-limit:]

    def _dedupe_numbered_records(self, items: list[Any], *, limit: int = 240) -> list[Any]:
        """Keep one structured record per chapter and drop stale manual shells."""

        records: list[Any] = []
        seen_titles_by_number: dict[int, str] = {}
        for item in items:
            if isinstance(item, dict):
                try:
                    number = int(item.get("chapter_number") or 0)
                except (TypeError, ValueError):
                    number = 0
                title = str(item.get("chapter_title") or "").strip()
                if number > 0:
                    seen_titles_by_number[number] = title
                    records = [
                        existing
                        for existing in records
                        if not (
                            isinstance(existing, dict)
                            and int(existing.get("chapter_number") or 0) == number
                        )
                    ]
                    records.append(item)
                    continue
                if title and title not in seen_titles_by_number.values():
                    records.append(item)
                continue
            if isinstance(item, str) and re.match(r"^\s*chapter\s+\d+\s*:", item, re.IGNORECASE):
                continue
            records.append(item)
        numbered_titles = {title for title in seen_titles_by_number.values() if title}
        records = [
            item
            for item in records
            if not (
                isinstance(item, dict)
                and not int(item.get("chapter_number") or 0)
                and str(item.get("chapter_title") or "").strip() in numbered_titles
            )
        ]
        records.sort(key=lambda item: int(item.get("chapter_number") or 0) if isinstance(item, dict) else 0)
        return records[-limit:]

    def _derive_opening_progression_ledger(self, chapters: list[dict[str, Any]], current: dict[str, Any]) -> dict[str, Any]:
        """Rebuild the current game ledger from accepted opening chapters."""

        ledger = dict(current)
        text = "\n".join(
            str(part or "")
            for chapter in chapters
            for part in (
                chapter.get("body"),
                (chapter.get("chapter_summary") or {}).get("summary"),
                "\n".join(str(item) for item in ((chapter.get("chapter_summary") or {}).get("facts") or [])),
                (chapter.get("chapter_summary") or {}).get("next_focus"),
            )
        )
        protagonist = dict(ledger.get("protagonist") or {})
        panel = dict(ledger.get("panel") or {})
        economy = dict(ledger.get("economy") or {})
        equipment = dict(ledger.get("equipment") or {})
        quests = dict(ledger.get("quests") or {})

        level_matches = re.findall(r"(?:升到|提升[:：]?|当前|为)\s*Lv\.\s*(\d+)", text, flags=re.IGNORECASE)
        if not level_matches and "Lv.2" in text and any(token in text for token in ("升到", "升级", "等级", "提升")):
            level_matches = ["2"]
        if not level_matches:
            level_matches = re.findall(r"Lv\.\s*(\d+)", text, flags=re.IGNORECASE)
        if level_matches:
            level = f"Lv.{max(int(item) for item in level_matches)}"
            protagonist["level"] = level
            panel["level"] = level
        if "见习冒险者" in text or "未转职" in text:
            protagonist["identity"] = "见习冒险者（未转职）"
            protagonist["class_path"] = "见习冒险者（未转职）"
            panel["identity"] = "见习冒险者（未转职）"

        exp_matches = re.findall(r"经验\s*([0-9]+\s*/\s*[0-9]+)", text)
        if exp_matches:
            protagonist["exp"] = re.sub(r"\s+", "", exp_matches[-1])
        elif "等级升到Lv.2" in text or "Lv.2" in text:
            protagonist.setdefault("exp", "12/200")

        durability_matches = re.findall(r"(?:新手法杖[：:]\s*|法杖[^，。；\n]{0,12})(\d{1,2}\s*/\s*\d{1,2})", text)
        if durability_matches:
            equipment["weapon"] = "新手法杖"
            equipment["durability"] = re.sub(r"\s+", "", durability_matches[-1])
            protagonist["weapon_durability"] = f"新手法杖：{equipment['durability']}"
        elif "新手法杖" in text:
            equipment.setdefault("weapon", "新手法杖")

        inventory = self._derive_opening_inventory(chapters)
        if inventory:
            economy["inventory"] = inventory
        if "钱袋：空" in text or "钱袋空" in text or "钱袋又空" in text:
            economy["game_currency"] = "空"
        elif "30铜" in text or "三十铜" in text:
            economy["game_currency"] = "30铜"
        if "27.60" in text:
            economy["real_balance"] = "27.60元"
        if "清道夫委托已提交" in text or "清道夫委托完成" in text:
            quests["清道夫委托"] = "已提交；奖励30铜已领取"
        if "后坡登记" in text:
            quests["后坡登记"] = "清道夫委托完成后已开启，夜烬已进入后坡第一段"
        if "灰石裂缝" in text:
            quests["灰石裂缝"] = "已发现；混沌之种出现第二次响应"

        if protagonist:
            ledger["protagonist"] = protagonist
        if panel:
            ledger["panel"] = panel
        if economy:
            ledger["economy"] = economy
            ledger.pop("currency", None)
            ledger.pop("inventory", None)
        if equipment:
            ledger["equipment"] = equipment
        if quests:
            ledger["quests"] = quests
        return ledger

    def _chapter_text_for_ledger(self, chapter: dict[str, Any]) -> str:
        summary = chapter.get("chapter_summary") if isinstance(chapter.get("chapter_summary"), dict) else {}
        return "\n".join(
            str(part or "")
            for part in (
                chapter.get("body"),
                summary.get("summary"),
                "\n".join(str(item) for item in (summary.get("facts") or [])),
                summary.get("next_focus"),
            )
        )

    def _derive_opening_inventory(self, chapters: list[dict[str, Any]]) -> dict[str, int]:
        inventory: dict[str, int] = {}
        tracked = {"灰狼毒腺", "粗糙狼皮", "小法力药水"}
        for chapter in sorted(chapters, key=lambda item: int(item.get("chapter_number") or 0)):
            text = self._chapter_text_for_ledger(chapter)
            scoped_backpacks = [
                item
                for item in re.findall(r"背包[^。\n】]*", text)
                if any(name in item and "×" in item for name in tracked)
            ]
            if scoped_backpacks:
                scoped: dict[str, int] = {}
                for name, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX]\s*(\d+)", scoped_backpacks[-1]):
                    if name in tracked:
                        scoped[name] = int(count)
                if scoped:
                    inventory.update(scoped)
            if "清道夫委托已提交" in text or "清道夫委托完成" in text:
                inventory["灰狼毒腺"] = 0
            if int(chapter.get("chapter_number") or 0) > 2:
                for name, count in re.findall(r"([\u4e00-\u9fa5A-Za-z0-9·]+)\s*[×xX]\s*(\d+)", text):
                    if name in {"灰狼毒腺", "粗糙狼皮"}:
                        inventory[name] = int(inventory.get(name, 0)) + int(count)
            if "喝掉了小法力药水" in text and inventory.get("小法力药水", 0) > 0:
                inventory["小法力药水"] = int(inventory["小法力药水"]) - 1
        return inventory

    def _character_names_in_chapter(self, state: dict[str, Any], chapter: dict[str, Any]) -> list[str]:
        text = "\n".join(
            [
                str(chapter.get("chapter_title") or ""),
                str(chapter.get("body") or ""),
                str((chapter.get("chapter_summary") or {}).get("summary") or ""),
            ]
        )
        names: list[str] = []
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            name = str(character.get("name") or "").strip()
            game_id = str(character.get("game_id") or (character.get("game_panel") or {}).get("game_id") or "").strip()
            if (name and name in text) or (game_id and game_id in text):
                names.append(name or game_id)
        for move in chapter.get("character_moves", []) if isinstance(chapter.get("character_moves"), list) else []:
            if isinstance(move, dict) and str(move.get("name") or "").strip():
                names.append(str(move["name"]).strip())
        return self._merge_unique([], names, limit=16)

    def _chapter_entity_cards(self, chapter: dict[str, Any]) -> list[dict[str, Any]]:
        """Infer trackable NPC/system cards from visible chapter text.

        Web-game chapters often introduce durable entities as services or
        information surfaces rather than named people. They still need cards so
        later simulation can remember their boundaries.
        """
        chapter_number = int(chapter.get("chapter_number") or 0)
        text = "\n".join(
            [
                str(chapter.get("chapter_title") or ""),
                str(chapter.get("body") or ""),
                str((chapter.get("chapter_summary") or {}).get("summary") or ""),
            ]
        )
        specs = [
            {
                "name": "论坛",
                "triggers": ("论坛", "帖子"),
                "role": "信息源",
                "location": "内置论坛",
                "goal": "提供玩家传闻、掉率基准、价格噪声和开服情报",
                "memory": "论坛已出现为开服信息源：掉率、坐标、材料价格和玩家抱怨都从这里进入叙事。",
                "active": True,
            },
            {
                "name": "公共频道",
                "triggers": ("公共频道", "世界频道"),
                "role": "玩家群体",
                "location": "聊天频道",
                "goal": "暴露散人玩家情绪、抢怪冲突、组队需求和即时传闻",
                "memory": "公共频道持续滚动玩家喊话，是低可信但高频的世界噪声。",
                "active": False,
            },
            {
                "name": "交易行告示牌",
                "triggers": ("交易行", "告示牌", "求购："),
                "role": "市场机制",
                "location": "起始村广场",
                "goal": "显示求购单、均价、成交量和区域材料流通预警",
                "memory": "交易行告示牌已显示灰狼毒腺求购、均价和材料流通预警，是经济线的可见界面。",
                "active": True,
            },
            {
                "name": "药剂师NPC",
                "triggers": ("药剂师", "药剂铺"),
                "role": "服务NPC",
                "location": "起始村药剂铺",
                "goal": "按规则收取任务材料、出售法力药水并提示下一环任务",
                "memory": "药剂师NPC负责委托、药水价格和材料提交，话术机械且边界明确。",
                "active": True,
            },
            {
                "name": "药剂铺老妇人",
                "triggers": ("灰头巾老妇人", "老妇人", "药剂铺"),
                "role": "服务NPC",
                "location": "起始村药剂铺",
                "goal": "执行药剂铺收货规则：十份一批，少了不收",
                "memory": "药剂铺老妇人明确毒腺十份一批，不零收；单份交易需走交易木牌。",
                "active": False,
            },
            {
                "name": "清道夫委托",
                "triggers": ("清道夫委托", "提交十份灰狼毒腺"),
                "role": "任务线",
                "location": "起始村药剂铺",
                "goal": "用灰狼毒腺回收驱动新手任务，并逐步提高材料要求",
                "memory": "清道夫委托一环需要十份灰狼毒腺，奖励三十铜；下一环需要灰狼心脏。",
                "active": True,
            },
            {
                "name": "铁匠铺自助修理台",
                "triggers": ("自助修理台", "铁匠铺", "修复新手法杖"),
                "role": "服务设施",
                "location": "起始村铁匠铺",
                "goal": "提供装备修复并扣除铜币",
                "memory": "铁匠铺自助修理台可修复新手法杖，当前修复成本为三铜。",
                "active": False,
            },
            {
                "name": "白河仓库收购方",
                "triggers": ("白河仓库", "收购方", "收购规则"),
                "active_triggers": ("追问材料来源", "来源风险", "谈条件", "收购方问", "收购方说", "白河仓库的人", "仓库那边问"),
                "role": "收购方NPC",
                "location": "白河仓库",
                "goal": "确认材料能不能收、风险由谁担、来源是否干净",
                "memory": "白河仓库收购方围绕材料、价格、担保和来源风险与夜烬谈条件。",
                "active": False,
            },
            {
                "name": "系统公告",
                "triggers": ("系统滚动条", "系统公告", "区域材料流通预警"),
                "role": "系统机制",
                "location": "玩家界面",
                "goal": "以可见公告暴露协议提示、任务进度和风险变化",
                "memory": "系统公告/滚动条已用于呈现底层协议、隐藏优势和任务/路线进度反馈。",
                "active": True,
            },
        ]
        cards: list[dict[str, Any]] = []
        for spec in specs:
            if not any(trigger and trigger in text for trigger in spec["triggers"]):
                continue
            active = bool(spec["active"])
            active_triggers = spec.get("active_triggers")
            if isinstance(active_triggers, tuple) and any(trigger and trigger in text for trigger in active_triggers):
                active = True
            cards.append(
                {
                    "name": spec["name"],
                    "role": spec["role"],
                    "game_id": "",
                    "goals": [spec["goal"]],
                    "memory": [f"第{chapter_number}章：{spec['memory']}"] if chapter_number else [spec["memory"]],
                    "relationships": {},
                    "current_emotion": "steady",
                    "location": spec["location"],
                    "secrets": [],
                    "frozen": False,
                    "lifecycle_state": "active" if active else "proposed",
                    "last_proposed_chapter": chapter_number,
                    "last_approved_chapter": chapter_number if active else 0,
                    "introduced_by": f"chapter:{chapter_number}" if chapter_number else "chapter",
                    "npc_profile": {
                        "service_role": spec["role"],
                        "authority_scope": [spec["goal"]],
                        "information_limits": ["只能提供正文已可见的信息，不替作者解释规则。"],
                        "incentives": [],
                        "interaction_rules": ["作为界面、服务或NPC边界参与推演。"],
                    },
                }
            )
        return cards

    def _outline_text_for_chapter(self, project: dict[str, Any], chapter_number: int) -> str:
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        opening_arc = blueprint.get("opening_arc") if isinstance(blueprint.get("opening_arc"), dict) else {}
        beats = opening_arc.get("chapter_beats") if isinstance(opening_arc.get("chapter_beats"), list) else []
        parts = [str(project.get("current_focus") or ""), str(blueprint.get("current_arc") or "")]
        for beat in beats:
            if isinstance(beat, dict) and int(beat.get("chapter") or 0) == chapter_number:
                parts.extend(str(beat.get(key) or "") for key in ("title", "required_payoff", "ending_hook"))
        return "\n".join(parts)

    def _proposed_character_cards_from_outline(self, state: dict[str, Any], project: dict[str, Any]) -> list[dict[str, Any]]:
        target = int(state.get("current_chapter") or 0) + 1
        text = self._outline_text_for_chapter(project, target)
        specs: list[dict[str, Any]] = []
        if "白河仓库" in text or "收购方" in text or "收购" in text:
            specs.append(
                {
                    "name": "白河仓库收购方",
                    "role": "收购方NPC",
                    "location": "白河仓库",
                    "goals": ["确认材料能不能收、风险由谁担、来源是否干净。"],
                    "memory": [f"第{target}章计划出场：确认收购规则和交易风险，开始追问材料来源。"],
                    "character_type": "交易线NPC",
                    "core_motivation": "赚钱但怕担责，愿意收货，也会试探夜烬的材料来源。",
                    "behavior_logic": "先看货，再看担保和来源；话不说死，价格和风险一起压。",
                    "interaction_mode": "口语化谈条件，不替作者解释规则，只围绕货、价、担保和风险说话。",
                    "story_function": "把异常掉落从个人收益推进到交易渠道风险。",
                    "chapter_role": f"第{target}章待出场",
                }
            )
        if "村长" in text:
            specs.append(
                {
                    "name": "灰烬村村长",
                    "role": "村内任务NPC",
                    "location": "灰烬村",
                    "goals": ["只按村内记录和任务前置放行，不主动透露隐藏线。"],
                    "memory": [f"第{target}章大纲可能需要村长承接灰石裂缝记录。"],
                    "character_type": "任务节点NPC",
                    "core_motivation": "维护村内任务秩序，避免异常记录扩散。",
                    "behavior_logic": "只承认可见记录，不承认玩家猜测。",
                    "interaction_mode": "说话像办手续，能给的只给一半。",
                    "story_function": "承接隐藏路线和任务权限。",
                    "chapter_role": f"第{target}章待出场",
                }
            )
        cards: list[dict[str, Any]] = []
        for spec in specs:
            cards.append(
                {
                    **spec,
                    "current_emotion": "steady",
                    "frozen": False,
                    "lifecycle_state": "proposed",
                    "last_proposed_chapter": target,
                    "last_approved_chapter": 0,
                    "introduced_by": f"outline:{target}",
                    "npc_profile": {
                        "service_role": spec["role"],
                        "authority_scope": spec["goals"],
                        "information_limits": ["出场前只作为写作包候选卡；正文未写到之前不能当成已出场事实。"],
                        "interaction_rules": ["如果本章使用这个人物，必须先按角色卡写，不得临场换身份。"],
                    },
                }
            )
        return cards

    def _canonical_character_name(self, name: str) -> str:
        aliases = {
            "药剂师NPC": "药剂师洛婶",
            "药剂师": "药剂师洛婶",
            "药剂铺老妇人": "药剂师洛婶",
            "灰头巾老妇人": "药剂师洛婶",
            "老妇人": "药剂师洛婶",
            "洛婶": "药剂师洛婶",
            "补给商·铁栓": "仓库管理员铁栓",
            "补给商铁栓": "仓库管理员铁栓",
            "铁栓": "仓库管理员铁栓",
        }
        return aliases.get(name.strip(), name.strip())

    def _is_character_card(self, card: dict[str, Any]) -> bool:
        name = self._canonical_character_name(str(card.get("name") or ""))
        role = str(card.get("role") or "").strip()
        if not name:
            return False
        if name in {"论坛", "公共频道", "交易行告示牌", "清道夫委托", "系统公告"}:
            return False
        if role in {"信息源", "玩家群体", "市场机制", "任务线", "服务设施", "系统机制"}:
            return False
        return True

    def _merge_character_cards(self, existing: list[Any], additions: list[dict[str, Any]]) -> list[dict[str, Any]]:
        by_name: dict[str, dict[str, Any]] = {}
        for item in existing:
            if not isinstance(item, dict):
                continue
            item = dict(item)
            name = self._canonical_character_name(str(item.get("name") or ""))
            if name:
                item["name"] = name
            if not self._is_character_card(item):
                continue
            if name:
                by_name[name] = dict(item)
        for card in additions:
            card = dict(card)
            name = self._canonical_character_name(str(card.get("name") or ""))
            if not name:
                continue
            card["name"] = name
            if not self._is_character_card(card):
                continue
            current = dict(by_name.get(name) or {"name": name})
            current["role"] = current.get("role") or card.get("role") or "NPC"
            current["game_id"] = current.get("game_id") or card.get("game_id") or ""
            if card.get("game_panel"):
                panel = dict(current.get("game_panel") or {})
                panel.update({key: value for key, value in dict(card.get("game_panel") or {}).items() if value not in (None, "", [], {})})
                current["game_panel"] = panel
            for field in (
                "character_type",
                "core_motivation",
                "behavior_logic",
                "interaction_mode",
                "story_function",
                "chapter_role",
                "social_profile",
                "psychological_profile",
                "moral_profile",
                "performance_profile",
            ):
                if card.get(field) and not current.get(field):
                    current[field] = card[field]
            current["goals"] = self._merge_unique(list(current.get("goals") or []), list(card.get("goals") or []), limit=8)
            current["memory"] = self._merge_unique(list(current.get("memory") or []), list(card.get("memory") or []), limit=20)
            current["poison_points"] = self._merge_unique(
                list(current.get("poison_points") or []),
                list(card.get("poison_points") or []),
                limit=8,
            )
            current["location"] = card.get("location") or current.get("location") or ""
            current["current_emotion"] = current.get("current_emotion") or card.get("current_emotion") or "steady"
            current["relationships"] = current.get("relationships") or {}
            current["secrets"] = current.get("secrets") or []
            current["frozen"] = bool(current.get("frozen") or False)
            if current.get("lifecycle_state") != "active":
                current["lifecycle_state"] = card.get("lifecycle_state") or current.get("lifecycle_state") or "proposed"
            current["last_proposed_chapter"] = max(
                int(current.get("last_proposed_chapter") or 0),
                int(card.get("last_proposed_chapter") or 0),
            )
            current["last_approved_chapter"] = max(
                int(current.get("last_approved_chapter") or 0),
                int(card.get("last_approved_chapter") or 0),
            )
            current["introduced_by"] = current.get("introduced_by") or card.get("introduced_by") or ""
            if card.get("npc_profile") and not current.get("npc_profile"):
                current["npc_profile"] = card["npc_profile"]
            by_name[name] = current
        return list(by_name.values())

    def _protagonist_character_card(self, state: dict[str, Any], project: dict[str, Any] | None = None) -> dict[str, Any] | None:
        ledger = state.get("progression_ledger") if isinstance(state.get("progression_ledger"), dict) else {}
        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
        name = str(protagonist.get("real_name") or "苏叶").strip()
        game_id = str(protagonist.get("game_id") or "夜烬").strip()
        if not name and not game_id:
            return None
        current_chapter = int(state.get("current_chapter") or 0)
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}
        skills = protagonist.get("skills") if isinstance(protagonist.get("skills"), list) else []
        weapon = str(equipment.get("weapon") or "新手法杖").strip()
        durability = str(equipment.get("durability") or protagonist.get("weapon_durability") or "").strip()
        return {
            "name": name or game_id,
            "role": "protagonist",
            "game_id": game_id,
            "character_type": "现实压力型网游主角",
            "core_motivation": "先解决现实账单，再把千倍爆率藏在幕后，换成等级、装备、路线和交易渠道优势。",
            "behavior_logic": "先看成本、退路和暴露风险，再动手；能用规则和地形解决，就不正面炫耀。",
            "interaction_mode": "对外少说异常，只说够用的理由；面对NPC按规则办事，面对玩家保持普通新手的样子。",
            "story_function": "承载现实压力、隐藏优势和新手村快速成长线。",
            "chapter_role": "主视角",
            "goals": [
                "在《天启之门》前期暗中拉开进度。",
                "继续把异常掉落转成稳定收益，同时不暴露千倍爆率。",
            ],
            "memory": [
                "现实急账已在第一章通过裂纹狼心担保交易解决，余额312.60元。",
                f"当前进度：{protagonist.get('level') or 'Lv.3'}，经验{protagonist.get('exp') or ''}。",
                "核心异常：底层协议校验通过、掉落判定×1000、混沌之种未解析。",
            ],
            "location": "灰烬村 / 灰石裂缝外沿",
            "current_emotion": "克制",
            "secrets": ["掉落判定×1000", "混沌之种未解析"],
            "poison_points": ["不能写成装高手", "不能让外人全知主角异常", "对话要口语化并说完整"],
            "game_panel": {
                "game_id": game_id,
                "level": protagonist.get("level") or (ledger.get("panel") or {}).get("level"),
                "class_path": protagonist.get("class_path") or protagonist.get("identity") or "见习冒险者（未转职）",
                "exp": protagonist.get("exp") or "",
                "hp": protagonist.get("hp") or "",
                "mp": protagonist.get("mp") or "",
                "skills": skills,
                "equipment": {
                    "武器": weapon,
                    "耐久": durability,
                    "强化": equipment.get("modifier") or "",
                },
                "inventory": inventory,
                "currency": economy.get("game_currency") or "",
                "quests": quests,
                "updated_chapter": current_chapter,
            },
            "performance_profile": {
                "speech_style": "白话、完整、少装腔；解释选择时把原因说清。",
                "action_style": "先观察规则和地形，再做低风险动作。",
                "risk_posture": "隐藏异常收益，避免被玩家和NPC提前盯上。",
                "decision_rules": ["不公开千倍爆率", "优先解决现实压力和游戏内续航", "每章要有可见成长"],
            },
            "frozen": False,
            "lifecycle_state": "active",
            "last_proposed_chapter": current_chapter,
            "last_approved_chapter": current_chapter,
            "introduced_by": "baseline:protagonist",
        }

    def _infer_chapter_duration_minutes(self, chapter: dict[str, Any]) -> int:
        text = "\n".join([str(chapter.get("body") or ""), str((chapter.get("chapter_summary") or {}).get("summary") or "")])
        explicit_minutes = [int(value) for value in re.findall(r"(\d{1,3})\s*分钟", text)]
        if explicit_minutes:
            return max(10, min(240, explicit_minutes[-1]))
        explicit_hours = [int(value) for value in re.findall(r"(\d{1,2})\s*小时", text)]
        if explicit_hours:
            return max(30, min(360, explicit_hours[-1] * 60))
        if any(token in text for token in ("回村", "交任务", "修复", "购买", "寄售", "职业大厅")):
            return 45
        if any(token in text for token in ("灰狼坡深处", "副本", "试炼", "赶路", "采样")):
            return 60
        return 40

    def _clock_label(self, minutes_since_launch: int) -> str:
        day = minutes_since_launch // (24 * 60) + 1
        minute_of_day = minutes_since_launch % (24 * 60)
        if minute_of_day < 5 * 60:
            phase = "深夜"
        elif minute_of_day < 8 * 60:
            phase = "清晨"
        elif minute_of_day < 12 * 60:
            phase = "上午"
        elif minute_of_day < 14 * 60:
            phase = "中午"
        elif minute_of_day < 18 * 60:
            phase = "下午"
        elif minute_of_day < 21 * 60:
            phase = "傍晚"
        else:
            phase = "夜晚"
        return f"开服第{day}天{phase}"

    def _sync_time_state_after_chapter(self, state: dict[str, Any], project: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return {}
        existing = dict(state.get("time_state") or ((project.get("world_blueprint") or {}).get("time_state") or {}))
        launch_offset = int(existing.get("launch_clock_offset_minutes") or 17 * 60)
        previous_elapsed = int(existing.get("elapsed_minutes_since_launch") or 0)
        spans = [
            dict(item)
            for item in existing.get("chapter_time_spans", [])
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) != chapter_number
        ]
        # Replaying earlier chapters should rebuild elapsed time from the remaining spans.
        previous_elapsed = sum(int(item.get("duration_minutes") or 0) for item in spans)
        duration = self._infer_chapter_duration_minutes(chapter)
        start_label = self._clock_label(launch_offset + previous_elapsed)
        end_minutes = previous_elapsed + duration
        end_label = self._clock_label(launch_offset + end_minutes)
        span = {
            "chapter_number": chapter_number,
            "chapter_title": chapter.get("chapter_title") or f"Chapter {chapter_number}",
            "start": start_label,
            "end": end_label,
            "duration_minutes": duration,
            "scene_time": f"第{chapter_number}章章末",
        }
        spans.append(span)
        spans.sort(key=lambda item: int(item.get("chapter_number") or 0))
        total_elapsed = sum(int(item.get("duration_minutes") or 0) for item in spans)
        day = total_elapsed // (24 * 60) + 1
        time_state = {
            "server_day": day,
            "server_phase": f"开服第{day}天",
            "game_clock": self._clock_label(launch_offset + total_elapsed).replace(f"开服第{day}天", "") or "开服初期",
            "real_clock": existing.get("real_clock") or "晚上",
            "launch_clock_offset_minutes": launch_offset,
            "current_scene_time": f"第{chapter_number}章章末",
            "elapsed_minutes_since_launch": total_elapsed,
            "elapsed_since_launch": f"约{max(1, round(total_elapsed / 60, 1))}小时",
            "chapter_time_spans": spans[-120:],
            "cooldowns": existing.get("cooldowns") or [],
            "scheduled_events": existing.get("scheduled_events") or [],
            "time_rules": self._merge_unique(
                list(existing.get("time_rules") or []),
                [
                    "下一章必须承接 current_scene_time，除非正文明确下线、过夜或长途赶路。",
                    "前期开服节奏按小时推进，不要无说明跳到第二天或跨越大量任务。",
                    "寄售、任务、怪物刷新和NPC服务需要写出等待、路程或冷却代价。",
                ],
                limit=20,
            ),
        }
        state["time_state"] = time_state
        return time_state

    def _sync_state_after_chapter(self, state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return state
        synced = dict(state)
        summary = self._chapter_summary_payload(chapter)
        synced["current_chapter"] = max(int(synced.get("current_chapter") or 0), chapter_number)
        synced["chapter_summaries"] = self._replace_by_chapter_number(
            list(synced.get("chapter_summaries") or []),
            summary,
            limit=240,
        )
        chapter_fact_prefix = f"第{chapter_number}章事实："
        chapter_summary_prefix = f"第{chapter_number}章摘要："
        existing_world_facts = [
            str(item)
            for item in list(synced.get("world_facts") or [])
            if not str(item).startswith(chapter_fact_prefix) and not str(item).startswith(chapter_summary_prefix)
        ]
        facts = [f"第{chapter_number}章事实：{fact}" for fact in summary["facts"]]
        facts.append(f"第{chapter_number}章摘要：{summary['summary']}")
        synced["world_facts"] = self._merge_unique(existing_world_facts, facts, limit=260)
        timeline_entry = {
            "chapter_number": chapter_number,
            "summary": summary["summary"],
            "impact": summary["next_focus"],
        }
        synced["timeline"] = self._replace_by_chapter_number(
            list(synced.get("timeline") or []),
            timeline_entry,
            limit=240,
        )
        memory_entry = {
            "chapter_number": chapter_number,
            "chapter_title": summary["chapter_title"],
            "summary": summary["summary"],
            "tags": [],
            "characters": self._character_names_in_chapter(synced, chapter),
            "locations": [],
            "factions": [],
            "quests": [],
            "items": [],
            "facts": summary["facts"],
            "unresolved_threads": summary["unresolved_threads"],
        }
        protagonist_card = self._protagonist_character_card(synced, self.project())
        protagonist_cards = [protagonist_card] if protagonist_card else []
        synced["characters"] = self._merge_character_cards(
            list(synced.get("characters") or []),
            [*protagonist_cards, *self._chapter_entity_cards(chapter)],
        )
        character_entity_names = [
            self._canonical_character_name(str(card.get("name") or ""))
            for card in self._chapter_entity_cards(chapter)
            if self._is_character_card(card)
        ]
        memory_entry["characters"] = self._merge_unique(
            list(memory_entry["characters"]),
            [*(["苏叶"] if protagonist_card else []), *character_entity_names],
            limit=24,
        )
        synced["memory_index"] = self._replace_by_chapter_number(
            list(synced.get("memory_index") or []),
            memory_entry,
            limit=240,
        )
        self._sync_time_state_after_chapter(synced, self.project(), chapter)
        return synced

    def _sync_project_after_chapter(self, project: dict[str, Any], state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            return project
        summary = self._chapter_summary_payload(chapter)
        synced = dict(project)
        is_game_story = self._is_game_story_payload(synced, state)
        blueprint = dict(synced.get("world_blueprint") or {})
        continuity = dict(blueprint.get("continuity_state") or {})
        previous_chapter_facts: list[str] = []
        for item in continuity.get("chapter_facts", []) if isinstance(continuity.get("chapter_facts"), list) else []:
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) == chapter_number:
                previous_chapter_facts = [str(fact) for fact in item.get("facts") or [] if str(fact).strip()]
                break
        chapter_record = {
            "chapter_number": chapter_number,
            "chapter_title": summary["chapter_title"],
            "summary": summary["summary"],
            "facts": summary["facts"],
            "unresolved_threads": summary["unresolved_threads"],
            "next_focus": summary["next_focus"],
        }
        continuity["latest_chapter"] = chapter_number
        continuity["latest_title"] = summary["chapter_title"]
        continuity["latest_summary"] = summary["summary"]
        continuity["next_focus"] = summary["next_focus"]
        continuity["chapter_facts"] = self._replace_by_chapter_number(
            list(continuity.get("chapter_facts") or []),
            chapter_record,
            limit=120,
        )
        existing_running_facts = [
            str(item)
            for item in list(continuity.get("running_facts") or [])
            if str(item) not in previous_chapter_facts
        ]
        continuity["running_facts"] = self._merge_unique(
            existing_running_facts,
            summary["facts"],
            limit=160,
        )
        blueprint["continuity_state"] = continuity
        if isinstance(state.get("time_state"), dict):
            blueprint["time_state"] = state["time_state"]
        synced["world_blueprint"] = blueprint
        if summary["next_focus"] and summary["next_focus"] != "continue":
            synced["current_focus"] = summary["next_focus"]

        existing_profiles: list[dict[str, Any]] = []
        for item in synced.get("character_profiles", []) if isinstance(synced.get("character_profiles"), list) else []:
            if not isinstance(item, dict):
                continue
            profile = dict(item)
            name = self._canonical_character_name(str(profile.get("name") or ""))
            if not name:
                continue
            profile["name"] = name
            if not self._is_character_card(profile):
                continue
            existing_profiles.append(profile)
        by_name = {str(item.get("name")): item for item in existing_profiles}
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            character = dict(character)
            name = self._canonical_character_name(str(character.get("name") or ""))
            if not name:
                continue
            character["name"] = name
            if not self._is_character_card(character):
                continue
            profile = dict(by_name.get(name) or {"name": name})
            for key in ("role", "game_id", "goals", "secrets", "relationships", "lifecycle_state"):
                if character.get(key) not in (None, "", [], {}):
                    profile[key] = character.get(key)
            if isinstance(character.get("real_state"), dict) and character["real_state"]:
                profile["real_state"] = deepcopy(character["real_state"])
            elif not is_game_story:
                profile.pop("game_state", None)
            if is_game_story and isinstance(character.get("game_state"), dict) and character["game_state"]:
                profile["game_state"] = deepcopy(character["game_state"])
            profile["current_emotion"] = character.get("current_emotion") or profile.get("current_emotion") or "neutral"
            profile["current_location"] = character.get("location") or profile.get("current_location") or ""
            profile["latest_chapter"] = chapter_number
            memories = character.get("memory") if isinstance(character.get("memory"), list) else []
            if memories:
                profile["memory"] = self._merge_unique(
                    list(profile.get("memory") or []),
                    [self._compact_text(item, 180) for item in memories[-6:]],
                    limit=40,
                )
            game_panel = character.get("game_panel")
            if isinstance(game_panel, dict) and game_panel:
                panel = dict(game_panel)
                if is_game_story and isinstance(character.get("game_state"), dict):
                    current = character["game_state"].get("current")
                    if isinstance(current, dict):
                        for field in _GAME_STATE_FIELDS:
                            value = current.get(field)
                            if value not in (None, "", [], {}):
                                panel[field] = deepcopy(value)
                profile["game_panel"] = panel | {"updated_chapter": chapter_number}
            if not is_game_story:
                profile.pop("game_state", None)
            by_name[name] = profile
        synced["character_profiles"] = list(by_name.values())
        relationship_updates: list[dict[str, Any]] = []
        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict):
                continue
            source = self._canonical_character_name(str(character.get("name") or ""))
            relationships = character.get("relationships")
            if isinstance(relationships, dict):
                items = relationships.items()
            elif isinstance(relationships, list):
                items = (("", item) for item in relationships)
            else:
                items = ()
            for fallback_target, relation in items:
                if not isinstance(relation, dict):
                    continue
                target = self._canonical_character_name(
                    str(relation.get("target") or relation.get("name") or fallback_target or "")
                )
                if not source or not target or source == target:
                    continue
                relation_summary = self._compact_text(
                    relation.get("current_state")
                    or relation.get("bond")
                    or summary.get("summary")
                    or "关系状态更新",
                    180,
                )
                relationship_updates.append(
                    {
                        "source": source,
                        "target": target,
                        "relation_type": relation.get("relation_type"),
                        "bond": relation.get("bond"),
                        "current_state": relation.get("current_state"),
                        "trust": relation.get("trust"),
                        "tension": relation.get("tension"),
                        "last_changed_chapter": chapter_number,
                        "changes": [
                            {
                                "chapter_number": chapter_number,
                                "summary": relation_summary,
                                "trust": relation.get("trust"),
                                "tension": relation.get("tension"),
                            }
                        ],
                    }
                )
        synced["relationship_graph"] = apply_relationship_updates(
            synced.get("relationship_graph"), relationship_updates
        )
        return synced

    def _sync_after_chapter(self, chapter: dict[str, Any], state: dict[str, Any] | None = None) -> dict[str, Any]:
        base_state = dict(state or self.state())
        synced_state = self._sync_state_after_chapter(base_state, chapter)
        synced_state = self._sync_ledger_from_chapter_body(synced_state, chapter)
        chapter["updated_story"] = synced_state
        chapter["chapter_summary"] = self._chapter_summary_payload(chapter)
        new_lessons = lessons_from_quality_report(chapter.get("quality_report") if isinstance(chapter.get("quality_report"), dict) else {})
        synced_state["writing_lessons"] = merge_writing_lessons(synced_state.get("writing_lessons"), new_lessons)
        chapter["updated_story"] = synced_state
        synced_project = self._sync_project_after_chapter(self.project(), synced_state, chapter)
        blueprint = dict(synced_project.get("world_blueprint") or {})
        blueprint["writing_learning"] = learning_snapshot(synced_state.get("writing_lessons"))
        synced_project["world_blueprint"] = blueprint
        self._write_json(self.webnovel_dir / "state.json", synced_state)
        self._write_json(self.webnovel_dir / "project.json", synced_project)
        return synced_state

    def _state_before_chapter(self, chapter_number: int) -> dict[str, Any]:
        current_state = dict(self.state())
        if int(current_state.get("current_chapter") or 0) == chapter_number:
            current_state["current_chapter"] = max(0, chapter_number - 1)
            return current_state
        if chapter_number > 1:
            previous = self.chapter(chapter_number - 1)
            previous_state = previous.get("updated_story") if isinstance(previous, dict) else {}
            if isinstance(previous_state, dict) and previous_state:
                return dict(previous_state)
        state = current_state
        state["current_chapter"] = max(0, chapter_number - 1)
        state["progression_ledger"] = {}
        return state

    def _chapter_body_ledger_summary(self, chapter: dict[str, Any], ledger: dict[str, Any]) -> dict[str, Any]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("chapter_title") or f"第{chapter_number}章")
        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests") if isinstance(ledger.get("quests"), dict) else {}
        inventory = economy.get("inventory") if isinstance(economy.get("inventory"), dict) else {}

        exp = str(protagonist.get("exp") or "").strip()
        hp = str(protagonist.get("hp") or "").strip()
        mp = str(protagonist.get("mp") or "").strip()
        durability = str(equipment.get("durability") or "").strip()
        currency = str(economy.get("game_currency") or "").strip()
        backpack = str(economy.get("backpack") or "").strip()

        inv_text = "、".join(f"{name}×{count}" for name, count in inventory.items()) if inventory else "空"
        facts: list[str] = [
            "苏叶现实余额27.60元未变" if "27.60元" in str(chapter.get("body") or "") else "",
            f"夜烬仍为Lv.1见习冒险者（未转职）",
            f"经验{exp}" if exp else "",
            f"生命{hp}" if hp else "",
            f"法力{mp}" if mp else "",
            f"新手法杖{durability}" if durability else "",
            f"钱袋{currency}" if currency else "",
            f"背包为{inv_text}" + (f"，占用{backpack}" if backpack else ""),
        ]
        for name, value in quests.items():
            text = str(value).strip()
            if text:
                facts.append(f"{name}：{text}")
        facts = [item for item in facts if item]

        quest_focus = ""
        for name in ("后坡巡查", "清道夫委托"):
            if name in quests:
                quest_focus = f"{name}{quests[name]}"
                break
        summary = f"夜烬本章推进{quest_focus or '当前任务'}，章末账本为经验{exp or '未明'}、生命{hp or '未明'}、法力{mp or '未明'}、钱袋{currency or '未明'}、背包{inv_text}。"
        next_focus = "继续补给并推进后坡巡查剩余进度，隐藏千倍掉落来源。"
        if "后坡巡查" in quests and "2/3" in str(quests["后坡巡查"]):
            next_focus = "先解决血蓝和补给，再完成后坡巡查最后一段。"
        return {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "cadence": "measured",
            "summary": summary,
            "facts": facts[:12],
            "unresolved_threads": [
                item
                for item in (
                    "后坡巡查还未完成" if "后坡巡查" in quests and "2/3" in str(quests["后坡巡查"]) else "",
                    "现实余额仍未改变" if "27.60元" in str(chapter.get("body") or "") else "",
                    "混沌之种仍未解析" if "混沌之种" in str(chapter.get("body") or "") else "",
                )
                if item
            ],
            "next_focus": next_focus,
            "primary_conflict": {"collision": next_focus},
            "secondary_conflict": {"detail": "旁人只能把夜烬看成低血、熟路或运气好的散人。"},
            "event_beat": {"turn": "任务推进", "pivot": next_focus},
        }

    def _sync_game_character_from_ledger(
        self,
        character: dict[str, Any],
        ledger: dict[str, Any],
        *,
        chapter_number: int | None = None,
    ) -> dict[str, Any]:
        """Write game ledger leaves to game_state and its legacy panel only."""

        protagonist = ledger.get("protagonist") if isinstance(ledger.get("protagonist"), dict) else {}
        economy = ledger.get("economy") if isinstance(ledger.get("economy"), dict) else {}
        equipment = ledger.get("equipment") if isinstance(ledger.get("equipment"), dict) else {}
        quests = ledger.get("quests")
        pressure = ledger.get("pressure") if isinstance(ledger.get("pressure"), dict) else {}
        panel = dict(character.get("game_panel") or {})
        game_state = dict(character.get("game_state") or {})
        current = dict(game_state.get("current") or {}) if isinstance(game_state.get("current"), dict) else {}
        previous_current = deepcopy(current)

        game_id = protagonist.get("game_id") or current.get("game_id") or panel.get("game_id") or character.get("game_id")
        if not game_id and character.get("name") == "苏叶":
            game_id = "夜烬"
        values = {
            "game_id": game_id,
            "level": protagonist.get("level"),
            "class_path": protagonist.get("class_path"),
            "exp": protagonist.get("exp"),
            "hp": protagonist.get("hp"),
            "mp": protagonist.get("mp"),
            "attributes": protagonist.get("attributes"),
            "equipment": equipment,
            "inventory": economy.get("inventory"),
            "backpack": economy.get("backpack"),
            "currency": economy.get("game_currency") or economy.get("currency") or ledger.get("currency"),
            "quests": quests,
            "risk": pressure,
        }
        skills = ledger.get("skills")
        if isinstance(skills, list):
            values["skills"] = [str(item) for item in skills if str(item).strip()]
        elif isinstance(skills, dict):
            values["skills"] = [
                str(item)
                for value in skills.values()
                for item in (value if isinstance(value, list) else [value])
                if str(item).strip()
            ]

        for field, value in values.items():
            if value in (None, "", [], {}):
                continue
            current[field] = deepcopy(value)
            panel[field] = deepcopy(value)
        if current.get("game_id"):
            character["game_id"] = current["game_id"]
        if chapter_number is not None:
            panel["updated_chapter"] = chapter_number
        game_state["current"] = current
        game_state.setdefault("recent_changes", [])
        changed_fields = [
            field
            for field in values
            if previous_current.get(field) != current.get(field)
        ]
        if chapter_number is not None and changed_fields:
            fact = f"游戏账本更新：{', '.join(changed_fields[:5])}"
            recent_changes = game_state["recent_changes"]
            if not any(
                isinstance(item, dict)
                and item.get("chapter") == int(chapter_number)
                and item.get("fact") == fact
                for item in recent_changes
            ):
                recent_changes.append({"chapter": int(chapter_number), "fact": fact})
        character["game_state"] = game_state
        character["game_panel"] = panel
        return character

    @staticmethod
    def _chapter_state_events(chapter: dict[str, Any]) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        for key in ("state_changes", "events", "ledger_events"):
            raw = chapter.get(key)
            if isinstance(raw, dict):
                raw = raw.get("events") or raw.get("changes") or []
            if isinstance(raw, list):
                events.extend(item for item in raw if isinstance(item, dict))
        summary = chapter.get("chapter_summary")
        if isinstance(summary, dict) and isinstance(summary.get("state_changes"), list):
            events.extend(item for item in summary["state_changes"] if isinstance(item, dict))
        return events

    @staticmethod
    def _event_change_payload(
        event: dict[str, Any],
        *,
        line: str,
        strict_namespace: bool = False,
    ) -> dict[str, Any]:
        change = event.get("change") or event.get("state_change") or event.get("state_delta")
        if not isinstance(change, dict):
            change = {}
        namespace_keys = {"real_change", "real_state", "game_change", "game_state"}
        has_namespace = any(key in event or key in change for key in namespace_keys)
        if line == "reality":
            candidates = (
                event.get("real_change"),
                event.get("real_state"),
                change.get("real_change"),
                change.get("real_state"),
            )
        else:
            candidates = (
                event.get("game_change"),
                event.get("game_state"),
                change.get("game_change"),
                change.get("game_state"),
            )
        selected = next((item for item in candidates if isinstance(item, dict)), None) if has_namespace else None
        if selected is None and not has_namespace and not strict_namespace:
            selected = change
        if not isinstance(selected, dict):
            return {}
        if isinstance(selected.get("current"), dict):
            current = selected["current"]
        else:
            current = {
                key: value
                for key, value in selected.items()
                if key not in {"line", "scene_line", "fact", "recent_changes", "real_change", "game_change"}
            }
        return {
            "current": deepcopy(current),
            "fact": str(event.get("fact") or selected.get("fact") or change.get("fact") or "").strip(),
        } if current else {}

    def _apply_chapter_state_events(
        self,
        state: dict[str, Any],
        chapter: dict[str, Any],
        *,
        is_game_story: bool,
    ) -> None:
        chapter_number = int(chapter.get("chapter_number") or 0)
        characters = state.get("characters") if isinstance(state.get("characters"), list) else []
        for event in self._chapter_state_events(chapter):
            raw_line = str(event.get("line") or event.get("scene_line") or "").strip().lower()
            if raw_line in {"游戏", "game_state"}:
                raw_line = "game"
            elif raw_line in {"现实", "real", "real_state"}:
                raw_line = "reality"
            elif raw_line in {"混合", "mixed", "过渡", "切换"}:
                raw_line = "transition"
            if raw_line not in {"game", "reality", "transition"}:
                continue
            lines = ("reality", "game") if raw_line == "transition" else (raw_line,)
            for line in lines:
                if line == "game" and not is_game_story:
                    continue
                change = self._event_change_payload(
                    event,
                    line=line,
                    strict_namespace=raw_line == "transition",
                )
                if not isinstance(change.get("current"), dict) or not change["current"]:
                    continue
                target = str(event.get("character") or event.get("character_name") or event.get("target") or "").strip()
                if target:
                    selected = [
                        item
                        for item in characters
                        if isinstance(item, dict) and item.get("name") == target
                    ]
                    if not selected:
                        continue
                else:
                    selected = [
                        item
                        for item in characters
                        if isinstance(item, dict) and item.get("role") in {"protagonist", "主角"}
                    ]
                    if not selected:
                        selected = [item for item in characters if isinstance(item, dict)][:1]
                for character in selected:
                    state_key = "game_state" if line == "game" else "real_state"
                    existing = character.get(state_key) if isinstance(character.get(state_key), dict) else {}
                    existing_current = existing.get("current") if isinstance(existing.get("current"), dict) else {}
                    if not any(existing_current.get(key) != value for key, value in change["current"].items()):
                        continue
                    merged = merge_state_change(
                        character,
                        line=line,
                        change=change,
                        chapter=chapter_number,
                    )
                    character.clear()
                    character.update(merged)
                    if line == "game":
                        _sync_game_panel_from_state(character)

    def _sync_ledger_from_chapter_body(self, state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        body = str(chapter.get("body") or "")
        is_game_story = self._is_game_story_payload(self.project(), state)
        if not body or not is_game_story:
            self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
            return state
        chinese_markers = (
            "经验",
            "生命",
            "法力",
            "钱袋：",
            "钱袋:",
            "背包：",
            "背包:",
            "新手法杖",
            "后坡巡查",
            "清道夫委托",
            "铜币",
            "等级：",
            "等级:",
            "任务：",
            "任务:",
        )
        english_field = re.search(
            r"\b(?:experience|exp|hp|health|mp|mana|inventory|backpack|level|durability|equipment)\s*(?:[:=]|\s+\d)",
            body,
            flags=re.IGNORECASE,
        )
        currency_field = re.search(
            r"\b(?:currency|coins?)\s*[:=]",
            body,
            flags=re.IGNORECASE,
        )
        amount_context = re.search(
            r"\b\d+(?:\.\d+)?\s*(?:coins?|copper|gold|silver)\b",
            body,
            flags=re.IGNORECASE,
        )
        if not any(marker in body for marker in chinese_markers) and not (english_field or currency_field or amount_context):
            self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
            return state
        ledger = dict(state.get("progression_ledger") or {})
        protagonist = dict(ledger.get("protagonist") or {})
        panel = dict(ledger.get("panel") or {})
        economy = dict(ledger.get("economy") or {})
        equipment = dict(ledger.get("equipment") or {})
        quests = dict(ledger.get("quests") or {})

        def last(pattern: str) -> str:
            matches = re.findall(pattern, body, flags=re.IGNORECASE)
            return str(matches[-1]).strip() if matches else ""

        level = last(r"(?:等级|level)\s*(?:[：:]\s*)?(?:lv\.\s*)?(\d+)")
        exp = last(r"(?:经验|experience|exp)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)")
        hp = last(r"(?:生命|hp|health)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)")
        mp = last(r"(?:法力|mp|mana)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+)")
        durability = last(r"(?:新手法杖|耐久|durability)\s*(?:[：:]\s*)?(\d+\s*/\s*\d+|\d{1,3}%)")
        money = last(r"(?:钱袋\s*[：:]|currency\s*[:=]|coins?\s*[:=])\s*([^\n。；,，】]+)")
        if not money:
            amount_matches = re.findall(
                r"\b\d+(?:\.\d+)?\s*(?:coins?|copper|gold|silver)\b",
                body,
                flags=re.IGNORECASE,
            )
            money = str(amount_matches[-1]).strip() if amount_matches else ""
        patrol = last(r"后坡巡查[：:]\s*(\d+\s*/\s*\d+)")
        quest_line = last(r"(?:任务\s*[：:]|quest(?:\s+status)?\s*[:=])\s*([^\n。】]+)")

        if level:
            protagonist["level"] = f"Lv.{level}"
            panel["level"] = protagonist["level"]
        if exp:
            protagonist["exp"] = exp.replace(" ", "")
            panel["exp"] = protagonist["exp"]
        if hp:
            protagonist["hp"] = hp.replace(" ", "")
        if mp:
            protagonist["mp"] = mp.replace(" ", "")
        if durability:
            protagonist["weapon_durability"] = f"新手法杖：{durability.replace(' ', '')}"
            equipment["weapon"] = "新手法杖"
            equipment["durability"] = durability.replace(" ", "")
        if money:
            economy["game_currency"] = money.rstrip("】】 ]")

        inventory_line = last(r"(?:背包|inventory|backpack)\s*(?:[：:]\s*)?([^\n。]+)")
        if inventory_line:
            inventory: dict[str, int] = {}
            for raw_item, count in re.findall(
                r"([^×xX*＊,，;；]+?)\s*[×xX*＊]\s*(\d+)",
                inventory_line,
            ):
                item = re.sub(r"\s+", " ", raw_item).strip(" \t:：;；,，")
                if item:
                    inventory[item] = int(count)
            if inventory:
                economy["inventory"] = inventory
        occupied = last(r"占用[：:]\s*(\d+\s*/\s*20)")
        if not occupied and inventory_line:
            occupied_match = re.search(r"(?:占用)?\s*(\d+\s*/\s*20)", inventory_line)
            occupied = occupied_match.group(1) if occupied_match else ""
        if occupied:
            economy["backpack"] = occupied.replace(" ", "")
        if quest_line:
            quests["active"] = quest_line

        if "清道夫委托已完成" in body:
            quests["清道夫委托"] = "已提交；奖励30铜已领取"
            inv = economy.get("inventory")
            if isinstance(inv, dict) and "灰狼毒腺" not in inv:
                inv["灰狼毒腺"] = 0
        elif "清道夫委托" in body and ("未接取" in body or "没接" in body or "没交" in body):
            quests["清道夫委托"] = "未接取；未提交；奖励未到账"
        if "后坡巡查未登记" in body or "我先不接" in body:
            quests["后坡巡查"] = "可登记；第二章章末未登记"
        if patrol:
            quests["后坡巡查"] = patrol.replace(" ", "")
        for stale_quest in ("导师基础登记", "元素回廊前置", "职业试炼", "转职任务"):
            if stale_quest in quests and stale_quest not in body:
                quests.pop(stale_quest, None)

        protagonist.setdefault("identity", "见习冒险者（未转职）")
        protagonist.setdefault("class_path", "见习冒险者（未转职）")
        protagonist.setdefault("level", "Lv.1")
        panel.setdefault("identity", "见习冒险者（未转职）")
        panel.setdefault("level", "Lv.1")

        ledger["protagonist"] = protagonist
        protagonist.pop("cost_delta", None)
        ledger["panel"] = panel
        ledger["economy"] = economy
        ledger["equipment"] = equipment
        equipment.pop("durability_delta", None)
        ledger["quests"] = quests
        state["progression_ledger"] = ledger

        for character in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(character, dict) or character.get("role") not in {"protagonist", "主角"}:
                continue
            character.setdefault("game_panel", {})
            character["game_panel"]["identity"] = protagonist.get("identity", "见习冒险者（未转职）")
            self._sync_game_character_from_ledger(
                character,
                ledger,
                chapter_number=int(chapter.get("chapter_number") or 0),
            )
        if level or exp or hp or mp or durability or money or inventory_line or quest_line:
            summary = self._chapter_body_ledger_summary(chapter, ledger)
            chapter["chapter_summary"] = summary
            state["chapter_summaries"] = self._replace_by_chapter_number(
                list(state.get("chapter_summaries") or []),
                summary,
                limit=240,
            )
            chapter_number = int(chapter.get("chapter_number") or 0)
            fact_prefix = f"第{chapter_number}章事实："
            summary_prefix = f"第{chapter_number}章摘要："
            existing_world_facts = [
                str(item)
                for item in list(state.get("world_facts") or [])
                if not str(item).startswith(fact_prefix) and not str(item).startswith(summary_prefix)
            ]
            body_facts = [f"{fact_prefix}{fact}" for fact in summary["facts"]]
            body_facts.append(f"{summary_prefix}{summary['summary']}")
            state["world_facts"] = self._merge_unique(existing_world_facts, body_facts, limit=260)
            timeline_entry = {
                "chapter_number": chapter_number,
                "summary": summary["summary"],
                "impact": summary["next_focus"],
            }
            state["timeline"] = self._replace_by_chapter_number(
                list(state.get("timeline") or []),
                timeline_entry,
                limit=240,
            )
            memory_entry = {
                "chapter_number": chapter_number,
                "chapter_title": summary["chapter_title"],
                "summary": summary["summary"],
                "tags": [],
                "characters": self._character_names_in_chapter(state, chapter),
                "locations": [],
                "factions": [],
                "quests": [],
                "items": [],
                "facts": summary["facts"],
                "unresolved_threads": summary["unresolved_threads"],
            }
            state["memory_index"] = self._replace_by_chapter_number(
                list(state.get("memory_index") or []),
                memory_entry,
                limit=240,
            )
        self._apply_chapter_state_events(state, chapter, is_game_story=is_game_story)
        return state

    def _frozen_chapters(self) -> set[int]:
        state = self.state()
        ledger = state.get("progression_ledger") if isinstance(state.get("progression_ledger"), dict) else {}
        lock = ledger.get("continuity_lock") if isinstance(ledger.get("continuity_lock"), dict) else {}
        raw = lock.get("chapters_frozen") if isinstance(lock.get("chapters_frozen"), list) else []
        frozen: set[int] = set()
        for item in raw:
            try:
                frozen.add(int(item))
            except (TypeError, ValueError):
                continue
        return frozen

    def _assert_chapter_not_frozen(self, chapter_number: int, operation: str) -> None:
        if chapter_number in self._frozen_chapters():
            raise ValueError(f"chapter_frozen:{chapter_number}:{operation}")

    def freeze_opening_baseline(self, *, through_chapter: int = 3, commit_message: str | None = None) -> dict[str, Any]:
        """Rebuild durable opening memory from chapter files and lock it.

        The opening chapters are the highest-leverage continuity source for a
        webnovel. This method strips stale state shells, replays the accepted
        chapter records into state memory, and records a small continuity lock
        that later generation can preflight against.
        """

        if through_chapter <= 0:
            raise ValueError("through_chapter_must_be_positive")
        available = set(self.chapter_numbers())
        missing = [number for number in range(1, through_chapter + 1) if number not in available]
        if missing:
            raise FileNotFoundError(f"missing_opening_chapters:{','.join(str(item) for item in missing)}")

        original = self.state()
        rebuilt = dict(original)
        rebuilt["chapter_summaries"] = [
            item
            for item in self._dedupe_numbered_records(list(rebuilt.get("chapter_summaries") or []))
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]
        rebuilt["timeline"] = [
            item
            for item in self._dedupe_numbered_records(list(rebuilt.get("timeline") or []))
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]
        rebuilt["memory_index"] = [
            item
            for item in self._dedupe_numbered_records(list(rebuilt.get("memory_index") or []))
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]

        chapter_titles: dict[str, str] = {}
        opening_chapters: list[dict[str, Any]] = []
        for number in range(1, through_chapter + 1):
            chapter = self.chapter(number)
            opening_chapters.append(chapter)
            chapter_titles[str(number)] = str(chapter.get("chapter_title") or f"Chapter {number}")
            rebuilt = self._sync_state_after_chapter(rebuilt, chapter)

        rebuilt["current_chapter"] = max(int(rebuilt.get("current_chapter") or 0), through_chapter)
        ledger = self._derive_opening_progression_ledger(opening_chapters, dict(rebuilt.get("progression_ledger") or {}))
        lock = dict(ledger.get("continuity_lock") or {})
        frozen = sorted(set(self._frozen_chapters()) | set(range(1, through_chapter + 1)))
        lock["chapters_frozen"] = frozen
        lock["opening_baseline"] = {
            "through_chapter": through_chapter,
            "chapter_titles": chapter_titles,
            "next_chapter": through_chapter + 1,
            "source": "chapter_files",
        }
        ledger["continuity_lock"] = lock
        rebuilt["progression_ledger"] = ledger
        self._write_json(self.webnovel_dir / "state.json", rebuilt)

        project = self.project()
        synced_project = dict(project)
        blueprint = dict(synced_project.get("world_blueprint") or {})
        continuity = dict(blueprint.get("continuity_state") or {})
        continuity["chapter_facts"] = [
            item
            for item in continuity.get("chapter_facts", [])
            if not (isinstance(item, dict) and 0 < int(item.get("chapter_number") or 0) <= through_chapter)
        ]
        blueprint["continuity_state"] = continuity
        synced_project["world_blueprint"] = blueprint
        for chapter in opening_chapters:
            synced_project = self._sync_project_after_chapter(synced_project, rebuilt, chapter)
        synced_project["current_chapter"] = max(int(synced_project.get("current_chapter") or 0), through_chapter)
        self._write_json(self.webnovel_dir / "project.json", synced_project)

        commit = self.commit(
            message=commit_message or f"freeze opening baseline through chapter {through_chapter}",
            operation="freeze-opening",
            chapter_number=through_chapter,
        )
        return {
            "schema_version": "file-project-opening-baseline/v1",
            "through_chapter": through_chapter,
            "chapters_frozen": frozen,
            "chapter_titles": chapter_titles,
            "preflight": self.opening_preflight(next_chapter=through_chapter + 1),
            "commit": commit,
        }

    def opening_preflight(self, *, next_chapter: int | None = None) -> dict[str, Any]:
        """Report whether the current project state can safely continue."""

        state = self.state()
        persisted_state = self._read_json(self.webnovel_dir / "state.json", {}) or state
        ledger = state.get("progression_ledger") if isinstance(state.get("progression_ledger"), dict) else {}
        lock = ledger.get("continuity_lock") if isinstance(ledger.get("continuity_lock"), dict) else {}
        baseline = lock.get("opening_baseline") if isinstance(lock.get("opening_baseline"), dict) else {}
        through_chapter = int(baseline.get("through_chapter") or 0)
        target = int(next_chapter or baseline.get("next_chapter") or (int(state.get("current_chapter") or 0) + 1))
        issues: list[str] = []

        if through_chapter:
            missing_frozen = [
                number
                for number in range(1, through_chapter + 1)
                if number not in self._frozen_chapters()
            ]
            if missing_frozen:
                issues.append(f"opening chapters not frozen: {missing_frozen}")
            missing_files = [
                number
                for number in range(1, through_chapter + 1)
                if number not in self.chapter_numbers()
            ]
            if missing_files:
                issues.append(f"opening chapter files missing: {missing_files}")
            if target <= through_chapter:
                issues.append(f"next chapter {target} would rewrite frozen opening baseline")

        numbered_summaries = [
            int(item.get("chapter_number") or 0)
            for item in state.get("chapter_summaries", [])
            if isinstance(item, dict) and int(item.get("chapter_number") or 0) > 0
        ]
        duplicate_summaries = sorted({number for number in numbered_summaries if numbered_summaries.count(number) > 1})
        if duplicate_summaries:
            issues.append(f"duplicate chapter summaries: {duplicate_summaries}")

        preflight_text = {
            "author_constraints": persisted_state.get("author_constraints", []),
            "world_facts": persisted_state.get("world_facts", []),
            "timeline": persisted_state.get("timeline", []),
            "chapter_summaries": persisted_state.get("chapter_summaries", []),
            "memory_index": persisted_state.get("memory_index", []),
            "progression_ledger": persisted_state.get("progression_ledger", {}),
        }
        text_blob = json.dumps(preflight_text, ensure_ascii=False)
        blocked_tokens = (
            "？？",
            "门槛",
            "熟练度",
            "元素法师学徒",
            "货币：",
            "法师兄",
            "先看成本",
            "先看余额",
            "先问价",
        )
        leaked = [token for token in blocked_tokens if token in text_blob]
        if leaked:
            issues.append(f"blocked stale tokens in state: {leaked}")
        bad_titles = [
            str(item.get("chapter_title") or "")
            for item in state.get("chapter_summaries", [])
            if isinstance(item, dict)
            and re.fullmatch(r"[\?？]{2,}", str(item.get("chapter_title") or "").strip())
        ]
        if bad_titles:
            issues.append("chapter titles are unresolved question marks")

        return {
            "schema_version": "file-project-opening-preflight/v1",
            "ok": not issues,
            "issues": issues,
            "next_chapter": target,
            "opening_baseline": baseline,
        }

    def _assert_opening_preflight(self, chapter_number: int) -> None:
        report = self.opening_preflight(next_chapter=chapter_number)
        baseline = report.get("opening_baseline") if isinstance(report.get("opening_baseline"), dict) else {}
        if baseline and not report.get("ok"):
            raise ValueError(f"opening_preflight_failed:{'; '.join(report.get('issues') or [])}")

    def exists(self) -> bool:
        return (self.story_system_dir / "MASTER_SETTING.json").exists() and (self.webnovel_dir / "state.json").exists()

    def master_setting(self) -> dict[str, Any]:
        return self._read_json(self.story_system_dir / "MASTER_SETTING.json", {}) or {}

    @staticmethod
    def _is_game_story_payload(project: dict[str, Any], state: dict[str, Any] | None = None) -> bool:
        def is_game_alias(value: Any) -> bool:
            normalized = " ".join(
                str(value or "")
                .strip()
                .casefold()
                .replace("_", " ")
                .replace("-", " ")
                .split()
            )
            return normalized in {"网游", "web game", "game web", "game webnovel"}

        world_blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        raw_explicit_ids = world_blueprint.get("genre_plugin_ids")
        if isinstance(raw_explicit_ids, str):
            raw_explicit_ids = [raw_explicit_ids]
        if any(is_game_alias(item) for item in (raw_explicit_ids if isinstance(raw_explicit_ids, list) else [])):
            return True
        explicit_ids = normalize_novel_type_ids(world_blueprint.get("genre_plugin_ids"))
        if "game_webnovel" in explicit_ids:
            return True
        if explicit_ids:
            return False
        state = state if isinstance(state, dict) else {}
        raw_state_types = state.get("genre_plugin_ids")
        if isinstance(raw_state_types, str):
            raw_state_types = [raw_state_types]
        if any(is_game_alias(item) for item in (raw_state_types if isinstance(raw_state_types, list) else [])):
            return True
        if is_game_alias(state.get("genre")):
            return True
        try:
            project_model = NovelProject.model_validate(project)
        except Exception:
            project_model = None
        if project_model is not None and any(
            plugin.plugin_id == "game_webnovel" for plugin in select_genre_plugins(project_model)
        ):
            return True
        state_ids = normalize_novel_type_ids(state.get("genre_plugin_ids"))
        if state_ids:
            return "game_webnovel" in state_ids
        return "game_webnovel" in normalize_novel_type_ids(state.get("genre"))

    def project(self) -> dict[str, Any]:
        project = self._read_json(self.webnovel_dir / "project.json", {}) or self.master_setting().get("project", {}) or {}
        project = dict(project)
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        is_game_story = self._is_game_story_payload(project, state)
        project["character_profiles"] = [
            _normalize_character_persistence_card(item, is_game_story=is_game_story)
            for item in project.get("character_profiles", [])
            if isinstance(item, dict)
        ]
        if "relationship_graph" in project:
            project["relationship_graph"] = normalize_relationship_graph(project.get("relationship_graph"))
        else:
            project["relationship_graph"] = graph_from_character_cards(project.get("character_profiles"))
        return project

    def opening_brief(self) -> dict[str, Any]:
        payload = self._read_json(self.webnovel_dir / "opening_brief.json", {})
        return OpeningBrief.model_validate(payload).model_dump(mode="json")

    def opening_directions(self) -> dict[str, Any] | None:
        path = self.webnovel_dir / "opening_directions.json"
        if not path.exists():
            return None
        return OpeningDirectionSet.model_validate(self._read_json(path, {})).model_dump(mode="json")

    def opening_setup(self) -> dict[str, Any]:
        project = self.project()
        candidates = self.opening_directions()
        project_id = str(project.get("project_id") or self.root.name)
        public_project_id = project_id if project_id.startswith("file:") else f"file:{project_id}"
        selected_id = str((candidates or {}).get("selected_id") or "")
        pipeline_stage = str(project.get("pipeline_stage") or "idea_pending")
        next_page = "outline" if selected_id or pipeline_stage == "outlining" else "setup"
        return {
            "brief": self.opening_brief(),
            "directions": list((candidates or {}).get("directions") or []),
            "selected_id": selected_id,
            "pipeline_stage": pipeline_stage,
            "next_path": f"/projects/{quote(public_project_id, safe='')}/{next_page}",
        }

    def generate_opening_directions(
        self, generator: Any, *, guidance: str = ""
    ) -> dict[str, Any]:
        existing = self.opening_directions()
        if existing and existing.get("selected_id"):
            raise ValueError("direction_already_selected")
        brief = OpeningBrief.model_validate(self.opening_brief())
        result = generator.generate(brief, guidance=guidance.strip())
        try:
            directions = OpeningDirectionSet.model_validate(result)
        except (TypeError, ValueError) as exc:
            raise ValueError("opening_direction_generation_failed") from exc
        project = {**self.project(), "pipeline_stage": "direction_ready"}
        self._replace_json_transaction(
            {
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "opening_directions.json": directions.model_dump(mode="json"),
            }
        )
        return self.opening_setup()

    def select_opening_direction(self, direction_id: str) -> dict[str, Any]:
        payload = self.opening_directions()
        if payload is None:
            raise KeyError("direction_not_found")
        directions = OpeningDirectionSet.model_validate(payload)
        if directions.selected_id:
            raise ValueError("direction_already_selected")
        selected = next(
            (direction for direction in directions.directions if direction.id == direction_id),
            None,
        )
        if selected is None:
            raise KeyError("direction_not_found")

        project = {
            **self.project(),
            "title": selected.title,
            "pipeline_stage": "outlining",
        }
        outline = normalize_project_outline(
            {
                "overall": {
                    "story": selected.hook,
                    "protagonist_goal": selected.protagonist_goal,
                    "main_conflict": selected.main_conflict,
                    "growth_path": selected.growth_path,
                    "ending_direction": selected.opening_promise,
                },
                "arcs": [],
                "chapters": [],
            }
        )
        selected_directions = directions.model_copy(update={"selected_id": selected.id})
        self._replace_json_transaction(
            {
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "outline.json": outline,
                self.webnovel_dir / "opening_directions.json": selected_directions.model_dump(mode="json"),
            }
        )
        return self.opening_setup()

    def project_outline(self) -> dict[str, Any]:
        path = self.webnovel_dir / "outline.json"
        if path.exists():
            return {**normalize_project_outline(self._read_json(path, {})), "source": "saved"}
        return {**outline_from_legacy_project(self.project()), "source": "legacy"}

    def update_project_outline(self, payload: dict[str, Any]) -> dict[str, Any]:
        outline_payload = dict(payload)
        outline_payload.pop("source", None)
        state = self._read_json(self.webnovel_dir / "state.json", {})
        current_chapter = int(state.get("current_chapter") or 0)
        normalized = validate_outline_for_project(
            outline_payload, current_chapter=current_chapter
        )
        self._write_json_atomic(self.webnovel_dir / "outline.json", normalized)
        return {**normalized, "source": "saved"}

    def _planning_opening_direction(self, project: dict[str, Any], outline: dict[str, Any]) -> dict[str, str]:
        directions = self.opening_directions()
        selected_id = str((directions or {}).get("selected_id") or "")
        selected = next(
            (
                dict(item)
                for item in (directions or {}).get("directions", [])
                if isinstance(item, dict) and str(item.get("id") or "") == selected_id
            ),
            None,
        )
        if selected:
            return {
                key: str(selected.get(key) or "")
                for key in ("title", "hook", "protagonist_goal", "main_conflict", "growth_path", "opening_promise")
            }
        overall = outline.get("overall") if isinstance(outline.get("overall"), dict) else {}
        seed = str(project.get("seed_outline") or project.get("world_summary") or overall.get("story") or project.get("title") or "")
        focus = str(project.get("current_focus") or overall.get("protagonist_goal") or seed)
        return {
            "title": str(project.get("title") or ""),
            "hook": str(overall.get("story") or seed),
            "protagonist_goal": str(overall.get("protagonist_goal") or focus),
            "main_conflict": str(overall.get("main_conflict") or project.get("world_summary") or seed),
            "growth_path": str(overall.get("growth_path") or "主角在连续行动、代价和反馈中取得真实成长。"),
            "opening_promise": str(overall.get("ending_direction") or "开篇建立的核心冲突会得到阶段性兑现。"),
        }

    def _planning_brief(self) -> OutlinePlanningBrief:
        project = self.project()
        outline = dict(self.project_outline())
        outline.pop("source", None)
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        plugin_ids = blueprint.get("genre_plugin_ids") if isinstance(blueprint.get("genre_plugin_ids"), list) else []
        novel_type_id = str(plugin_ids[0] if plugin_ids else "generic_webnovel")
        existing_cards: list[dict[str, Any]] = []
        for item in [
            *(project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []),
            *(state.get("characters") if isinstance(state.get("characters"), list) else []),
        ]:
            if not isinstance(item, dict) or not str(item.get("name") or "").strip():
                continue
            card = normalize_character_profile(item)
            existing_cards.append(
                {
                    key: card.get(key)
                    for key in (
                        "name",
                        "role",
                        "character_tier",
                        "first_appearance",
                        "identity_profile",
                        "background_profile",
                        "current_life_profile",
                        "story_drive",
                        "dialogue_examples",
                    )
                }
            )
            if len(existing_cards) >= 6:
                break
        summaries = state.get("chapter_summaries") if isinstance(state.get("chapter_summaries"), list) else []
        return OutlinePlanningBrief(
            novel_type_id=novel_type_id,
            title=str(project.get("title") or ""),
            opening_direction=self._planning_opening_direction(project, outline),
            author_constraints=[str(item) for item in project.get("author_constraints", []) if str(item).strip()],
            existing_outline=outline,
            existing_characters=existing_cards,
            current_chapter=int(state.get("current_chapter") or 0),
            recent_chapter_summaries=[dict(item) for item in summaries[-3:] if isinstance(item, dict)],
        )

    def _merge_generated_character_cards(self, generated: list[dict[str, Any]]) -> list[dict[str, Any]]:
        project = self.project()
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        existing: dict[str, dict[str, Any]] = {}
        existing_order: list[str] = []
        for item in [
            *(project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []),
            *(state.get("characters") if isinstance(state.get("characters"), list) else []),
        ]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            if not name:
                continue
            if name not in existing:
                existing[name] = dict(item)
                existing_order.append(name)
            else:
                existing[name] = merge_character_profile(existing[name], item)

        generated_names: list[str] = []
        for card in generated:
            name = str(card.get("name") or "").strip()
            if not name:
                continue
            generated_names.append(name)
            existing[name] = merge_character_profile(existing.get(name, {"name": name}), card)
        order = [*generated_names, *(name for name in existing_order if name not in generated_names)]
        return [normalize_character_profile(existing[name]) for name in order]

    def _extend_outline(
        self,
        current: dict[str, Any],
        addition: dict[str, Any],
        *,
        current_chapter: int,
    ) -> dict[str, Any]:
        current = normalize_project_outline(current)
        addition = normalize_project_outline(addition)
        added_numbers = [int(item["chapter_number"]) for item in addition["chapters"]]
        expected = outline_window_status(
            current,
            current_chapter=current_chapter,
        )["next_chapter_numbers"]
        if not expected:
            raise ValueError("outline_window_already_full")
        if added_numbers != expected:
            raise ValueError("generated_chapters_do_not_match_target_window")
        arcs = {str(item["id"]): dict(item) for item in current["arcs"]}
        for arc in addition["arcs"]:
            arc_id = str(arc["id"])
            existing_arc = arcs.get(arc_id)
            if existing_arc is None:
                arcs[arc_id] = dict(arc)
                continue
            merged_arc = merge_character_profile(existing_arc, arc)
            merged_arc["end_chapter"] = max(int(existing_arc["end_chapter"]), int(arc["end_chapter"]))
            merged_arc["long_term_antagonist_traces"] = list(
                dict.fromkeys(
                    [
                        *existing_arc.get("long_term_antagonist_traces", []),
                        *arc.get("long_term_antagonist_traces", []),
                    ]
                )
            )
            arcs[arc_id] = merged_arc
        return normalize_project_outline(
            {
                "overall": merge_character_profile(current["overall"], addition["overall"]),
                "arcs": list(arcs.values()),
                "chapters": [*current["chapters"], *addition["chapters"]],
            }
        )

    def _preserve_committed_outline(
        self,
        current: dict[str, Any],
        generated: dict[str, Any],
        *,
        current_chapter: int,
    ) -> dict[str, Any]:
        current = normalize_project_outline(current)
        generated = normalize_project_outline(generated)
        committed = {
            item["chapter_number"]: item
            for item in current["chapters"]
            if item["chapter_number"] <= current_chapter
        }
        future = {
            item["chapter_number"]: item
            for item in generated["chapters"]
            if item["chapter_number"] > current_chapter
        }
        return normalize_project_outline(
            {
                "overall": generated["overall"],
                "arcs": generated["arcs"],
                "chapters": [*committed.values(), *future.values()],
            }
        )

    def save_generated_outline_plan(self, plan: Any, *, mode: str) -> dict[str, Any]:
        validated = GeneratedOutlinePlan.model_validate(plan)
        if mode not in {"initial", "regenerate", "extend"}:
            raise ValueError("invalid_outline_planning_mode")

        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        current_chapter = int(state.get("current_chapter") or 0)
        current_outline = dict(self.project_outline())
        current_outline.pop("source", None)
        if mode == "initial":
            if current_chapter != 0:
                raise ValueError("initial_outline_requires_unstarted_project")
            expected_chapter_numbers = list(range(1, 31))
        elif mode == "regenerate":
            ceiling = normalize_project_outline(current_outline)["overall"][
                "extension_ceiling_chapter"
            ]
            expected_chapter_numbers = list(
                range(current_chapter + 1, min(current_chapter + 30, ceiling) + 1)
            )
        else:
            expected_chapter_numbers = outline_window_status(
                current_outline,
                current_chapter=current_chapter,
            )["next_chapter_numbers"]
            if not expected_chapter_numbers:
                raise ValueError("outline_window_already_full")
        if mode in {"initial", "regenerate"}:
            validated = validate_generated_opening_plan(
                validated.model_dump(mode="json"),
                expected_chapter_numbers=expected_chapter_numbers,
            )

        generated_outline = validated.outline.model_dump(mode="json")
        if mode == "extend":
            generated_outline = self._extend_outline(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
            )
        elif mode == "regenerate":
            generated_outline = self._preserve_committed_outline(
                current_outline,
                generated_outline,
                current_chapter=current_chapter,
            )
        cards = self._merge_generated_character_cards(
            [card.model_dump(mode="json") for card in validated.characters]
        )
        project = dict(self.project())
        project["character_profiles"] = cards
        project["relationship_graph"] = merge_relationship_graph(
            project.get("relationship_graph"),
            graph_from_character_cards(cards),
        )
        project["pipeline_stage"] = "world_ready"
        first_arc = generated_outline["arcs"][0] if generated_outline["arcs"] else {}
        project["current_focus"] = str(first_arc.get("goal") or project.get("current_focus") or "")
        state["characters"] = cards
        state["outline"] = str(generated_outline["overall"].get("story") or state.get("outline") or "")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        snapshot_path = self.story_system_dir / "plans" / f"{stamp}-{mode}.json"
        snapshot = {
            "schema_version": "generated-outline-plan/v1",
            "mode": mode,
            "outline": generated_outline,
            "characters": cards,
        }
        self._replace_json_transaction(
            {
                self.webnovel_dir / "outline.json": generated_outline,
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "state.json": state,
                snapshot_path: snapshot,
            }
        )
        return {**snapshot, "source": "generated"}

    def generate_outline_plan(
        self,
        generator: Any,
        *,
        mode: str,
        guidance: str = "",
    ) -> dict[str, Any]:
        plan = generator.generate(self._planning_brief(), mode=mode, guidance=guidance.strip())
        return self.save_generated_outline_plan(plan, mode=mode)

    @staticmethod
    def _writer_scene_kind(scene_cards: list[dict[str, Any]], *, is_game_story: bool) -> str:
        return scene_kind_for_cards(scene_cards, is_game_story=is_game_story)

    def _writer_character_cards(
        self,
        state: dict[str, Any],
        selected_outline: dict[str, Any],
        *,
        scene_kind: str = "reality",
    ) -> list[dict[str, Any]]:
        characters = [
            dict(item)
            for item in state.get("characters", [])
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        chapter = selected_outline.get("chapter") if isinstance(selected_outline.get("chapter"), dict) else {}
        cast = [str(item).strip() for item in chapter.get("cast", []) if str(item).strip()]

        protagonist = next(
            (
                card
                for card in characters
                if str(card.get("character_tier") or "").strip() == "protagonist"
                or str(card.get("role") or "").strip().lower() in {"protagonist", "主角"}
            ),
            None,
        )
        wanted = list(cast) if cast else [str(card.get("name") or "").strip() for card in characters[:6]]
        if protagonist:
            protagonist_name = str(protagonist.get("name") or "").strip()
            if protagonist_name and protagonist_name not in wanted:
                wanted.insert(0, protagonist_name)

        selected: list[dict[str, Any]] = []
        seen: set[str] = set()
        for identifier in wanted:
            card = next(
                (item for item in characters if self._character_matches(item, identifier)),
                None,
            )
            if card is None:
                continue
            name = str(card.get("name") or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            projected = project_character_for_scene(card, scene_kind=scene_kind)
            selected.append(projected)
        return selected

    def update_project(self, patch: dict[str, Any]) -> dict[str, Any]:
        normalized_patch_genre_ids: list[str] | None = None
        patch_world_blueprint = patch.get("world_blueprint")
        if (
            patch_world_blueprint is not None
            and isinstance(patch_world_blueprint, dict)
            and "genre_plugin_ids" in patch_world_blueprint
        ):
            raw_genre_ids = patch_world_blueprint.get("genre_plugin_ids")
            if raw_genre_ids is None:
                genre_values: list[Any] = []
            elif isinstance(raw_genre_ids, str):
                genre_values = [raw_genre_ids]
            elif isinstance(raw_genre_ids, list):
                genre_values = raw_genre_ids
            else:
                raise ValueError("invalid_novel_type")

            normalized_patch_genre_ids = []
            for value in genre_values:
                if not str(value or "").strip():
                    continue
                resolved_id = resolve_novel_type_id(value)
                if not resolved_id:
                    raise ValueError("invalid_novel_type")
                if resolved_id not in normalized_patch_genre_ids:
                    normalized_patch_genre_ids.append(resolved_id)

        project = dict(self.project())
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        for key in (
            "title",
            "world_summary",
            "author_constraints",
            "character_profiles",
            "relationship_graph",
            "enabled_skill_ids",
            "status",
            "pipeline_stage",
        ):
            if key in patch and patch[key] is not None:
                project[key] = patch[key]
        if "relationship_graph" in patch and patch.get("relationship_graph") is not None:
            project["relationship_graph"] = normalize_relationship_graph(patch["relationship_graph"])
        if patch.get("seed_outline") is not None:
            project["seed_outline"] = patch["seed_outline"]
            state["outline"] = patch["seed_outline"]
        if patch.get("world_blueprint") is not None:
            world_blueprint = patch["world_blueprint"]
            if normalized_patch_genre_ids is not None:
                world_blueprint = dict(world_blueprint)
                world_blueprint["genre_plugin_ids"] = normalized_patch_genre_ids
            project["world_blueprint"] = world_blueprint
            if isinstance(world_blueprint, dict) and "genre_plugin_ids" in world_blueprint:
                raw_genre_ids = world_blueprint.get("genre_plugin_ids")
                genre_plugin_ids = normalize_novel_type_ids(raw_genre_ids)
                explicitly_empty = raw_genre_ids in (None, "", []) or (
                    isinstance(raw_genre_ids, list)
                    and not any(str(item or "").strip() for item in raw_genre_ids)
                )
                synchronized_genre_ids: list[str] | None = None
                if genre_plugin_ids:
                    state["genre_plugin_ids"] = genre_plugin_ids
                    synchronized_genre_ids = genre_plugin_ids
                    primary_type = runtime_novel_type(genre_plugin_ids[0])
                    if primary_type is not None:
                        state["genre"] = primary_type.name
                elif explicitly_empty:
                    state["genre_plugin_ids"] = []
                    state["genre"] = ""
                    synchronized_genre_ids = []
                if synchronized_genre_ids is not None:
                    world_facts = (
                        state.get("world_facts")
                        if isinstance(state.get("world_facts"), list)
                        else []
                    )
                    state["world_facts"] = [
                        fact
                        for fact in world_facts
                        if not (
                            isinstance(fact, str)
                            and novel_type_id_from_metadata_fact(fact)
                        )
                    ]
                    if synchronized_genre_ids:
                        state["world_facts"].append(
                            f"小说类型：{synchronized_genre_ids[0]}"
                        )
        if patch.get("current_focus") is not None:
            project["current_focus"] = patch["current_focus"]
            state["current_focus"] = patch["current_focus"]
        elif isinstance(project.get("world_blueprint"), dict) and project["world_blueprint"].get("current_arc"):
            project["current_focus"] = project.get("current_focus") or project["world_blueprint"]["current_arc"]
        self._write_json(self.webnovel_dir / "project.json", project)
        self._write_json(self.webnovel_dir / "state.json", state)
        return project

    @staticmethod
    def _merge_character_patch(current: Any, patch: Any) -> Any:
        if isinstance(current, dict) and isinstance(patch, dict):
            merged = dict(current)
            for key, value in patch.items():
                merged[key] = FileProjectStore._merge_character_patch(merged.get(key), value)
            return merged
        return patch

    @staticmethod
    def _character_matches(card: dict[str, Any], identifier: str) -> bool:
        target = str(identifier or "").strip()
        if not target:
            return False
        panel = card.get("game_panel") if isinstance(card.get("game_panel"), dict) else {}
        return target in {
            str(card.get("name") or "").strip(),
            str(card.get("game_id") or "").strip(),
            str(panel.get("game_id") or "").strip(),
        }

    def _completed_character_card(self, card: dict[str, Any], *, genre: str = "") -> dict[str, Any]:
        def drop_none(value: Any) -> Any:
            if isinstance(value, dict):
                return {key: drop_none(item) for key, item in value.items() if item is not None}
            if isinstance(value, list):
                return [drop_none(item) for item in value]
            return value

        card = drop_none(card)
        raw_state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        normalized_card = _normalize_character_persistence_card(
            card,
            is_game_story=self._is_game_story_payload(self.project(), raw_state),
        )
        validated = CharacterState.model_validate(normalized_card)
        completed = complete_portrait(
            validated,
            genre=genre,
            story_function=str(normalized_card.get("story_function") or ""),
        )
        completed_card = self._merge_character_patch(
            normalized_card,
            completed.model_dump(exclude_defaults=True, exclude_none=True),
        )
        return _normalize_character_persistence_card(
            completed_card,
            is_game_story=self._is_game_story_payload(self.project(), raw_state),
        )

    def update_character(self, name: str, patch: dict[str, Any]) -> dict[str, Any]:
        identifier = str(name or "").strip()
        if not identifier:
            raise KeyError("character_not_found:")
        patch = dict(patch or {})

        visible_state = self.state()
        visible_cards = visible_state.get("characters") if isinstance(visible_state.get("characters"), list) else []
        current = next(
            (dict(item) for item in visible_cards if isinstance(item, dict) and self._character_matches(item, identifier)),
            None,
        )
        if current is None:
            raise KeyError(f"character_not_found:{identifier}")
        canonical_name = str(current.get("name") or "").strip()
        if patch.get("name") and str(patch["name"]).strip() != canonical_name:
            raise ValueError("character_name_immutable")

        merged = self._merge_character_patch(current, patch)
        merged["name"] = canonical_name
        completed = self._completed_character_card(merged, genre=str(visible_state.get("genre") or ""))

        raw_state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        raw_cards = [dict(item) for item in raw_state.get("characters", []) if isinstance(item, dict)]
        raw_index = next(
            (index for index, item in enumerate(raw_cards) if self._character_matches(item, canonical_name)),
            None,
        )
        if raw_index is None:
            raw_cards.append(completed)
        else:
            raw_cards[raw_index] = self._merge_character_patch(raw_cards[raw_index], completed)
        is_game_story = self._is_game_story_payload(self.project(), raw_state)
        raw_cards = [
            _normalize_character_persistence_card(card, is_game_story=is_game_story)
            for card in raw_cards
        ]
        raw_state["characters"] = raw_cards

        project = dict(self.project())
        project_cards = [dict(item) for item in project.get("character_profiles", []) if isinstance(item, dict)]
        project_index = next(
            (index for index, item in enumerate(project_cards) if self._character_matches(item, canonical_name)),
            None,
        )
        if project_index is None:
            project_cards.append(dict(completed))
        else:
            project_cards[project_index] = self._merge_character_patch(project_cards[project_index], completed)
        project["character_profiles"] = [
            _normalize_character_persistence_card(card, is_game_story=is_game_story)
            for card in project_cards
        ]
        self._replace_json_transaction(
            {
                self.webnovel_dir / "state.json": raw_state,
                self.webnovel_dir / "project.json": project,
            }
        )

        return raw_cards[raw_index if raw_index is not None else -1]

    def complete_character_portrait(self, name: str) -> dict[str, Any]:
        identifier = str(name or "").strip()
        visible_state = self.state()
        cards = visible_state.get("characters") if isinstance(visible_state.get("characters"), list) else []
        current = next(
            (dict(item) for item in cards if isinstance(item, dict) and self._character_matches(item, identifier)),
            None,
        )
        if current is None:
            raise KeyError(f"character_not_found:{identifier}")
        completed = self._completed_character_card(current, genre=str(visible_state.get("genre") or ""))
        return self.update_character(str(completed.get("name") or identifier), completed)

    def state(self) -> dict[str, Any]:
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        sanitized = self._sanitize_story_state(state)
        additions: list[dict[str, Any]] = []
        project = self.project()
        protagonist_card = self._protagonist_character_card(sanitized, self.project())
        if protagonist_card:
            additions.append(protagonist_card)
        additions.extend(self._proposed_character_cards_from_outline(sanitized, project))
        for number in self.chapter_numbers():
            try:
                chapter = self._read_json(self.story_system_dir / "chapters" / f"{number:04d}.json", {}) or {}
            except (OSError, ValueError, json.JSONDecodeError):
                chapter = {}
            if isinstance(chapter, dict):
                additions.extend(self._chapter_entity_cards(chapter))
        if additions:
            sanitized["characters"] = self._merge_character_cards(list(sanitized.get("characters") or []), additions)
        characters = sanitized.get("characters") if isinstance(sanitized.get("characters"), list) else []
        genre = str(sanitized.get("genre") or project.get("genre") or "")
        sanitized["characters"] = [
            self._completed_character_card(dict(item), genre=genre)
            for item in characters
            if isinstance(item, dict) and self._is_character_card(item)
        ]
        return sanitized

    def chapter_numbers(self) -> list[int]:
        numbers: list[int] = []
        chapters_path = self.story_system_dir / "chapters"
        if chapters_path.exists():
            for path in chapters_path.glob("*.json"):
                try:
                    numbers.append(int(path.stem))
                except ValueError:
                    continue
        return sorted(set(numbers))

    def chapter(self, chapter_number: int | None = None) -> dict[str, Any]:
        numbers = self.chapter_numbers()
        if not numbers:
            raise FileNotFoundError("no_chapters")
        target = chapter_number or numbers[-1]
        path = self.story_system_dir / "chapters" / f"{target:04d}.json"
        chapter = self._read_json(path)
        if not isinstance(chapter, dict):
            raise FileNotFoundError(f"chapter_not_found:{target}")
        return self._hydrate_chapter_display_fields(chapter)

    def review(self, chapter_number: int | None = None) -> dict[str, Any]:
        chapter = self.chapter(chapter_number)
        target = int(chapter.get("chapter_number") or chapter_number or 0)
        review = self._read_json(self.story_system_dir / "reviews" / f"{target:04d}.json")
        if isinstance(review, dict) and review:
            return review
        quality_report = chapter.get("quality_report")
        if isinstance(quality_report, dict) and quality_report:
            return quality_report
        return validate_bundle(chapter)

    def commit(self, *, message: str, operation: str = "manual", chapter_number: int | None = None) -> dict[str, Any]:
        commits_dir = self.story_system_dir / "commits"
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        manifest: list[dict[str, Any]] = []
        for path in [
            self.story_system_dir / "MASTER_SETTING.json",
            self.webnovel_dir / "project.json",
            self.webnovel_dir / "state.json",
            *sorted((self.story_system_dir / "chapters").glob("*.json")),
            *sorted((self.story_system_dir / "reviews").glob("*.json")),
            *sorted(self.chapters_dir.glob("*.md")),
        ]:
            if not path.exists() or not path.is_file():
                continue
            data = path.read_bytes()
            manifest.append(
                {
                    "path": path.relative_to(self.root).as_posix(),
                    "bytes": len(data),
                    "sha256": sha256(data).hexdigest(),
                }
            )
        payload = {
            "schema_version": "file-project-commit/v1",
            "timestamp": timestamp,
            "operation": operation,
            "message": message,
            "chapter_number": chapter_number,
            "project": self.summary(),
            "manifest": manifest,
        }
        slug = re.sub(r"[^a-zA-Z0-9_.-]+", "-", f"{operation}-ch{chapter_number}" if chapter_number else operation).strip("-")
        commit_path = commits_dir / f"{timestamp}-{slug or 'commit'}.json"
        self._write_json(commit_path, payload)
        self._write_json(commits_dir / "latest_commit.json", payload | {"commit_file": commit_path.relative_to(self.root).as_posix()})
        return payload | {"commit_file": commit_path.relative_to(self.root).as_posix()}

    def write_chapter(
        self,
        *,
        chapter_number: int,
        title: str,
        body: str,
        next_outline: str = "",
        summary: str = "",
        instructions: list[str] | None = None,
        overwrite: bool = False,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        if chapter_number <= 0:
            raise ValueError("chapter_number_must_be_positive")
        self._assert_chapter_not_frozen(chapter_number, "write")
        self._assert_opening_preflight(chapter_number)
        if not str(body).strip():
            raise ValueError("body_required")
        paths = self._chapter_paths(chapter_number, title)
        if paths["json"].exists() and not overwrite:
            raise FileExistsError(f"chapter_exists:{chapter_number}")

        state = self.state()
        current_chapter = max(int(state.get("current_chapter") or 0), chapter_number)
        chapter_summary = {
            "chapter_title": title,
            "cadence": "measured",
            "summary": summary or f"Manual chapter {chapter_number}.",
            "facts": [item for item in (instructions or []) if str(item).strip()] or ["manual draft"],
            "next_focus": next_outline or "continue",
            "primary_conflict": "manual draft",
            "secondary_conflict": "manual draft",
            "event_beat": "manual draft",
        }
        updated_story = dict(state)
        updated_story["current_chapter"] = current_chapter
        if not updated_story.get("timeline"):
            updated_story["timeline"] = [f"chapter {chapter_number}: {title}"]
        if not updated_story.get("chapter_summaries"):
            updated_story["chapter_summaries"] = [chapter_summary]

        chapter = {
            "chapter_number": chapter_number,
            "chapter_title": title,
            "body": body,
            "cadence": "measured",
            "next_outline": next_outline or "continue",
            "chapter_summary": chapter_summary,
            "event_plan": {
                "chapter_number": chapter_number,
                "next_focus": next_outline or "continue",
                "stakes": summary or next_outline or "manual draft",
                "world_reactions": chapter_summary["facts"][:3],
            },
            "updated_story": updated_story,
            "manual_instructions": instructions or [],
        }
        chapter = self._hydrate_chapter_display_fields(chapter, updated_story)
        review = _manual_chapter_quality_report(chapter)
        chapter["quality_report"] = review
        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=title,
            review=review,
            operation="write",
        )

        synced_state = self._sync_after_chapter(chapter, updated_story)
        self._remove_chapter_markdowns(chapter_number)
        self._write_json(paths["json"], chapter)
        self._write_json(paths["review"], review)
        self._write_text(paths["markdown"], body)
        synced_state["current_chapter"] = max(int(synced_state.get("current_chapter") or 0), current_chapter)
        self._write_json(self.webnovel_dir / "state.json", synced_state)
        commit = self.commit(
            message=commit_message or f"write chapter {chapter_number}",
            operation="write",
            chapter_number=chapter_number,
        )
        return {
            "schema_version": "file-project-write/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": title,
            "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
            "review": review,
            "commit": commit,
        }

    def persist_bundle(self, bundle: Any, *, operation: str = "generate", commit_message: str | None = None) -> dict[str, Any]:
        chapter = self._bundle_to_dict(bundle)
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            raise ValueError("chapter_number_must_be_positive")
        title = _normalize_chapter_title(str(chapter.get("chapter_title") or f"Chapter {chapter_number}"), chapter_number)
        chapter["chapter_title"] = title
        if isinstance(chapter.get("chapter_summary"), dict):
            chapter["chapter_summary"]["chapter_title"] = title
        body = str(chapter.get("body") or "")
        if not body.strip():
            raise ValueError("body_required")
        _assert_auto_chapter_length(body, operation=operation)

        updated_story = chapter.get("updated_story")
        if hasattr(updated_story, "model_dump"):
            updated_story = updated_story.model_dump(mode="json")
            chapter["updated_story"] = updated_story

        quality_report = chapter.get("quality_report")
        if not isinstance(quality_report, dict) or not quality_report:
            quality_report = validate_bundle(chapter)
            chapter["quality_report"] = quality_report
        review = quality_report
        if "writing_review" not in review:
            review = {
                "schema_version": "file-writing-review/v1",
                "writing_review": {"pass": bool(quality_report.get("ok")), "issues": quality_report.get("issues", [])},
                "quality_report": quality_report,
            }
            chapter["quality_report"] = review

        try:
            _assert_auto_chapter_quality(review, operation=operation)
        except ValueError:
            failed_dir = self.root / ".story-system" / "failed-drafts"
            failed_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
            failed_path = failed_dir / f"{stamp}-{operation}-ch{chapter_number}.json"
            self._write_json(
                failed_path,
                {
                    "schema_version": "file-project-failed-draft/v1",
                    "operation": operation,
                    "chapter_number": chapter_number,
                    "chapter_title": title,
                    "body": body,
                    "review": review,
                },
            )
            raise

        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=title,
            review=review,
            operation=operation,
        )

        base_state = self._usable_bundle_state(updated_story, self.state())
        chapter = self._hydrate_chapter_display_fields(chapter, base_state)
        self._sync_after_chapter(chapter, base_state)

        paths = self._chapter_paths(chapter_number, title)
        self._remove_chapter_markdowns(chapter_number)
        self._write_json(paths["json"], chapter)
        self._write_json(paths["review"], review)
        self._write_text(paths["markdown"], body)
        commit = self.commit(
            message=commit_message or f"{operation} chapter {chapter_number}",
            operation=operation,
            chapter_number=chapter_number,
        )
        return {
            "schema_version": "file-project-persist-bundle/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": title,
            "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
            "review": review,
            "commit": commit,
        }

    def generate_next_chapter(
        self,
        engine: Any | None = None,
        *,
        chapter_direction_id: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        from packages.story_core.engine import StoryEngine

        state = self.state()
        project = self.project()
        target_chapter = int(state.get("current_chapter") or 0) + 1
        chapter_direction = self._resolve_chapter_direction(state, project, target_chapter, chapter_direction_id)
        if chapter_direction:
            state = dict(state)
            ledger = dict(state.get("progression_ledger") or {})
            ledger["chapter_direction"] = chapter_direction
            state["progression_ledger"] = ledger
        story = StoryState.model_validate(self._story_state_payload_for_direction(state, project, target_chapter))
        generator = engine or StoryEngine()
        bundle = generator.generate_next_chapter(story)
        persisted = self.persist_bundle(bundle, operation="generate", commit_message=commit_message)
        return {
            "schema_version": "file-project-generate-next/v1",
            "root": str(self.root),
            "chapter_number": persisted["chapter_number"],
            "chapter_title": persisted["chapter_title"],
            "chapter_direction": chapter_direction,
            "persisted": persisted,
        }

    def _regeneration_variant(self, chapter_number: int) -> dict[str, Any]:
        variants = [
            {
                "id": "boundary-combat-cost",
                "axes": ["战斗消耗", "药剂铺委托边界"],
                "avoid": [],
            },
            {
                "id": "boundary-inventory-route",
                "axes": ["背包容量", "仓库窗口边界"],
                "avoid": ["上一版完整灰狼坡消耗顺序", "药剂铺作为唯一服务节点"],
            },
            {
                "id": "boundary-durability-route",
                "axes": ["装备耐久", "修理铺前置条件"],
                "avoid": ["上一版完整灰狼坡消耗顺序", "药剂铺作为唯一服务节点"],
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
        if chapter_number != 1:
            return None
        return {
            "boundary-combat-cost": "灰狼坡试水",
            "boundary-inventory-route": "背包快满了",
            "boundary-durability-route": "法杖快断了",
            "progression-lead": "灰狼坡先一步",
        }.get(variant_id)

    def _reset_first_chapter_regeneration_state(self, state: dict[str, Any]) -> dict[str, Any]:
        """Strip generated chapter residue before replaying chapter one.

        Re-running chapter 1 must start from the story bible, not from the
        latest saved game panel. Otherwise old materials like 灰鼠毒腺 leak back
        into a new 灰狼 simulation through current_state.
        """

        reset = dict(state)
        reset["chapter_summaries"] = []
        reset["timeline"] = []
        reset["memory_index"] = []
        reset["current_chapter"] = 0
        reset["progression_ledger"] = {}
        reset.pop("time_state", None)
        chapter_residue_tokens = (
            "第1章",
            "第2章",
            "第3章",
            "第4章",
            "章末",
            "Lv.",
            "Lv",
            "经验",
            "生命",
            "法力",
            "钱袋",
            "背包",
            "灰鼠",
            "灰狼毒腺",
            "粗糙狼皮",
            "清道夫",
            "后坡",
            "巡夜",
            "废井",
            "驱狼粉",
            "污染源",
        )
        reset["world_facts"] = [
            fact
            for fact in list(reset.get("world_facts") or [])
            if not str(fact).startswith("第") and not any(token in str(fact) for token in chapter_residue_tokens)
        ]
        characters = []
        for character in list(reset.get("characters") or []):
            if not isinstance(character, dict):
                continue
            role = str(character.get("role") or "")
            if role not in {"主角", "protagonist"} and str(character.get("name") or "") != "苏叶":
                continue
            cleaned = dict(character)
            # Rebuild the target chapter from the story bible, not a game_state
            # materialized from the stale legacy panel during normal loading.
            cleaned.pop("game_state", None)
            cleaned["game_panel"] = {"game_id": cleaned.get("game_id") or "夜烬"}
            cleaned["memory"] = [
                item
                for item in list(cleaned.get("memory") or [])
                if not any(token in str(item) for token in chapter_residue_tokens)
            ]
            if not cleaned["memory"]:
                cleaned["memory"] = [
                    "现实段落用苏叶，游戏内行动、交易、任务和玩家称呼优先用夜烬。",
                    "现实账单压力未解决；现实余额只有发生到账、提现、卖币或支付剧情时才更新。",
                ]
            cleaned["goals"] = ["进入《天启之门》，低调验证千倍爆率能不能带来成长领先。"]
            cleaned["location"] = "现实出租屋，等待《天启之门》开服"
            cleaned["current_emotion"] = "tense"
            characters.append(cleaned)
        if characters:
            reset["characters"] = characters
        return reset

    def regenerate_chapter(
        self,
        chapter_number: int,
        engine: Any | None = None,
        *,
        variant: str | None = None,
        guidance: str | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        from packages.story_core.engine import StoryEngine

        if chapter_number < 1:
            raise ValueError("chapter_number_must_be_positive")
        self._assert_chapter_not_frozen(chapter_number, "regenerate")
        self._assert_opening_preflight(chapter_number)

        if chapter_number > 1:
            base_chapter = self.chapter(chapter_number - 1)
            base_state = dict(self.state())
        else:
            base_state = self._reset_first_chapter_regeneration_state(dict(self.state()))

        base_state["current_chapter"] = chapter_number - 1
        ledger = dict(base_state.get("progression_ledger") or {})
        variant_payload = self._regeneration_variant(chapter_number)
        if variant:
            variant_payload = {**variant_payload, "id": variant}
            if variant == "progression-lead":
                variant_payload.setdefault("axes", ["千倍爆率转化为任务/装备/技能/路线领先"])
                variant_payload.setdefault(
                    "avoid",
                    ["公开炫耀清道夫委托", "市场玩家盯盘", "提现换算人民币", "公会追查", "把材料账本写成第一章公开高潮"],
                )
                variant_payload["skip_expansion"] = False
        # Regeneration should first prove the simulated facts can land cleanly.
        # Whole-chapter style adaptation is slow and can rewrite locked nouns,
        # so it is an explicit later pass instead of part of default retry.
        variant_payload.setdefault("skip_style_adapt", True)
        variant_payload.setdefault("skip_expansion", False)
        guidance_text = self._compact_text(guidance, 1200)
        if guidance_text:
            variant_payload["rewrite_guidance"] = {"source": "book_dissection", "text": guidance_text}
        ledger["simulation_variant"] = variant_payload
        base_state["progression_ledger"] = ledger

        project = self.project()
        story_payload = dict(base_state)
        story_payload["outline_context"] = self._story_state_payload_for_direction(
            base_state,
            project,
            chapter_number,
        )["outline_context"]
        story = StoryState.model_validate(story_payload)
        generator = engine or StoryEngine()
        bundle = generator.generate_next_chapter(story)
        if int(getattr(bundle, "chapter_number", 0) or 0) != chapter_number:
            raise ValueError(f"regenerated_wrong_chapter:{getattr(bundle, 'chapter_number', None)}")
        quality_report = getattr(bundle, "quality_report", None)
        writing_review = quality_report.get("writing_review") if isinstance(quality_report, dict) else None
        if isinstance(quality_report, dict) and quality_report and quality_report.get("ok") is False:
            issues = quality_report.get("issues") or []
            if isinstance(writing_review, dict):
                issues = [*issues, *(writing_review.get("issues") or [])]
            issue_text = "; ".join(str(item) for item in issues[:5] if str(item).strip())
            if _regeneration_quality_blocking(quality_report, writing_review if isinstance(writing_review, dict) else None):
                raise ValueError(f"regenerated_quality_failed:{issue_text or 'quality_report_not_ok'}")
            quality_report["regeneration_quality_warning"] = [str(item) for item in issues if str(item).strip()][:10]
        title_override = self._regeneration_title_override(chapter_number, str(variant_payload.get("id") or ""))
        if title_override:
            bundle.chapter_title = title_override
            if isinstance(getattr(bundle, "chapter_summary", None), dict):
                bundle.chapter_summary["chapter_title"] = title_override
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

    def rewrite_chapter(
        self,
        *,
        chapter_number: int,
        body: str,
        title: str | None = None,
        next_outline: str | None = None,
        instructions: list[str] | None = None,
        commit_message: str | None = None,
    ) -> dict[str, Any]:
        self._assert_chapter_not_frozen(chapter_number, "rewrite")
        self._assert_opening_preflight(chapter_number)
        if not str(body).strip():
            raise ValueError("body_required")
        chapter = dict(self.chapter(chapter_number))
        next_title = title or str(chapter.get("chapter_title") or f"Chapter {chapter_number}")
        chapter["chapter_title"] = next_title
        chapter["body"] = body
        if next_outline is not None:
            chapter["next_outline"] = next_outline or "continue"
        chapter["manual_instructions"] = [*(chapter.get("manual_instructions") or []), *(instructions or [])]
        summary = dict(chapter.get("chapter_summary") or {})
        summary["chapter_title"] = next_title
        summary.setdefault("cadence", chapter.get("cadence") or "measured")
        existing_summary = self._compact_text(summary.get("summary"), 320)
        summary["summary"] = (
            existing_summary
            if existing_summary and not self._is_placeholder_text(existing_summary)
            else self._compact_text(body, 320)
        )
        if instructions:
            summary["facts"] = [item for item in instructions if str(item).strip()]
        else:
            summary.setdefault("facts", ["manual rewrite"])
        summary.setdefault("next_focus", chapter.get("next_outline") or "continue")
        summary.setdefault("primary_conflict", "manual rewrite")
        summary.setdefault("secondary_conflict", "manual rewrite")
        summary.setdefault("event_beat", "manual rewrite")
        chapter["chapter_summary"] = summary
        chapter.setdefault("cadence", "measured")
        chapter.setdefault("next_outline", summary.get("next_focus") or "continue")
        chapter["chapter_intent"] = {
            "next_focus": chapter["next_outline"],
            "primary_conflict": summary.get("primary_conflict") or "manual rewrite",
        }
        chapter["event_plan"] = {
            "chapter_number": chapter_number,
            "next_focus": chapter["next_outline"],
            "summary": summary.get("summary") or f"Manual rewrite chapter {chapter_number}.",
            "stakes": summary.get("summary") or chapter["next_outline"],
            "world_reactions": summary.get("facts", [])[:3],
        }
        chapter["simulation_plan"] = {
            "chapter_number": chapter_number,
            "chapter_goal": chapter["next_outline"],
        }
        updated_story = self._state_before_chapter(chapter_number)
        updated_story.setdefault("timeline", [f"chapter {chapter_number}: {next_title}"])
        updated_story.setdefault("chapter_summaries", [summary])
        chapter["updated_story"] = updated_story

        chapter = self._hydrate_chapter_display_fields(chapter, updated_story)
        review = _manual_chapter_quality_report(chapter)
        chapter["quality_report"] = review
        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=next_title,
            review=review,
            operation="rewrite",
        )
        self._sync_after_chapter(chapter, updated_story)
        paths = self._chapter_paths(chapter_number, next_title)
        self._remove_chapter_markdowns(chapter_number)
        self._write_json(paths["json"], chapter)
        self._write_json(paths["review"], review)
        self._write_text(paths["markdown"], body)
        commit = self.commit(
            message=commit_message or f"rewrite chapter {chapter_number}",
            operation="rewrite",
            chapter_number=chapter_number,
        )
        return {
            "schema_version": "file-project-rewrite/v1",
            "root": str(self.root),
            "chapter_number": chapter_number,
            "chapter_title": next_title,
            "files": {key: path.relative_to(self.root).as_posix() for key, path in paths.items() if path.exists()},
            "review": review,
            "commit": commit,
        }

    def summary(self) -> dict[str, Any]:
        project = self.project()
        state = self.state()
        chapters = [
            {
                "chapter_number": int(self.chapter(number).get("chapter_number") or number),
                "chapter_title": str(self.chapter(number).get("chapter_title") or f"第{number}章"),
            }
            for number in self.chapter_numbers()
        ]
        return {
            "schema_version": "file-project-summary/v1",
            "root": str(self.root),
            "project_id": project.get("project_id"),
            "title": project.get("title") or state.get("outline"),
            "active_story_id": project.get("active_story_id") or state.get("story_id"),
            "current_chapter": state.get("current_chapter") or (chapters[-1]["chapter_number"] if chapters else 0),
            "chapter_count": len(chapters),
            "chapters": chapters,
        }

    def query(self, keyword: str, *, max_results: int = 20) -> dict[str, Any]:
        needle = keyword.strip()
        if not needle:
            raise ValueError("keyword_required")
        results: list[dict[str, Any]] = []
        search_paths = [
            self.story_system_dir / "MASTER_SETTING.json",
            self.webnovel_dir / "project.json",
            self.webnovel_dir / "state.json",
            *sorted((self.story_system_dir / "chapters").glob("*.json")),
            *sorted(self.chapters_dir.glob("*.md")),
        ]
        for path in search_paths:
            if not path.exists() or not path.is_file():
                continue
            text = path.read_text(encoding="utf-8", errors="ignore")
            index = text.find(needle)
            if index < 0:
                continue
            start = max(0, index - 80)
            end = min(len(text), index + len(needle) + 120)
            results.append(
                {
                    "file": str(path.relative_to(self.root)),
                    "match": needle,
                    "snippet": text[start:end].replace("\r\n", "\n"),
                }
            )
            if len(results) >= max_results:
                break
        return {
            "schema_version": "file-project-query/v1",
            "root": str(self.root),
            "keyword": needle,
            "result_count": len(results),
            "results": results,
        }

    def _story_state_payload_for_direction(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        target_chapter: int,
    ) -> dict[str, Any]:
        project_outline = dict(self.project_outline())
        project_outline.pop("source", None)
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        state_genre_ids = state.get("genre_plugin_ids")
        project_genre_ids = world_blueprint.get("genre_plugin_ids")
        genre_plugin_ids = normalize_novel_type_ids(state_genre_ids)
        if not genre_plugin_ids:
            genre_plugin_ids = normalize_novel_type_ids(project_genre_ids)
        characters: list[dict[str, Any]] = []
        for item in state.get("characters", []) if isinstance(state.get("characters"), list) else []:
            if not isinstance(item, dict):
                continue
            panel = item.get("game_panel") if isinstance(item.get("game_panel"), dict) else {}
            characters.append(
                {
                    "name": str(item.get("name") or panel.get("game_id") or "主角"),
                    "role": str(item.get("role") or "protagonist"),
                    "game_id": str(item.get("game_id") or panel.get("game_id") or ""),
                }
            )
            if len(characters) >= 4:
                break
        return {
            "story_id": str(state.get("story_id") or project.get("active_story_id") or project.get("project_id") or "file-project"),
            "outline": str(state.get("outline") or project.get("seed_outline") or project.get("title") or ""),
            "genre": str(state.get("genre") or project.get("genre") or ""),
            "genre_plugin_ids": genre_plugin_ids,
            "style": str(state.get("style") or project.get("style") or ""),
            "current_chapter": int(state.get("current_chapter") or 0),
            "enabled_skill_ids": list(project.get("enabled_skill_ids") or state.get("enabled_skill_ids") or []),
            "author_constraints": list(state.get("author_constraints") or []),
            "world_facts": list(state.get("world_facts") or []),
            "progression_ledger": dict(state.get("progression_ledger") or {}),
            "characters": characters,
            "outline_context": select_outline_context(project_outline, target_chapter),
        }

    def _chapter_direction_options(self, state: dict[str, Any], project: dict[str, Any], chapter_number: int) -> dict[str, Any]:
        story = StoryState.model_validate(self._story_state_payload_for_direction(state, project, chapter_number))
        return build_chapter_direction_options(story, chapter_number)

    def _resolve_chapter_direction(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        chapter_number: int,
        chapter_direction_id: str | None,
    ) -> dict[str, Any]:
        direction_id = str(chapter_direction_id or "").strip()
        if not direction_id:
            return {}
        options = self._chapter_direction_options(state, project, chapter_number)
        for option in options.get("options", []):
            if isinstance(option, dict) and str(option.get("id") or "") == direction_id:
                return option
        raise ValueError(f"unknown_chapter_direction:{direction_id}")

    def writing_packet(self, chapter_number: int | None = None) -> dict[str, Any]:
        state = self.state()
        project = self.project()
        world_blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        forbidden_breaks = world_blueprint.get("forbidden_breaks") if isinstance(world_blueprint.get("forbidden_breaks"), list) else []
        progression_rules = world_blueprint.get("progression_rules") if isinstance(world_blueprint.get("progression_rules"), list) else []
        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        latest_chapter = self.chapter(latest_number) if latest_number else {}
        target = chapter_number or int(state.get("current_chapter") or latest_number or 0) + 1
        project_outline = dict(self.project_outline())
        project_outline.pop("source", None)
        selected_outline = select_outline_context(project_outline, int(target or 0))
        outline_context = {
            "overall": selected_outline.get("overall"),
            "active_arc": selected_outline.get("active_arc"),
            "chapter": selected_outline.get("chapter"),
        }
        chapter_outline = outline_context["chapter"] if isinstance(outline_context.get("chapter"), dict) else {}
        recent = []
        for number in numbers[-3:]:
            item = self.chapter(number)
            recent.append(
                {
                    "chapter_number": item.get("chapter_number"),
                    "chapter_title": item.get("chapter_title"),
                    "summary": (item.get("chapter_summary") or {}).get("summary"),
                    "next_focus": item.get("next_outline") or (item.get("event_plan") or {}).get("next_focus"),
                }
            )
        scene_cards: list[dict[str, Any]] = []
        if chapter_outline:
            chapter = int(chapter_outline.get("chapter_number") or target or 0)
            title = self._compact_text(chapter_outline.get("title"), 80) or f"第{chapter}章剧情点"
            goal = self._compact_text(chapter_outline.get("goal"), 220)
            action = self._compact_text(chapter_outline.get("action"), 220)
            payoff = self._compact_text(chapter_outline.get("payoff"), 220)
            turn = self._compact_text(chapter_outline.get("turn"), 220)
            hook = self._compact_text(chapter_outline.get("ending_hook"), 180)
            scene_cards.append(
                {
                    "id": f"outline-beat-{chapter}",
                    "title": title,
                    "purpose": payoff or goal or action or turn or "按大纲推进本章明确结果。",
                    "goal": goal,
                    "action": action,
                    "payoff": payoff,
                    "turn": turn,
                    "ending_hook": hook,
                    "chapter": chapter,
                    "source": "outline_context.chapter",
                    "line": chapter_outline.get("line"),
                    "scene_line": chapter_outline.get("scene_line"),
                }
            )
        is_game_story = self._is_game_story_payload(project, state)
        scene_kind = self._writer_scene_kind(scene_cards, is_game_story=is_game_story)
        hard_locks = [
            "正文必须满足目标字数区间，低于下限不能通过章节检查。",
            "前十章每章必须给出可见成长或可见收益，不能连续只给线索。",
            "装备称呼统一写法杖或新手法杖，不用木杖、抬杖、握杖、杖身、杖尖这类生硬简称。",
            "游戏内说前置任务或前置条件，不写任务门槛。",
            "新人物出场前必须先有角色卡；没有角色卡只能作为待出场对象提出，不能直接写成已出场角色。",
        ]
        current_focus = state.get("current_focus") or project.get("current_focus")
        if current_focus:
            hard_locks.append(f"当前主线焦点：{self._compact_text(current_focus, 220)}")
        if chapter_outline:
            goal = self._compact_text(chapter_outline.get("goal"), 220)
            payoff = self._compact_text(chapter_outline.get("payoff"), 220)
            hook = self._compact_text(chapter_outline.get("ending_hook"), 180)
            if goal:
                hard_locks.append(f"第{target}章目标：{goal}")
            if payoff:
                hard_locks.append(f"第{target}章必须兑现：{payoff}")
            if hook:
                hard_locks.append(f"第{target}章结尾钩子：{hook}")
        hard_locks.extend(str(item) for item in progression_rules[:4] if str(item).strip())
        hard_locks.extend(str(item) for item in forbidden_breaks[:4] if str(item).strip())
        characters = self._writer_character_cards(state, selected_outline, scene_kind=scene_kind)
        relationship_context = select_relationship_subgraph(
            project.get("relationship_graph"),
            [str(card.get("name") or "") for card in characters],
        )
        chapter_direction_options = self._chapter_direction_options(state, project, int(target or 0))
        enabled_skill_ids = [
            str(item).strip()
            for item in (project.get("enabled_skill_ids") or state.get("enabled_skill_ids") or [])
            if str(item).strip()
        ]
        skill_context = {
            purpose: skill_pack_prompt_context(enabled_skill_ids, purpose=purpose, max_chars_per_pack=2600)
            for purpose in ("writer", "dialogue", "style", "genre", "continuity", "reviewer")
        }
        packet_project = dict(project)
        packet_project["character_profiles"] = characters
        packet_project.pop("relationship_graph", None)
        if isinstance(project.get("world_blueprint"), dict):
            packet_blueprint = dict(world_blueprint)
            packet_blueprint.pop("current_arc", None)
            packet_blueprint.pop("opening_arc", None)
            packet_project["world_blueprint"] = packet_blueprint
        return {
            "schema_version": "file-writing-packet/v1",
            "root": str(self.root),
            "target_chapter": target,
            "chapter_number": target,
            "scene_kind": scene_kind,
            "latest_chapter_number": latest_number,
            "prose_renderer": prose_renderer_contract(),
            "target_chars": {"min": FILE_CHAPTER_MIN_CHARS, "max": FILE_CHAPTER_MAX_CHARS},
            "hard_locks": hard_locks,
            "scene_cards": scene_cards,
            "outline_context": outline_context,
            "character_cards": characters,
            "relationship_context": relationship_context,
            "title_contract": {
                "style": "tomato_concrete_short_title",
                "rules": [
                    "4到10字左右，像真实章节目录，不像广告文案",
                    "优先使用具体事件、地点、道具、职业、NPC服务点或委托名",
                    "可以有悬念，但不要用“他/别人/没人知道”这类营销句式",
                    "避免材料数量、铜币账目、成本核算、后台规则和说明句",
                ],
                "examples": [
                    "登录建号",
                    "职业学徒",
                    "任务委托",
                    "低级野怪区",
                    "回村补给",
                ],
            },
            "style_rules": [
                '语言贴近番茄爆款网文的白话节奏：目标清楚、反馈直接，旁白少做抽象解释；每个场景都要有目标、阻力、收益或危机。少解释只针对旁白，对话不能省略连接词和因果，必须把原因、条件或态度说完整。',
                "正文少用比喻和形容词链，优先写动作、数值、道具消耗、位置变化和直接后果。",
                "每个场景都要有目标、阻力、收益或危机，结尾必须留下下一步问题。",
                "前10章节奏要快，连续两章不能只拿线索不给成长；下一章至少兑现一个可见成长：等级、经验大幅推进、技能、装备、货币补给或任务权限。",
                "装备称呼统一：普通叙述只写“法杖”或“新手法杖”，修理、持握、表面裂纹和攻击动作都用完整称呼；“裂纹杖芯”作为道具名可以保留。",
                "人物先行：本章要出场的新NPC必须先在角色卡里有候选卡；模型只能提出建议，不能直接改写既有角色主档。",
            ],
            "outline_constraints": {
                "volume_plan": world_blueprint.get("volume_plan") or {},
                "longform_framework": world_blueprint.get("longform_framework") or {},
                "chapter_formula": world_blueprint.get("chapter_formula") or [],
                "progression_rules": progression_rules,
                "forbidden_breaks": forbidden_breaks,
            },
            "project": packet_project,
            "state": {
                "story_id": state.get("story_id"),
                "genre": state.get("genre"),
                "style": state.get("style"),
                "current_chapter": state.get("current_chapter"),
                "current_focus": state.get("current_focus") or project.get("current_focus"),
                "time_state": state.get("time_state") or world_blueprint.get("time_state", {}),
                "author_constraints": state.get("author_constraints", []),
                "world_facts": state.get("world_facts", [])[-20:],
                "characters": characters,
            },
            "recent_chapters": recent,
            "latest_review": self.review(None) if numbers else {},
            "latest_event_plan": latest_chapter.get("event_plan", {}) if isinstance(latest_chapter, dict) else {},
            "chapter_direction_options": chapter_direction_options,
            "skill_context": {key: value for key, value in skill_context.items() if value},
        }

    def _prompt_plan_from_chapter(self, chapter: dict[str, Any]) -> dict[str, Any]:
        plan: dict[str, Any] = {}
        for key in (
            "character_moves",
            "chapter_intent",
            "event_plan",
            "memory_constraints",
            "chapter_seed",
            "simulation_plan",
            "world_events",
            "scene_cards",
            "style_guidance",
            "governance",
            "writing_taskbook",
        ):
            value = chapter.get(key)
            if value not in (None, "", [], {}):
                plan[key] = value
        return plan

    @staticmethod
    def _prompt_entry(
        *,
        key: str,
        title: str,
        agent: str,
        stage: str,
        content: str,
        source: str,
        description: str = "",
        module_keys: list[str] | None = None,
    ) -> dict[str, Any]:
        text = str(content or "")
        return {
            "key": key,
            "title": title,
            "agent": agent,
            "stage": stage,
            "source": source,
            "description": description,
            "content": text,
            "chars": len(text),
            "module_keys": list(module_keys or []),
        }

    @staticmethod
    def _prompt_review_payload(review: Any) -> dict[str, Any]:
        if not isinstance(review, dict):
            return {}
        nested = review.get("writing_review") if isinstance(review.get("writing_review"), dict) else None
        if nested:
            merged = dict(nested)
            for key in ("ok", "pass", "issues", "revision_plan", "scores"):
                if key in review and key not in merged:
                    merged[key] = review[key]
            return merged
        return review

    def _slim_prompt_preview_value(self, value: Any, *, depth: int = 0) -> Any:
        if depth > 4:
            return self._compact_text(value, 160)
        if isinstance(value, str):
            return self._compact_text(value, 180)
        if isinstance(value, list):
            return [self._slim_prompt_preview_value(item, depth=depth + 1) for item in value[:8]]
        if isinstance(value, dict):
            result: dict[str, Any] = {}
            for key, item in value.items():
                if item in (None, "", [], {}):
                    continue
                result[str(key)] = self._slim_prompt_preview_value(item, depth=depth + 1)
            return result
        return value

    def _compact_prompt_preview_packet(self, packet: Any) -> dict[str, Any]:
        if not isinstance(packet, dict):
            return {}

        state = packet.get("state") if isinstance(packet.get("state"), dict) else {}
        outline_constraints = packet.get("outline_constraints") if isinstance(packet.get("outline_constraints"), dict) else {}
        latest_review = packet.get("latest_review") if isinstance(packet.get("latest_review"), dict) else {}
        latest_event_plan = packet.get("latest_event_plan") if isinstance(packet.get("latest_event_plan"), dict) else {}
        characters = state.get("characters") if isinstance(state.get("characters"), list) else []
        recent_chapters = packet.get("recent_chapters") if isinstance(packet.get("recent_chapters"), list) else []

        return {
            "schema_version": packet.get("schema_version"),
            "target_chapter": packet.get("target_chapter"),
            "scene_kind": packet.get("scene_kind"),
            "instruction": self._compact_text(packet.get("instruction"), 260),
            "hard_locks": [self._compact_text(item, 160) for item in packet.get("hard_locks", [])[:10]],
            "scene_cards": self._slim_prompt_preview_value(packet.get("scene_cards", [])[:6]),
            "outline_context": self._slim_prompt_preview_value(packet.get("outline_context")),
            "title_contract": self._slim_prompt_preview_value(packet.get("title_contract")),
            "style_rules": [self._compact_text(item, 180) for item in packet.get("style_rules", [])[:6]],
            "outline_constraints": {
                "volume_plan": self._slim_prompt_preview_value(outline_constraints.get("volume_plan")),
                "longform_framework": self._slim_prompt_preview_value(outline_constraints.get("longform_framework")),
                "chapter_formula": self._slim_prompt_preview_value(outline_constraints.get("chapter_formula", [])[:8]),
                "progression_rules": self._slim_prompt_preview_value(outline_constraints.get("progression_rules", [])[:6]),
                "forbidden_breaks": self._slim_prompt_preview_value(outline_constraints.get("forbidden_breaks", [])[:8]),
            },
            "state": {
                "story_id": state.get("story_id"),
                "genre": state.get("genre"),
                "style": state.get("style"),
                "current_chapter": state.get("current_chapter"),
                "current_focus": self._compact_text(state.get("current_focus"), 260),
                "time_state": self._slim_prompt_preview_value(state.get("time_state")),
                "author_constraints": [self._compact_text(item, 160) for item in state.get("author_constraints", [])[:8]],
                "world_facts": [self._compact_text(item, 180) for item in state.get("world_facts", [])[-10:]],
                "characters": [
                    {
                        "name": item.get("name"),
                        "role": item.get("role"),
                        "location": self._compact_text(item.get("location"), 80),
                        "goal": self._compact_text(item.get("goal"), 140),
                        "state_context": self._slim_prompt_preview_value(item.get("state_context")),
                    }
                    for item in characters[:6]
                    if isinstance(item, dict)
                ],
            },
            "recent_chapters": [
                {
                    "chapter_number": item.get("chapter_number"),
                    "chapter_title": item.get("chapter_title"),
                    "summary": self._compact_text(item.get("summary") or item.get("body"), 220),
                    "next_focus": self._compact_text(item.get("next_focus"), 160),
                }
                for item in recent_chapters[-3:]
                if isinstance(item, dict)
            ],
            "latest_event_plan": self._slim_prompt_preview_value(
                {
                    "chapter_title": latest_event_plan.get("chapter_title"),
                    "turn": latest_event_plan.get("turn"),
                    "pivot": latest_event_plan.get("pivot"),
                    "collision": latest_event_plan.get("collision"),
                    "stakes": latest_event_plan.get("stakes"),
                    "next_focus": latest_event_plan.get("next_focus"),
                    "chapter_end_hook": latest_event_plan.get("chapter_end_hook"),
                }
            ),
            "latest_review": self._slim_prompt_preview_value(
                {
                    "ok": latest_review.get("ok") if "ok" in latest_review else latest_review.get("pass"),
                    "issues": latest_review.get("issues", [])[:8],
                    "revision_plan": latest_review.get("revision_plan", [])[:8],
                    "scores": latest_review.get("scores"),
                }
            ),
            "note": "提示词面板显示压缩写作包；完整写作包仍由 writing_packet 接口返回。",
        }

    def prompt_preview(self, chapter_number: int | None = None) -> dict[str, Any]:
        from packages.story_core.orchestrator import (
            MAX_CHAPTER_CHARS,
            TARGET_CHAPTER_CHARS,
            StoryOrchestrator,
            _character_context_for_prompt,
            _genre_context_for_prompt,
            _story_snapshot,
        )
        from packages.story_core.prompt_modules import modules_for_stage, prompt_module_catalog
        from packages.story_core.style_adaptation import build_style_adapt_prompt

        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        state = self.state()
        project = self.project()
        target = int(chapter_number or state.get("current_chapter") or latest_number or 1)
        chapter: dict[str, Any] = {}
        try:
            chapter = self.chapter(target)
        except FileNotFoundError:
            chapter = {}

        state_before_chapter = self._state_before_chapter(target)
        story_payload = dict(state_before_chapter)
        story_payload["outline_context"] = self._story_state_payload_for_direction(
            state_before_chapter,
            project,
            target,
        )["outline_context"]
        story = StoryState.model_validate(story_payload)
        orchestrator = StoryOrchestrator()
        writing_packet = self.writing_packet(target)
        plan = self._prompt_plan_from_chapter(chapter)
        plan["scene_cards"] = writing_packet.get("scene_cards", [])
        body = str(chapter.get("body") or "")
        review = chapter.get("quality_report") if isinstance(chapter.get("quality_report"), dict) else {}
        if not review and chapter:
            try:
                review = self.review(target)
            except FileNotFoundError:
                review = {}
        review = self._prompt_review_payload(review)

        core_context = _story_snapshot(story)
        character_context = _character_context_for_prompt(story, plan)
        genre_context = _genre_context_for_prompt(story, target, plan)
        modules: list[dict[str, Any]] = [
            self._prompt_entry(
                key="core_context",
                title="核心上下文模块",
                agent="context",
                stage="核心上下文",
                content=json.dumps(core_context, ensure_ascii=False, indent=2),
                source="orchestrator._story_snapshot",
                description="主线、世界事实、账本、最近记忆和活世界信号；不包含完整人物角色卡。",
            ),
            self._prompt_entry(
                key="character_context",
                title="本章人物模块",
                agent="context",
                stage="人物角色卡",
                content=json.dumps(character_context, ensure_ascii=False, indent=2),
                source="orchestrator._character_context_for_prompt",
                description="按本章计划提取出场人物的角色卡；不是全量人物库。",
            ),
            self._prompt_entry(
                key="genre_context",
                title="题材写法模块",
                agent="context",
                stage="题材写法",
                content=json.dumps(genre_context, ensure_ascii=False, indent=2),
                source="orchestrator._genre_context_for_prompt",
                description="按项目题材单独选择写法。当前网游项目加载网游模块，其他题材加载对应模块。",
            ),
        ]
        enabled_skill_ids = [
            str(item).strip()
            for item in (project.get("enabled_skill_ids") or state.get("enabled_skill_ids") or [])
            if str(item).strip()
        ]
        for purpose, title in (
            ("writer", "正文写作 Skill"),
            ("dialogue", "对话 Skill"),
            ("style", "风格 Skill"),
            ("genre", "题材 Skill"),
            ("continuity", "连续性 Skill"),
            ("reviewer", "审稿 Skill"),
        ):
            skill_context = skill_pack_prompt_context(enabled_skill_ids, purpose=purpose, max_chars_per_pack=2600)
            if not skill_context:
                continue
            modules.append(
                self._prompt_entry(
                    key=f"skill_context_{purpose}",
                    title=title,
                    agent="context",
                    stage="Skill",
                    content=json.dumps(skill_context, ensure_ascii=False, indent=2),
                    source=f"skill_packs.enabled_skill_ids.{purpose}",
                    description="按用途裁剪后的本地 skill 包内容；只在相关阶段读取。",
                )
            )
        if isinstance(review, dict) and review:
            modules.append(
                self._prompt_entry(
                    key="review_context",
                    title="审稿报告模块",
                    agent="review",
                    stage="审稿报告",
                    content=json.dumps(review, ensure_ascii=False, indent=2),
                    source="chapter.quality_report",
                    description="改稿阶段才读取的审稿问题和修复清单。",
                )
            )
        packet_preview = self._compact_prompt_preview_packet(writing_packet)
        modules.append(
            self._prompt_entry(
                key="packet_context",
                title="写作包预览模块",
                agent="codex",
                stage="写作包",
                content=json.dumps(packet_preview, ensure_ascii=False, indent=2),
                source="file_project_store.writing_packet_compact_preview",
                description="给人工/Codex查看的压缩写作包；完整写作包仍由写作包接口返回。",
            )
        )

        prompts: list[dict[str, Any]] = [
            self._prompt_entry(
                key="director_plan",
                title="导演/剧情计划 Prompt",
                agent="director",
                stage="剧情计划生成",
                content=orchestrator._plan_prompt(story, target),
                source="rebuilt_from_state_before_chapter",
                description="生成 event_plan、chapter_intent、scene_cards 等结构化剧情计划。",
                module_keys=["core_context", "outline_context"],
            ),
            self._prompt_entry(
                key="writer_body",
                title="整章正文 Prompt",
                agent="writer",
                stage="整章正文生成",
                content=orchestrator._body_prompt(story, target, plan),
                source="rebuilt_from_chapter_plan",
                description="整章正文实际提示词，按输出要求、本章方向、本章事实、出场人物和正文写法五块装配。",
                module_keys=[
                    "core_context",
                    "outline_context",
                    "chapter_plan",
                    "character_context",
                    "genre_context",
                    "style_context",
                    "skill_context_writer",
                    "skill_context_dialogue",
                    "skill_context_style",
                    "skill_context_genre",
                    "writing_taskbook",
                ],
            ),
        ]

        taskbook = plan.get("writing_taskbook")
        if isinstance(taskbook, dict):
            taskbook_module = self._prompt_entry(
                key="writing_taskbook",
                title="本章方向模块",
                agent="context",
                stage="本章方向",
                content=format_taskbook_brief_section(taskbook),
                source="chapter.writing_taskbook",
                description="只保留本章目标、场面推进和收束，不重复通用风格规则。",
            )
            modules.append(taskbook_module)
            prompts.append(
                self._prompt_entry(
                    key="writing_taskbook",
                    title="写作任务书 Prompt 片段",
                    agent="writer",
                    stage="写作任务书",
                    content=taskbook_module["content"],
                    source="chapter.writing_taskbook",
                    description="整章正文读取的场景任务、风格合同和场面写法模板。",
                    module_keys=["writing_taskbook"],
                )
            )

        if body.strip():
            source_body_placeholder = f"[原正文由 source_body 注入；面板不展示正文全文；当前正文 {len(body)} 字。]"
            prompts.extend(
                [
                    self._prompt_entry(
                        key="revision",
                        title="审稿改稿 Prompt",
                        agent="writer",
                        stage="审稿改稿",
                        content=orchestrator._revision_prompt(
                            story,
                            target,
                            source_body_placeholder,
                            plan,
                            review if isinstance(review, dict) else {},
                        ),
                        source="rebuilt_from_chapter_body_and_review",
                        description="章节未通过写作审稿时，用于自动改稿的完整提示词。",
                        module_keys=["core_context", "character_context", "genre_context", "writing_taskbook", "review_context"],
                    ),
                    self._prompt_entry(
                        key="expansion",
                        title="章节扩写 Prompt",
                        agent="writer",
                        stage="章节扩写",
                        content="\n".join(
                            [
                                "下面这章正文太短，请在不改变剧情事实和结尾钩子的前提下扩写成完整网文章节。",
                                f"目标篇幅：{TARGET_CHAPTER_CHARS}。",
                                "扩写重点：补足场景调度、战斗过程、任务/装备/技能/路线前置任务、人物对话、心理活动、系统面板反馈、背景节拍和章末压力；第一章不要补成交易、提交委托、修理或买药水。",
                                "只输出扩写后的小说正文，不要解释，不要列大纲。",
                                f"原正文：\n{source_body_placeholder}",
                            ]
                        ),
                        source="rebuilt_conditional_prompt",
                        description="正文低于目标篇幅时触发。",
                        module_keys=["source_body"],
                    ),
                    self._prompt_entry(
                        key="compression",
                        title="章节压缩 Prompt",
                        agent="writer",
                        stage="章节压缩",
                        content="\n".join(
                            [
                                "下面这章正文超过目标篇幅，请在不改变剧情事实、人物选择、游戏账本、结尾钩子的前提下压缩。",
                                f"目标篇幅：保留完整网文章节感，但压到4300到5000字之间，绝对不要超过{MAX_CHAPTER_CHARS}字。",
                                "压缩方法：删重复解释、删绕圈心理、合并相似动作和面板反馈；保留现实压力、登录建号、首次击杀、异常掉落、背包/血蓝/耐久代价、外人误判和下一步钩子。",
                                "第一章不要新增寄售、上架、成交、到账、手续费扣款、提现、任务提交、修理或买药。",
                                "只输出压缩后的小说正文，不要解释，不要列大纲。",
                                f"原正文：\n{source_body_placeholder}",
                            ]
                        ),
                        source="rebuilt_conditional_prompt",
                        description="正文超过目标篇幅时触发。",
                        module_keys=["source_body"],
                    ),
                    self._prompt_entry(
                        key="style_adapt",
                        title="风格适配 Prompt",
                        agent="writer",
                        stage="风格适配",
                        content=build_style_adapt_prompt(source_body_placeholder, plan),
                        source="rebuilt_conditional_prompt",
                        description="启用风格适配时触发，用于把已生成正文改成项目文风。",
                        module_keys=["writing_taskbook", "source_body"],
                    ),
                ]
            )

        prompts.append(
            self._prompt_entry(
                key="review_agents",
                title="读者/编辑/审稿 Agent 说明",
                agent="review",
                stage="质量审稿",
                content="\n".join(
                    [
                        "读者 agent、编辑 agent、审稿 agent 当前主要读取章节正文和质量报告执行本地规则/函数检查。",
                        "它们不是独立调用 LLM 的隐藏提示词；如果后续接入 LLM 审稿，应把对应 prompt 也写入本接口。",
                    ]
                ),
                source="local_rule_based_review",
                description="说明为什么这里没有额外隐藏 prompt。",
                module_keys=["review_context"],
            )
        )

        return {
            "schema_version": "file-project-prompt-preview/v1",
            "project_id": self.project().get("project_id") or self.root.name,
            "chapter_number": target,
            "chapter_title": chapter.get("chapter_title") or "",
            "source": "rebuilt_from_current_project_files",
            "has_chapter": bool(chapter),
            "module_catalog": prompt_module_catalog(),
            "stage_modules": {
                stage: [module.key for module in modules_for_stage(stage)]
                for stage in ("planning", "writing", "revision", "validation")
            },
            "modules": modules,
            "prompts": prompts,
        }
