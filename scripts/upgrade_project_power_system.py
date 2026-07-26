from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import datetime
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
TARGET_PROJECT_ID = "p-gou-webgame-restored"
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.p_gou_power_system_data import build_power_system_spec  # noqa: E402
from packages.story_core.power_systems import (  # noqa: E402
    legacy_power_summary,
    validate_power_system_spec,
)
from packages.story_core.world_blueprint_context import (  # noqa: E402
    MANAGED_MARKER,
    render_power_markdown,
)


class FilesystemContainmentError(ValueError):
    pass


def _validate_target_project(root: Path, project: dict[str, Any] | None = None) -> None:
    if root.name != TARGET_PROJECT_ID:
        raise ValueError(
            "this migration only supports project directory "
            f"'{TARGET_PROJECT_ID}', got '{root.name}'"
        )
    if project is None or "project_id" not in project:
        return
    project_id = project["project_id"]
    if project_id != TARGET_PROJECT_ID:
        raise ValueError(
            f"project.json project_id must be '{TARGET_PROJECT_ID}', got {project_id!r}"
        )


class FilesystemTransactionError(RuntimeError):
    def __init__(
        self,
        *,
        primary_error: Exception | None,
        rollback_errors: list[tuple[Path, Exception]],
        cleanup_errors: list[tuple[Path, Exception]],
        residual_temp_paths: list[Path],
        changed: bool,
        canonical_valid: bool,
    ) -> None:
        self.primary_error = primary_error
        self.rollback_errors = tuple(rollback_errors)
        self.cleanup_errors = tuple(cleanup_errors)
        self.residual_temp_paths = tuple(residual_temp_paths)
        self.rollback_failed = bool(rollback_errors)
        self.cleanup_failed = bool(cleanup_errors)
        self.changed = changed
        self.canonical_valid = canonical_valid
        if primary_error is not None:
            message = f"primary failure: {type(primary_error).__name__}: {primary_error}"
        else:
            message = "canonical commit succeeded but temporary-file cleanup failed"
        super().__init__(message)


def _build_power_system_spec() -> dict[str, Any]:
    return build_power_system_spec()


_LEVEL_TWENTY = re.compile(r"(?i)(?:lv\.?\s*20|20\s*级)")
_CONTRADICTORY_LEVEL_TWENTY = re.compile(
    r"第二次\s*(?:职业)?(?:转职|晋升|进阶)|再次\s*(?:职业)?转职|二次\s*(?:职业)?转职|二转|第二职业\s*(?:晋升|进阶)"
)
_LEVEL_TEN = re.compile(r"(?i)(?:lv\.?\s*10|10\s*级)")
_OUTLINE_NARRATIVE_FIELDS = frozenset(
    {
        "action",
        "beat",
        "close_route",
        "continue_route",
        "current_strategy",
        "description",
        "end_state",
        "ending_contract",
        "ending_direction",
        "ending_hook",
        "game_line_payoff",
        "goal",
        "growth_path",
        "key_event",
        "main_conflict",
        "obstacle",
        "payoff",
        "progression",
        "progression_path",
        "protagonist_goal",
        "reality_line_payoff",
        "stage_antagonist",
        "story",
        "summary",
        "synopsis",
        "title",
        "turn",
    }
)
_OUTLINE_DICT_CONTAINERS = frozenset(
    {"extension_gate", "overall", "outline", "progression", "summary"}
)
_OUTLINE_LIST_CONTAINERS = frozenset(
    {
        "arc_beats",
        "arcs",
        "beats",
        "chapter_beats",
        "chapters",
        "events",
        "key_events",
        "plot_beats",
        "progression_beats",
        "summaries",
    }
)
_OUTLINE_EXCLUDED_KEY_PARTS = (
    "note",
    "author",
    "dialogue",
    "quote",
    "excerpt",
    "instruction",
    "constraint",
    "rule",
    "raw",
    "source",
)


def _clean_outline_text(value: str) -> tuple[str, bool]:
    cleaned = value
    if _LEVEL_TWENTY.search(cleaned):
        cleaned = _CONTRADICTORY_LEVEL_TWENTY.sub("职业专精", cleaned)
    if _LEVEL_TEN.search(cleaned) and "正式法系职业" in cleaned:
        cleaned = cleaned.replace("正式法系职业", "元素法师")
    return cleaned, cleaned != value


def _outline_key(key: Any) -> str:
    return str(key).strip().casefold()


def _outline_key_is_excluded(key: str) -> bool:
    return any(part in key for part in _OUTLINE_EXCLUDED_KEY_PARTS)


