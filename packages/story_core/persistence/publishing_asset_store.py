from __future__ import annotations

import json
import logging
import os
import re
import tempfile
from copy import deepcopy
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from packages.story_core.cover_renderer import CoverRenderError, normalize_cover_title
from packages.story_core.persistence.project_locking import with_project_update_lock
from packages.story_core.persistence.publishing_filesystem import PinnedPublishingFilesystem


_MISSING = object()


class PublishingAssetStoreMixin:
    """Transactional project synopsis and cover asset persistence."""

    @property
    def cover_base_path(self) -> Path:
        return self.webnovel_dir / "assets" / "cover-base.png"

    @property
    def rendered_cover_path(self) -> Path:
        return self.webnovel_dir / "assets" / "cover.png"

    @staticmethod
    def _publishing_assets_default() -> dict[str, Any]:
        return {
            "schema_version": "publishing-assets/v1",
            "synopsis": None,
            "cover": None,
        }

    @staticmethod
    def _json_safe_dict(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
            raise ValueError("publishing_asset_write_failed")
        try:
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
            restored = json.loads(serialized)
        except (TypeError, ValueError, OverflowError, RecursionError) as exc:
            raise ValueError("publishing_asset_write_failed") from exc
        if not isinstance(restored, dict):  # pragma: no cover - guarded above
            raise ValueError("publishing_asset_write_failed")
        PublishingAssetStoreMixin._validate_publishing_value(restored)
        return restored

    @staticmethod
    def _validate_publishing_value(value: Any) -> None:
        containers = 0

        def visit(item: Any, depth: int = 0) -> None:
            nonlocal containers
            if depth > 32:
                raise ValueError("publishing_asset_write_failed")
            if isinstance(item, str):
                if len(item) > 16_000:
                    raise ValueError("publishing_asset_write_failed")
                return
            if item is None or isinstance(item, (bool, int, float)):
                return
            if isinstance(item, dict):
                containers += 1
                if containers > 1_024 or any(not isinstance(key, str) for key in item):
                    raise ValueError("publishing_asset_write_failed")
                for nested in item.values():
                    visit(nested, depth + 1)
                return
            if isinstance(item, list):
                containers += 1
                if containers > 1_024:
                    raise ValueError("publishing_asset_write_failed")
                for nested in item:
                    visit(nested, depth + 1)
                return
            raise ValueError("publishing_asset_write_failed")

        visit(value)
        if len(json.dumps(value, ensure_ascii=False, allow_nan=False).encode("utf-8")) > 65_536:
            raise ValueError("publishing_asset_write_failed")

    @staticmethod
    def _json_safe_value(value: Any) -> tuple[bool, Any]:
        try:
            serialized = json.dumps(value, ensure_ascii=False, allow_nan=False)
            restored = json.loads(serialized)
            PublishingAssetStoreMixin._validate_publishing_value(restored)
            return True, restored
        except (TypeError, ValueError, OverflowError, RecursionError):
            return False, None

    @staticmethod
    def _publishing_path_like_key(key: str) -> bool:
        folded = key.casefold()
        return folded in {"path", "file", "filename", "url", "uri", "filepath", "file_path"} or folded.endswith(
            ("_path", "_file", "_filename", "_url", "_uri", "_filepath")
        )

    @classmethod
    def _sanitize_future_publishing_value(cls, value: Any) -> Any:
        """Deep-clone JSON-safe future data while removing storage references."""
        dropped = object()

        def unsafe_string(item: str) -> bool:
            candidate = item.strip()
            return bool(
                candidate.startswith(("/", "\\", "file:"))
                or re.match(r"^[a-zA-Z]:[\\/]", candidate)
                or re.search(r"(^|[\\/])\.\.([\\/]|$)", candidate)
            )

        def clean(item: Any) -> Any:
            if isinstance(item, str) and unsafe_string(item):
                return dropped
            if isinstance(item, dict):
                sanitized: dict[str, Any] = {}
                for key, nested in item.items():
                    if not isinstance(key, str) or cls._publishing_path_like_key(key):
                        continue
                    cleaned = clean(nested)
                    if cleaned is not dropped:
                        sanitized[key] = cleaned
                return sanitized
            if isinstance(item, list):
                return [cleaned for nested in item if (cleaned := clean(nested)) is not dropped]
            return item

        cleaned = clean(value)
        return None if cleaned is dropped else cleaned

    @classmethod
    def _normalize_publishing_assets(cls, value: Any) -> dict[str, Any]:
        normalized = cls._publishing_assets_default()
        if not isinstance(value, dict):
            return normalized
        for key, item in value.items():
            if key in {"schema_version", "synopsis", "cover", "updated_at"} or not isinstance(key, str):
                continue
            if cls._publishing_path_like_key(key):
                continue
            is_safe, safe_item = cls._json_safe_value(item)
            if is_safe:
                normalized[key] = cls._sanitize_future_publishing_value(safe_item)
        updated_at = value.get("updated_at")
        if isinstance(updated_at, str) and updated_at.strip():
            normalized["updated_at"] = updated_at.strip()
        synopsis = value.get("synopsis")
        if isinstance(synopsis, dict):
            try:
                normalized["synopsis"] = cls._sanitize_future_publishing_value(cls._json_safe_dict(synopsis))
            except ValueError:
                pass
        raw_cover = value.get("cover")
        if not isinstance(raw_cover, dict):
            return normalized
        cover: dict[str, Any] = {}
        for key, item in raw_cover.items():
            if not isinstance(key, str):
                continue
            if cls._publishing_path_like_key(key) and key not in {"base_path", "rendered_path"}:
                continue
            is_safe, safe_item = cls._json_safe_value(item)
            if is_safe:
                cover[key] = cls._sanitize_future_publishing_value(safe_item)
        prompt = raw_cover.get("prompt")
        if isinstance(prompt, str) and prompt.strip():
            cover["prompt"] = prompt.strip()[:2000]
        else:
            cover.pop("prompt", None)
        model = raw_cover.get("model")
        if isinstance(model, str) and model.strip():
            cover["model"] = model.strip()
        else:
            cover.pop("model", None)
        if raw_cover.get("base_path") == "assets/cover-base.png":
            cover["base_path"] = "assets/cover-base.png"
        else:
            cover.pop("base_path", None)
        if raw_cover.get("rendered_path") == "assets/cover.png":
            cover["rendered_path"] = "assets/cover.png"
        else:
            cover.pop("rendered_path", None)
        schema_version = raw_cover.get("schema_version")
        if isinstance(schema_version, str) and schema_version.strip():
            cover["schema_version"] = schema_version.strip()
        else:
            cover.pop("schema_version", None)
        rendered_title = raw_cover.get("rendered_title")
        if isinstance(rendered_title, str):
            cover["rendered_title"] = rendered_title
        else:
            cover.pop("rendered_title", None)
        normalized["cover"] = cover or None
        return normalized

    def _safe_metadata_document(self, path: Path) -> dict[str, Any]:
        try:
            payload = self._read_json(path, {})
        except (OSError, ValueError, json.JSONDecodeError):
            return {}
        return dict(payload) if isinstance(payload, dict) else {}

    @staticmethod
    def _is_reparse_point(path: Path) -> bool:
        try:
            details = os.lstat(path)
        except FileNotFoundError:
            return False
        return path.is_symlink() or bool(getattr(details, "st_file_attributes", 0) & 0x400)

    def _assert_publishing_target_safe(self, target: Path) -> None:
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.assert_target(target)
            return
        target = Path(target)
        try:
            relative = target.absolute().relative_to(self.root)
        except ValueError as exc:
            raise ValueError("publishing_asset_write_failed") from exc
        current = self.root
        if self._is_reparse_point(current):
            raise ValueError("publishing_asset_write_failed")
        for part in relative.parts[:-1]:
            current = current / part
            if self._is_reparse_point(current):
                raise ValueError("publishing_asset_write_failed")
        if os.path.lexists(target) and self._is_reparse_point(target):
            raise ValueError("publishing_asset_write_failed")
        if not target.parent.resolve().is_relative_to(self.root):
            raise ValueError("publishing_asset_write_failed")

    @staticmethod
    def _complete_project_payload(project: Any) -> bool:
        return (
            isinstance(project, dict)
            and isinstance(project.get("project_id"), str)
            and bool(project["project_id"].strip())
            and isinstance(project.get("title"), str)
            and bool(project["title"].strip())
        )

    @classmethod
    def _complete_master_payload(cls, master: Any) -> bool:
        return (
            isinstance(master, dict)
            and master.get("schema_version") == "story-system-master-setting/v1"
            and cls._complete_project_payload(master.get("project"))
        )

    def _mutation_metadata_document(self, path: Path) -> dict[str, Any] | None:
        self._assert_publishing_target_safe(path)
        filesystem = self._active_publishing_filesystem
        exists = filesystem.exists(path) if filesystem is not None else os.path.lexists(path)
        if not exists:
            return None
        try:
            raw = filesystem.read_bytes(path) if filesystem is not None else path.read_bytes()
            payload = json.loads(raw.decode("utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("publishing_asset_write_failed") from exc
        if not isinstance(payload, dict):
            raise ValueError("publishing_asset_write_failed")
        return dict(payload)

    def _publishing_assets_from_metadata(self) -> dict[str, Any]:
        project = self._safe_metadata_document(self.webnovel_dir / "project.json")
        if "publishing_assets" in project:
            return self._normalize_publishing_assets(project.get("publishing_assets"))
        master = self._safe_metadata_document(self.story_system_dir / "MASTER_SETTING.json")
        master_project = master.get("project")
        if isinstance(master_project, dict):
            return self._normalize_publishing_assets(master_project.get("publishing_assets"))
        return self._publishing_assets_default()

    def _prepare_publishing_temp(self, path: Path, content: bytes, *, suffix: str = ".tmp") -> Path:
        if self._active_publishing_filesystem is not None:
            return self._active_publishing_filesystem.prepare(path, content, suffix=suffix)
        self._assert_publishing_target_safe(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self._assert_publishing_target_safe(path)
        fd, temp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=suffix)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
            if os.name != "nt" and path.exists():
                os.chmod(temp_path, os.stat(path).st_mode & 0o777)
        except Exception:
            try:
                temp_path.unlink(missing_ok=True)
            except OSError:
                logging.getLogger(__name__).warning("publishing temp cleanup deferred: %s", temp_path)
            raise
        return temp_path

    def _replace_asset(self, source: Path, target: Path) -> None:
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.replace(source, target)
        else:
            os.replace(source, target)

    def _replace_metadata(self, source: Path, target: Path) -> None:
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.replace(source, target)
        else:
            os.replace(source, target)

    def _restore_publishing_backup(self, backup: Path, target: Path) -> None:
        self._assert_publishing_target_safe(target)
        if self._active_publishing_filesystem is not None:
            self._active_publishing_filesystem.replace(backup, target)
        else:
            os.replace(backup, target)

    def _best_effort_unlink(self, path: Path) -> None:
        try:
            if self._active_publishing_filesystem is not None:
                self._active_publishing_filesystem.unlink(path)
            else:
                path.unlink(missing_ok=True)
        except (OSError, ValueError):
            logging.getLogger(__name__).warning("publishing transaction cleanup deferred: %s", path)

    def _best_effort_fsync_parent(self, path: Path) -> None:
        if os.name == "nt":
            return
        if self._active_publishing_filesystem is not None:
            try:
                self._active_publishing_filesystem.fsync_parent(path)
            except (OSError, ValueError):
                logging.getLogger(__name__).warning("publishing parent fsync deferred: %s", path.parent)
            return
        try:
            descriptor = os.open(path.parent, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        except OSError:
            pass
        finally:
            try:
                os.close(descriptor)
            except OSError:
                logging.getLogger(__name__).warning("publishing parent descriptor cleanup deferred: %s", path.parent)

    def _publishing_metadata_payloads(
        self,
        publishing_assets: dict[str, Any],
    ) -> dict[Path, dict[str, Any]]:
        project_path = self.webnovel_dir / "project.json"
        master_path = self.story_system_dir / "MASTER_SETTING.json"
        project = self._mutation_metadata_document(project_path)
        master = self._mutation_metadata_document(master_path)
        if project is None and master is None:
            raise ValueError("publishing_asset_write_failed")
        if project is None:
            master_project = master.get("project") if isinstance(master, dict) else None
            if not self._complete_master_payload(master) or not self._complete_project_payload(master_project):
                raise ValueError("publishing_asset_write_failed")
            project = dict(master_project)
        if master is None:
            if not self._complete_project_payload(project):
                raise ValueError("publishing_asset_write_failed")
            master = {"schema_version": "story-system-master-setting/v1", "project": deepcopy(project)}
        master_project = master.get("project")
        if not isinstance(master_project, dict):
            raise ValueError("publishing_asset_write_failed")
        if not self._complete_project_payload(project) or not self._complete_project_payload(master_project):
            raise ValueError("publishing_asset_write_failed")
        master_project = dict(master_project)
        project["publishing_assets"] = deepcopy(publishing_assets)
        master_project["publishing_assets"] = deepcopy(publishing_assets)
        master["project"] = master_project
        return {project_path: project, master_path: master}

    def _publishing_transaction(
        self,
        publishing_assets: dict[str, Any],
        *,
        asset_contents: tuple[bytes, bytes] | None = None,
        asset_updates: dict[Path, bytes] | None = None,
    ) -> None:
        """Best-effort cross-file transaction; retained .rollback files signal incomplete recovery after a fault."""
        self._validate_publishing_value(publishing_assets)
        if asset_contents is not None and asset_updates is not None:
            raise ValueError("publishing_asset_write_failed")
        metadata_targets = [
            self.webnovel_dir / "project.json",
            self.story_system_dir / "MASTER_SETTING.json",
        ]
        if asset_contents is not None:
            asset_updates = {
                self.cover_base_path: asset_contents[0],
                self.rendered_cover_path: asset_contents[1],
            }
        asset_updates = asset_updates or {}
        allowed_asset_targets = {self.cover_base_path, self.rendered_cover_path}
        if any(target not in allowed_asset_targets or not isinstance(content, bytes) for target, content in asset_updates.items()):
            raise ValueError("publishing_asset_write_failed")
        asset_targets = list(asset_updates)
        all_targets = asset_targets + metadata_targets
        prepared: list[Path] = []
        rollback_files: dict[Path, Path | None] = {}
        committed: list[Path] = []
        with PinnedPublishingFilesystem(self.root) as filesystem:
            prior_filesystem = self._active_publishing_filesystem
            self._active_publishing_filesystem = filesystem
            try:
                metadata_payloads = self._publishing_metadata_payloads(publishing_assets)
                metadata_targets = list(metadata_payloads)
                for target in all_targets:
                    self._assert_publishing_target_safe(target)
                    if filesystem.exists(target):
                        rollback_files[target] = self._prepare_publishing_temp(
                            target, filesystem.read_bytes(target), suffix=".rollback"
                        )
                    else:
                        rollback_files[target] = None
                if asset_updates:
                    asset_temps: list[Path] = []
                    for target in asset_targets:
                        content = asset_updates[target]
                        prepared_temp = self._prepare_publishing_temp(target, content)
                        prepared.append(prepared_temp)
                        asset_temps.append(prepared_temp)
                else:
                    asset_temps = []

                metadata_temps: dict[Path, Path] = {}
                for target, payload in metadata_payloads.items():
                    serialized = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
                    metadata_temps[target] = self._prepare_publishing_temp(target, serialized)
                    prepared.append(metadata_temps[target])

                for source, target in zip(asset_temps, asset_targets, strict=True):
                    self._replace_asset(source, target)
                    committed.append(target)
                    self._best_effort_fsync_parent(target)
                for target in metadata_targets:
                    self._replace_metadata(metadata_temps[target], target)
                    committed.append(target)
                    self._best_effort_fsync_parent(target)
                for backup in rollback_files.values():
                    if backup is not None:
                        self._best_effort_unlink(backup)
            except Exception as exc:
                rollback_errors: list[Exception] = []
                for target in reversed(committed):
                    try:
                        backup = rollback_files[target]
                        if backup is None:
                            filesystem.unlink(target)
                        else:
                            self._restore_publishing_backup(backup, target)
                        self._best_effort_fsync_parent(target)
                    except Exception as rollback_exc:  # pragma: no cover - exercised by fault seams
                        rollback_errors.append(rollback_exc)
                for path in prepared:
                    self._best_effort_unlink(path)
                if rollback_errors:
                    raise ValueError("publishing_asset_write_failed") from ExceptionGroup(
                        "publishing transaction and recovery failures", [exc, *rollback_errors]
                    )
                for backup in rollback_files.values():
                    if backup is not None:
                        self._best_effort_unlink(backup)
                raise ValueError("publishing_asset_write_failed") from exc
            finally:
                for path in prepared:
                    self._best_effort_unlink(path)
                self._active_publishing_filesystem = prior_filesystem

    @with_project_update_lock
    def publishing_assets(self) -> dict[str, Any]:
        return self._publishing_assets_from_metadata()

    @with_project_update_lock
    def save_synopsis(
        self,
        synopsis: dict[str, Any],
        *,
        expected_synopsis: dict[str, Any] | None | object = _MISSING,
    ) -> dict[str, Any]:
        try:
            saved = self._publishing_assets_from_metadata()
            if expected_synopsis is not _MISSING and saved.get("synopsis") != expected_synopsis:
                raise ValueError("publishing_asset_stale_synopsis")
            saved["synopsis"] = self._json_safe_dict(synopsis)
            saved["updated_at"] = self._publishing_updated_at()
            self._publishing_transaction(saved)
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_synopsis"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @staticmethod
    def _publishing_prompt(prompt: str) -> str:
        if not isinstance(prompt, str):
            raise ValueError("publishing_asset_write_failed")
        normalized = prompt.strip()
        if not normalized or len(normalized) > 2000:
            raise ValueError("publishing_asset_write_failed")
        return normalized

    @staticmethod
    def _publishing_updated_at() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @with_project_update_lock
    def save_cover_prompt(self, prompt: str, *, expected_prompt: str | None = None) -> dict[str, Any]:
        try:
            saved = self._publishing_assets_from_metadata()
            cover = dict(saved["cover"] or {})
            if expected_prompt is not None and str(cover.get("prompt") or "") != expected_prompt.strip():
                raise ValueError("publishing_asset_stale_cover")
            cover["prompt"] = self._publishing_prompt(prompt)
            cover["updated_at"] = self._publishing_updated_at()
            saved["cover"] = cover
            saved["updated_at"] = cover["updated_at"]
            self._publishing_transaction(saved)
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @with_project_update_lock
    def save_cover(
        self,
        *,
        prompt: str,
        base_image: bytes,
        rendered_image: bytes,
        model: str,
        expected_prompt: str | None = None,
        expected_title: str | None = None,
        rendered_title: str | None = None,
    ) -> dict[str, Any]:
        try:
            if not isinstance(base_image, bytes) or not isinstance(rendered_image, bytes):
                raise ValueError("publishing_asset_write_failed")
            if len(base_image) > self.PUBLISHING_ASSET_MAX_BYTES or len(rendered_image) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_write_failed")
            if not base_image or not rendered_image or not isinstance(model, str) or not model.strip() or len(model.strip()) > 256:
                raise ValueError("publishing_asset_write_failed")
            project = self.project()
            try:
                title = normalize_cover_title(str(project.get("title") or ""))
            except CoverRenderError as exc:
                raise ValueError("publishing_asset_write_failed") from exc
            if not title:
                raise ValueError("publishing_asset_write_failed")
            saved = self._publishing_assets_from_metadata()
            current_prompt = str((saved.get("cover") or {}).get("prompt") or "")
            if expected_prompt is not None and current_prompt != expected_prompt.strip():
                raise ValueError("publishing_asset_stale_cover")
            if expected_title is not None and title != expected_title:
                raise ValueError("publishing_asset_stale_cover")
            if rendered_title is not None and rendered_title != title:
                raise ValueError("publishing_asset_stale_cover")
            updated_at = self._publishing_updated_at()
            saved["cover"] = {
                "prompt": self._publishing_prompt(prompt),
                "model": model.strip(),
                "base_path": "assets/cover-base.png",
                "rendered_path": "assets/cover.png",
                "schema_version": "cover/v1",
                "base_image_version": sha256(base_image).hexdigest(),
                "rendered_from_base_version": sha256(base_image).hexdigest(),
                "rendered_title": rendered_title or title,
                "image_version": sha256(rendered_image).hexdigest(),
                "mime_type": "image/png",
                "updated_at": updated_at,
            }
            saved["updated_at"] = updated_at
            self._publishing_transaction(saved, asset_contents=(base_image, rendered_image))
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    @with_project_update_lock
    def save_cover_base(self, *, prompt: str, base_image: bytes, model: str, expected_prompt: str | None = None, expected_title: str | None = None) -> dict[str, Any]:
        """Persist a validated source image without replacing the current rendered cover."""
        try:
            if not isinstance(base_image, bytes) or not base_image or len(base_image) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_write_failed")
            if not isinstance(model, str) or not model.strip() or len(model.strip()) > 256:
                raise ValueError("publishing_asset_write_failed")
            saved = self._publishing_assets_from_metadata()
            current_prompt = str((saved.get("cover") or {}).get("prompt") or "")
            current_title = normalize_cover_title(str(self.project().get("title") or ""))
            if (expected_prompt is not None and current_prompt != expected_prompt.strip()) or (expected_title is not None and current_title != expected_title):
                raise ValueError("publishing_asset_stale_cover")
            cover = dict(saved["cover"] or {})
            updated_at = self._publishing_updated_at()
            cover.update(
                {
                    "prompt": self._publishing_prompt(prompt),
                    "model": model.strip(),
                    "base_path": "assets/cover-base.png",
                    "schema_version": "cover/v1",
                    "base_image_version": sha256(base_image).hexdigest(),
                    "updated_at": updated_at,
                }
            )
            saved["cover"] = cover
            saved["updated_at"] = updated_at
            self._publishing_transaction(saved, asset_updates={self.cover_base_path: base_image})
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc

    def _read_publishing_asset(self, path: Path) -> bytes | None:
        try:
            with PinnedPublishingFilesystem(self.root) as filesystem:
                if not filesystem.exists(path):
                    return None
                content = filesystem.read_bounded_bytes(path, self.PUBLISHING_ASSET_MAX_BYTES)
            if not content or len(content) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_read_failed")
            return content
        except ValueError:
            raise
        except OSError as exc:
            raise ValueError("publishing_asset_read_failed") from exc

    @with_project_update_lock
    def read_cover_base(self) -> tuple[bytes, str] | None:
        content = self._read_publishing_asset(self.cover_base_path)
        if content is None:
            return None
        cover = self._publishing_assets_from_metadata().get("cover") or {}
        derived = sha256(content).hexdigest()
        version = str(cover.get("base_image_version") or derived) if isinstance(cover, dict) else derived
        if version != derived:
            raise ValueError("publishing_asset_read_failed")
        return content, version

    @with_project_update_lock
    def read_rendered_cover(self) -> bytes | None:
        return self._read_publishing_asset(self.rendered_cover_path)

    @with_project_update_lock
    def save_rendered_cover(self, rendered_image: bytes, *, expected_base_version: str, expected_title: str | None = None, rendered_title: str | None = None) -> dict[str, Any]:
        try:
            if not isinstance(rendered_image, bytes) or not rendered_image or len(rendered_image) > self.PUBLISHING_ASSET_MAX_BYTES:
                raise ValueError("publishing_asset_write_failed")
            saved = self._publishing_assets_from_metadata()
            cover = dict(saved["cover"] or {})
            if cover.get("base_path") != "assets/cover-base.png":
                raise ValueError("publishing_asset_write_failed")
            current_base_version = str(cover.get("base_image_version") or "")
            if not current_base_version:
                base = self._read_publishing_asset(self.cover_base_path)
                if base is None:
                    raise ValueError("publishing_asset_write_failed")
                current_base_version = sha256(base).hexdigest()
                cover["base_image_version"] = current_base_version
            if not expected_base_version or current_base_version != expected_base_version:
                raise ValueError("publishing_asset_stale_base")
            try:
                title = normalize_cover_title(str(self.project().get("title") or ""))
            except CoverRenderError as exc:
                raise ValueError("publishing_asset_write_failed") from exc
            if not title:
                raise ValueError("publishing_asset_write_failed")
            if expected_title is not None and title != expected_title:
                raise ValueError("publishing_asset_stale_cover")
            if rendered_title is not None and rendered_title != title:
                raise ValueError("publishing_asset_stale_cover")
            updated_at = self._publishing_updated_at()
            cover.update(
                {
                    "rendered_path": "assets/cover.png",
                    "schema_version": "cover/v1",
                    "rendered_title": rendered_title or title,
                    "image_version": sha256(rendered_image).hexdigest(),
                    "rendered_from_base_version": expected_base_version,
                    "mime_type": "image/png",
                    "updated_at": updated_at,
                }
            )
            saved["cover"] = cover
            saved["updated_at"] = updated_at
            self._publishing_transaction(saved, asset_updates={self.rendered_cover_path: rendered_image})
            return saved
        except ValueError as exc:
            if str(exc) in {"publishing_asset_write_failed", "publishing_asset_stale_base", "publishing_asset_stale_cover"}:
                raise
            raise ValueError("publishing_asset_write_failed") from exc
        except Exception as exc:
            raise ValueError("publishing_asset_write_failed") from exc
