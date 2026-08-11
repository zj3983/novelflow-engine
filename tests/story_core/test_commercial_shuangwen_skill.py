from __future__ import annotations

import json
import os
import re
import shutil
from hashlib import sha256
from pathlib import Path
from unittest.mock import Mock

import pytest
from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects as file_project_routes
from apps.api.routes import stories as story_routes
from packages.story_core.candidate_draft import CandidateDraft
from packages.story_core.file_project_creation import (
    FileProjectCreateSpec,
    create_file_project,
)
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.genre_stages.common_writer import writer_skill_trace
from packages.story_core.model_gateway import ModelResponse
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.outline_planning_generation import LLMOutlinePlanningGenerator
from packages.story_core.runtime_config import StageRuntimeSettings
from packages.story_core.skill_packs import (
    extract_skill_instructions,
    get_skill_pack,
    list_skill_packs,
    resolve_enabled_skill_ids,
    skill_module_key,
    skill_pack_prompt_context,
)


PACKS_DIR = Path(__file__).resolve().parents[2] / "data" / "skill-packs"
PACK_DIR = PACKS_DIR / "commercial-shuangwen"
PROTECTED_PROJECT_ENV = "NOVEL_AUTOGROWTH_PROTECTED_PROJECT_ROOT"
GAME_SPECIFIC_MARKERS = (
    "game_webnovel",
    "\u516c\u4f1a\u62bc\u4e0a\u58f0\u671b\u5c01\u9501\u526f\u672c",
    "\u73a9\u5bb6\u8c03\u51fa\u524d\u7ae0\u9996\u901a\u8bb0\u5f55",
)
GENRE_MARKERS = {
    "通用": "审核",
    "game_webnovel": "公会",
    "xuanhuan": "石碑",
    "xianxia": "玉简",
    "urban": "保证金",
    "science_fiction": "维修窗",
}
GENRE_CATEGORY_MARKERS = (
    "宏观循环：",
    "章节细纲：",
    "正面反击：",
    "章末钩子正例：",
    "章末钩子反例：",
    "动作替代心理正例：",
    "抽象心理反例：",
)


def _enable_local_packs(monkeypatch) -> None:
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(PACKS_DIR))


def _protected_project_root(tmp_path: Path) -> Path:
    configured_root = os.environ.get(PROTECTED_PROJECT_ENV, "").strip()
    if configured_root:
        candidate = Path(configured_root)
        assert candidate.is_dir(), f"protected_project_root_missing:{candidate}"
        return candidate.resolve(strict=True)

    sentinel = tmp_path / "protected-project-sentinel"
    sentinel.mkdir()
    (sentinel / "project.json").write_text(
        '{"enabled_skill_ids": []}\n',
        encoding="utf-8",
    )
    return sentinel.resolve(strict=True)


def _content_fingerprint(root: Path) -> str:
    digest = sha256()
    paths = sorted(
        root.rglob("*"),
        key=lambda item: item.relative_to(root).as_posix(),
    )
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_symlink():
            link_target = os.readlink(path).encode("utf-8")
            digest.update(b"L\0" + relative + b"\0" + link_target)
        elif path.is_dir():
            digest.update(b"D\0" + relative + b"\0")
        elif path.is_file():
            digest.update(b"F\0" + relative + b"\0")
            with path.open("rb") as source:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
            digest.update(b"\0")
        else:
            digest.update(b"O\0" + relative + b"\0")
    return digest.hexdigest()


def _checked_project_path(source_path: str, temp_root: Path) -> Path:
    resolved_root = temp_root.resolve(strict=True)
    resolved_project = Path(source_path).resolve(strict=True)
    assert resolved_project != resolved_root
    assert resolved_project.is_relative_to(resolved_root)
    return resolved_project


def _remove_checked_projects(project_paths: list[Path], temp_root: Path) -> None:
    resolved_root = temp_root.resolve(strict=True)
    for project_path in project_paths:
        resolved_project = project_path.resolve(strict=False)
        assert resolved_project != resolved_root
        assert resolved_project.is_relative_to(resolved_root)
        if resolved_project.exists():
            assert resolved_project.is_dir()
            shutil.rmtree(resolved_project)
        assert not resolved_project.exists()
    assert not any(path.is_dir() for path in resolved_root.iterdir())


