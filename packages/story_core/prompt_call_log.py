"""Persistent, context-local records for real model calls."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import tempfile
from threading import Lock
from typing import Any
from uuid import uuid4

from packages.story_core.genre_stages.base import GenreStageProfile


_current_recorder: ContextVar["PromptCallLog | None"] = ContextVar("current_prompt_call_recorder", default=None)
_index_lock = Lock()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, indent=2))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, path)
    finally:
        temp_path.unlink(missing_ok=True)


class PromptCallLog:
    def __init__(
        self,
        root: str | Path,
        *,
        project_id: str,
        profile: GenreStageProfile | None = None,
    ) -> None:
        self.root = Path(root)
        self.project_id = str(project_id)
        self.profile = profile
        self.calls_dir = self.root / "prompt_calls"
        self.index_path = self.calls_dir / "index.jsonl"

    def _detail_path(self, call_id: str) -> Path:
        return self.calls_dir / f"{call_id}.json"

    def _append_event(self, payload: dict[str, Any]) -> None:
        self.calls_dir.mkdir(parents=True, exist_ok=True)
        summary = {
            key: payload.get(key)
            for key in (
                "call_id",
                "project_id",
                "chapter_number",
                "stage",
                "agent",
                "attempt",
                "status",
                "provider",
                "model",
                "temperature",
                "started_at",
                "finished_at",
                "elapsed_seconds",
                "prompt_chars",
                "output_chars",
                "error",
                "genre_stage_profile",
                "genre_stage_modules",
            )
        }
        with _index_lock:
            with self.index_path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(summary, ensure_ascii=False) + "\n")

    def _attempt(self, *, chapter_number: int, stage: str) -> int:
        matches = [
            item
            for item in self.list(chapter_number=chapter_number)
            if str(item.get("stage")) == str(stage)
        ]
        return len(matches) + 1

    def start(
        self,
        *,
        chapter_number: int,
        stage: str,
        agent: str,
        user_prompt: str,
        system_prompt: str = "",
        module_keys: list[str] | None = None,
        template_key: str = "",
        template_source: str = "",
        template_version: str = "",
        provider: str = "",
        model: str = "",
        temperature: float | None = None,
        genre_stage: str = "",
    ) -> str:
        call_id = f"pc-{uuid4().hex}"
        payload: dict[str, Any] = {
            "schema_version": "prompt-call/v1",
            "call_id": call_id,
            "project_id": self.project_id,
            "chapter_number": int(chapter_number),
            "stage": str(stage),
            "agent": str(agent),
            "attempt": self._attempt(chapter_number=int(chapter_number), stage=str(stage)),
            "status": "started",
            "provider": str(provider),
            "model": str(model),
            "temperature": temperature,
            "started_at": _now_iso(),
            "finished_at": "",
            "elapsed_seconds": None,
            "system_prompt": str(system_prompt),
            "user_prompt": str(user_prompt),
            "prompt_chars": len(str(system_prompt)) + len(str(user_prompt)),
            "module_keys": list(module_keys or []),
            "template_key": str(template_key),
            "template_source": str(template_source),
            "template_version": str(template_version),
            "genre_stage_profile": self.profile.profile_id if self.profile is not None else "",
            "genre_stage_modules": (
                list(self.profile.modules_for(genre_stage))
                if self.profile is not None
                else []
            ),
            "output_chars": 0,
            "output_summary": "",
            "error": "",
        }
        _atomic_write(self._detail_path(call_id), payload)
        self._append_event(payload)
        return call_id

    def finish(
        self,
        call_id: str,
        *,
        status: str,
        provider: str = "",
        model: str = "",
        elapsed_seconds: float | None = None,
        output: str = "",
        error: str = "",
    ) -> dict[str, Any]:
        payload = self.get(call_id)
        payload.update(
            {
                "status": str(status),
                "provider": str(provider),
                "model": str(model),
                "finished_at": _now_iso(),
                "elapsed_seconds": elapsed_seconds,
                "output_chars": len(str(output)),
                "output_summary": str(output)[:300],
                "error": str(error),
            }
        )
        _atomic_write(self._detail_path(call_id), payload)
        self._append_event(payload)
        return payload

    def get(self, call_id: str) -> dict[str, Any]:
        path = self._detail_path(call_id)
        if not path.exists():
            raise FileNotFoundError(f"prompt_call_not_found:{call_id}")
        return json.loads(path.read_text(encoding="utf-8-sig"))

    def list(self, *, chapter_number: int | None = None) -> list[dict[str, Any]]:
        if not self.calls_dir.exists():
            return []
        records: list[dict[str, Any]] = []
        for path in self.calls_dir.glob("pc-*.json"):
            try:
                payload = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, json.JSONDecodeError):
                continue
            if chapter_number is not None and int(payload.get("chapter_number") or 0) != int(chapter_number):
                continue
            records.append(
                {
                    key: payload.get(key)
                    for key in (
                        "call_id",
                        "project_id",
                        "chapter_number",
                        "stage",
                        "agent",
                        "attempt",
                        "status",
                        "provider",
                        "model",
                        "temperature",
                        "started_at",
                        "finished_at",
                        "elapsed_seconds",
                        "prompt_chars",
                        "output_chars",
                        "error",
                        "genre_stage_profile",
                        "genre_stage_modules",
                    )
                }
            )
        return sorted(records, key=lambda item: (str(item.get("started_at") or ""), str(item.get("call_id") or "")))


@contextmanager
def prompt_call_recording(recorder: PromptCallLog) -> Iterator[None]:
    token = _current_recorder.set(recorder)
    try:
        yield
    finally:
        _current_recorder.reset(token)


def start_prompt_call(**payload: Any) -> str | None:
    recorder = _current_recorder.get()
    return recorder.start(**payload) if recorder is not None else None


def finish_prompt_call(call_id: str | None, **payload: Any) -> None:
    recorder = _current_recorder.get()
    if recorder is not None and call_id:
        recorder.finish(call_id, **payload)
