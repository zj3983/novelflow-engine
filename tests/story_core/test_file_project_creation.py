import json
import re
from dataclasses import FrozenInstanceError

import pytest
from pydantic import ValidationError

from packages.story_core import file_project_creation
from packages.story_core.file_project_creation import (
    FileProjectCreateSpec,
    create_file_project,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.novel_type_catalog import NOVEL_TYPE_CATALOG
from packages.story_core.project_outline import normalize_project_outline


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_create_blank_project_writes_clean_complete_project(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(
            mode="blank",
            title="  照夜行  ",
            novel_type_id=" XUANHUAN ",
        ),
        project_id_factory=lambda: "p-test-blank",
    )

    assert created.project_id == "p-test-blank"
    assert created.root == tmp_path / "p-test-blank"
    assert created.next_path == "/projects/file%3Ap-test-blank/outline"
    expected_directories = {
        ".story-system",
        ".story-system/chapters",
        ".story-system/reviews",
        ".webnovel",
        "chapters",
        "commits",
        "reviews",
    }
    assert {
        path.relative_to(created.root).as_posix()
        for path in created.root.rglob("*")
        if path.is_dir()
    } == expected_directories
    assert {
        path.relative_to(created.root).as_posix()
        for path in created.root.rglob("*")
        if path.is_file()
    } == {
        ".story-system/MASTER_SETTING.json",
        ".webnovel/project.json",
        ".webnovel/state.json",
        ".webnovel/outline.json",
    }

    project = read_json(created.root / ".webnovel/project.json")
    state = read_json(created.root / ".webnovel/state.json")
    outline = read_json(created.root / ".webnovel/outline.json")
    master = read_json(created.root / ".story-system/MASTER_SETTING.json")
    assert project == {
        "project_id": "p-test-blank",
        "title": "照夜行",
        "seed_outline": "",
        "world_summary": "",
        "current_focus": "",
        "author_constraints": [],
        "character_profiles": [],
        "relationship_graph": [],
        "enabled_skill_ids": [],
        "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "current_chapter": 0,
        "status": "draft",
        "pipeline_stage": "draft",
    }
    assert state["story_id"] == "file:p-test-blank"
    assert state["outline"] == ""
    assert state["genre"] == NOVEL_TYPE_CATALOG["xuanhuan"].label
    assert state["style"] == "通俗网文"
    assert state["current_chapter"] == 0
    assert state["characters"] == []
    assert state["world_facts"] == []
    assert state["progression_ledger"] == {}
    assert state["timeline"] == []
    assert state["foreshadowing"] == []
    assert state["chapter_summaries"] == []
    assert state["memory_index"] == []
    assert outline == normalize_project_outline({})
    assert master == {
        "schema_version": "story-system-master-setting/v1",
        "project": project,
        "state": state,
    }


def test_create_inspiration_project_keeps_idea_isolated(tmp_path):
    idea = "失业律师替陌生人追一笔旧账"
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(
            mode="inspiration",
            title="  旧账  ",
            novel_type_id="urban",
            idea=f"  {idea}  ",
        ),
        project_id_factory=lambda: "p-test-idea",
    )

    project = read_json(created.root / ".webnovel/project.json")
    state = read_json(created.root / ".webnovel/state.json")
    outline = read_json(created.root / ".webnovel/outline.json")
    brief = read_json(created.root / ".webnovel/opening_brief.json")
    assert created.next_path == "/projects/file%3Ap-test-idea/setup"
    assert project["title"] == "旧账"
    assert project["pipeline_stage"] == "idea_pending"
    assert brief == {
        "schema_version": "opening-brief/v1",
        "mode": "inspiration",
        "novel_type_id": "urban",
        "idea": idea,
        "working_title": "旧账",
    }
    for payload in (project, state, outline):
        assert idea not in json.dumps(payload, ensure_ascii=False)


def test_inspiration_without_title_uses_unnamed_project_title(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(
            mode="inspiration",
            novel_type_id="urban",
            idea="一条灵感",
        ),
        project_id_factory=lambda: "p-unnamed",
    )

    assert read_json(created.root / ".webnovel/project.json")["title"] == "未命名作品"
    assert read_json(created.root / ".webnovel/opening_brief.json")["working_title"] == ""


@pytest.mark.parametrize(
    ("payload", "error"),
    [
        ({"mode": "blank", "title": "   ", "novel_type_id": "urban"}, "title_required"),
        (
            {"mode": "inspiration", "idea": "\t\n", "novel_type_id": "urban"},
            "idea_required",
        ),
        ({"mode": "blank", "title": "书", "novel_type_id": "unknown"}, "invalid_novel_type"),
    ],
)
def test_create_spec_rejects_invalid_inputs(payload, error):
    with pytest.raises(ValidationError, match=error):
        FileProjectCreateSpec.model_validate(payload)


