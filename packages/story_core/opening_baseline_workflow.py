from __future__ import annotations

import json
import re
from typing import Any


class OpeningBaselineWorkflowMixin:
    """Freeze opening chapters and validate continuity before later writes."""

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
