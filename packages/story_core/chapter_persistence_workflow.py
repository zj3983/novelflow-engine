from __future__ import annotations

import re
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any

from packages.story_core.chapter_read_model import (
    _normalize_chapter_title,
    _usable_chapter_title,
)
from packages.story_core.generation_quality import (
    chapter_outline_title as _chapter_outline_title,
)
from packages.story_core.outline_rolling_store import RollingOutlineStore
from packages.story_core.persistence.project_locking import (
    with_project_update_lock as _with_project_update_lock,
)
from packages.story_core.quality import validate_bundle


class ChapterPersistenceWorkflowMixin:
    """Persist manual, generated, regenerated, and historical chapter updates."""

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
        review = self._manual_quality_report(chapter)
        chapter["quality_report"] = review
        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=title,
            review=review,
            operation="write",
        )

        synced_state = self._sync_after_chapter(chapter, updated_story)
        self._remove_chapter_markdowns(chapter_number)
        self._write_text(paths["markdown"], body)
        chapter = self._separate_chapter_body_to_markdown(chapter, paths)
        self._write_json(paths["json"], chapter)
        self._write_json(paths["review"], review)
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

    def _apply_historical_foreshadowing_projection(
        self,
        chapter: dict[str, Any],
        payloads: dict[Path, Any],
        projection: dict[str, Any],
    ) -> None:
        target_chapter = int(chapter.get("chapter_number") or 0)
        state_path = self.webnovel_dir / "state.json"
        if isinstance(payloads.get(state_path), dict):
            payloads[state_path]["foreshadowing"] = deepcopy(projection["final"])
            payloads[state_path]["manual_foreshadowing"] = deepcopy(
                projection.get("manual") or []
            )

        by_chapter = projection.get("by_chapter") or {}
        source_chapters = projection.get("chapters") or {}
        for chapter_number, ledger in by_chapter.items():
            if chapter_number < target_chapter:
                continue
            if chapter_number == target_chapter:
                target_snapshot = chapter.get("updated_story")
                if isinstance(target_snapshot, dict):
                    target_snapshot["foreshadowing"] = deepcopy(ledger)
                continue
            path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            saved_chapter = deepcopy(payloads.get(path) or source_chapters.get(chapter_number))
            snapshot = saved_chapter.get("updated_story") if isinstance(saved_chapter, dict) else None
            if isinstance(snapshot, dict):
                snapshot["foreshadowing"] = deepcopy(ledger)
                payloads[path] = saved_chapter

    def _persist_historical_transaction(
        self,
        chapter: dict[str, Any],
        review: dict[str, Any],
        body: str,
        payloads: dict[Path, Any],
        *,
        operation: str,
        commit_message: str | None,
    ) -> tuple[dict[str, Path], dict[str, Any]]:
        chapter_number = int(chapter.get("chapter_number") or 0)
        title = str(chapter.get("chapter_title") or f"Chapter {chapter_number}")
        paths = self._chapter_paths(chapter_number, title)
        existing_markdowns = list(self.chapters_dir.glob(f"{chapter_number:04d}*.md"))
        managed_snapshot = self._snapshot_managed_files(
            [
                *payloads,
                paths["json"],
                paths["review"],
                paths["markdown"],
                self.story_system_dir / "chapter-index.json",
                *existing_markdowns,
            ],
            [self.story_system_dir / "commits"],
        )
        try:
            payloads[paths["json"]] = chapter
            payloads[paths["review"]] = review
            self._replace_json_transaction(payloads)
            self._remove_chapter_markdowns(chapter_number)
            self._write_text(paths["markdown"], body)
            commit = self.commit(
                message=commit_message or f"{operation} chapter {chapter_number}",
                operation=operation,
                chapter_number=chapter_number,
            )
        except Exception:
            try:
                self._restore_managed_files(*managed_snapshot)
            except Exception as rollback_exc:
                raise RuntimeError("historical_persistence_rollback_failed") from rollback_exc
            raise
        return paths, commit

    def _authoritative_chapter_title(
        self,
        chapter_number: int,
        *,
        operation: str,
        fallback_title: str = "",
    ) -> str:
        """Return the title owned by chapter detail, not by the writer.

        A rewrite preserves the existing formal title. New chapters prefer
        the rolling detail and fall back to the compatible base outline.
        """
        if operation == "regenerate":
            formal = self._read_json(
                self.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
                {},
            )
            formal_title = _usable_chapter_title(
                formal.get("chapter_title") if isinstance(formal, dict) else "",
                chapter_number,
            )
            if formal_title:
                return formal_title

        rolling = RollingOutlineStore(self.root).read_chapter(chapter_number) or {}
        rolling_title = _usable_chapter_title(rolling.get("title"), chapter_number)
        if rolling_title:
            return rolling_title

        outline = self._read_json(self.webnovel_dir / "outline.json", {})
        for row in outline.get("chapters", []) if isinstance(outline, dict) else []:
            if not isinstance(row, dict):
                continue
            if row.get("chapter_number") != chapter_number:
                continue
            base_title = _usable_chapter_title(row.get("title"), chapter_number)
            if base_title:
                return base_title

        # Low-level imports and isolated persistence callers may predate the
        # outline subsystem entirely. Real outlined projects must never use
        # this compatibility path: once outline.json exists, a missing target
        # title is an actionable planning error.
        if not (self.webnovel_dir / "outline.json").is_file() and fallback_title:
            return _normalize_chapter_title(fallback_title, chapter_number)
        raise ValueError(f"chapter_outline_title_required:{chapter_number}")

    @_with_project_update_lock
    def persist_bundle(
        self,
        bundle: Any,
        *,
        operation: str = "generate",
        commit_message: str | None = None,
        accept_quality_warnings: bool = False,
    ) -> dict[str, Any]:
        chapter = self._bundle_to_dict(bundle)
        chapter_number = int(chapter.get("chapter_number") or 0)
        if chapter_number <= 0:
            raise ValueError("chapter_number_must_be_positive")
        raw_title = str(chapter.get("chapter_title") or "").strip()
        if operation in {"generate", "regenerate"}:
            raw_title = self._authoritative_chapter_title(
                chapter_number,
                operation=operation,
                fallback_title=raw_title,
            )
        title = _normalize_chapter_title(raw_title, chapter_number)
        chapter["chapter_title"] = title
        if isinstance(chapter.get("chapter_summary"), dict):
            chapter["chapter_summary"]["chapter_title"] = title
        body = str(chapter.get("body") or "")
        updated_story = chapter.get("updated_story")
        if hasattr(updated_story, "model_dump"):
            updated_story = updated_story.model_dump(mode="json")
            chapter["updated_story"] = updated_story
        quality_report = chapter.get("quality_report")
        if not isinstance(quality_report, dict) or not quality_report:
            quality_report = validate_bundle(chapter)
            chapter["quality_report"] = quality_report
        failure_reason = self._generation_failure_reason(quality_report)
        if not body.strip():
            if operation in {"generate", "regenerate"}:
                if not failure_reason:
                    writing_review = quality_report.get("writing_review") if isinstance(quality_report, dict) else {}
                    if isinstance(writing_review, dict):
                        quality_issues = [str(item) for item in (writing_review.get("issues") or []) if str(item).strip()]
                    else:
                        quality_issues = []
                    if not quality_issues:
                        quality_issues = [str(item) for item in (quality_report.get("issues") or []) if str(item).strip()] if isinstance(quality_report, dict) else []
                    failure_reason = "; ".join(quality_issues[:4]) if quality_issues else "empty_body"
                if not failure_reason:
                    failure_reason = "empty_body"
                reason = failure_reason
                raise ValueError(f"{operation}_failed:{reason}")
            raise ValueError("body_required")
        if operation in {"generate", "regenerate"} and failure_reason and not accept_quality_warnings:
            raise ValueError(f"{operation}_failed:{failure_reason}")
        chapter = self._ensure_regenerate_continuity_fields(
            chapter,
            chapter_number=chapter_number,
            chapter_title=title,
        )
        if not accept_quality_warnings:
            self._assert_generated_chapter_length(body, operation=operation)

        review = quality_report
        if "writing_review" not in review:
            review = {
                "schema_version": "file-writing-review/v1",
                "writing_review": {"pass": bool(quality_report.get("ok")), "issues": quality_report.get("issues", [])},
                "quality_report": quality_report,
            }
            chapter["quality_report"] = review

        assertion_report = quality_report if isinstance(quality_report, dict) else {}
        if "writing_review" in review and isinstance(review["writing_review"], dict) and "writing_review" not in assertion_report:
            assertion_report = dict(assertion_report)
            assertion_report["writing_review"] = review["writing_review"]

        try:
            if accept_quality_warnings:
                assertion_report["manual_quality_override"] = True
                if isinstance(quality_report, dict):
                    quality_report["manual_quality_override"] = True
                if isinstance(review, dict):
                    review["manual_quality_override"] = True
            else:
                self._assert_generated_chapter_quality(
                    assertion_report,
                    operation=operation,
                )
            if bool(assertion_report.get("regeneration_degraded")):
                if isinstance(quality_report, dict):
                    quality_report["regeneration_degraded"] = True
                if isinstance(review, dict):
                    review["regeneration_degraded"] = True
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

        historical_foreshadowing = (
            self._historical_foreshadowing_for_rewrite(chapter)
            if operation == "regenerate"
            else None
        )
        historical_rebase = (
            self._prepare_historical_attribute_rebase(chapter, updated_story)
            if operation == "regenerate"
            else None
        )

        if historical_rebase is not None:
            chapter, payloads = historical_rebase
            if historical_foreshadowing is not None:
                self._apply_historical_foreshadowing_projection(
                    chapter,
                    payloads,
                    historical_foreshadowing,
                )
            paths, commit = self._persist_historical_transaction(
                chapter,
                review,
                body,
                payloads,
                operation=operation,
                commit_message=commit_message,
            )
            self._append_workflow_log(
                chapter_number=chapter_number,
                chapter_title=title,
                review=review,
                operation=operation,
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

        if historical_foreshadowing is not None:
            current_state = self.state()
            target_snapshot = self._validated_runtime_state(updated_story, current_state)
            base_state = self._usable_bundle_state(
                updated_story,
                current_state,
                target_chapter=chapter_number,
            )
            base_state = dict(base_state)
            base_state["foreshadowing"] = deepcopy(historical_foreshadowing["final"])
            chapter = self._hydrate_chapter_display_fields(chapter, base_state)
            synced_state, synced_project = self._prepare_sync_after_chapter(chapter, base_state)
            synced_state["foreshadowing"] = deepcopy(historical_foreshadowing["final"])

            if target_snapshot is not None:
                target_snapshot = self._sync_state_after_chapter(
                    deepcopy(target_snapshot),
                    chapter,
                )
                target_snapshot = self._sync_ledger_from_chapter_body(target_snapshot, chapter)
                target_snapshot["current_chapter"] = chapter_number
                chapter["updated_story"] = target_snapshot

            payloads = {
                self.webnovel_dir / "state.json": synced_state,
                self.webnovel_dir / "project.json": synced_project,
            }
            self._apply_historical_foreshadowing_projection(
                chapter,
                payloads,
                historical_foreshadowing,
            )
            paths, commit = self._persist_historical_transaction(
                chapter,
                review,
                body,
                payloads,
                operation=operation,
                commit_message=commit_message,
            )
            self._append_workflow_log(
                chapter_number=chapter_number,
                chapter_title=title,
                review=review,
                operation=operation,
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

        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=title,
            review=review,
            operation=operation,
        )
        base_state = self._usable_bundle_state(
            updated_story,
            self.state(),
            target_chapter=chapter_number,
        )
        chapter = self._hydrate_chapter_display_fields(chapter, base_state)
        self._sync_after_chapter(chapter, base_state)

        paths = self._chapter_paths(chapter_number, title)
        self._remove_chapter_markdowns(chapter_number)
        self._write_text(paths["markdown"], body)
        chapter = self._separate_chapter_body_to_markdown(chapter, paths)
        self._write_json(paths["json"], chapter)
        self._write_json(paths["review"], review)
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

    @_with_project_update_lock
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
        # A manual body rewrite has no evidence extractor. Keeping the old
        # chapter's thread claims would be less safe than leaving them empty.
        summary["unresolved_threads"] = []
        summary["resolved_threads"] = []
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
        current_state = self.state()
        current_chapter = int(current_state.get("current_chapter") or 0)
        updated_story = self._generation_state_for_target(current_state, chapter_number)
        updated_story.setdefault("timeline", [f"chapter {chapter_number}: {next_title}"])
        updated_story.setdefault("chapter_summaries", [summary])
        chapter["updated_story"] = updated_story

        chapter = self._hydrate_chapter_display_fields(chapter, updated_story)
        review = self._manual_quality_report(chapter)
        chapter["quality_report"] = review
        historical_foreshadowing = self._historical_foreshadowing_for_rewrite(chapter)
        if historical_foreshadowing is not None:
            target_state = self._sync_state_after_chapter(
                self._state_before_chapter(chapter_number),
                chapter,
            )
            target_state = self._sync_ledger_from_chapter_body(target_state, chapter)
            target_state["current_chapter"] = chapter_number
            chapter["updated_story"] = target_state

            global_state = deepcopy(current_state)
            global_state["foreshadowing"] = deepcopy(historical_foreshadowing["final"])
            global_state["manual_foreshadowing"] = deepcopy(
                historical_foreshadowing.get("manual") or []
            )
            global_state["current_chapter"] = current_chapter
            payloads = {self.webnovel_dir / "state.json": global_state}
            self._apply_historical_foreshadowing_projection(
                chapter,
                payloads,
                historical_foreshadowing,
            )
            paths, commit = self._persist_historical_transaction(
                chapter,
                review,
                body,
                payloads,
                operation="rewrite",
                commit_message=commit_message,
            )
        else:
            self._sync_after_chapter(chapter, updated_story)
            paths = self._chapter_paths(chapter_number, next_title)
            self._remove_chapter_markdowns(chapter_number)
            self._write_text(paths["markdown"], body)
            chapter = self._separate_chapter_body_to_markdown(chapter, paths)
            self._write_json(paths["json"], chapter)
            self._write_json(paths["review"], review)
            commit = self.commit(
                message=commit_message or f"rewrite chapter {chapter_number}",
                operation="rewrite",
                chapter_number=chapter_number,
            )
        self._append_workflow_log(
            chapter_number=chapter_number,
            chapter_title=next_title,
            review=review,
            operation="rewrite",
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
