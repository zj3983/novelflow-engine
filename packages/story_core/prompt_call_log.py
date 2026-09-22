"""Persistent, context-local records for real model calls."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime, timezone
import hashlib
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

_STANDARD_USAGE_KEYS = ("prompt_tokens", "completion_tokens", "total_tokens")


def _safe_usage(value: Any) -> dict[str, int | float]:
    if not isinstance(value, Mapping):
        return {}
    usage: dict[str, int | float] = {}
    for key in _STANDARD_USAGE_KEYS:
        candidate = value.get(key)
        if isinstance(candidate, (int, float)) and not isinstance(candidate, bool):
            usage[key] = candidate
    return usage


def _safe_finish_reason(raw: Any) -> str | None:
    if not isinstance(raw, Mapping):
        return None
    choices = raw.get("choices")
    if not isinstance(choices, (list, tuple)) or not choices:
        return None
    first = choices[0]
    if not isinstance(first, Mapping):
        return None
    finish_reason = first.get("finish_reason")
    if finish_reason is None:
        return None
    return str(finish_reason)[:80]


def _json_error_kind(error: json.JSONDecodeError) -> str:
    message = str(error.msg or "").casefold()
    if "unterminated" in message:
        return "unterminated_object"
    if "expecting property name" in message:
        return "invalid_object_member"
    if "expecting value" in message:
        return "missing_value"
    if "expecting ',' delimiter" in message:
        return "missing_delimiter"
    return "syntax_error"


def classify_json_response(output: str) -> dict[str, Any]:
    """Classify JSON response shape without persisting the response body."""

    text = str(output or "").strip()
    if text.startswith("```"):
        text = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("```")
        ).strip()
    starts_with_object = text.startswith("{")
    ends_with_object = text.endswith("}")
    decoder = json.JSONDecoder()
    try:
        parsed, end = decoder.raw_decode(text)
    except json.JSONDecodeError as error:
        start = text.find("{")
        last = text.rfind("}")
        if starts_with_object and not ends_with_object:
            classification = "json.unterminated_object"
            error_kind = "unterminated_object"
        elif start == -1 or last <= start:
            classification = "json.no_object_boundary"
            error_kind = _json_error_kind(error)
        else:
            try:
                json.loads(text[start : last + 1])
            except json.JSONDecodeError:
                classification = "json.syntax_error"
                error_kind = _json_error_kind(error)
            else:
                classification = "json.trailing_content"
                error_kind = _json_error_kind(error)
        return {
            "classification": classification,
            "starts_with_object": starts_with_object,
            "ends_with_object": ends_with_object,
            "json_error_position": int(error.pos),
            "json_error_kind": error_kind,
        }

    if isinstance(parsed, dict):
        classification = (
            "json.trailing_content" if text[end:].strip() else "json.valid_object"
        )
    else:
        classification = "json.valid_non_object"
    return {
        "classification": classification,
        "starts_with_object": starts_with_object,
        "ends_with_object": ends_with_object,
        "json_error_position": None,
        "json_error_kind": None,
    }


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
                "protocol",
                "model",
                "temperature",
                "temperature_omitted",
                "requested_max_tokens",
                "json_mode",
                "resolved_model",
                "started_at",
                "finished_at",
                "elapsed_seconds",
                "prompt_chars",
                "output_chars",
                "output_sha256",
                "finish_reason",
                "usage",
                "json_diagnostic",
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
        protocol: str = "",
        model: str = "",
        temperature: float | None = None,
        requested_max_tokens: int | None = None,
        json_mode: bool = False,
        resolved_model: str = "",
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
            "protocol": str(protocol),
            "model": str(model),
            "temperature": temperature,
            "temperature_omitted": False,
            "requested_max_tokens": requested_max_tokens,
            "json_mode": bool(json_mode),
            "resolved_model": str(resolved_model),
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
            "output_prefix": "",
            "output_suffix": "",
            "output_sha256": "",
            "finish_reason": None,
            "usage": {},
            "json_diagnostic": None,
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
        protocol: str = "",
        model: str = "",
        elapsed_seconds: float | None = None,
        output: str = "",
        error: str = "",
        temperature_omitted: bool = False,
        requested_max_tokens: int | None = None,
        json_mode: bool | None = None,
        resolved_model: str = "",
        raw: Any = None,
        usage: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        payload = self.get(call_id)
        output_text = str(output or "")
        output_prefix = output_text[:300]
        output_suffix = output_text[-300:] if output_text else ""
        existing_json_mode = bool(payload.get("json_mode"))
        effective_json_mode = existing_json_mode if json_mode is None else bool(json_mode)
        payload.update(
            {
                "status": str(status),
                "provider": str(provider),
                "protocol": str(protocol),
                "model": str(model),
                "resolved_model": str(resolved_model or ""),
                "finished_at": _now_iso(),
                "elapsed_seconds": elapsed_seconds,
                "output_chars": len(output_text),
                "output_summary": output_prefix,
                "output_prefix": output_prefix,
                "output_suffix": output_suffix,
                "output_sha256": (
                    hashlib.sha256(output_text.encode("utf-8")).hexdigest()
                    if output_text
                    else ""
                ),
                "finish_reason": _safe_finish_reason(raw),
                "usage": _safe_usage(usage),
                "json_diagnostic": (
                    classify_json_response(output_text)
                    if effective_json_mode and output_text
                    else None
                ),
                "error": str(error),
            }
        )
        if requested_max_tokens is not None:
            payload["requested_max_tokens"] = requested_max_tokens
        if json_mode is not None:
            payload["json_mode"] = bool(json_mode)
        payload["temperature_omitted"] = bool(temperature_omitted)
        if temperature_omitted:
            payload["temperature"] = None
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
                        "protocol",
                        "model",
                        "temperature",
                        "temperature_omitted",
                        "requested_max_tokens",
                        "json_mode",
                        "resolved_model",
                        "started_at",
                        "finished_at",
                        "elapsed_seconds",
                        "prompt_chars",
                        "output_chars",
                        "output_sha256",
                        "finish_reason",
                        "usage",
                        "json_diagnostic",
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