def _clean_outline_list(value: list[Any]) -> tuple[list[Any], bool]:
    result: list[Any] = []
    changed = False
    for item in value:
        if isinstance(item, dict):
            cleaned, item_changed = _clean_outline_mapping(item)
        elif isinstance(item, list):
            cleaned, item_changed = _clean_outline_list(item)
        elif isinstance(item, str):
            cleaned, item_changed = _clean_outline_text(item)
        else:
            cleaned, item_changed = item, False
        result.append(cleaned)
        changed = changed or item_changed
    return result, changed


def _clean_outline_mapping(value: dict[Any, Any]) -> tuple[dict[Any, Any], bool]:
    result: dict[Any, Any] = {}
    changed = False
    for key, item in value.items():
        normalized_key = _outline_key(key)
        item_changed = False
        if _outline_key_is_excluded(normalized_key):
            cleaned = item
        elif isinstance(item, str) and normalized_key in _OUTLINE_NARRATIVE_FIELDS:
            cleaned, item_changed = _clean_outline_text(item)
        elif isinstance(item, dict) and normalized_key in _OUTLINE_DICT_CONTAINERS:
            cleaned, item_changed = _clean_outline_mapping(item)
        elif isinstance(item, list) and normalized_key in _OUTLINE_LIST_CONTAINERS:
            cleaned, item_changed = _clean_outline_list(item)
        else:
            cleaned = item
        result[key] = cleaned
        changed = changed or item_changed
    return result, changed


def _clean_outline_value(value: Any) -> tuple[Any, bool]:
    if isinstance(value, dict):
        return _clean_outline_mapping(value)
    if isinstance(value, list):
        result: list[Any] = []
        changed = False
        for item in value:
            if isinstance(item, dict):
                cleaned, item_changed = _clean_outline_mapping(item)
            else:
                cleaned, item_changed = item, False
            result.append(cleaned)
            changed = changed or item_changed
        return result, changed
    return value, False


def _read_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    return json.loads(raw.decode("utf-8-sig")), raw


def _serialization_style(raw: bytes) -> tuple[int | str | None, str, bool, bool]:
    decoded = raw.decode("utf-8-sig")
    newline = "\r\n" if "\r\n" in decoded else "\n"
    match = re.search(r"(?:\r?\n)([ \t]+)\"", decoded)
    indent: int | str | None
    if match:
        whitespace = match.group(1)
        indent = "\t" if "\t" in whitespace else len(whitespace)
    else:
        indent = None
    return indent, newline, decoded.endswith(("\n", "\r")), raw.startswith(b"\xef\xbb\xbf")


def _encode_json(value: Any, source: bytes) -> bytes:
    indent, newline, trailing_newline, bom = _serialization_style(source)
    text = json.dumps(value, ensure_ascii=False, indent=indent)
    if newline != "\n":
        text = text.replace("\n", newline)
    if trailing_newline:
        text += newline
    encoded = text.encode("utf-8")
    return (b"\xef\xbb\xbf" + encoded) if bom else encoded


def _is_managed_markdown(path: Path) -> bool:
    try:
        with path.open("r", encoding="utf-8-sig") as handle:
            return handle.readline().rstrip("\r\n") == MANAGED_MARKER
    except UnicodeDecodeError:
        return False


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _require_contained_path(root: Path, path: Path, label: str) -> None:
    resolved_parent = path.parent.resolve(strict=False)
    resolved_target = path.resolve(strict=False)
    if not _is_relative_to(resolved_parent, root) or not _is_relative_to(
        resolved_target, root
    ):
        raise FilesystemContainmentError(f"path_escape: {label}")


def _stage_write(root: Path, path: Path, content: bytes) -> Path:
    _require_contained_path(root, path.parent, "staging_parent")
    path.parent.mkdir(parents=True, exist_ok=True)
    _require_contained_path(root, path.parent, "staging_parent")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        _require_contained_path(root, temporary, "staging_file")
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        return temporary
    except Exception as exc:
        try:
            os.close(descriptor)
        except OSError:
            pass
        setattr(exc, "_migration_temp_path", temporary)
        raise


def _capture_targets(writes: list[tuple[Path, bytes]]) -> dict[Path, tuple[bool, bytes]]:
    originals: dict[Path, tuple[bool, bytes]] = {}
    for path, _ in writes:
        existed = path.exists()
        originals[path] = (existed, path.read_bytes() if existed else b"")
    return originals


def _targets_differ(originals: dict[Path, tuple[bool, bytes]]) -> bool:
    for path, (existed, original) in originals.items():
        try:
            current_exists = path.exists()
            if current_exists != existed:
                return True
            if current_exists and path.read_bytes() != original:
                return True
        except OSError:
            return True
    return False