@pytest.fixture
def isolated_task8_api(tmp_path: Path, monkeypatch):
    _enable_local_packs(monkeypatch)
    temp_root = (tmp_path / "task-8-api-projects").resolve()
    temp_root.mkdir()
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(temp_root))
    legacy_create = Mock(
        side_effect=AssertionError("legacy SQLite project creation called")
    )
    monkeypatch.setattr(story_routes.store, "create_project", legacy_create)

    protected_project_root = _protected_project_root(tmp_path)
    protected_project_before = _content_fingerprint(protected_project_root)
    generated_projects: list[Path] = []
    try:
        with TestClient(app) as client:
            yield client, temp_root, generated_projects, legacy_create
    finally:
        try:
            _remove_checked_projects(generated_projects, temp_root)
        finally:
            assert (
                _content_fingerprint(protected_project_root)
                == protected_project_before
            )


def _joined_instructions(context: list[dict[str, object]]) -> str:
    return "\n".join(
        str(module["instructions"])
        for pack_context in context
        for module in pack_context["modules"]  # type: ignore[index,union-attr]
    )


def _genre_blocks(source: str) -> dict[str, str]:
    headings = list(re.finditer(r"^## \[([^\]]+)\]\s*$", source, flags=re.MULTILINE))
    return {
        match.group(1): source[match.end() : headings[index + 1].start() if index + 1 < len(headings) else None]
        for index, match in enumerate(headings)
    }


