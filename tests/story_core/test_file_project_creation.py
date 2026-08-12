import json
import re
from dataclasses import FrozenInstanceError
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from packages.story_core import file_project_creation
from packages.story_core.file_project_creation import (
    FileProjectCreateSpec,
    create_file_project,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import NovelProject, NovelProjectSummary
from packages.story_core.novel_type_catalog import NOVEL_TYPE_CATALOG
from packages.story_core.project_outline import normalize_project_outline
from packages.story_core.skill_packs import get_skill_pack, skill_module_key


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def commercial_shuangwen_module_ids():
    pack = get_skill_pack("commercial-shuangwen")
    assert pack is not None
    return [skill_module_key(pack.skill_id, module.module_id) for module in pack.modules]


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
    assert created.next_path == "/projects/file%3Ap-test-blank/setup"
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
        ".webnovel/opening_brief.json",
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
            "enabled_skill_module_ids": [],
            "world_blueprint": {"genre_plugin_ids": ["xuanhuan"]},
        "current_chapter": 0,
        "status": "draft",
        "pipeline_stage": "idea_pending",
    }
    assert NovelProject.model_validate(project).pipeline_stage == "idea_pending"
    assert NovelProjectSummary.model_validate(project).pipeline_stage == "idea_pending"
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
    assert state["enabled_skill_ids"] == []
    assert state["enabled_skill_module_ids"] == []
    assert outline == normalize_project_outline({})
    assert read_json(created.root / ".webnovel/opening_brief.json") == {
        "schema_version": "opening-brief/v1",
        "mode": "blank",
        "novel_type_id": "xuanhuan",
        "idea": "请根据书名《照夜行》和所选小说类型构思故事。",
        "working_title": "照夜行",
    }
    assert master == {
        "schema_version": "story-system-master-setting/v1",
        "project": project,
        "state": state,
    }


def test_create_project_persists_selected_narrative_enhancement_in_project_and_state(tmp_path):
    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(
            mode="blank",
            title="照夜行",
            novel_type_id="xuanhuan",
            narrative_enhancement_ids=["commercial-shuangwen"],
        ),
        project_id_factory=lambda: "p-enhanced",
    )

    expected_skill_ids = ["commercial-shuangwen"]
    expected_module_ids = commercial_shuangwen_module_ids()
    project = read_json(created.root / ".webnovel/project.json")
    state = read_json(created.root / ".webnovel/state.json")
    master = read_json(created.root / ".story-system/MASTER_SETTING.json")

    for payload in (project, state):
        assert payload["enabled_skill_ids"] == expected_skill_ids
        assert payload["enabled_skill_module_ids"] == expected_module_ids
    assert master["project"] == project
    assert master["state"] == state


def test_create_project_rejects_known_enhancement_when_pack_is_missing(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(tmp_path / "missing-skill-packs"))

    with pytest.raises(
        ValueError,
        match=(
            "narrative_enhancement_unavailable:commercial-shuangwen:"
            "skill_pack_missing"
        ),
    ):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(
                mode="blank",
                title="照夜行",
                novel_type_id="xuanhuan",
                narrative_enhancement_ids=["commercial-shuangwen"],
            ),
            project_id_factory=lambda: "p-missing-enhancement",
        )
    assert not (tmp_path / "p-missing-enhancement").exists()


def test_create_project_rejects_incomplete_commercial_shuangwen_pack(
    tmp_path,
    monkeypatch,
):
    pack = SimpleNamespace(
        skill_id="commercial-shuangwen",
        modules=[SimpleNamespace(module_id="plot-engine")],
    )
    monkeypatch.setattr(file_project_creation, "get_skill_pack", lambda _skill_id: pack)

    with pytest.raises(
        ValueError,
        match="narrative_enhancement_incomplete:commercial-shuangwen:missing_modules:",
    ):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(
                mode="blank",
                title="照夜行",
                novel_type_id="xuanhuan",
                narrative_enhancement_ids=["commercial-shuangwen"],
            ),
            project_id_factory=lambda: "p-incomplete-enhancement",
        )
    assert not (tmp_path / "p-incomplete-enhancement").exists()