def _transactional_write(
    root: Path,
    writes: list[tuple[Path, bytes]],
    originals: dict[Path, tuple[bool, bytes]],
) -> None:
    if set(originals) != {path for path, _ in writes}:
        raise ValueError("transaction originals do not match write targets")
    staged: list[tuple[Path, Path]] = []
    temporary_paths: list[Path] = []
    replaced: list[Path] = []
    primary_error: Exception | None = None
    rollback_errors: list[tuple[Path, Exception]] = []
    canonical_valid = False

    try:
        for path, content in writes:
            temporary = _stage_write(root, path, content)
            staged.append((path, temporary))
            temporary_paths.append(temporary)
    except Exception as staging_error:
        primary_error = staging_error
        failed_temp = getattr(staging_error, "_migration_temp_path", None)
        if isinstance(failed_temp, Path):
            temporary_paths.append(failed_temp)

    if primary_error is None:
        try:
            for path, temporary in staged:
                os.replace(temporary, path)
                replaced.append(path)
            canonical_valid = True
        except Exception as commit_error:
            primary_error = commit_error
            for path in reversed(replaced):
                existed, original = originals[path]
                try:
                    if existed:
                        restoration = _stage_write(root, path, original)
                        temporary_paths.append(restoration)
                        os.replace(restoration, path)
                    else:
                        path.unlink(missing_ok=True)
                except Exception as rollback_error:
                    failed_temp = getattr(
                        rollback_error, "_migration_temp_path", None
                    )
                    if isinstance(failed_temp, Path):
                        temporary_paths.append(failed_temp)
                    rollback_errors.append((path, rollback_error))

    cleanup_errors: list[tuple[Path, Exception]] = []
    for temporary in dict.fromkeys(temporary_paths):
        try:
            temporary.unlink(missing_ok=True)
        except Exception as cleanup_error:
            cleanup_errors.append((temporary, cleanup_error))

    residual_temp_paths: list[Path] = []
    for temporary in dict.fromkeys(temporary_paths):
        try:
            if temporary.exists():
                residual_temp_paths.append(temporary)
        except OSError:
            residual_temp_paths.append(temporary)

    changed = _targets_differ(originals)
    if primary_error is not None or cleanup_errors:
        raise FilesystemTransactionError(
            primary_error=primary_error,
            rollback_errors=rollback_errors,
            cleanup_errors=cleanup_errors,
            residual_temp_paths=residual_temp_paths,
            changed=changed,
            canonical_valid=canonical_valid,
        ) from primary_error


