import json
import subprocess

import pytest
from packages.story_core.generation_progress import generation_progress

from packages.story_core.models import CharacterState, StoryState
from packages.story_core import orchestrator as orchestrator_module
from packages.story_core.orchestrator import StoryOrchestrator

_REAL_CHAT = StoryOrchestrator._chat


def test_workflow_character_names_come_from_card_identities():
    payload = {
        "selection": "planned_characters",
        "requested_names": ["苏叶"],
        "cards": [
            {"identity": {"name": "苏叶", "role": "protagonist"}},
            {"identity": {"name": "顾明", "role": "supporting"}},
        ],
    }

    assert orchestrator_module._planning_character_names(payload) == ["苏叶", "顾明"]


@pytest.mark.parametrize(
    "failure",
    [
        RuntimeError("codexcli_failed:boom"),
        subprocess.TimeoutExpired(cmd="codex", timeout=1),
    ],
)
def test_chat_returns_error_tuple_when_cli_provider_fails(monkeypatch, failure):
    from packages.story_core.runtime_config import StageRuntimeSettings

    settings = StageRuntimeSettings(
        provider="codexcli",
        model="codex-model",
        codex_command="codex",
    )
    monkeypatch.setattr(orchestrator_module, "resolve_stage_runtime", lambda stage: settings)

    def _raise(*args, **kwargs):
        raise failure

    monkeypatch.setattr(orchestrator_module, "post_json_with_retry", _raise)

    story = StoryState(
        story_id="s-chat-cli-failure",
        outline="A scribe tests failure handling.",
        genre="fantasy",
        style="noir",
    )
    text, error = _REAL_CHAT(
        StoryOrchestrator(), story, "prompt", max_tokens=16, json_mode=False, stage="写作"
    )

    assert text == ""
    assert "model_request_failed" in error


def test_orchestrator_runs_all_phases_and_returns_bundle():
    story = StoryState(
        story_id="s-orc-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    bundle = StoryOrchestrator().generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.body
    assert bundle.chapter_title
    assert bundle.next_outline
    assert "writing_review" in bundle.quality_report


def test_whole_chapter_writing_is_default_path():
    orchestrator = StoryOrchestrator()

    assert orchestrator._use_segmented_writing(1, {}) is False


def test_segmented_writing_is_disabled_in_production():
    orchestrator = StoryOrchestrator()

    assert orchestrator._use_segmented_writing(1, {"writing_settings": {"use_segmented_writing": True}}) is False


def _post_draft_plan() -> dict:
    return {
        "character_moves": [
            {"name": "林照", "goal": "去东院", "emotion": "愤怒", "action": "搬炉", "priority": 1}
        ],
        "chapter_intent": {"chapter_title": "计划标题", "next_focus": "去东院"},
        "event_plan": {"turn": "计划把炉搬到东院", "next_focus": "去东院", "world_reactions": []},
        "memory_constraints": {
            "ledger_updates": {"protagonist": {"location": "东院", "spirit_stones": 99}}
        },
        "chapter_summary": {
            "summary": "计划中的错误摘要",
            "facts": ["林照得到九十九枚灵石"],
            "unresolved_threads": ["东院的秘密"],
            "next_focus": "去东院",
            "chapter_title": "计划标题",
        },
    }


def _post_draft_memory_payload() -> dict:
    return {
        "summary": "林照把断香炉搬回偏殿，周执事让他明早去账房。",
        "facts": [{"text": "断香炉已搬回偏殿", "evidence": "把断香炉搬回偏殿"}],
        "unresolved_threads": [{"text": "账房为何找林照", "evidence": "明早去账房回话"}],
        "next_focus": "明早去账房",
        "chapter_title": "搬炉",
        "character_updates": [
            {"name": "林照", "goal": "明早去账房", "location": "偏殿", "evidence": "林照把断香炉搬回偏殿"}
        ],
        "ledger_updates": {"protagonist": {"location": "偏殿"}},
        "ledger_evidence": {"protagonist.location": "搬回偏殿"},
    }


def _disable_optional_writing_passes(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": True, "issues": []},
    )


def test_orchestrator_persists_only_memory_extracted_after_final_body(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    monkeypatch.setattr(
        orchestrator_module,
        "apply_simulated_state_deltas",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("simulated delta must not persist")),
    )
    story = StoryState(
        story_id="s-final-memory-order",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", current_emotion="平静", location="祖祠")],
        progression_ledger={"protagonist": {"location": "祖祠"}},
    )
    final_body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"
    calls = []
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage, prompt))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return final_body, ""
        if agent == "memory":
            assert final_body in prompt
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [item[0] for item in calls] == ["planner", "writer", "memory"]
    assert bundle.chapter_summary["facts"] == ["断香炉已搬回偏殿"]
    assert bundle.updated_story.progression_ledger["protagonist"]["location"] == "偏殿"
    assert "spirit_stones" not in bundle.updated_story.progression_ledger["protagonist"]
    assert bundle.updated_story.characters[0].location == "偏殿"
    assert bundle.updated_story.characters[0].current_emotion == "平静"
    assert bundle.chapter_summary["primary_conflict"] == {}
    assert bundle.chapter_summary["secondary_conflict"] == {}
    assert bundle.chapter_summary["event_beat"] == {}
    assert "计划中的错误摘要" not in bundle.updated_story.model_dump_json()
    assert "九十九枚灵石" not in bundle.updated_story.model_dump_json()
    assert bundle.simulation_plan["memory_sync"]["status"] == "ok"
    assert bundle.quality_report["memory_sync"]["status"] == "ok"