def test_create_project_rejects_commercial_shuangwen_module_purpose_mismatch(
    tmp_path,
    monkeypatch,
):
    required_purposes = {
        "plot-engine": ["outline"],
        "chapter-sop": ["chapter_plan"],
        "writer-execution": ["writer", "reviewer"],
        "review-checklist": ["reviewer"],
        "genre-examples": ["outline", "chapter_plan", "writer"],
    }
    pack = SimpleNamespace(
        skill_id="commercial-shuangwen",
        modules=[
            SimpleNamespace(module_id=module_id, purposes=purposes)
            for module_id, purposes in required_purposes.items()
        ],
    )
    monkeypatch.setattr(file_project_creation, "get_skill_pack", lambda _skill_id: pack)

    with pytest.raises(
        ValueError,
        match=(
            "narrative_enhancement_incomplete:commercial-shuangwen:"
            "invalid_module_purposes:writer-execution:unexpected=reviewer"
        ),
    ):
        create_file_project(
            tmp_path,
            FileProjectCreateSpec(
                mode="blank",
                title="Purpose Contract",
                novel_type_id="xuanhuan",
                narrative_enhancement_ids=["commercial-shuangwen"],
            ),
            project_id_factory=lambda: "p-purpose-mismatch",
        )
    assert not (tmp_path / "p-purpose-mismatch").exists()


def test_create_project_does_not_enable_pack_root_as_stage_module(tmp_path, monkeypatch):
    stage_module_purposes = {
        "plot-engine": ["outline"],
        "chapter-sop": ["chapter_plan"],
        "writer-execution": ["writer"],
        "review-checklist": ["reviewer"],
        "genre-examples": ["outline", "chapter_plan", "writer"],
    }
    stage_module_ids = list(stage_module_purposes)
    pack = SimpleNamespace(
        skill_id="commercial-shuangwen",
        modules=[
            SimpleNamespace(module_id="root", purposes=[]),
            *(
                SimpleNamespace(module_id=module_id, purposes=purposes)
                for module_id, purposes in stage_module_purposes.items()
            ),
        ],
    )
    monkeypatch.setattr(file_project_creation, "get_skill_pack", lambda _skill_id: pack)

    created = create_file_project(
        tmp_path,
        FileProjectCreateSpec(
            mode="blank",
            title="照夜行",
            novel_type_id="xuanhuan",
            narrative_enhancement_ids=["commercial-shuangwen"],
        ),
        project_id_factory=lambda: "p-no-root-module",
    )

    project = read_json(created.root / ".webnovel/project.json")
    assert project["enabled_skill_module_ids"] == [
        skill_module_key(pack.skill_id, module_id) for module_id in stage_module_ids
    ]


@pytest.mark.parametrize("enhancements", [None, []])
def test_create_spec_omitted_or_empty_narrative_enhancements_stay_disabled(tmp_path, enhancements):
    payload = {
        "mode": "blank",
        "title": "照夜行",
        "novel_type_id": "xuanhuan",
    }
    if enhancements is not None:
        payload["narrative_enhancement_ids"] = enhancements

    spec = FileProjectCreateSpec.model_validate(payload)
    created = create_file_project(
        tmp_path,
        spec,
        project_id_factory=lambda: f"p-disabled-{enhancements is not None}",
    )

    assert spec.narrative_enhancement_ids == []
    for relative_path in (".webnovel/project.json", ".webnovel/state.json"):
        persisted = read_json(created.root / relative_path)
        assert persisted["enabled_skill_ids"] == []
        assert persisted["enabled_skill_module_ids"] == []


def test_create_spec_rejects_unknown_narrative_enhancement():
    with pytest.raises(ValidationError, match="unknown_narrative_enhancement_id:unknown-method"):
        FileProjectCreateSpec(
            mode="blank",
            title="照夜行",
            novel_type_id="xuanhuan",
            narrative_enhancement_ids=["unknown-method"],
        )


def test_create_spec_deduplicates_narrative_enhancements_preserving_order():
    spec = FileProjectCreateSpec(
        mode="blank",
        title="照夜行",
        novel_type_id="xuanhuan",
        narrative_enhancement_ids=[
            " commercial-shuangwen ",
            "commercial-shuangwen",
        ],
    )

    assert spec.narrative_enhancement_ids == ["commercial-shuangwen"]


def test_create_spec_rejects_more_than_eight_narrative_enhancements():
    with pytest.raises(ValidationError, match="too_long"):
        FileProjectCreateSpec(
            mode="blank",
            title="照夜行",
            novel_type_id="xuanhuan",
            narrative_enhancement_ids=["commercial-shuangwen"] * 9,
        )


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
    assert NovelProject.model_validate(project).pipeline_stage == "idea_pending"
    assert NovelProjectSummary.model_validate(project).pipeline_stage == "idea_pending"
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
