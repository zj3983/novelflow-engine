from __future__ import annotations

import json
import re
from hashlib import sha256
from pathlib import Path

import pytest

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


def test_commercial_shuangwen_end_to_end_isolates_two_xuanhuan_projects(
    tmp_path: Path,
    monkeypatch,
) -> None:
    _enable_local_packs(monkeypatch)
    project_root = (tmp_path / "isolated-projects").resolve()
    project_root.mkdir()
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(project_root))

    tracked_project_id = "p-da2c16a6ee9440d6ad52cb402ead88a0"
    tracked_guard = tmp_path / "tracked-project-guard" / tracked_project_id
    tracked_guard.mkdir(parents=True)
    tracked_project_path = tracked_guard / "project.json"
    tracked_project_path.write_text(
        json.dumps(
            {
                "project_id": tracked_project_id,
                "enabled_skill_ids": [],
                "enabled_skill_module_ids": [],
            }
        ),
        encoding="utf-8",
    )
    tracked_before = tracked_project_path.read_bytes()

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

    baseline = create_file_project(
        project_root,
        FileProjectCreateSpec.model_validate(
            {**base_payload, "narrative_enhancement_ids": []}
        ),
        project_id_factory=lambda: "p-task8-baseline",
    )
    enhanced = create_file_project(
        project_root,
        FileProjectCreateSpec.model_validate(
            {
                **base_payload,
                "title": "石碑第九纹",
                "narrative_enhancement_ids": ["commercial-shuangwen"],
            }
        ),
        project_id_factory=lambda: "p-task8-enhanced",
    )
    baseline_store = FileProjectStore(baseline.root)
    enhanced_store = FileProjectStore(enhanced.root)

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
    for value in (*CHAPTER_CONTRACT["payoff_contract"].values(), *CHAPTER_CONTRACT["chapter_sop"].values()):
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
        assert "公会押上声望封锁副本" not in text
        assert "玩家调出前章首通记录" not in text

    confirmed_body = "沈砚补全最后一式，石碑第九纹亮起，周执事重新打开名册。"
    for store, include_contract in (
        (baseline_store, False),
        (enhanced_store, True),
    ):
        state = store.state()
        state["current_chapter"] = 1
        store._write_json_atomic(store.webnovel_dir / "state.json", state)
        chapter = {
            "chapter_number": 1,
            "chapter_title": "石碑第九纹",
            "body": confirmed_body,
            "quality_report": {"ok": True, "issues": []},
        }
        if include_contract:
            chapter.update(CHAPTER_CONTRACT)
        store._write_json(
            store.story_system_dir / "chapters" / "0001.json",
            chapter,
        )

    baseline_gateway = _PassingReviewGateway()
    with pytest.raises(ValueError, match="commercial_shuangwen_skill_disabled"):
        baseline_store.run_shuangwen_review(1, model_gateway=baseline_gateway)
    assert baseline_gateway.calls == []

    review_gateway = _PassingReviewGateway()
    body_before = enhanced_store.chapter(1)["body"]
    body_hash_before = sha256(body_before.encode("utf-8")).hexdigest()
    candidate_hash_before = enhanced_store._candidate_artifacts_hash()
    report = enhanced_store.run_shuangwen_review(
        1,
        model_gateway=review_gateway,
    )
    body_after = enhanced_store.chapter(1)["body"]
    assert report["executed"] is True
    assert report["status"] == "passed"
    assert review_gateway.calls[0][0] == "consistency"
    assert "review-checklist" in review_gateway.calls[0][1].prompt
    assert body_after == body_before
    assert sha256(body_after.encode("utf-8")).hexdigest() == body_hash_before
    assert enhanced_store._candidate_artifacts_hash() == candidate_hash_before
    assert (
        enhanced_store.review(1)["skill_reviews"]["commercial-shuangwen"]
        == report
    )

    assert tracked_project_path.read_bytes() == tracked_before
    assert json.loads(tracked_project_path.read_text(encoding="utf-8"))[
        "enabled_skill_ids"
    ] == []
    assert {path.name for path in project_root.iterdir()} == {
        "p-task8-baseline",
        "p-task8-enhanced",
    }
