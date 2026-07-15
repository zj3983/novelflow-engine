from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Literal
from urllib.parse import quote
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.novel_type_catalog import resolve_novel_type_id, runtime_novel_type
from packages.story_core.project_outline import normalize_project_outline


PROJECT_ID_PATTERN = re.compile(r"p-[A-Za-z0-9-]+")


class FileProjectCreateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["blank", "inspiration"]
    title: str = Field(default="", max_length=120)
    novel_type_id: str
    idea: str = Field(default="", max_length=1000)

    @field_validator("title", "idea", mode="before")
    @classmethod
    def trim_text_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_mode_fields(self) -> "FileProjectCreateSpec":
        normalized_type_id = resolve_novel_type_id(self.novel_type_id)
        if not normalized_type_id:
            raise ValueError("invalid_novel_type")
        self.novel_type_id = normalized_type_id
        if self.mode == "blank" and not self.title:
            raise ValueError("title_required")
        if self.mode == "inspiration" and not self.idea:
            raise ValueError("idea_required")
        return self


@dataclass(frozen=True)
class CreatedFileProject:
    project_id: str
    root: Path
    next_path: str


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def _project_payload(project_id: str, spec: FileProjectCreateSpec) -> dict[str, Any]:
    return {
        "project_id": project_id,
        "title": spec.title or "未命名作品",
        "seed_outline": "",
        "world_summary": "",
        "current_focus": "",
        "author_constraints": [],
        "character_profiles": [],
        "relationship_graph": [],
        "enabled_skill_ids": [],
        "world_blueprint": {"genre_plugin_ids": [spec.novel_type_id]},
        "current_chapter": 0,
        "status": "draft",
        "pipeline_stage": "draft" if spec.mode == "blank" else "idea_pending",
    }


def _state_payload(project_id: str, novel_type_id: str) -> dict[str, Any]:
    novel_type = runtime_novel_type(novel_type_id)
    if novel_type is None:
        raise ValueError("invalid_novel_type")
    state = StoryState(
        story_id=f"file:{project_id}",
        outline="",
        genre=novel_type.name,
        genre_plugin_ids=[novel_type.id],
        style="通俗网文",
        current_chapter=0,
    )
    return state.model_dump(mode="json")


def _write_project_files(
    root: Path,
    project_id: str,
    spec: FileProjectCreateSpec,
) -> None:
    for relative_path in (
        ".story-system/chapters",
        ".story-system/reviews",
        ".webnovel",
        "chapters",
        "commits",
        "reviews",
    ):
        (root / relative_path).mkdir(parents=True, exist_ok=True)

    project = _project_payload(project_id, spec)
    state = _state_payload(project_id, spec.novel_type_id)
    outline = normalize_project_outline({})
    master_setting = {
        "schema_version": "story-system-master-setting/v1",
        "project": project,
        "state": state,
    }

    _write_json(root / ".webnovel/project.json", project)
    _write_json(root / ".webnovel/state.json", state)
    _write_json(root / ".webnovel/outline.json", outline)
    if spec.mode == "inspiration":
        _write_json(
            root / ".webnovel/opening_brief.json",
            {
                "schema_version": "opening-brief/v1",
                "mode": "inspiration",
                "novel_type_id": spec.novel_type_id,
                "idea": spec.idea,
                "working_title": spec.title,
            },
        )
    _write_json(root / ".story-system/MASTER_SETTING.json", master_setting)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _validate_created_project(
    root: Path,
    project_id: str,
    spec: FileProjectCreateSpec,
) -> None:
    required_directories = (
        ".story-system/chapters",
        ".story-system/reviews",
        ".webnovel",
        "chapters",
        "commits",
        "reviews",
    )
    required_files = (
        ".story-system/MASTER_SETTING.json",
        ".webnovel/project.json",
        ".webnovel/state.json",
        ".webnovel/outline.json",
    )
    if not all((root / path).is_dir() for path in required_directories):
        raise ValueError("incomplete_project_directories")
    if not all((root / path).is_file() for path in required_files):
        raise ValueError("incomplete_project_files")

    project = _read_json(root / ".webnovel/project.json")
    state = _read_json(root / ".webnovel/state.json")
    outline = _read_json(root / ".webnovel/outline.json")
    master_setting = _read_json(root / ".story-system/MASTER_SETTING.json")
    if project != _project_payload(project_id, spec):
        raise ValueError("invalid_project_payload")
    if state != _state_payload(project_id, spec.novel_type_id):
        raise ValueError("invalid_story_state")
    if outline != normalize_project_outline({}):
        raise ValueError("invalid_project_outline")
    if master_setting != {
        "schema_version": "story-system-master-setting/v1",
        "project": project,
        "state": state,
    }:
        raise ValueError("invalid_master_setting")
    if StoryState.model_validate(state).model_dump(mode="json") != state:
        raise ValueError("invalid_story_state")
    if normalize_project_outline(outline) != outline:
        raise ValueError("invalid_project_outline")

    opening_brief_path = root / ".webnovel/opening_brief.json"
    if spec.mode == "inspiration":
        expected_brief = {
            "schema_version": "opening-brief/v1",
            "mode": "inspiration",
            "novel_type_id": spec.novel_type_id,
            "idea": spec.idea,
            "working_title": spec.title,
        }
        if not opening_brief_path.is_file() or _read_json(opening_brief_path) != expected_brief:
            raise ValueError("invalid_opening_brief")
    elif opening_brief_path.exists():
        raise ValueError("unexpected_opening_brief")

    store = FileProjectStore(root)
    readable_state = store.state()
    if (
        not store.exists()
        or store.project() != project
        or readable_state.get("story_id") != state["story_id"]
        or readable_state.get("current_chapter") != 0
    ):
        raise ValueError("unreadable_file_project")


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        pass
    finally:
        os.close(descriptor)


def create_file_project(
    export_root: str | Path,
    spec: FileProjectCreateSpec,
    *,
    project_id_factory: Callable[[], str] | None = None,
) -> CreatedFileProject:
    project_id = (project_id_factory or (lambda: f"p-{uuid4().hex}"))()
    if not isinstance(project_id, str) or PROJECT_ID_PATTERN.fullmatch(project_id) is None:
        raise ValueError("invalid_generated_project_id")

    export_path = Path(export_root)
    export_path.mkdir(parents=True, exist_ok=True)
    final_root = export_path / project_id
    if final_root.exists():
        raise FileExistsError("project_id_conflict")

    temp_root = Path(tempfile.mkdtemp(prefix=f".{project_id}.tmp-", dir=export_path))
    try:
        _write_project_files(temp_root, project_id, spec)
        _validate_created_project(temp_root, project_id, spec)
        _fsync_directory(temp_root)
        if final_root.exists():
            raise FileExistsError("project_id_conflict")
        os.replace(temp_root, final_root)
    except Exception:
        shutil.rmtree(temp_root, ignore_errors=True)
        raise

    _fsync_directory(export_path)
    route_id = quote(f"file:{project_id}", safe="")
    next_page = "setup" if spec.mode == "inspiration" else "outline"
    return CreatedFileProject(
        project_id=project_id,
        root=final_root,
        next_path=f"/projects/{route_id}/{next_page}",
    )
