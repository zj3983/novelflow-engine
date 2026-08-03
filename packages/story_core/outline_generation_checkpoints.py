from __future__ import annotations

import json
import os
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


OUTLINE_GENERATION_PHASES = (
    "outline_foundation",
    "character_roster",
    "chapter_window",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OutlineCheckpointStore:
    """Project-local, atomically persisted outline generation checkpoints."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.manifest_path = self.root / "manifest.json"

    @staticmethod
    def _phase_entry(phase: str) -> dict[str, Any]:
        return {
            "id": phase,
            "status": "waiting",
            "started_at": "",
            "completed_at": "",
            "error": "",
        }

    def _empty_manifest(self, fingerprint: str = "") -> dict[str, Any]:
        return {
            "schema_version": "outline-generation-checkpoints/v1",
            "fingerprint": fingerprint,
            "updated_at": _now(),
            "phases": [self._phase_entry(phase) for phase in OUTLINE_GENERATION_PHASES],
        }

    def _read_manifest(self) -> dict[str, Any]:
        if not self.manifest_path.exists():
            return self._empty_manifest()
        try:
            value = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, json.JSONDecodeError):
            return self._empty_manifest()
        return value if isinstance(value, dict) else self._empty_manifest()

    def _write_json(self, path: Path, payload: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temporary = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=path.parent,
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)

    def _payload_path(self, phase: str) -> Path:
        self._require_phase(phase)
        return self.root / f"{phase}.json"

    @staticmethod
    def _require_phase(phase: str) -> None:
        if phase not in OUTLINE_GENERATION_PHASES:
            raise ValueError(f"unknown_outline_generation_phase:{phase}")

    def _write_manifest(self, manifest: dict[str, Any]) -> None:
        manifest["updated_at"] = _now()
        self._write_json(self.manifest_path, manifest)

    def prepare(self, fingerprint: str) -> dict[str, Any]:
        normalized = str(fingerprint or "").strip()
        if not normalized:
            raise ValueError("outline_generation_fingerprint_required")
        manifest = self._read_manifest()
        if manifest.get("fingerprint") != normalized:
            self.root.mkdir(parents=True, exist_ok=True)
            for phase in OUTLINE_GENERATION_PHASES:
                self._payload_path(phase).unlink(missing_ok=True)
            manifest = self._empty_manifest(normalized)
            self._write_manifest(manifest)
        return deepcopy(manifest)

    def status(self) -> dict[str, Any]:
        return deepcopy(self._read_manifest())

    def _update_phase(self, phase: str, **patch: Any) -> None:
        self._require_phase(phase)
        manifest = self._read_manifest()
        phases = manifest.get("phases")
        if not isinstance(phases, list):
            phases = [self._phase_entry(item) for item in OUTLINE_GENERATION_PHASES]
            manifest["phases"] = phases
        entry = next((item for item in phases if isinstance(item, dict) and item.get("id") == phase), None)
        if entry is None:
            entry = self._phase_entry(phase)
            phases.append(entry)
        entry.update(patch)
        self._write_manifest(manifest)

    def mark_running(self, phase: str) -> None:
        self._update_phase(
            phase,
            status="running",
            started_at=_now(),
            completed_at="",
            error="",
        )

    def complete(self, phase: str, payload: dict[str, Any]) -> None:
        self._require_phase(phase)
        self._write_json(self._payload_path(phase), deepcopy(dict(payload)))
        self._update_phase(
            phase,
            status="completed",
            completed_at=_now(),
            error="",
        )

    def fail(self, phase: str, error: str) -> None:
        self._update_phase(
            phase,
            status="failed",
            completed_at=_now(),
            error=str(error or "outline_generation_failed")[:1000],
        )

    def invalidate_from(self, phase: str) -> None:
        self._require_phase(phase)
        start = OUTLINE_GENERATION_PHASES.index(phase)
        manifest = self._read_manifest()
        entries = {
            str(item.get("id")): item
            for item in manifest.get("phases", [])
            if isinstance(item, dict)
        }
        for invalidated in OUTLINE_GENERATION_PHASES[start:]:
            self._payload_path(invalidated).unlink(missing_ok=True)
            entries[invalidated] = self._phase_entry(invalidated)
        manifest["phases"] = [
            entries.get(item, self._phase_entry(item))
            for item in OUTLINE_GENERATION_PHASES
        ]
        self._write_manifest(manifest)

    def completed_payloads(self) -> dict[str, dict[str, Any]]:
        manifest = self._read_manifest()
        completed = {
            str(item.get("id"))
            for item in manifest.get("phases", [])
            if isinstance(item, dict) and item.get("status") == "completed"
        }
        payloads: dict[str, dict[str, Any]] = {}
        for phase in OUTLINE_GENERATION_PHASES:
            path = self._payload_path(phase)
            if phase not in completed or not path.exists():
                continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                payloads[phase] = payload
        return payloads