def test_create_spec_trims_before_enforcing_length_limits():
    spec = FileProjectCreateSpec(
        mode="inspiration",
        title=f"  {'题' * 120}  ",
        idea=f"  {'想' * 1000}  ",
        novel_type_id="urban",
    )

    assert len(spec.title) == 120
    assert len(spec.idea) == 1000
    with pytest.raises(ValidationError):
        FileProjectCreateSpec(
            mode="blank",
            title="题" * 121,
            novel_type_id="urban",
        )
    with pytest.raises(ValidationError):
        FileProjectCreateSpec(
            mode="inspiration",
            idea="想" * 1001,
            novel_type_id="urban",
        )


def test_create_spec_forbids_extra_fields():
    with pytest.raises(ValidationError, match="extra_forbidden"):
        FileProjectCreateSpec.model_validate(
            {
                "mode": "blank",
                "title": "书",
                "novel_type_id": "urban",
                "unexpected": True,
            }
        )


def test_user_title_never_controls_directory(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(
            mode="blank",
            title="../../别处",
            novel_type_id="urban",
        ),
        project_id_factory=lambda: "p-safe-id",
    )

    assert created.root == tmp_path / "p-safe-id"
    assert not (tmp_path.parent / "别处").exists()


@pytest.mark.parametrize("project_id", ["bad", "p_unsafe", "p-../unsafe", "p-"])
def test_create_rejects_invalid_generated_project_id(tmp_path, project_id):
    with pytest.raises(ValueError, match="invalid_generated_project_id"):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(mode="blank", title="书", novel_type_id="urban"),
            project_id_factory=lambda: project_id,
        )


def test_default_generated_project_id_matches_contract(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(mode="blank", title="书", novel_type_id="urban"),
    )

    assert re.fullmatch(r"p-[A-Za-z0-9-]+", created.project_id)
    assert created.root.name == created.project_id


def test_create_rejects_final_directory_collision(tmp_path):
    collision = tmp_path / "p-existing"
    collision.mkdir()

    with pytest.raises(FileExistsError, match="project_id_conflict"):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(mode="blank", title="书", novel_type_id="urban"),
            project_id_factory=lambda: "p-existing",
        )

    assert list(tmp_path.iterdir()) == [collision]


def test_created_project_is_readable_by_file_project_store(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(mode="blank", title="可读项目", novel_type_id="xianxia"),
        project_id_factory=lambda: "p-readable",
    )
    store = FileProjectStore(created.root)

    assert store.exists()
    assert store.project() == read_json(created.root / ".webnovel/project.json")
    assert store.state()["story_id"] == "file:p-readable"
    assert store.state()["current_chapter"] == 0


def test_failed_initialization_removes_temporary_directory(tmp_path, monkeypatch):
    def fail_write(*_args):
        raise OSError("disk")

    monkeypatch.setattr(file_project_creation, "_write_project_files", fail_write)

    with pytest.raises(OSError, match="disk"):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(mode="blank", title="失败测试", novel_type_id="urban"),
            project_id_factory=lambda: "p-failed",
        )

    assert list(tmp_path.iterdir()) == []


def test_incomplete_project_payload_is_not_published(tmp_path, monkeypatch):
    original_write = file_project_creation._write_project_files

    def write_incomplete(root, project_id, spec):
        original_write(root, project_id, spec)
        project = {"project_id": project_id}
        master = read_json(root / ".story-system/MASTER_SETTING.json")
        master["project"] = project
        (root / ".webnovel/project.json").write_text(
            json.dumps(project, ensure_ascii=False),
            encoding="utf-8",
        )
        (root / ".story-system/MASTER_SETTING.json").write_text(
            json.dumps(master, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(file_project_creation, "_write_project_files", write_incomplete)

    with pytest.raises(ValueError, match="invalid_project_payload"):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(mode="blank", title="书", novel_type_id="urban"),
            project_id_factory=lambda: "p-incomplete",
        )

    assert list(tmp_path.iterdir()) == []


def test_invalid_opening_brief_is_not_published(tmp_path, monkeypatch):
    original_write = file_project_creation._write_project_files

    def write_invalid_brief(root, project_id, spec):
        original_write(root, project_id, spec)
        (root / ".webnovel/opening_brief.json").write_text(
            json.dumps({"idea": spec.idea}, ensure_ascii=False),
            encoding="utf-8",
        )

    monkeypatch.setattr(file_project_creation, "_write_project_files", write_invalid_brief)

    with pytest.raises(ValueError, match="invalid_opening_brief"):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(
                mode="inspiration",
                idea="一条灵感",
                novel_type_id="urban",
            ),
            project_id_factory=lambda: "p-invalid-brief",
        )

    assert list(tmp_path.iterdir()) == []


def test_created_file_project_is_immutable(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(mode="blank", title="书", novel_type_id="urban"),
        project_id_factory=lambda: "p-frozen",
    )

    with pytest.raises(FrozenInstanceError):
        created.project_id = "p-other"
