from __future__ import annotations

"""Filesystem persistence for candidate chapter drafts."""

import json
from pathlib import Path
from typing import Iterable

from packages.story_core.candidate_draft import CandidateDraft

_CANDIDATE_CACHE: dict[Path, tuple[int, CandidateDraft]] = {}


class CandidateStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.directory = self.root / ".story-system" / "candidates"

    def save(self, draft: CandidateDraft) -> Path:
        self.directory.mkdir(parents=True, exist_ok=True)
        target = self.directory / f"{draft.candidate_id}.json"
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(
            json.dumps(draft.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        temporary.replace(target)
        return target

    def save_latest(self, draft: CandidateDraft) -> Path:
        for existing in self.list(
            project_id=draft.project_id,
            chapter_number=draft.chapter_number,
        ):
            if existing.candidate_id == draft.candidate_id or existing.status != "pending":
                continue
            existing.supersede()
            self.save(existing)
        return self.save(draft)

    def get(self, candidate_id: str) -> CandidateDraft | None:
        target = self.directory / f"{candidate_id}.json"
        if not target.is_file():
            return None
        return CandidateDraft.from_dict(json.loads(target.read_text(encoding="utf-8")))

    def list(
        self,
        *,
        project_id: str | None = None,
        chapter_number: int | None = None,
    ) -> list[CandidateDraft]:
        if not self.directory.is_dir():
            return []
        global _CANDIDATE_CACHE
        items: list[CandidateDraft] = []
        for path in self.directory.glob("cd-*.json"):
            try:
                mtime = path.stat().st_mtime_ns
                cached = _CANDIDATE_CACHE.get(path)
                if cached is not None and cached[0] == mtime:
                    draft = cached[1]
                else:
                    draft = CandidateDraft.from_dict(json.loads(path.read_text(encoding="utf-8")))
                    _CANDIDATE_CACHE[path] = (mtime, draft)
            except (OSError, ValueError, TypeError, json.JSONDecodeError):
                continue
            if project_id is not None and draft.project_id != project_id:
                continue
            if chapter_number is not None and draft.chapter_number != chapter_number:
                continue
            items.append(draft)
        return sorted(items, key=lambda item: item.created_at)
