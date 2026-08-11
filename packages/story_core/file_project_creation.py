from __future__ import annotations

import json
import os
import re
import shutil
import stat
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
NARRATIVE_ENHANCEMENT_MODULE_IDS = {
    "commercial-shuangwen": (
        "commercial-shuangwen::plot-engine",
        "commercial-shuangwen::chapter-sop",
        "commercial-shuangwen::writer-execution",
        "commercial-shuangwen::review-checklist",
        "commercial-shuangwen::genre-examples",
    ),
}


class FileProjectCreateSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    mode: Literal["blank", "inspiration"]
    title: str = Field(default="", max_length=120)
    novel_type_id: str
    idea: str = Field(default="", max_length=1000)
    narrative_enhancement_ids: list[str] = Field(default_factory=list, max_length=8)

    @field_validator("title", "idea", mode="before")
    @classmethod
    def trim_text_fields(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @field_validator("narrative_enhancement_ids")
    @classmethod
    def normalize_narrative_enhancement_ids(cls, value: list[str]) -> list[str]:
        normalized_ids: list[str] = []
        for raw_id in value:
            enhancement_id = raw_id.strip()
            if enhancement_id not in NARRATIVE_ENHANCEMENT_MODULE_IDS:
                raise ValueError(f"unknown_narrative_enhancement_id:{enhancement_id}")
            if enhancement_id not in normalized_ids:
                normalized_ids.append(enhancement_id)
        return normalized_ids

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


def _narrative_skill_selection(spec: FileProjectCreateSpec) -> tuple[list[str], list[str]]:
    enabled_skill_ids = list(spec.narrative_enhancement_ids)
    enabled_module_ids = [
        module_id
        for enhancement_id in enabled_skill_ids
        for module_id in NARRATIVE_ENHANCEMENT_MODULE_IDS[enhancement_id]
    ]
    return enabled_skill_ids, enabled_module_ids


def _project_payload(project_id: str, spec: FileProjectCreateSpec) -> dict[str, Any]:
    enabled_skill_ids, enabled_module_ids = _narrative_skill_selection(spec)
    return {
        "project_id": project_id,
        "title": spec.title or "未命名作品",
        "seed_outline": "",
        "world_summary": "",
        "current_focus": "",
        "author_constraints": [],
        "character_profiles": [],
        "relationship_graph": [],
        "enabled_skill_ids": enabled_skill_ids,
        "enabled_skill_module_ids": enabled_module_ids,
        "world_blueprint": {"genre_plugin_ids": [spec.novel_type_id]},
        "current_chapter": 0,
        "status": "draft",
        "pipeline_stage": "idea_pending",
    }


def _state_payload(project_id: str, spec: FileProjectCreateSpec) -> dict[str, Any]:
    novel_type = runtime_novel_type(spec.novel_type_id)
    if novel_type is None:
        raise ValueError("invalid_novel_type")
    enabled_skill_ids, enabled_module_ids = _narrative_skill_selection(spec)
    state = StoryState(
        story_id=f"file:{project_id}",
        outline="",
        genre=novel_type.name,
        genre_plugin_ids=[novel_type.id],
        style="通俗网文",
        current_chapter=0,
        enabled_skill_ids=enabled_skill_ids,
        enabled_skill_module_ids=enabled_module_ids,
    )
    return state.model_dump(mode="json")


def _opening_brief_payload(spec: FileProjectCreateSpec) -> dict[str, Any]:
    idea = spec.idea if spec.mode == "inspiration" else f"请根据书名《{spec.title}》和所选小说类型构思故事。"
    return {
        "schema_version": "opening-brief/v1",
        "mode": spec.mode,
        "novel_type_id": spec.novel_type_id,
        "idea": idea,
        "working_title": spec.title,
    }


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
    state = _state_payload(project_id, spec)
    outline = normalize_project_outline({})
    master_setting = {
        "schema_version": "story-system-master-setting/v1",
        "project": project,
        "state": state,
    }

    _write_json(root / ".webnovel/project.json", project)
    _write_json(root / ".webnovel/state.json", state)
    _write_json(root / ".webnovel/outline.json", outline)
    _write_json(root / ".webnovel/opening_brief.json", _opening_brief_payload(spec))
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
    if state != _state_payload(project_id, spec):
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
    if not opening_brief_path.is_file() or _read_json(opening_brief_path) != _opening_brief_payload(spec):
        raise ValueError("invalid_opening_brief")

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


def _remove_project_tree(path: Path) -> None:
    def remove_readonly(function, value, _error) -> None:
        os.chmod(value, stat.S_IWRITE)
        function(value)

    shutil.rmtree(path, ignore_errors=False, onerror=remove_readonly)


def write_file_project_atomically(
    export_root: str | Path,
    project_id: str,
    writer: Callable[[Path], None],
) -> Path:
    if not isinstance(project_id, str) or PROJECT_ID_PATTERN.fullmatch(project_id) is None:
        raise ValueError("invalid_generated_project_id")

    export_path = Path(export_root)
    export_path.mkdir(parents=True, exist_ok=True)
    final_root = export_path / project_id
    if final_root.exists():
        raise FileExistsError("project_id_conflict")

    temp_root = Path(tempfile.mkdtemp(prefix=f".{project_id}.tmp-", dir=export_path))
    try:
        writer(temp_root)
        _fsync_directory(temp_root)
        if final_root.exists():
            raise FileExistsError("project_id_conflict")
        os.replace(temp_root, final_root)
    except Exception:
        try:
            _remove_project_tree(temp_root)
        except OSError:
            pass
        raise

    _fsync_directory(export_path)
    return final_root


def create_file_project(
    export_root: str | Path,
    spec: FileProjectCreateSpec,
    *,
    project_id_factory: Callable[[], str] | None = None,
) -> CreatedFileProject:
    project_id = (project_id_factory or (lambda: f"p-{uuid4().hex}"))()

    def write(root: Path) -> None:
        _write_project_files(root, project_id, spec)
        _validate_created_project(root, project_id, spec)

    final_root = write_file_project_atomically(export_root, project_id, write)
    route_id = quote(f"file:{project_id}", safe="")
    next_page = "setup"
    return CreatedFileProject(
        project_id=project_id,
        root=final_root,
        next_path=f"/projects/{route_id}/{next_page}",
    )
