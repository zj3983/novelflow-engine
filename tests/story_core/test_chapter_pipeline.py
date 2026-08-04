from types import SimpleNamespace

from packages.story_core.pipeline.chapter_pipeline import (
    ChapterPipeline,
    build_chapter_pipeline_event,
    chapter_pipeline_stage_order,
)
from packages.story_core.pipeline.context_stage import build_context_stage_events, prepare_chapter_context
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def test_chapter_pipeline_stage_order_skips_world_simulation_when_not_required():
    assert chapter_pipeline_stage_order(run_world_simulation=False) == [
        "context",
        "plan",
        "writing",
        "quality_gate",
        "candidate_output",
    ]


def test_chapter_pipeline_stage_order_never_adds_a_second_plot_stage():
    assert chapter_pipeline_stage_order(run_world_simulation=True) == [
        "context",
        "plan",
        "writing",
        "quality_gate",
        "candidate_output",
    ]


def test_pipeline_event_preserves_detail_step_and_adds_parent_stage_and_model_metadata():
    event = build_chapter_pipeline_event(
        "write_body",
        "写手生成正文",
        status="done",
        source="writer",
        reads=["章节规划", "角色卡"],
        outputs={"body_chars": 3200},
        provider="codexcli",
        model="gpt-5",
    )

    step = event["artifact"]["workflow_step"]
    assert event["stage"] == "write_body"
    assert step["pipeline_stage"] == "writing"
    assert step["reads"] == ["章节规划", "角色卡"]
    assert event["artifact"]["model_call"] == {"provider": "codexcli", "model": "gpt-5"}


def test_chapter_pipeline_wraps_legacy_generator_and_records_effective_stage_order():
    bundle = SimpleNamespace(simulation_plan={"world_simulation_ran": True})
    calls = []

    result = ChapterPipeline().run("story", generate_bundle=lambda story: calls.append(story) or bundle)

    assert result is bundle
    assert calls == ["story"]
    assert result.pipeline_stages == [
        "context",
        "plan",
        "writing",
        "quality_gate",
        "candidate_output",
    ]


def test_story_orchestrator_public_entry_delegates_through_chapter_pipeline(monkeypatch):
    orchestrator = StoryOrchestrator()
    bundle = SimpleNamespace(simulation_plan={"world_simulation_ran": False})
    monkeypatch.setattr(orchestrator, "_generate_next_chapter_bundle", lambda story: bundle)

    result = orchestrator.generate_next_chapter("story")

    assert result is bundle
    assert result.pipeline_stages == ["context", "plan", "writing", "quality_gate", "candidate_output"]


def test_context_stage_assembles_selected_inputs_and_stable_snapshot():
    story = StoryState(
        story_id="context-stage",
        outline="主角进入旧城调查失踪案。",
        current_chapter=1,
        genre="都市",
        style="轻松",
        world_context={"city": {"name": "临江"}},
        author_constraints=["对话自然"],
    )
    director_context = {
        "character_cards": {
            "cards": [{"identity": {"name": "林舟"}}],
            "requested_names": ["林舟"],
        },
        "relationship_graph": {"edges": []},
        "foreshadowing": ["旧城钥匙的来源"],
        "memory_index": [{"summary": "上一章收到匿名短信"}],
    }

    first = prepare_chapter_context(story, 2, director_context)
    second = prepare_chapter_context(story, 2, director_context)

    assert first.character_names == ["林舟"]
    assert first.outline_reads == ["总纲", "第2章细纲", "上一章摘要与结尾"]
    assert first.context_package.sections["world"] == {"city": {"name": "临江"}}
    assert first.context_package.sections["author_request"] == ["对话自然"]
    assert first.context_package.snapshot_id == second.context_package.snapshot_id


def test_context_stage_builds_all_detailed_read_events():
    story = StoryState(
        story_id="context-events",
        outline="调查旧城。",
        genre="都市",
        style="轻松",
        world_context={"city": {}},
        world_facts=["旧城昨夜停电"],
        progression_ledger={"task": "寻找证人"},
    )
    prepared = prepare_chapter_context(
        story,
        1,
        {"character_cards": {"cards": [{"identity": {"name": "林舟"}}]}},
    )

    events = build_context_stage_events(prepared)

    assert [event["stage"] for event in events] == ["read_outline", "read_characters", "read_world_state"]
    assert all(event["artifact"]["workflow_step"]["pipeline_stage"] == "context" for event in events)
    assert events[0]["artifact"]["workflow_step"]["reads"] == ["总纲", "第1章细纲"]
    assert events[2]["artifact"]["outputs"]["context_snapshot_id"] == prepared.context_package.snapshot_id