def test_commercial_shuangwen_pack_has_exact_stage_modules(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    pack = get_skill_pack("commercial-shuangwen")

    assert pack is not None
    assert pack.skill_id == "commercial-shuangwen"
    assert pack.name == "商业爽文推进"
    assert {module.module_id: module.purposes for module in pack.modules} == {
        "chapter-sop": ["chapter_plan"],
        "genre-examples": ["outline", "chapter_plan", "writer"],
        "plot-engine": ["outline"],
        "review-checklist": ["reviewer"],
        "writer-execution": ["writer"],
    }


def test_pack_contract_limits_scope_and_disables_automatic_actions() -> None:
    manifest = json.loads((PACK_DIR / "manifest.json").read_text(encoding="utf-8"))
    root_skill = (PACK_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert manifest["enabled_by_default"] is False
    assert manifest["scope"] == "narrative_method"
    assert manifest["can_invent_canon"] is False
    assert manifest["requests_automatic_revision"] is False
    assert "只提供叙事方法" in root_skill
    assert "不得虚构正典事实" in root_skill
    assert "不得请求自动修订" in root_skill


def test_outline_extraction_keeps_the_concrete_macro_loop(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    context = skill_pack_prompt_context(
        ["commercial-shuangwen"],
        purpose="outline",
        include_examples=True,
        genre_id="xuanhuan",
    )
    instructions = _joined_instructions(context)

    assert "设局/需求" in instructions
    assert "降维打击" in instructions
    assert "打压/拉仇恨" in instructions
    assert "震惊与收割" in instructions
    assert "主角与读者已知" in instructions
    assert "对手错误认知" in instructions
    assert "误判如何驱动冲突" in instructions
    assert "纠错与回报" in instructions


def test_plot_engine_structure_outputs_operational_information_gap_fields(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)
    pack = get_skill_pack("commercial-shuangwen")
    assert pack is not None
    plot_engine = next(module for module in pack.modules if module.module_id == "plot-engine")
    structure = plot_engine.content.split("## 结构示例", 1)[1]

    for marker in ("主角与读者已知", "对手错误认知", "误判如何驱动冲突", "纠错与回报"):
        assert marker in structure


def test_xuanhuan_context_keeps_only_general_and_xuanhuan_examples(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    context = skill_pack_prompt_context(
        ["commercial-shuangwen"],
        purpose="writer",
        include_examples=True,
        genre_id="xuanhuan",
    )
    instructions = _joined_instructions(context)

    assert "玄幻" in instructions
    assert "石碑" in instructions
    assert "game_webnovel" not in instructions
    assert "网游" not in instructions
    assert "玩家" not in instructions
    assert "副本" not in instructions


def test_every_module_keeps_complete_examples_and_required_sections(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)
    pack = get_skill_pack("commercial-shuangwen")
    assert pack is not None

    for module in pack.modules:
        assert "## 规则" in module.content or "### 规则" in module.content
        assert "## 正例" in module.content or "### 正例" in module.content
        assert "## 反例" in module.content or "### 反例" in module.content
        assert "## 结构示例" in module.content or "### 结构示例" in module.content

    chapter_sop = next(module for module in pack.modules if module.module_id == "chapter-sop")
    instructions = extract_skill_instructions(
        chapter_sop.content,
        limit=5000,
        include_examples=True,
    )
    assert "正例有效，因为" in instructions
    assert "反例失败，因为" in instructions
    assert "担保人" in instructions
    assert "可执行的问题" in instructions
    assert instructions.count("。") >= 10


def test_every_genre_block_contains_all_useful_example_categories() -> None:
    source = (PACK_DIR / "skills" / "genre-examples" / "SKILL.md").read_text(encoding="utf-8")
    blocks = _genre_blocks(source)

    assert set(blocks) == set(GENRE_MARKERS)
    for genre, domain_marker in GENRE_MARKERS.items():
        block = blocks[genre]
        assert domain_marker in block
        for category in GENRE_CATEGORY_MARKERS:
            assert category in block, f"{genre} missing {category}"


def test_genre_category_examples_are_complete_sentences() -> None:
    source = (PACK_DIR / "skills" / "genre-examples" / "SKILL.md").read_text(encoding="utf-8")

    for genre, block in _genre_blocks(source).items():
        category_lines = [
            line.removeprefix("- ").strip()
            for line in block.splitlines()
            if any(line.removeprefix("- ").strip().startswith(marker) for marker in GENRE_CATEGORY_MARKERS)
        ]
        assert len(category_lines) == len(GENRE_CATEGORY_MARKERS), genre
        assert all(line.endswith("。") for line in category_lines), genre
        assert "有效，因为" in block
        assert "失败，因为" in block


def test_installed_pack_is_not_enabled_implicitly(monkeypatch) -> None:
    _enable_local_packs(monkeypatch)

    assert "commercial-shuangwen" in {pack.skill_id for pack in list_skill_packs()}
    assert resolve_enabled_skill_ids({}, {}) == []
    assert skill_pack_prompt_context([], purpose="writer", include_examples=True) == []


CHAPTER_CONTRACT = {
    "payoff_contract": {
        "need": "沈砚必须拿到内门名额",
        "pressure": "周执事只给一炷香验碑",
        "hidden_advantage": "沈砚掌握能点亮第九纹的完整拳路",
        "concrete_reward": "石碑亮起第九纹并登记内门名额",
    },
    "chapter_sop": {
        "opening_carry": "接上周执事扣住名册",
        "mid_feedback": "石碑依次亮起前八纹",
        "turn": "第九纹点亮并映出旧族谱",
        "ending_hook": "族谱缺名指向藏谱阁",
    },
}


def _capture_outline_prompt(store: FileProjectStore) -> dict[str, object]:
    captured: dict[str, object] = {}

    def invalid_local_response(_base_url, _path, payload, _api_key, **_kwargs):
        captured["system"] = payload["messages"][0]["content"]
        captured["context"] = json.loads(payload["messages"][1]["content"])
        return {"choices": [{"message": {"content": "not-json"}}]}

    runtime = StageRuntimeSettings(
        provider_id="deepseek",
        protocol="openai_compatible",
        model="task-8-outline-capture",
        api_key="test-key",
    )
    generator = LLMOutlinePlanningGenerator(
        post_json=invalid_local_response,
        runtime_resolver=lambda _stage: runtime,
    )

    with pytest.raises(ValueError, match="outline_planning_generation_failed"):
        generator.generate(store._planning_brief(), mode="initial")
    return captured


def _workflow_outline(*, enhanced: bool) -> dict[str, object]:
    chapter: dict[str, object] = {
        "chapter_number": 1,
        "title": "石碑第九纹",
        "goal": "沈砚取得内门名额",
        "obstacle": "周执事扣住登记名册",
        "action": "沈砚在石碑前演示完整拳路",
        "turn": "石碑亮起第九纹",
        "payoff": "内门名额登记完成",
        "ending_hook": "石碑映出旧族谱上的缺名",
        "cast": [],
        "scene_chain": [
            {
                "location": "宗门石碑前",
                "pov": "沈砚",
                "goal": "取回登记名册",
                "obstacle": "周执事拒绝登记",
                "action": "沈砚按门规申请当场验碑",
                "change": "周执事被迫开放石碑",
                "next": "沈砚开始演拳",
            },
            {
                "location": "宗门石碑前",
                "pov": "沈砚",
                "goal": "证明拳路完整",
                "obstacle": "石碑前八纹迟迟不稳",
                "action": "沈砚补全最后一式",
                "change": "第九纹亮起",
                "next": "名册重新打开",
            },
            {
                "location": "登记台",
                "pov": "沈砚",
                "goal": "完成内门登记",
                "obstacle": "旧族谱映出缺失姓名",
                "action": "沈砚拓下缺名位置",
                "change": "内门名额落定并出现新线索",
                "next": "沈砚前往藏谱阁",
            },
        ],
    }
    if enhanced:
        chapter.update(CHAPTER_CONTRACT)
    return {
        "overall": {
            "story": "沈砚以完整拳路通过宗门石碑试炼。",
            "ending_direction": "沈砚查清旧族谱被删改的真相。",
        },
        "arcs": [
            {
                "id": "opening",
                "title": "石碑试炼",
                "start_chapter": 1,
                "end_chapter": 1,
                "goal": "取得内门名额",
                "obstacle": "周执事阻止登记",
                "payoff": "名额落定",
            }
        ],
        "chapters": [chapter],
    }


def _capture_production_writer_prompt(
    store: FileProjectStore,
    monkeypatch,
) -> dict[str, object]:
    story = StoryState.model_validate(
        store._story_state_payload_for_direction(
            store.state(),
            store.project(),
            1,
        )
    )
    orchestrator = StoryOrchestrator()
    original_body_prompt = orchestrator._body_prompt
    captured: dict[str, object] = {}

    def capture_body_prompt(current_story, chapter_number, plan):
        context = orchestrator._build_writer_context(
            current_story,
            chapter_number,
            plan,
        )
        captured["plan"] = plan
        captured["skill_context"] = context.skill_context
        captured["prompt"] = original_body_prompt(
            current_story,
            chapter_number,
            plan,
        )
        return captured["prompt"]

    def stop_before_model_body(_story, _prompt, *, agent, **_kwargs):
        if agent == "planner":
            raise AssertionError("saved chapter outline unexpectedly invoked the planner")
        if agent == "writer":
            return "", "task-8 stopped before real chapter generation"
        raise AssertionError(f"unexpected model agent: {agent}")

    monkeypatch.setattr(orchestrator, "_body_prompt", capture_body_prompt)
    monkeypatch.setattr(orchestrator, "_timed_chat", stop_before_model_body)
    orchestrator.generate_next_chapter(story)
    return captured


class _PassingReviewGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def complete_stage(self, stage, request):
        self.calls.append((stage, request))
        checks = {
            key: []
            for key in (
                "goal",
                "pressure",
                "information_gap",
                "counterattack",
                "payoff",
                "reaction",
                "ending_hook",
                "cliches",
            )
        }
        return ModelResponse(
            ok=True,
            text=json.dumps(
                {
                    "schema_version": "skill-review/v1",
                    "skill_id": "commercial-shuangwen",
                    "executed": True,
                    "status": "passed",
                    "summary": "本章合同已兑现。",
                    "checks": checks,
                    "issues": [],
                },
                ensure_ascii=False,
            ),
            provider="test",
            model="task-8-reviewer",
            operation=request.operation,
            request_id="task-8-review-trace",
        )


def _create_prompt_contract_stores(
    tmp_path: Path,
) -> tuple[FileProjectStore, FileProjectStore]:
    project_root = tmp_path / "prompt-contract-projects"
    base_payload = {
        "mode": "blank",
        "title": "Prompt Contract Baseline",
        "novel_type_id": "xuanhuan",
    }
    baseline = create_file_project(
        project_root,
        FileProjectCreateSpec.model_validate(
            {**base_payload, "narrative_enhancement_ids": []}
        ),
        project_id_factory=lambda: "p-prompt-contract-baseline",
    )
    enhanced = create_file_project(
        project_root,
        FileProjectCreateSpec.model_validate(
            {
                **base_payload,
                "title": "Prompt Contract Enhanced",
                "narrative_enhancement_ids": ["commercial-shuangwen"],
            }
        ),
        project_id_factory=lambda: "p-prompt-contract-enhanced",
    )
    return FileProjectStore(baseline.root), FileProjectStore(enhanced.root)


def _seed_pending_candidate(
    store: FileProjectStore,
    *,
    body: str,
    include_contract: bool,
) -> CandidateDraft:
    """Seed the pending candidate that has no public fixture-upload endpoint."""

    submission_payload: dict[str, object] = {
        "chapter_number": 1,
        "chapter_title": "石碑第九纹",
        "body": body,
        "updated_story": store.state(),
        "quality_report": {"ok": True, "issues": []},
    }
    if include_contract:
        submission_payload.update(CHAPTER_CONTRACT)
    candidate = CandidateDraft.create(
        project_id=str(store.project()["project_id"]),
        chapter_number=1,
        chapter_title="石碑第九纹",
        body=body,
        quality_report={"ok": True, "issues": []},
        submission_payload=submission_payload,
    )
    store.candidate_store.save(candidate)
    return candidate


def test_private_prompt_assembly_isolates_commercial_shuangwen_contracts(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_local_packs(monkeypatch)
    baseline_store, enhanced_store = _create_prompt_contract_stores(tmp_path)

    baseline_outline_request = _capture_outline_prompt(baseline_store)
    enhanced_outline_request = _capture_outline_prompt(enhanced_store)
    baseline_context = baseline_outline_request["context"]
    enhanced_context = enhanced_outline_request["context"]
    assert isinstance(baseline_context, dict)
    assert isinstance(enhanced_context, dict)
    assert "skill_context" not in baseline_context
    assert "Skill methods may shape conflict and payoff" not in str(
        baseline_outline_request["system"]
    )
    assert "payoff_contract" not in json.dumps(
        baseline_context["output_schema"],
        ensure_ascii=False,
    )
    outline_skill_context = enhanced_context["skill_context"]["outline"]
    chapter_skill_context = enhanced_context["skill_context"]["chapter_plan"]
    assert [
        module["module_id"]
        for skill in outline_skill_context
        for module in skill["modules"]
    ] == ["genre-examples", "plot-engine"]
    assert [
        module["module_id"]
        for skill in chapter_skill_context
        for module in skill["modules"]
    ] == ["chapter-sop", "genre-examples"]
    enhanced_outline_text = json.dumps(outline_skill_context, ensure_ascii=False)
    assert "审核员怕担责而扣件" in enhanced_outline_text
    assert "周执事押上长老担保" in enhanced_outline_text
    assert "payoff_contract" in json.dumps(
        enhanced_context["output_schema"],
        ensure_ascii=False,
    )
    assert "chapter_sop" in json.dumps(
        enhanced_context["output_schema"],
        ensure_ascii=False,
    )
    assert "Every chapter must include payoff_contract" in " ".join(
        enhanced_context["validation_rules"]
    )

    baseline_store.update_project_outline(_workflow_outline(enhanced=False))
    enhanced_store.update_project_outline(_workflow_outline(enhanced=True))
    baseline_writer = _capture_production_writer_prompt(baseline_store, monkeypatch)
    enhanced_writer = _capture_production_writer_prompt(enhanced_store, monkeypatch)
    baseline_writer_prompt = str(baseline_writer["prompt"])
    enhanced_writer_prompt = str(enhanced_writer["prompt"])
    baseline_writer_modules = writer_skill_trace(baseline_writer["skill_context"])
    enhanced_writer_modules = writer_skill_trace(enhanced_writer["skill_context"])
    assert baseline_writer_modules == []
    assert [module["module_id"] for module in enhanced_writer_modules] == [
        "genre-examples",
        "writer-execution",
    ]
    contract_values = (
        *CHAPTER_CONTRACT["payoff_contract"].values(),
        *CHAPTER_CONTRACT["chapter_sop"].values(),
    )
    for value in contract_values:
        assert value not in baseline_writer_prompt
        assert value in enhanced_writer_prompt
    assert "写清施压者为什么误判" not in baseline_writer_prompt
    assert "写清施压者为什么误判" in enhanced_writer_prompt
    assert "审核员怕担责而扣件" in enhanced_writer_prompt
    assert "周执事押上长老担保" in enhanced_writer_prompt

    for text in (
        json.dumps(baseline_context, ensure_ascii=False),
        json.dumps(enhanced_context, ensure_ascii=False),
        baseline_writer_prompt,
        enhanced_writer_prompt,
    ):
        for marker in GAME_SPECIFIC_MARKERS:
            assert marker not in text


def test_commercial_shuangwen_http_workflow_isolates_creation_and_manual_review(
    isolated_task8_api,
    monkeypatch,
) -> None:
    client, temp_root, generated_projects, legacy_create = isolated_task8_api

    base_payload = {
        "mode": "blank",
        "title": "石碑试炼",
        "novel_type_id": "xuanhuan",
    }
    assert FileProjectCreateSpec.model_validate(base_payload).narrative_enhancement_ids == []
    assert FileProjectCreateSpec.model_validate(
        {**base_payload, "narrative_enhancement_ids": []}
    ).narrative_enhancement_ids == []
    assert skill_pack_prompt_context(
        ["missing-pack"],
        purpose="outline",
        include_examples=True,
        genre_id="xuanhuan",
    ) == []

    baseline_response = client.post(
        "/file-projects",
        json={**base_payload, "narrative_enhancement_ids": []},
    )
    assert baseline_response.status_code == 201, baseline_response.text
    baseline_project = baseline_response.json()
    baseline_root = _checked_project_path(baseline_project["source_path"], temp_root)
    generated_projects.append(baseline_root)

    enhanced_response = client.post(
        "/file-projects",
        json={
            **base_payload,
            "title": "Task 8 Enhanced Xuanhuan",
            "narrative_enhancement_ids": ["commercial-shuangwen"],
        },
    )
    assert enhanced_response.status_code == 201, enhanced_response.text
    enhanced_project = enhanced_response.json()
    enhanced_root = _checked_project_path(enhanced_project["source_path"], temp_root)
    generated_projects.append(enhanced_root)
    assert baseline_root != enhanced_root
    assert {path.name for path in temp_root.iterdir()} == {
        baseline_root.name,
        enhanced_root.name,
    }
    baseline_store = FileProjectStore(baseline_root)
    enhanced_store = FileProjectStore(enhanced_root)
    legacy_create.assert_not_called()

    pack = get_skill_pack("commercial-shuangwen")
    assert pack is not None
    expected_module_ids = [
        skill_module_key(pack.skill_id, module.module_id)
        for module in pack.modules
        if module.module_id != "root"
    ]
    for payload in (baseline_store.project(), baseline_store.state()):
        assert payload["enabled_skill_ids"] == []
        assert payload["enabled_skill_module_ids"] == []
    for payload in (enhanced_store.project(), enhanced_store.state()):
        assert payload["enabled_skill_ids"] == ["commercial-shuangwen"]
        assert payload["enabled_skill_module_ids"] == expected_module_ids

    packet_response = client.get(
        f"/file-projects/{enhanced_root.name}/writing-packet?chapter_number=1"
    )
    assert packet_response.status_code == 200, packet_response.text
    packet_skill_context = packet_response.json().get("skill_context", {})
    assert set(packet_skill_context) == {"writer"}
    packet_modules = [
        module["module_id"]
        for pack_context in packet_skill_context["writer"]
        for module in pack_context.get("modules", [])
    ]
    assert packet_modules == ["genre-examples", "writer-execution"]
    packet_skill_text = json.dumps(packet_skill_context, ensure_ascii=False)
    assert "周执事押上长老担保" in packet_skill_text
    assert "公会押上声望封锁副本" not in packet_skill_text
    assert "review-checklist" not in packet_skill_text

    baseline_outline_response = client.put(
        f"/file-projects/{baseline_root.name}/outline",
        json=_workflow_outline(enhanced=False),
    )
    enhanced_outline_response = client.put(
        f"/file-projects/{enhanced_root.name}/outline",
        json=_workflow_outline(enhanced=True),
    )
    assert baseline_outline_response.status_code == 200, (
        baseline_outline_response.text
    )
    assert enhanced_outline_response.status_code == 200, (
        enhanced_outline_response.text
    )

    confirmed_body = "沈砚补全最后一式，石碑第九纹亮起，周执事重新打开名册。"
    baseline_candidate = _seed_pending_candidate(
        baseline_store,
        body=confirmed_body,
        include_contract=False,
    )
    enhanced_candidate = _seed_pending_candidate(
        enhanced_store,
        body=confirmed_body,
        include_contract=True,
    )
    for project_root, candidate in (
        (baseline_root, baseline_candidate),
        (enhanced_root, enhanced_candidate),
    ):
        confirm_response = client.post(
            f"/file-projects/{project_root.name}/candidates/"
            f"{candidate.candidate_id}/confirm?force=true"
        )
        assert confirm_response.status_code == 200, confirm_response.text
        assert confirm_response.json()["candidate"]["status"] == "confirmed"

    baseline_gateway = _PassingReviewGateway()
    monkeypatch.setattr(
        file_project_routes,
        "shuangwen_model_gateway",
        baseline_gateway,
        raising=False,
    )
    baseline_review_response = client.post(
        f"/file-projects/{baseline_root.name}/chapters/1/skill-reviews/commercial-shuangwen"
    )
    assert baseline_review_response.status_code == 409
    assert (
        baseline_review_response.json()["detail"]
        == "commercial_shuangwen_skill_disabled"
    )
    assert baseline_gateway.calls == []

    review_gateway = _PassingReviewGateway()
    monkeypatch.setattr(
        file_project_routes,
        "shuangwen_model_gateway",
        review_gateway,
        raising=False,
    )
    enhanced_chapter = enhanced_store.chapter(1)
    enhanced_body_path = enhanced_store.root / str(enhanced_chapter["body_path"])
    body_before = enhanced_body_path.read_bytes()
    candidate_hash_before = enhanced_store._candidate_artifacts_hash()
    review_response = client.post(
        f"/file-projects/{enhanced_root.name}/chapters/1/skill-reviews/commercial-shuangwen"
    )
    assert review_response.status_code == 200, review_response.text
    report = review_response.json()
    assert report["executed"] is True
    assert report["status"] == "passed"
    assert report["runtime"] == "test"
    assert report["model"] == "task-8-reviewer"
    assert review_gateway.calls[0][0] == "consistency"
    review_prompt = review_gateway.calls[0][1].prompt
    assert "review-checklist" in review_prompt
    for marker in GAME_SPECIFIC_MARKERS:
        assert marker not in review_prompt
    assert enhanced_body_path.read_bytes() == body_before
    assert enhanced_store.chapter(1)["body"].encode("utf-8") == body_before
    assert enhanced_store._candidate_artifacts_hash() == candidate_hash_before
    assert (
        enhanced_store.review(1)["skill_reviews"]["commercial-shuangwen"]
        == report
    )

    checked_baseline_root = _checked_project_path(str(baseline_root), temp_root)
    shutil.rmtree(checked_baseline_root)
    assert not checked_baseline_root.exists()
