from __future__ import annotations

from hashlib import sha256
from pathlib import Path
from typing import Any

from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.pipeline.chapter_pipeline import build_chapter_pipeline_event
from packages.story_core.persistence.snapshot_store import SnapshotStore
from packages.story_core.workflow_telemetry import append_workflow_telemetry


class ChapterArtifactStoreMixin:
    """Chapter files, workflow telemetry, and candidate draft persistence."""

    @staticmethod
    def _snapshot_managed_files(
        paths: list[Path],
        directories: list[Path],
    ) -> tuple[dict[Path, bytes | None], tuple[Path, ...]]:
        return SnapshotStore.snapshot_managed_files(paths, directories)

    @staticmethod
    def _restore_managed_files(
        snapshot: dict[Path, bytes | None],
        directories: tuple[Path, ...],
    ) -> None:
        SnapshotStore.restore_managed_files(snapshot, directories)

    def _write_text(self, path: Path, text: str) -> None:
        self.snapshot_store.write_text(path, text)

    def _chapter_markdown_name(self, chapter_number: int, title: str) -> str:
        return self.chapter_store.markdown_name(chapter_number, title)

    def _remove_chapter_markdowns(self, chapter_number: int) -> None:
        self.chapter_store.remove_markdowns(chapter_number)

    def _separate_chapter_body_to_markdown(
        self,
        chapter: dict[str, Any],
        paths: dict[str, Path],
    ) -> dict[str, Any]:
        """Move ``chapter['body']`` into a Markdown file and update the metadata.

        After this call the returned chapter dict carries
        ``body_path``, ``body_sha256`` and ``body_chars`` instead of ``body``. The
        Markdown file at ``paths['markdown']`` is the new source
        of truth. The input dict is *not* mutated in place; callers
        that want to keep the legacy body on disk should rely on
        the workbench, not this helper.
        """
        if not isinstance(chapter, dict):
            return chapter
        body_value = chapter.get("body")
        if not isinstance(body_value, str) or not body_value:
            return chapter
        markdown_path = paths.get("markdown")
        if markdown_path is None:
            return chapter
        # Skip the split when the chapter already points at a
        # Markdown body and the recorded hash matches; that means
        # a previous save already split the body and we are
        # rewriting the same content.
        existing_path = chapter.get("body_path")
        existing_sha = chapter.get("body_sha256")
        if (
            existing_path
            and existing_sha
            and Path(str(existing_path)) == markdown_path
            and sha256(body_value.encode("utf-8")).hexdigest()
            == existing_sha
        ):
            updated = dict(chapter)
            updated.pop("body", None)
            updated["body_chars"] = len("".join(body_value.split()))
            return updated
        sha = sha256(body_value.encode("utf-8")).hexdigest()
        try:
            relative = markdown_path.relative_to(self.root)
        except ValueError:
            relative = markdown_path
        updated = dict(chapter)
        updated.pop("body", None)
        updated["body_path"] = str(relative).replace("\\", "/")
        updated["body_sha256"] = sha
        updated["body_chars"] = len("".join(body_value.split()))
        return updated

    def _chapter_paths(self, chapter_number: int, title: str) -> dict[str, Path]:
        return self.chapter_store.paths(chapter_number, title)

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

    def _save_candidate_from_bundle(
        self,
        bundle: Any,
        *,
        project_id: str,
        quality_report: dict[str, Any] | None = None,
        operation: str = "generate",
    ) -> CandidateDraft:
        submission_payload = self._bundle_to_dict(bundle)
        updated_story = submission_payload.get("updated_story")
        if hasattr(updated_story, "model_dump"):
            submission_payload["updated_story"] = updated_story.model_dump(mode="json")
        # Run the fact extractor so the candidate carries a pending
        # ContinuityDelta. The canon view is best-effort: when the
        # project has a registered canon registry we use it,
        # otherwise we fall back to an empty view and the deterministic
        # layer records orphan references only. The wiring here is
        # additive — the existing v1 save path is unchanged for
        # callers that never set a continuity delta.
        chapter_number = int(getattr(bundle, "chapter_number", 0) or 0)
        body = str(getattr(bundle, "body", "") or "")
        # The modular pipeline already ran the FactExtractor against
        # the project's on-disk canon and shipped the resulting
        # ``ContinuityDelta`` on the bundle. Re-extracting here
        # against a possibly-empty canon would silently drop every
        # entity the new pipeline saw, so we prefer the bundle's
        # delta when one is present.
        existing_delta = getattr(bundle, "continuity_delta", None)
        if existing_delta is not None:
            continuity_delta = existing_delta
        else:
            continuity_delta = self._extract_continuity_delta(
                body=body,
                chapter_number=chapter_number,
            )
        # Re-run the deterministic length gate while building the
        # candidate so the workbench's "通过" indicator agrees
        # with the confirmation gate. The user feedback after
        # Round 5 flagged that the candidate page said passable
        # while the confirmation later rejected the same body
        # for being below the 3800-character hard gate. The
        # pipeline already surfaces ``chapter.length_too_short``
        # as a consistency finding for the writer stage, but
        # we merge the deterministic length review into the
        # candidate envelope too so callers that bypass the
        # orchestrator (test fixtures, hand-crafted bundles)
        # still see the same failure the confirmation will
        # reject.
        quality_report = self._merge_candidate_length_review(
            quality_report=quality_report,
            bundle=bundle,
            body=body,
        )
        context_trace_ids = self._candidate_context_trace_ids(bundle)
        candidate = CandidateDraft.create(
            project_id=project_id,
            chapter_number=chapter_number,
            chapter_title=str(getattr(bundle, "chapter_title", "") or ""),
            body=body,
            context_snapshot_id=str(getattr(bundle, "context_snapshot_id", "") or ""),
            quality_report=quality_report
            if isinstance(quality_report, dict)
            else getattr(bundle, "quality_report", None)
            if isinstance(getattr(bundle, "quality_report", None), dict)
            else {},
            submission_payload=submission_payload,
            operation=operation,
            continuity_delta=continuity_delta,
            context_trace_ids=context_trace_ids,
        )
        self.candidate_store.save_latest(candidate)
        report_generation_progress(
            build_chapter_pipeline_event(
                "candidate_output",
                "保存候选稿",
                status="done",
                source="candidate_store",
                used_modules=["candidate_store"],
                reads=["最终正文", "综合审稿结果", "待确认状态变更"],
                outputs={
                    "candidate_id": candidate.candidate_id,
                    "chapter_number": candidate.chapter_number,
                    "operation": candidate.operation,
                    "status": candidate.status,
                    "context_snapshot_id": candidate.context_snapshot_id,
                },
            )
        )
        return candidate
