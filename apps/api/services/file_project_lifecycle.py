"""Archive, trash, restore, and permanently delete file projects."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

from packages.story_core.file_project_store import FileProjectStore


class FileProjectLifecycleError(ValueError):
    pass


def archive_project(store: FileProjectStore) -> FileProjectStore:
    store.update_project(
        {
            "project_lifecycle": "archived",
            "archived_at": datetime.now(timezone.utc).isoformat(),
        }
    )
    return store


def trash_project(
    store: FileProjectStore,
    *,
    export_root: Path,
    move: Callable[[str, str], object] = shutil.move,
) -> FileProjectStore:
    project = store.project()
    previous = "archived" if project.get("project_lifecycle") == "archived" else "active"
    trashed_at = datetime.now(timezone.utc).isoformat()
    original_root = store.root.resolve()
    trash_root = (export_root / ".trash").resolve()
    destination = trash_root / store.root.name
    if destination.exists():
        raise FileProjectLifecycleError("file_project_trash_path_conflict")
    metadata_path = original_root / "trash.json"
    metadata_path.write_text(
        json.dumps(
            {
                "original_path": str(original_root),
                "trashed_at": trashed_at,
                "pre_trash_lifecycle": previous,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    trash_root.mkdir(parents=True, exist_ok=True)
    try:
        store.update_project(
            {
                "project_lifecycle": "trashed",
                "pre_trash_lifecycle": previous,
                "trashed_at": trashed_at,
            }
        )
        move(str(original_root), str(destination))
    except Exception:
        if original_root.exists():
            store.update_project({"project_lifecycle": previous, "trashed_at": ""})
            metadata_path.unlink(missing_ok=True)
        raise
    return FileProjectStore(destination)


def restore_project(
    store: FileProjectStore,
    *,
    export_root: Path,
    move: Callable[[str, str], object] = shutil.move,
) -> FileProjectStore:
    metadata_path = store.root / "trash.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise FileProjectLifecycleError("file_project_trash_metadata_invalid") from exc
    original_root = Path(str(metadata.get("original_path") or "")).resolve()
    if original_root.parent != export_root.resolve():
        raise FileProjectLifecycleError("file_project_trash_metadata_invalid")
    if original_root.exists():
        raise FileProjectLifecycleError("file_project_restore_path_conflict")
    previous = str(metadata.get("pre_trash_lifecycle") or "active")
    restored_lifecycle = "archived" if previous == "archived" else "active"
    archived_at = str(store.project().get("archived_at") or "")
    store.update_project(
        {
            "project_lifecycle": restored_lifecycle,
            "trashed_at": "",
            "archived_at": "" if restored_lifecycle == "active" else archived_at,
        }
    )
    try:
        move(str(store.root), str(original_root))
    except Exception:
        store.update_project(
            {
                "project_lifecycle": "trashed",
                "trashed_at": str(metadata.get("trashed_at") or ""),
                "archived_at": archived_at,
            }
        )
        raise
    restored = FileProjectStore(original_root)
    (original_root / "trash.json").unlink(missing_ok=True)
    return restored


def activate_project(store: FileProjectStore) -> FileProjectStore:
    store.update_project({"project_lifecycle": "active", "archived_at": "", "trashed_at": ""})
    return store


def delete_trashed_project(
    store: FileProjectStore,
    *,
    export_root: Path,
    confirmation_title: str,
    actual_title: str,
    remove_tree: Callable[[Path], object] = shutil.rmtree,
) -> Path:
    if confirmation_title != actual_title:
        raise FileProjectLifecycleError("project_title_confirmation_mismatch")
    trash_root = (export_root / ".trash").resolve()
    resolved = store.root.resolve()
    if resolved.parent != trash_root:
        raise FileProjectLifecycleError("file_project_delete_path_invalid")
    remove_tree(resolved)
    return resolved