def _write_fsynced_file(path: Path, content: bytes) -> None:
    with path.open("xb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())


def _backup(
    root: Path, metadata_dir: Path, project_bytes: bytes, outline_bytes: bytes
) -> Path:
    backups_parent = metadata_dir / "backups"
    _require_contained_path(root, backups_parent, "backups_parent")
    backups_parent.mkdir(parents=True, exist_ok=True)
    _require_contained_path(root, backups_parent, "backups_parent")
    staging = Path(
        tempfile.mkdtemp(
            prefix=".power-system-", suffix=".tmp", dir=backups_parent
        )
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    destination = backups_parent / f"power-system-{stamp}"
    try:
        _require_contained_path(root, staging, "backup_staging")
        _require_contained_path(root, staging / "project.json", "backup_project")
        _require_contained_path(root, staging / "outline.json", "backup_outline")
        _require_contained_path(root, destination, "backup_destination")
        _write_fsynced_file(staging / "project.json", project_bytes)
        _write_fsynced_file(staging / "outline.json", outline_bytes)
        os.replace(staging, destination)
        return destination
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise


def upgrade_project(
    project_dir: str | Path, *, check: bool = False, backup: bool = True
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "changed": False,
        "valid": False,
        "backup_path": None,
        "changes": [],
    }
    transaction_originals: dict[Path, tuple[bool, bytes]] | None = None
    try:
        root = Path(project_dir).resolve(strict=True)
        if not root.is_dir():
            raise NotADirectoryError(f"project root is not a directory: {root}")
        _validate_target_project(root)
        metadata = root / ".webnovel"
        project_path = metadata / "project.json"
        outline_path = metadata / "outline.json"
        power_path = root / "设定集" / "力量体系.md"
        _require_contained_path(root, project_path, "project_json")
        _require_contained_path(root, outline_path, "outline_json")
        _require_contained_path(root, power_path, "power_markdown")
        if backup:
            _require_contained_path(root, metadata / "backups", "backups_parent")
        project, project_bytes = _read_json(project_path)
        if not isinstance(project, dict):
            raise ValueError("project.json must contain a JSON object")
        _validate_target_project(root, project)
        outline, outline_bytes = _read_json(outline_path)
        if not isinstance(outline, (dict, list)):
            raise ValueError("project.json and outline.json must contain JSON objects or arrays")

        migrated_project = deepcopy(project)
        blueprint = migrated_project.setdefault("world_blueprint", {})
        if not isinstance(blueprint, dict):
            raise ValueError("project.json world_blueprint must be an object")
        spec = _build_power_system_spec()
        blueprint["power_system_spec"] = spec
        blueprint["power_system"] = legacy_power_summary(spec)
        validate_power_system_spec(blueprint["power_system_spec"], novel_type_id="game_webnovel")

        migrated_outline, outline_changed = _clean_outline_value(outline)
        expected_project_bytes = _encode_json(migrated_project, project_bytes)
        expected_outline_bytes = (
            _encode_json(migrated_outline, outline_bytes) if outline_changed else outline_bytes
        )
        project_changed = expected_project_bytes != project_bytes
        outline_file_changed = expected_outline_bytes != outline_bytes

        expected_power = render_power_markdown(project.get("title"), blueprint).encode("utf-8")
        power_exists = power_path.exists()
        power_managed = power_exists and _is_managed_markdown(power_path)
        current_power = power_path.read_bytes() if power_exists else None
        power_changed = (not power_exists or power_managed) and current_power != expected_power

        changes: list[str] = []
        if project_changed:
            changes.append("project.json: power system upgraded")
        if outline_file_changed:
            changes.append("outline.json: contradictory progression wording updated")
        if power_changed:
            changes.append(
                "设定集/力量体系.md: refreshed" if power_exists else "设定集/力量体系.md: created"
            )
        elif power_exists and not power_managed:
            changes.append("设定集/力量体系.md: skipped unmanaged")

        will_write = project_changed or outline_file_changed or power_changed
        result.update(changed=will_write, valid=True, changes=changes)
        if check or not will_write:
            return result

        writes: list[tuple[Path, bytes]] = []
        if project_changed:
            writes.append((project_path, expected_project_bytes))
        if outline_file_changed:
            writes.append((outline_path, expected_outline_bytes))
        if power_changed:
            writes.append((power_path, expected_power))
        transaction_originals = _capture_targets(writes)
        if backup:
            backup_path = _backup(root, metadata, project_bytes, outline_bytes)
            result["backup_path"] = str(backup_path)
        _transactional_write(root, writes, transaction_originals)
        return result
    except Exception as exc:
        transaction_error = (
            exc if isinstance(exc, FilesystemTransactionError) else None
        )
        persistent_change = (
            transaction_error.changed
            if transaction_error is not None
            else _targets_differ(transaction_originals)
            if transaction_originals is not None
            else False
        )
        rollback_failed = bool(
            transaction_error and transaction_error.rollback_failed
        )
        cleanup_failed = bool(
            transaction_error and transaction_error.cleanup_failed
        )
        rollback_errors = (
            [
                f"{path}: {type(error).__name__}: {error}"
                for path, error in transaction_error.rollback_errors
            ]
            if transaction_error is not None
            else []
        )
        cleanup_errors = (
            [
                f"{path}: {type(error).__name__}: {error}"
                for path, error in transaction_error.cleanup_errors
            ]
            if transaction_error is not None
            else []
        )
        residual_temp_paths = (
            [str(path) for path in transaction_error.residual_temp_paths]
            if transaction_error is not None
            else []
        )
        return {
            "changed": persistent_change,
            "valid": bool(transaction_error and transaction_error.canonical_valid),
            "backup_path": result.get("backup_path"),
            "changes": [f"error: {type(exc).__name__}: {exc}"],
            "rollback_failed": rollback_failed,
            "cleanup_failed": cleanup_failed,
            "rollback_errors": rollback_errors,
            "cleanup_errors": cleanup_errors,
            "residual_temp_paths": residual_temp_paths,
            "state": (
                "indeterminate"
                if rollback_failed
                else "changed"
                if persistent_change
                else "unchanged"
            ),
        }


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description="Upgrade a legacy file project's power system")
    parser.add_argument("project_dir")
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)
    result = upgrade_project(args.project_dir, check=args.check, backup=not args.no_backup)
    print(json.dumps(result, ensure_ascii=False))
    return (
        0
        if result["valid"]
        and not result.get("rollback_failed")
        and not result.get("cleanup_failed")
        else 1
    )


if __name__ == "__main__":
    raise SystemExit(main())