def test_orchestrator_retries_director_once_after_invalid_json(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    story = StoryState(
        story_id="s-director-json-retry",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    planner_calls = 0

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        nonlocal planner_calls
        if agent == "planner":
            planner_calls += 1
            if planner_calls == 1:
                return "", "计划返回内容不是有效 JSON"
            assert "上一次返回不是有效 JSON" in prompt
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return "林照把断香炉搬回偏殿。", ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert planner_calls == 2
    assert bundle.body == "林照把断香炉搬回偏殿。"


def test_orchestrator_retries_writer_once_after_empty_body(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    story = StoryState(
        story_id="s-writer-empty-retry",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    writer_calls = 0

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        nonlocal writer_calls
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            writer_calls += 1
            if writer_calls == 1:
                return "", "正文返回为空"
            assert "上一次没有返回正文" in prompt
            return "林照把断香炉搬回偏殿。", ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)

    bundle = orchestrator.generate_next_chapter(story)

    assert writer_calls == 2
    assert bundle.body == "林照把断香炉搬回偏殿。"


def test_orchestrator_memory_failure_uses_body_fallback_without_planned_state(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    monkeypatch.setattr(orchestrator_module, "apply_simulated_state_deltas", lambda *_args, **_kwargs: None)
    story = StoryState(
        story_id="s-final-memory-fallback",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", current_emotion="平静", location="祖祠")],
        progression_ledger={"protagonist": {"location": "祖祠"}},
    )
    final_body = "林照把断香炉搬回偏殿。"
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return final_body, ""
        if agent == "memory":
            return "", "memory unavailable"
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.simulation_plan["memory_sync"]["status"] == "fallback"
    assert bundle.updated_story.progression_ledger["protagonist"]["location"] == "祖祠"
    assert "spirit_stones" not in bundle.updated_story.progression_ledger["protagonist"]
    assert bundle.updated_story.characters[0].location == "祖祠"
    assert bundle.updated_story.characters[0].current_emotion == "平静"
    assert bundle.chapter_summary["summary"] in final_body
    assert bundle.chapter_summary["next_focus"] == ""
    assert bundle.chapter_summary["primary_conflict"] == {}
    assert bundle.chapter_summary["secondary_conflict"] == {}
    assert bundle.chapter_summary["event_beat"] == {}
    assert "计划中的错误摘要" not in bundle.updated_story.model_dump_json()


def test_grounded_memory_without_title_does_not_use_director_conflict_for_title(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    plan = _post_draft_plan()
    plan["character_moves"] = [
        {"name": "夜烬", "goal": "回村补给并购买药水", "emotion": "平静", "action": "回村", "priority": 1}
    ]
    plan["chapter_intent"]["chapter_title"] = "导演计划标题"
    plan["chapter_intent"]["next_focus"] = "回村补给并购买药水"
    plan["event_plan"]["next_focus"] = "回村补给并购买药水"
    body = "夜烬打倒灰狼。"
    memory = {
        "summary": body,
        "facts": [{"text": "夜烬打倒灰狼", "evidence": "夜烬打倒灰狼"}],
        "unresolved_threads": [],
        "next_focus": "",
        "chapter_title": "",
        "character_updates": [],
        "ledger_updates": {},
        "ledger_evidence": {},
    }
    story = StoryState(
        story_id="s-title-from-body-only",
        outline="夜烬在新手村打灰狼。",
        genre="game_webnovel",
        style="白描",
        characters=[CharacterState(name="夜烬", role="主角")],
    )
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(plan, ensure_ascii=False), ""
        if agent == "writer":
            return body, ""
        if agent == "memory":
            return json.dumps(memory, ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.quality_report["memory_sync"]["status"] == "ok"
    assert bundle.chapter_title != "导演计划标题"
    assert bundle.chapter_title != "回村补给"


def test_refresh_revised_bundle_reextracts_memory_from_revised_body(monkeypatch):
    _disable_optional_writing_passes(monkeypatch)
    base_story = StoryState(
        story_id="s-revised-memory",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", current_emotion="平静", location="祖祠")],
        progression_ledger={"protagonist": {"location": "祖祠"}},
    )
    initial_body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"
    orchestrator = StoryOrchestrator()

    def initial_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return initial_body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", initial_chat)
    bundle = orchestrator.generate_next_chapter(base_story)
    bundle.body = "林照把断香炉搬到后院。"
    revised_memory = {
        "summary": "林照把断香炉搬到后院。",
        "facts": [{"text": "断香炉已搬到后院", "evidence": "把断香炉搬到后院"}],
        "unresolved_threads": [],
        "next_focus": "",
        "chapter_title": "后院",
        "character_updates": [
            {"name": "林照", "location": "后院", "evidence": "林照把断香炉搬到后院"}
        ],
        "ledger_updates": {"protagonist": {"location": "后院"}},
        "ledger_evidence": {"protagonist.location": "搬到后院"},
    }

    def revised_chat(_story, prompt, *, agent, stage, **_kwargs):
        assert agent == "memory"
        assert bundle.body in prompt
        return json.dumps(revised_memory, ensure_ascii=False), ""

    monkeypatch.setattr(orchestrator, "_timed_chat", revised_chat)
    refreshed = orchestrator.refresh_revised_bundle_metadata(base_story, bundle)

    assert refreshed.chapter_summary["summary"] == revised_memory["summary"]
    assert refreshed.chapter_summary["facts"] == ["断香炉已搬到后院"]
    assert refreshed.updated_story.characters[0].location == "后院"
    assert refreshed.updated_story.progression_ledger["protagonist"]["location"] == "后院"
    assert refreshed.simulation_plan["memory_sync"]["status"] == "ok"
    assert refreshed.quality_report["memory_sync"]["status"] == "ok"
    assert "偏殿" not in refreshed.chapter_summary["summary"]


def test_memory_extraction_uses_selected_revision_body(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    initial_body = "林照按计划把断香炉留在东院。"
    revised_body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"

    def review(body_chapter, body, *_args, **_kwargs):
        if body == initial_body:
            return {"pass": False, "issues": ["连续性冲突：地点错误"]}
        return {"pass": True, "issues": []}

    monkeypatch.setattr(orchestrator_module, "_review_chapter_body", review)
    monkeypatch.setattr(
        orchestrator_module,
        "choose_best_revision",
        lambda **kwargs: {
            "body": kwargs["candidate_body"],
            "quality": kwargs["candidate_quality"],
            "report": {"selected": "candidate"},
        },
    )
    story = StoryState(
        story_id="s-memory-after-revision",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )
    orchestrator = StoryOrchestrator()
    calls = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer" and "审稿改稿" not in stage:
            return initial_body, ""
        if agent == "writer":
            return revised_body, ""
        if agent == "memory":
            assert revised_body in prompt
            assert initial_body not in prompt
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [item[0] for item in calls] == ["planner", "writer", "writer", "memory"]
    assert bundle.body == revised_body
    assert bundle.chapter_summary["facts"] == ["断香炉已搬回偏殿"]


def test_dialogue_issue_triggers_one_revision_and_learns_only_after_acceptance(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    initial_body = "林照问：“账房？”周执事说：“明早。”"
    revised_body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"

    def review(_chapter, body, *_args, **_kwargs):
        if body == initial_body:
            return {"pass": False, "issues": ["对话不够自然，人物只说短句。"]}
        return {"pass": True, "issues": []}

    monkeypatch.setattr(orchestrator_module, "_review_chapter_body", review)
    story = StoryState(
        story_id="s-dialogue-revision",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )
    orchestrator = StoryOrchestrator()
    calls = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer" and "审稿改稿" not in stage:
            return initial_body, ""
        if agent == "writer":
            return revised_body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [agent for agent, _stage in calls] == ["planner", "writer", "writer", "memory"]
    assert bundle.body == revised_body
    assert bundle.quality_report["revision_safety"]["accepted"] is True
    assert any("已验证改法" in lesson and "对话" in lesson for lesson in bundle.updated_story.writing_lessons)


def test_ordinary_prose_advice_does_not_trigger_revision_or_learning(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    body = "林照把断香炉搬回偏殿。周执事让他明早去账房回话。"
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": False, "issues": ["章末动作还可以更具体。"]},
    )
    story = StoryState(
        story_id="s-prose-advice",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )
    orchestrator = StoryOrchestrator()
    calls = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert [agent for agent, _stage in calls] == ["planner", "writer", "memory"]
    assert "revision_safety" not in bundle.quality_report
    assert bundle.updated_story.writing_lessons == []


def test_unresolved_dialogue_revision_is_rejected_and_not_learned(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)
    body = "林照问：“账房？”周执事说：“明早。”"
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": False, "issues": ["对话不够自然，人物只说短句。"]},
    )
    story = StoryState(
        story_id="s-unresolved-dialogue",
        outline="林照看守断香炉。",
        genre="xuanhuan",
        style="白描",
        characters=[CharacterState(name="林照", role="主角")],
    )
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            return json.dumps(_post_draft_plan(), ensure_ascii=False), ""
        if agent == "writer":
            return body, ""
        if agent == "memory":
            return json.dumps(_post_draft_memory_payload(), ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(story)

    assert bundle.body == body
    assert bundle.quality_report["revision_safety"]["accepted"] is False
    assert bundle.quality_report["revision_safety"]["selected"] == "original"
    assert "accepted_revision_actions" not in bundle.quality_report
    assert bundle.updated_story.writing_lessons == []


def test_progress_artifacts_expose_rewrite_inputs_for_transparency(monkeypatch):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda *_args, **_kwargs: False)

    def review(_chapter, body, *_args, **_kwargs):
        if body == "first draft":
            return {
                "pass": False,
                "issues": ["对话太快，读者抓不到真实反应。"],
                "revision_plan": ["把对话拆成两三句，让主角先停顿。"],
            }
        return {"pass": True, "issues": []}

    monkeypatch.setattr(orchestrator_module, "_review_chapter_body", review)
    story = StoryState(
        story_id="s-progress-rewrite-transparency",
        outline="夜烬在灰烬村第一次试炼失落与秩序。",
        genre="game fantasy",
        style="webnovel",
        characters=[CharacterState(name="夜烬", role="protagonist"), CharacterState(name="洛婶", role="npc")],
    )
    orchestrator = StoryOrchestrator()
    events: list[object] = []

    def fake_timed_chat(_story, prompt, *, agent, stage, **_kwargs):
        if agent == "planner":
            plan = {
                "character_moves": [{"name": "夜烬", "goal": "找到第一条可复盘支线", "emotion": "紧张", "action": "观察"}],
                "chapter_intent": {"chapter_title": "第一章 开局试验", "next_focus": "推进清道夫任务"},
                "event_plan": {"chapter_title": "第一章 开局试验", "next_focus": "推进清道夫任务", "turn": "稳住局面"},
                "memory_constraints": {},
                "chapter_summary": {
                    "summary": "夜烬在灰烬村完成第一次试练。",
                    "facts": ["见习冒险者第一次见到掉落异常"],
                    "unresolved_threads": [],
                    "next_focus": "补足基础生计",
                    "chapter_title": "第一章 开局试验",
                },
            }
            return json.dumps(plan, ensure_ascii=False), ""
        if agent == "writer" and stage.startswith("整章写作"):
            return "first draft", ""
        if agent == "writer" and "审稿改稿" in stage:
            return "revised draft", ""
        if agent == "memory":
            memory = {
                "summary": "夜烬稳住了第一轮输出。",
                "facts": [{"text": "完成第一轮试练", "evidence": "first draft"}],
                "unresolved_threads": [],
                "next_focus": "",
                "chapter_title": "第一章 开局试验",
                "character_updates": [{"name": "夜烬", "current_emotion": "警惕", "location": "灰烬村"}],
                "ledger_updates": {},
                "ledger_evidence": {},
            }
            return json.dumps(memory, ensure_ascii=False), ""
        raise AssertionError(agent)

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    with generation_progress(events.append):
        orchestrator.generate_next_chapter(story)

    dict_steps = [entry for entry in events if isinstance(entry, dict)]
    rewrite_event = next(
        (entry for entry in dict_steps if str(entry.get("message", "")).startswith("审稿改稿中")),
        None,
    )
    assert rewrite_event is not None
    artifact = rewrite_event.get("artifact")
    assert isinstance(artifact, dict), artifact
    inputs = artifact.get("inputs", {})
    assert isinstance(inputs, dict)
    assert "character_cards" in inputs
    assert "outline" in inputs
    assert "writer_plan" in inputs
    assert "review_snapshot" in inputs
    assert isinstance(inputs.get("character_cards"), dict)
    assert inputs.get("outline")

    plan_event = next(
        (entry for entry in dict_steps if str(entry.get("message", "")).startswith("剧情计划生成中")),
        None,
    )
    assert plan_event is not None
    plan_artifact = plan_event.get("artifact")
    assert isinstance(plan_artifact, dict)
    plan_inputs = plan_artifact.get("inputs", {})
    assert "story_outline" in plan_inputs
    assert "character_cards" in plan_inputs
    assert "world_simulation" not in plan_artifact.get("used_modules", [])

    director_done = next(
        (entry for entry in dict_steps if entry.get("message") == "剧情计划生成完成"),
        None,
    )
    assert director_done is not None
    assert "world_simulation" not in director_done["artifact"].get("used_modules", [])
    world_response_done = next(
        (entry for entry in dict_steps if entry.get("message") == "世界响应校验完成"),
        None,
    )
    assert world_response_done is not None
    assert world_response_done["source"] == "world_simulation"

    workflow_steps = {
        entry["artifact"]["workflow_step"]["id"]: entry
        for entry in dict_steps
        if isinstance(entry.get("artifact"), dict)
        and isinstance(entry["artifact"].get("workflow_step"), dict)
    }
    assert [
        step_id
        for step_id in (
            "read_outline",
            "read_characters",
            "read_world_state",
            "director_plan",
            "prepare_scenes",
            "write_body",
            "review_body",
            "write_memory",
        )
        if step_id not in workflow_steps
    ] == []
    assert workflow_steps["read_characters"]["artifact"]["workflow_step"]["reads"]
    assert workflow_steps["director_plan"]["artifact"]["outputs"]
    assert workflow_steps["write_body"]["artifact"]["outputs"]["body_chars"] > 0


def test_workflow_step_reports_explicit_reads_and_outputs():
    orchestrator = StoryOrchestrator()
    events: list[object] = []

    with generation_progress(events.append):
        orchestrator._emit_workflow_step(
            "read_outline",
            "读取大纲",
            status="done",
            source="context_loader",
            used_modules=["outline_agent"],
            reads=["总纲", "第2章细纲", "上一章结尾"],
            outputs={"chapter_goal": "推进灰狼坡任务"},
        )

    assert len(events) == 1
    event = events[0]
    assert isinstance(event, dict)
    assert event["status"] == "done"
    assert event["stage"] == "read_outline"
    artifact = event["artifact"]
    assert artifact["workflow_step"] == {
        "id": "read_outline",
        "label": "读取大纲",
        "reads": ["总纲", "第2章细纲", "上一章结尾"],
    }
    assert artifact["used_modules"] == ["outline_agent"]
    assert artifact["outputs"] == {"chapter_goal": "推进灰狼坡任务"}
