from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.cold_reader_review import review_cold_reader_experience
from packages.story_core.editor_agent import review_editor_agent
from packages.story_core.models import StoryState
from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.quality import validate_bundle
from packages.story_core.reader_agent import review_reader_agent
from packages.story_core.reviewer_agent import review_reviewer_agent
from packages.story_core.workflow_telemetry import append_workflow_telemetry
from packages.story_core.writing_learning import learning_snapshot, lessons_from_quality_report, merge_writing_lessons
from packages.story_core.writing_packet import prose_renderer_contract


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


def _manual_chapter_quality_report(chapter: dict[str, Any]) -> dict[str, Any]:
    quality_report = validate_bundle(chapter)
    body = str(chapter.get("body") or "")
    length_review = _chapter_length_review(body)
    ai_flavor_review = review_ai_flavor(body)
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
        "prose_style_review": prose_style_review,
        "cold_reader_review": cold_reader_review,
        "reader_agent_review": reader_agent_review,
        "editor_agent_review": editor_agent_review,
        "reviewer_agent_review": reviewer_agent_review,
        "revision_plan": _merge_revision_plans(
            ai_flavor_review.get("revision_plan", []),
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
                profile["game_panel"] = game_panel | {"updated_chapter": chapter_number}
            by_name[name] = profile
        synced["character_profiles"] = list(by_name.values())
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

    def _sync_ledger_from_chapter_body(self, state: dict[str, Any], chapter: dict[str, Any]) -> dict[str, Any]:
        body = str(chapter.get("body") or "")
        if not body:
            return state
        ledger = dict(state.get("progression_ledger") or {})
        protagonist = dict(ledger.get("protagonist") or {})
        panel = dict(ledger.get("panel") or {})
        economy = dict(ledger.get("economy") or {})
        equipment = dict(ledger.get("equipment") or {})
        quests = dict(ledger.get("quests") or {})

        def last(pattern: str) -> str:
            matches = re.findall(pattern, body)
            return str(matches[-1]).strip() if matches else ""

        exp = last(r"经验[：:]\s*(\d+\s*/\s*\d+)")
        hp = last(r"生命[：:]\s*(\d+\s*/\s*\d+)")
        mp = last(r"法力[：:]\s*(\d+\s*/\s*\d+)")
        durability = last(r"新手法杖[：:]\s*(\d+\s*/\s*\d+)")
        money = last(r"钱袋[：:]\s*([^\n。；；,，】]+)")
        patrol = last(r"后坡巡查[：:]\s*(\d+\s*/\s*\d+)")

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

        inventory_line = last(r"背包[：:]\s*([^\n。]+)")
        if inventory_line:
            inventory: dict[str, int] = {}
            for item, count in re.findall(r"([\u4e00-\u9fffA-Za-z0-9_]+)\s*[×xX*]\s*(\d+)", inventory_line):
                inventory[item] = int(count)
            if inventory:
                economy["inventory"] = inventory
        occupied = last(r"占用[：:]\s*(\d+\s*/\s*20)")
        if not occupied and inventory_line:
            occupied_match = re.search(r"(?:占用)?\s*(\d+\s*/\s*20)", inventory_line)
            occupied = occupied_match.group(1) if occupied_match else ""
        if occupied:
            economy["backpack"] = occupied.replace(" ", "")

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
            if not isinstance(character, dict) or character.get("role") != "protagonist":
                continue
            game_panel = dict(character.get("game_panel") or {})
            game_panel.update(
                {
                    "level": protagonist.get("level", game_panel.get("level")),
                    "identity": protagonist.get("identity", "见习冒险者（未转职）"),
                    "class_path": protagonist.get("class_path", "见习冒险者（未转职）"),
                    "exp": protagonist.get("exp", game_panel.get("exp")),
                    "hp": protagonist.get("hp", game_panel.get("hp")),
                    "mp": protagonist.get("mp", game_panel.get("mp")),
                    "equipment": {"weapon": protagonist.get("weapon_durability", equipment.get("weapon", "新手法杖"))},
                    "inventory": economy.get("inventory", game_panel.get("inventory", {})),
                    "backpack": economy.get("backpack", game_panel.get("backpack", "")),
                    "currency": economy.get("game_currency", game_panel.get("currency", "")),
                    "quests": quests,
                }
            )
            character["game_panel"] = game_panel
        if exp or hp or mp or inventory_line:
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

    def project(self) -> dict[str, Any]:
        return self._read_json(self.webnovel_dir / "project.json", {}) or self.master_setting().get("project", {}) or {}

    def update_project(self, patch: dict[str, Any]) -> dict[str, Any]:
        project = dict(self.project())
        state = dict(self._read_json(self.webnovel_dir / "state.json", {}) or {})
        for key in (
            "title",
            "world_summary",
            "author_constraints",
            "character_profiles",
            "relationship_graph",
            "status",
            "pipeline_stage",
        ):
            if key in patch and patch[key] is not None:
                project[key] = patch[key]
        if patch.get("seed_outline") is not None:
            project["seed_outline"] = patch["seed_outline"]
            state["outline"] = patch["seed_outline"]
        if patch.get("world_blueprint") is not None:
            project["world_blueprint"] = patch["world_blueprint"]
        if patch.get("current_focus") is not None:
            project["current_focus"] = patch["current_focus"]
            state["current_focus"] = patch["current_focus"]
        elif isinstance(project.get("world_blueprint"), dict) and project["world_blueprint"].get("current_arc"):
            project["current_focus"] = project.get("current_focus") or project["world_blueprint"]["current_arc"]
        self._write_json(self.webnovel_dir / "project.json", project)
        self._write_json(self.webnovel_dir / "state.json", state)
        return project

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
        title = str(chapter.get("chapter_title") or f"Chapter {chapter_number}")
        body = str(chapter.get("body") or "")
        if not body.strip():
            raise ValueError("body_required")

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

    def generate_next_chapter(self, engine: Any | None = None, *, commit_message: str | None = None) -> dict[str, Any]:
        from packages.story_core.engine import StoryEngine

        story = StoryState.model_validate(self.state())
        generator = engine or StoryEngine()
        bundle = generator.generate_next_chapter(story)
        persisted = self.persist_bundle(bundle, operation="generate", commit_message=commit_message)
        return {
            "schema_version": "file-project-generate-next/v1",
            "root": str(self.root),
            "chapter_number": persisted["chapter_number"],
            "chapter_title": persisted["chapter_title"],
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
                variant_payload["skip_expansion"] = True
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

        story = StoryState.model_validate(base_state)
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

    def writing_packet(self, chapter_number: int | None = None) -> dict[str, Any]:
        state = self.state()
        project = self.project()
        world_blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
        opening_arc = world_blueprint.get("opening_arc") if isinstance(world_blueprint.get("opening_arc"), dict) else {}
        chapter_beats = opening_arc.get("chapter_beats") if isinstance(opening_arc.get("chapter_beats"), list) else []
        forbidden_breaks = world_blueprint.get("forbidden_breaks") if isinstance(world_blueprint.get("forbidden_breaks"), list) else []
        progression_rules = world_blueprint.get("progression_rules") if isinstance(world_blueprint.get("progression_rules"), list) else []
        numbers = self.chapter_numbers()
        latest_number = numbers[-1] if numbers else 0
        latest_chapter = self.chapter(latest_number) if latest_number else {}
        target = chapter_number or int(state.get("current_chapter") or latest_number or 0) + 1
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
        target_beat = next(
            (
                beat
                for beat in chapter_beats
                if isinstance(beat, dict) and int(beat.get("chapter") or 0) == int(target or 0)
            ),
            {},
        )
        scene_cards: list[dict[str, Any]] = []
        for beat in chapter_beats:
            if not isinstance(beat, dict):
                continue
            chapter = int(beat.get("chapter") or 0)
            if target and chapter and chapter != int(target):
                continue
            title = self._compact_text(beat.get("title"), 80) or f"第{chapter or target}章剧情点"
            purpose = self._compact_text(beat.get("required_payoff") or beat.get("payoff") or beat.get("summary"), 220)
            hook = self._compact_text(beat.get("ending_hook") or beat.get("hook"), 180)
            scene_cards.append(
                {
                    "id": f"outline-beat-{chapter or target}",
                    "title": title,
                    "purpose": purpose or "按大纲推进本章明确收益，不只铺线索。",
                    "ending_hook": hook,
                    "chapter": chapter or target,
                    "source": "outline_constraints.opening_arc.chapter_beats",
                }
            )
        if not scene_cards and target_beat:
            scene_cards.append(
                {
                    "id": f"outline-beat-{target}",
                    "title": self._compact_text(target_beat.get("title"), 80) or f"第{target}章剧情点",
                    "purpose": self._compact_text(target_beat.get("required_payoff") or target_beat.get("payoff"), 220)
                    or "按本章大纲完成可见推进。",
                    "ending_hook": self._compact_text(target_beat.get("ending_hook"), 180),
                    "chapter": target,
                    "source": "outline_constraints.opening_arc.chapter_beats",
                }
            )
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
        if target_beat:
            payoff = self._compact_text(target_beat.get("required_payoff") or target_beat.get("payoff"), 220)
            hook = self._compact_text(target_beat.get("ending_hook") or target_beat.get("hook"), 180)
            if payoff:
                hard_locks.append(f"第{target}章必须兑现：{payoff}")
            if hook:
                hard_locks.append(f"第{target}章结尾钩子：{hook}")
        hard_locks.extend(str(item) for item in progression_rules[:4] if str(item).strip())
        hard_locks.extend(str(item) for item in forbidden_breaks[:4] if str(item).strip())
        characters = state.get("characters", []) if isinstance(state.get("characters"), list) else []
        return {
            "schema_version": "file-writing-packet/v1",
            "root": str(self.root),
            "target_chapter": target,
            "chapter_number": target,
            "latest_chapter_number": latest_number,
            "prose_renderer": prose_renderer_contract(),
            "target_chars": {"min": FILE_CHAPTER_MIN_CHARS, "max": FILE_CHAPTER_MAX_CHARS},
            "hard_locks": hard_locks,
            "scene_cards": scene_cards,
            "character_cards": characters,
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
                '语言贴近番茄爆款网文的白话节奏：目标清楚、反馈直接、少解释；每个场景都要有目标、阻力、收益或危机。句子按场面自然长短，对话必须把原因、条件或态度说完整。',
                "正文少用比喻和形容词链，优先写动作、数值、道具消耗、位置变化和直接后果。",
                "每个场景都要有目标、阻力、收益或危机，结尾必须留下下一步问题。",
                "前10章节奏要快，连续两章不能只拿线索不给成长；下一章至少兑现一个可见成长：等级、经验大幅推进、技能、装备、货币补给或任务权限。",
                "装备称呼统一：普通叙述只写“法杖”或“新手法杖”，修理、持握、表面裂纹和攻击动作都用完整称呼；“裂纹杖芯”作为道具名可以保留。",
                "人物先行：本章要出场的新NPC必须先在角色卡里有候选卡；模型只能提出建议，不能直接改写既有角色主档。",
            ],
            "outline_constraints": {
                "current_arc": world_blueprint.get("current_arc") or project.get("current_focus") or state.get("outline"),
                "opening_arc": opening_arc,
                "volume_plan": world_blueprint.get("volume_plan") or {},
                "longform_framework": world_blueprint.get("longform_framework") or {},
                "chapter_formula": world_blueprint.get("chapter_formula") or [],
                "progression_rules": progression_rules,
                "forbidden_breaks": forbidden_breaks,
            },
            "project": project,
            "state": {
                "story_id": state.get("story_id"),
                "genre": state.get("genre"),
                "style": state.get("style"),
                "current_chapter": state.get("current_chapter"),
                "current_focus": state.get("current_focus") or project.get("current_focus"),
                "time_state": state.get("time_state") or world_blueprint.get("time_state", {}),
                "author_constraints": state.get("author_constraints", []),
                "world_facts": state.get("world_facts", [])[-20:],
                "characters": state.get("characters", []),
            },
            "recent_chapters": recent,
            "latest_review": self.review(None) if numbers else {},
            "latest_event_plan": latest_chapter.get("event_plan", {}) if isinstance(latest_chapter, dict) else {},
        }
