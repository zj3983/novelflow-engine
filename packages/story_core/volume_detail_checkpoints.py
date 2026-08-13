from __future__ import annotations

import copy
import hashlib
import json
import os
import re
import tempfile
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any


SCHEMA_VERSION = "volume-detail-checkpoints/v1"
CHECKPOINT_STATUSES = frozenset({"waiting", "running", "completed", "failed"})

_VOLUME_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def _positive_integer(value: object, *, error: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(error)
    return value


def _json_copy(value: Any, *, error: str) -> Any:
    try:
        return json.loads(
            json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        )
    except (TypeError, ValueError) as exc:
        raise ValueError(error) from exc


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
            temporary_path = Path(handle.name)
        os.replace(temporary_path, path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


class VolumeDetailCheckpointStore:
    """Persist resumable chapter-detail batches for one active volume."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self._volume_id: str | None = None
        self._manifest: dict[str, Any] | None = None

    @staticmethod
    def _validate_volume_id(volume_id: object) -> str:
        if (
            not isinstance(volume_id, str)
            or volume_id in {"", ".", ".."}
            or _VOLUME_ID_PATTERN.fullmatch(volume_id) is None
        ):
            raise ValueError("invalid_volume_id")
        return volume_id

    def _volume_directory(self, volume_id: str) -> Path:
        validated = self._validate_volume_id(volume_id)
        return self.root / validated

    @staticmethod
    def _normalize_volume_range(volume_range: object) -> list[int]:
        if (
            not isinstance(volume_range, Sequence)
            or isinstance(volume_range, (str, bytes))
            or len(volume_range) != 2
        ):
            raise ValueError("invalid_volume_range")
        start = _positive_integer(volume_range[0], error="invalid_volume_range")
        end = _positive_integer(volume_range[1], error="invalid_volume_range")
        if end < start:
            raise ValueError("invalid_volume_range")
        return [start, end]

    @staticmethod
    def _normalize_batches(
        batches: object, *, volume_range: list[int]
    ) -> list[dict[str, Any]]:
        if (
            not isinstance(batches, Sequence)
            or isinstance(batches, (str, bytes))
            or not batches
        ):
            raise ValueError("empty_batches")

        normalized: list[dict[str, Any]] = []
        previous_end: int | None = None
        volume_start, volume_end = volume_range
        for raw_batch in batches:
            if (
                not isinstance(raw_batch, Sequence)
                or isinstance(raw_batch, (str, bytes))
                or len(raw_batch) != 2
            ):
                raise ValueError("invalid_batch")
            start = _positive_integer(raw_batch[0], error="invalid_batch")
            end = _positive_integer(raw_batch[1], error="invalid_batch")
            if end < start:
                raise ValueError("invalid_batch")
            if start < volume_start or end > volume_end:
                raise ValueError("batch_outside_volume_range")
            if previous_end is not None and start <= previous_end:
                raise ValueError("overlapping_batches")
            normalized.append(
                {
                    "id": f"{start:04d}-{end:04d}",
                    "start_chapter": start,
                    "end_chapter": end,
                    "status": "waiting",
                }
            )
            previous_end = end
        return normalized

    @staticmethod
    def _fingerprint(
        *,
        volume_id: str,
        volume_range: list[int],
        story_nodes: object,
        existing_outline_version: object,
        user_guidance: object,
        batches: list[dict[str, Any]],
    ) -> str:
        fingerprint_payload = _json_copy(
            {
                "volume_id": volume_id,
                "volume_range": volume_range,
                "story_nodes": story_nodes,
                "existing_outline_version": existing_outline_version,
                "user_guidance": user_guidance,
                "batches": [
                    [item["start_chapter"], item["end_chapter"]]
                    for item in batches
                ],
            },
            error="invalid_fingerprint_inputs",
        )
        encoded = json.dumps(
            fingerprint_payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def prepare(
        self,
        *,
        volume_id: str,
        batches: Sequence[Sequence[int]],
        volume_range: Sequence[int],
        story_nodes: object,
        existing_outline_version: object,
        user_guidance: str = "",
    ) -> dict[str, Any]:
        validated_volume_id = self._validate_volume_id(volume_id)
        normalized_range = self._normalize_volume_range(volume_range)
        normalized_batches = self._normalize_batches(
            batches, volume_range=normalized_range
        )
        fingerprint = self._fingerprint(
            volume_id=validated_volume_id,
            volume_range=normalized_range,
            story_nodes=story_nodes,
            existing_outline_version=existing_outline_version,
            user_guidance=user_guidance,
            batches=normalized_batches,
        )
        volume_directory = self._volume_directory(validated_volume_id)
        manifest_path = volume_directory / "manifest.json"

        existing: dict[str, Any] | None = None
        if manifest_path.is_file():
            existing = self._read_manifest(manifest_path)
            if existing.get("volume_id") != validated_volume_id:
                raise ValueError("invalid_checkpoint_manifest")
        if existing is not None and existing.get("fingerprint") == fingerprint:
            manifest = existing
        else:
            manifest = {
                "schema_version": SCHEMA_VERSION,
                "volume_id": validated_volume_id,
                "volume_range": normalized_range,
                "fingerprint": fingerprint,
                "batches": normalized_batches,
            }
            _atomic_write_json(manifest_path, manifest)
            for payload_path in volume_directory.glob("*.json"):
                if payload_path.name != "manifest.json":
                    payload_path.unlink(missing_ok=True)

        self._volume_id = validated_volume_id
        self._manifest = copy.deepcopy(manifest)
        return copy.deepcopy(manifest)

    def load(self, volume_id: str) -> dict[str, Any]:
        validated_volume_id = self._validate_volume_id(volume_id)
        manifest = self._read_manifest(
            self._volume_directory(validated_volume_id) / "manifest.json"
        )
        if manifest.get("volume_id") != validated_volume_id:
            raise ValueError("invalid_checkpoint_manifest")
        self._volume_id = validated_volume_id
        self._manifest = copy.deepcopy(manifest)
        return copy.deepcopy(manifest)

    @staticmethod
    def _read_manifest(path: Path) -> dict[str, Any]:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError("invalid_checkpoint_manifest") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise ValueError("invalid_checkpoint_manifest")
        try:
            VolumeDetailCheckpointStore._validate_volume_id(payload.get("volume_id"))
            volume_range = VolumeDetailCheckpointStore._normalize_volume_range(
                payload.get("volume_range")
            )
        except ValueError as exc:
            raise ValueError("invalid_checkpoint_manifest") from exc
        fingerprint = payload.get("fingerprint")
        if (
            not isinstance(fingerprint, str)
            or re.fullmatch(r"[0-9a-f]{64}", fingerprint) is None
        ):
            raise ValueError("invalid_checkpoint_manifest")
        batches = payload.get("batches")
        if not isinstance(batches, list) or not batches:
            raise ValueError("invalid_checkpoint_manifest")
        raw_ranges: list[list[int]] = []
        for batch in batches:
            if (
                not isinstance(batch, dict)
                or batch.get("status") not in CHECKPOINT_STATUSES
            ):
                raise ValueError("invalid_checkpoint_manifest")
            start = batch.get("start_chapter")
            end = batch.get("end_chapter")
            if batch.get("id") != (
                f"{start:04d}-{end:04d}"
                if isinstance(start, int)
                and not isinstance(start, bool)
                and isinstance(end, int)
                and not isinstance(end, bool)
                else None
            ):
                raise ValueError("invalid_checkpoint_manifest")
            raw_ranges.append([start, end])
        try:
            VolumeDetailCheckpointStore._normalize_batches(
                raw_ranges, volume_range=volume_range
            )
        except ValueError as exc:
            raise ValueError("invalid_checkpoint_manifest") from exc
        return payload

    def _active(self) -> tuple[str, dict[str, Any], Path]:
        if self._volume_id is None or self._manifest is None:
            raise ValueError("checkpoint_not_prepared")
        return (
            self._volume_id,
            self._manifest,
            self._volume_directory(self._volume_id),
        )

    @staticmethod
    def _batch_index(manifest: Mapping[str, Any], batch_id: str) -> int:
        if not isinstance(batch_id, str):
            raise ValueError("unknown_batch")
        for index, batch in enumerate(manifest["batches"]):
            if batch.get("id") == batch_id:
                return index
        raise ValueError(f"unknown_batch:{batch_id}")

    def _update_batch(
        self, batch_id: str, *, status: str, error: str | None = None
    ) -> dict[str, Any]:
        _, manifest, volume_directory = self._active()
        index = self._batch_index(manifest, batch_id)
        updated = copy.deepcopy(manifest)
        updated_batch = updated["batches"][index]
        updated_batch["status"] = status
        if error is None:
            updated_batch.pop("error", None)
        else:
            updated_batch["error"] = error
        _atomic_write_json(volume_directory / "manifest.json", updated)
        self._manifest = updated
        return copy.deepcopy(updated_batch)

    def running(self, batch_id: str) -> dict[str, Any]:
        return self._update_batch(batch_id, status="running")

    def fail(self, batch_id: str, error: str) -> dict[str, Any]:
        if not isinstance(error, str) or not error.strip():
            raise ValueError("invalid_batch_error")
        return self._update_batch(batch_id, status="failed", error=error.strip())

    @staticmethod
    def _validate_completed_payload(
        batch: Mapping[str, Any], payload: object
    ) -> dict[str, Any]:
        if not isinstance(payload, Mapping):
            raise ValueError("invalid_batch_payload")
        chapters = payload.get("chapters")
        if not isinstance(chapters, list):
            raise ValueError("invalid_batch_payload")
        actual: list[int] = []
        for chapter in chapters:
            if not isinstance(chapter, Mapping):
                raise ValueError("payload_chapter_mismatch")
            number = chapter.get("chapter_number")
            if not isinstance(number, int) or isinstance(number, bool):
                raise ValueError("payload_chapter_mismatch")
            actual.append(number)
        expected = list(
            range(batch["start_chapter"], batch["end_chapter"] + 1)
        )
        if actual != expected:
            raise ValueError("payload_chapter_mismatch")
        return _json_copy(payload, error="invalid_batch_payload")

    def complete(self, batch_id: str, payload: Mapping[str, Any]) -> dict[str, Any]:
        _, manifest, volume_directory = self._active()
        index = self._batch_index(manifest, batch_id)
        normalized_payload = self._validate_completed_payload(
            manifest["batches"][index], payload
        )
        _atomic_write_json(volume_directory / f"{batch_id}.json", normalized_payload)
        return self._update_batch(batch_id, status="completed")

    def completed_payloads(self) -> dict[str, dict[str, Any]]:
        _, manifest, volume_directory = self._active()
        completed: dict[str, dict[str, Any]] = {}
        for batch in manifest["batches"]:
            if batch["status"] != "completed":
                continue
            payload_path = volume_directory / f"{batch['id']}.json"
            try:
                payload = json.loads(payload_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise ValueError(f"invalid_completed_payload:{batch['id']}") from exc
            try:
                completed[batch["id"]] = self._validate_completed_payload(
                    batch, payload
                )
            except ValueError as exc:
                raise ValueError(f"invalid_completed_payload:{batch['id']}") from exc
        return completed

    def next_incomplete_batch(self) -> dict[str, Any] | None:
        _, manifest, _ = self._active()
        for batch in manifest["batches"]:
            if batch["status"] != "completed":
                return copy.deepcopy(batch)
        return None
