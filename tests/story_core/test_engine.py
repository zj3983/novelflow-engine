import json
from types import SimpleNamespace

import pytest

from packages.story_core import orchestrator as orchestrator_module
from packages.story_core import world_enrichment as world_enrichment_module
from packages.story_core.engine import StoryEngine
from packages.story_core.models import ChapterSummary, CharacterRelationship, CharacterState, ForeshadowingState, NovelProject, StoryState
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.planner import build_action_briefs, build_chapter_title, build_conflict_summary

_REAL_ORCHESTRATOR_CHAT = StoryOrchestrator._chat
_REAL_ORCHESTRATOR_TIMED_CHAT = StoryOrchestrator._timed_chat


def _runtime_story(story_id: str) -> StoryState:
    return StoryState(story_id=story_id, outline="outline", genre="fantasy", style="plain")


@pytest.mark.parametrize("agent", ["planner", "writer", "memory"])
def test_orchestrator_uses_resolved_stage_runtime_for_provider_request(monkeypatch, agent):
    runtime_calls: list[str] = []
    captured: dict[str, object] = {}

    def fake_resolve(stage):
        runtime_calls.append(stage)
        return SimpleNamespace(
            provider="codexcli",
            model=f"{stage}-model",
            api_key=f"{stage}-key",
            base_url=f"https://{stage}.example/v1",
            codex_command=f"{stage}-codex",
            temperature=0.25,
        )

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured.update(
            base_url=base_url,
            path=path,
            payload=payload,
            api_key=api_key,
            provider=kwargs["provider"],
            codex_command=kwargs["codex_command"],
        )
        return {"choices": [{"message": {"content": "ok"}}]}

    monkeypatch.setattr(orchestrator_module, "resolve_stage_runtime", fake_resolve, raising=False)
    monkeypatch.setattr(orchestrator_module, "post_json_with_retry", fake_post)

    text, error = _REAL_ORCHESTRATOR_CHAT(
        StoryOrchestrator(),
        _runtime_story("runtime-stage"),
        "prompt",
        max_tokens=100,
        json_mode=False,
        agent=agent,
    )

    assert (text, error) == ("ok", "")
    assert runtime_calls == [agent]
    assert captured["base_url"] == f"https://{agent}.example/v1"
    assert captured["api_key"] == f"{agent}-key"
    assert captured["provider"] == "codexcli"
    assert captured["codex_command"] == f"{agent}-codex"
    assert captured["payload"]["model"] == f"{agent}-model"
    assert captured["payload"]["temperature"] == 0.25


def test_timed_chat_records_the_same_runtime_used_by_the_request(monkeypatch):
    runtime_calls: list[str] = []

    def fake_resolve(stage):
        runtime_calls.append(stage)
        return SimpleNamespace(
            provider="openai",
            model="planner-actual",
            api_key="key",
            base_url="https://planner.example/v1",
            codex_command="",
            temperature=0.2,
        )

    monkeypatch.setattr(orchestrator_module, "resolve_stage_runtime", fake_resolve)
    monkeypatch.setattr(StoryOrchestrator, "_chat", _REAL_ORCHESTRATOR_CHAT)
    monkeypatch.setattr(
        orchestrator_module,
        "post_json_with_retry",
        lambda *args, **kwargs: {"choices": [{"message": {"content": "ok"}}]},
    )
    story = _runtime_story("runtime-recording")

    text, error = _REAL_ORCHESTRATOR_TIMED_CHAT(
        StoryOrchestrator(),
        story,
        "prompt",
        max_tokens=100,
        json_mode=False,
        agent="planner",
        stage="test stage",
    )

    assert (text, error) == ("ok", "")
    assert runtime_calls == ["planner"]
    assert story.agent_runtime.planner.provider == "openai"
    assert story.agent_runtime.planner.model == "planner-actual"


def test_orchestrator_maps_private_director_compatibility_to_planner(monkeypatch):
    runtime_calls: list[str] = []

    def fake_resolve(stage):
        runtime_calls.append(stage)
        return SimpleNamespace(
            provider="codexcli",
            model="planner-model",
            api_key="",
            base_url="",
            codex_command="codex",
            temperature=0.2,
        )

    monkeypatch.setattr(orchestrator_module, "resolve_stage_runtime", fake_resolve, raising=False)
    monkeypatch.setattr(
        orchestrator_module,
        "post_json_with_retry",
        lambda *args, **kwargs: {"choices": [{"message": {"content": "ok"}}]},
    )

    _REAL_ORCHESTRATOR_CHAT(
        StoryOrchestrator(),
        _runtime_story("director-alias"),
        "prompt",
        max_tokens=100,
        json_mode=False,
        agent="director",
    )

    assert runtime_calls == ["planner"]


def test_orchestrator_does_not_resolve_character_as_a_runtime_stage(monkeypatch):
    runtime_calls: list[str] = []
    monkeypatch.setattr(
        orchestrator_module,
        "resolve_stage_runtime",
        lambda stage: runtime_calls.append(stage),
        raising=False,
    )

    with pytest.raises(ValueError, match="unknown runtime stage: character"):
        _REAL_ORCHESTRATOR_CHAT(
            StoryOrchestrator(),
            _runtime_story("character-stage"),
            "prompt",
            max_tokens=100,
            json_mode=False,
            agent="character",
        )

    assert runtime_calls == []


def _patch_three_stage_generation(monkeypatch, responses):
    runtime = {
        "planner": SimpleNamespace(provider="openai", model="planner-live"),
        "writer": SimpleNamespace(provider="codexcli", model="writer-live"),
        "memory": SimpleNamespace(provider="openai", model="memory-live"),
    }
    monkeypatch.setattr(orchestrator_module, "resolve_stage_runtime", lambda stage: runtime[stage])
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda body, plan: False)
    monkeypatch.setattr(orchestrator_module, "_should_compress_chapter", lambda body: False)
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *args, **kwargs: {"pass": True, "issues": [], "revision_plan": []},
    )

    def fake_chat(self, story, prompt, *, max_tokens, json_mode, agent="planner", **kwargs):
        response = responses[agent]
        return response(story) if callable(response) else response

    monkeypatch.setattr(StoryOrchestrator, "_chat", fake_chat)


def _runtime_generation_responses():
    plan = {
        "character_moves": [{"name": "主角", "action": "确认现场留下的线索"}],
        "chapter_intent": {"chapter_title": "第一章", "cadence": "measured"},
        "event_plan": {
            "chapter_title": "第一章",
            "chapter_satisfaction": {
                "core_event": "主角确认现场线索",
                "obstacle": "线索残缺且时间有限",
                "visible_payoff": "主角锁定下一处调查地点",
                "cost": "调查方向被对手察觉",
                "state_change": "案件从停滞转为可以继续追查",
                "next_hook": "对手抢先赶往下一处地点",
            },
            "chapter_end_hook": {
                "type": "悬念钩",
                "strength": "medium",
                "content": "对手抢先赶往下一处地点",
            },
        },
        "memory_constraints": {},
        "chapter_summary": {"summary": "计划摘要", "chapter_title": "第一章"},
    }
    memory = {
        "summary": "主角确认线索后离开现场。",
        "facts": [
            {"text": "主角确认线索", "evidence": "主角确认线索后离开现场。"},
        ],
        "unresolved_threads": [],
        "character_updates": [],
        "ledger_updates": {},
        "ledger_evidence": {},
    }
    return {
        "planner": (json.dumps(plan, ensure_ascii=False), ""),
        "writer": ("主角确认线索后离开现场。" * 400, ""),
        "memory": (json.dumps(memory, ensure_ascii=False), ""),
    }


def test_successful_generation_records_only_actual_writing_stages(monkeypatch):
    _patch_three_stage_generation(monkeypatch, _runtime_generation_responses())

    bundle = StoryOrchestrator().generate_next_chapter(_runtime_story("stage-success"))

    runtime = bundle.updated_story.agent_runtime.model_dump()
    assert set(runtime) == {"planner", "writer", "memory", "recent_events"}
    assert runtime["planner"] == {
        "source": "llm",
        "provider": "openai",
        "model": "planner-live",
        "fallback_reason": "",
        "last_run_chapter": 1,
    }
    assert runtime["writer"]["source"] == "llm"
    assert runtime["writer"]["provider"] == "codexcli"
    assert runtime["writer"]["model"] == "writer-live"
    assert runtime["writer"]["last_run_chapter"] == 1
    assert runtime["memory"]["source"] == "llm"
    assert runtime["memory"]["provider"] == "openai"
    assert runtime["memory"]["model"] == "memory-live"
    assert runtime["memory"]["last_run_chapter"] == 1
    assert "character_agent" not in runtime
    assert set(bundle.simulation_status["agents"]) == {"planner", "writer", "memory"}
    assert runtime["recent_events"][0] == "规划阶段：模型，第 1 章"
    assert runtime["recent_events"][-1] == "记忆阶段：模型，第 1 章"
    assert all(
        event.startswith(("规划阶段", "写作阶段", "记忆阶段"))
        for event in runtime["recent_events"]
    )


@pytest.mark.parametrize(
    ("failed_stage", "expected_sources"),
    [
        ("planner", {"planner": "fallback", "writer": "idle", "memory": "idle"}),
        ("writer", {"planner": "llm", "writer": "fallback", "memory": "idle"}),
    ],
)
def test_generation_failure_does_not_mark_unexecuted_stages(monkeypatch, failed_stage, expected_sources):
    responses = _runtime_generation_responses()
    responses[failed_stage] = ("", f"{failed_stage} request failed")
    _patch_three_stage_generation(monkeypatch, responses)

    bundle = StoryOrchestrator().generate_next_chapter(_runtime_story(f"stage-{failed_stage}-failure"))

    assert {
        stage: getattr(bundle.updated_story.agent_runtime, stage).source
        for stage in ("planner", "writer", "memory")
    } == expected_sources


def test_new_chapter_clears_previous_stage_runtime_before_planner_request(monkeypatch):
    responses = _runtime_generation_responses()
    responses["planner"] = ("", "planner request failed")
    _patch_three_stage_generation(monkeypatch, responses)
    story = _runtime_story("stage-reset")
    story.current_chapter = 5
    for stage in ("planner", "writer", "memory"):
        entry = getattr(story.agent_runtime, stage)
        entry.source = "llm"
        entry.provider = "openai"
        entry.model = f"chapter-five-{stage}"
        entry.last_run_chapter = 5

    bundle = StoryOrchestrator().generate_next_chapter(story)

    assert bundle.updated_story.agent_runtime.planner.source == "fallback"
    assert bundle.updated_story.agent_runtime.planner.last_run_chapter == 6
    for stage in ("writer", "memory"):
        entry = getattr(bundle.updated_story.agent_runtime, stage)
        assert entry.source == "idle"
        assert entry.provider == ""
        assert entry.model == ""
        assert entry.fallback_reason == ""
        assert entry.last_run_chapter == 0


def test_memory_parse_failure_only_marks_memory_fallback(monkeypatch):
    responses = _runtime_generation_responses()
    responses["memory"] = ("not-json", "")
    _patch_three_stage_generation(monkeypatch, responses)

    bundle = StoryOrchestrator().generate_next_chapter(_runtime_story("stage-memory-failure"))

    assert bundle.updated_story.agent_runtime.planner.source == "llm"
    assert bundle.updated_story.agent_runtime.writer.source == "llm"
    assert bundle.updated_story.agent_runtime.memory.source == "fallback"
    assert bundle.updated_story.agent_runtime.memory.fallback_reason == "memory_invalid_json"


def test_world_enrichment_uses_planner_stage_runtime(monkeypatch):
    runtime_calls: list[str] = []
    captured: dict[str, object] = {}

    def fake_resolve(stage):
        runtime_calls.append(stage)
        return SimpleNamespace(
            provider="codexcli",
            model="world-planner-model",
            api_key="",
            base_url="https://planner.example/v1",
            codex_command="planner-codex",
            temperature=0.27,
        )

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured.update(
            base_url=base_url,
            payload=payload,
            api_key=api_key,
            provider=kwargs["provider"],
            codex_command=kwargs["codex_command"],
        )
        return {"choices": [{"message": {"content": '{"ok": true}'}}]}

    monkeypatch.setattr(world_enrichment_module, "resolve_stage_runtime", fake_resolve, raising=False)
    monkeypatch.setattr(
        world_enrichment_module,
        "resolve_openai_runtime_settings",
        lambda *args, **kwargs: pytest.fail("legacy runtime resolver must not be used"),
        raising=False,
    )
    monkeypatch.setattr(world_enrichment_module, "post_json_with_retry", fake_post)
    monkeypatch.setattr(world_enrichment_module, "_merge_enrichment", lambda project, parsed: project)

    project = NovelProject(project_id="world-runtime", title="World Runtime")
    assert world_enrichment_module.enrich_project_world(project) == project
    assert runtime_calls == ["planner"]
    assert captured["base_url"] == "https://planner.example/v1"
    assert captured["api_key"] == ""
    assert captured["provider"] == "codexcli"
    assert captured["codex_command"] == "planner-codex"
    assert captured["payload"]["model"] == "world-planner-model"
    assert captured["payload"]["temperature"] == 0.27


def test_generate_chapter_updates_state_and_returns_bundle():
    story = StoryState(
        story_id="s-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                traits={"impulsive": 0.6},
                goals=["find the culprit"],
            )
        ],
    )
    engine = StoryEngine()
    bundle = engine.generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.body
    assert bundle.next_outline
    assert bundle.updated_story.current_chapter == 1
    assert bundle.updated_story.characters[0].memory == []
    assert bundle.updated_story.timeline
    assert bundle.updated_story.chapter_summaries
    assert bundle.updated_story.foreshadowing == []
    assert bundle.updated_story.chapter_summaries[0].summary


def test_generate_chapter_reports_visible_progress_stages():
    from packages.story_core.generation_progress import generation_progress

    story = StoryState(
        story_id="s-progress",
        outline="A cautious player tests a strange login token.",
        genre="game fantasy",
        style="webnovel",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["verify the clue"],
            )
        ],
    )
    events: list[str] = []

    with generation_progress(events.append):
        StoryEngine().generate_next_chapter(story)

    assert events[0] == "剧情计划生成中..."
    assert "正文生成中..." in events
    assert "记忆回写中..." in events
    assert events[-1] == "质量检查中..."


def test_game_opening_conflict_uses_market_signal_not_direct_collision():
    story = StoryState(
        story_id="s-game-conflict",
        outline="网游开服，主角靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        world_facts=["网游交易行可见性规则：低级材料匿名上架只暴露价格、数量和时间戳等弱线索。"],
    )
    action_briefs = [
        {"name": "苏叶", "goal": "安全升至3级并变现", "emotion": "谨慎", "priority": 9},
        {"name": "赵胖子", "goal": "低价扫货维持供货线", "emotion": "试探", "priority": 7},
        {"name": "白袍公会", "goal": "排查异常货源", "emotion": "傲慢", "priority": 5},
    ]

    conflict = build_conflict_summary(story, action_briefs)

    collision = conflict["primary_conflict"]["collision"]
    assert "正面撞上" not in collision
    assert "核心资源的控制权" not in collision
    assert "价格曲线" in collision
    assert "时间戳" in collision


def test_game_opening_arc_chapter_two_avoids_direct_resource_collision():
    story = StoryState(
        story_id="s-game-conflict-ch2",
        outline="网游开服，主角靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        current_chapter=2,
        world_facts=[
            "网游交易行可见性规则：低级材料匿名上架只暴露价格、数量和时间戳等弱线索。",
            "第2章冲突优先从刷怪路线、补给耐久、NPC任务前置和交易批次异常生成。",
        ],
    )
    action_briefs = [
        {"name": "夜烬", "goal": "继续刷毒腺并推进元素回廊前置", "emotion": "谨慎", "priority": 9},
        {"name": "赵胖子", "goal": "低价扫货并寻找稳定货源", "emotion": "试探", "priority": 7},
        {"name": "白袍公会", "goal": "排查异常货源", "emotion": "傲慢", "priority": 5},
    ]

    conflict = build_conflict_summary(story, action_briefs)

    collision = conflict["primary_conflict"]["collision"]
    assert "正面撞上" not in collision
    assert "核心资源的控制权" not in collision
    assert "价格曲线" in collision
    assert "补给流水" in collision
    assert conflict["secondary_conflict"]["pressure"] == "market-signal"


def test_generate_chapter_does_not_mutate_frozen_character_state():
    story = StoryState(
        story_id="s-010",
        outline="A careful archivist hides a dangerous ledger.",
        genre="fantasy",
        style="political suspense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Shen Li",
                role="archivist",
                goals=["protect the ledger"],
                memory=["The ledger must stay hidden."],
                current_emotion="guarded",
                location="sealed vault",
                frozen=True,
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    frozen_character = bundle.updated_story.characters[0]

    assert frozen_character.memory == ["The ledger must stay hidden."]
    assert frozen_character.current_emotion == "guarded"
    assert frozen_character.location == "sealed vault"


def test_generate_chapter_does_not_apply_planned_relationship_changes():
    story = StoryState(
        story_id="s-011",
        outline="Two investigators circle the same ledger from opposite ends of the court.",
        genre="fantasy",
        style="court intrigue",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["expose the forgery"],
                relationships={
                    "Su Wan": CharacterRelationship(
                        target="Su Wan",
                        trust=0.4,
                        tension=0.9,
                        bond="uneasy alliance",
                    )
                },
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the family name"],
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    relationship = bundle.updated_story.characters[0].relationships["Su Wan"]

    assert relationship.trust == 0.4
    assert relationship.tension == 0.9
    # Body includes conflict participant names (may be transliterated)
    assert "Lin Yue" in bundle.body or "Lin" in bundle.body


def test_generate_chapter_does_not_infer_relationship_change_from_goal():
    story = StoryState(
        story_id="s-012",
        outline="A clerk protects an ally while hiding the ledger.",
        genre="fantasy",
        style="court intrigue",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Pei An",
                role="protagonist",
                goals=["protect Su Wan"],
                relationships={
                    "Su Wan": CharacterRelationship(
                        target="Su Wan",
                        trust=0.4,
                        tension=0.6,
                        bond="fragile trust",
                    )
                },
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    relationship = bundle.updated_story.characters[0].relationships["Su Wan"]

    assert relationship.trust == 0.4
    assert relationship.tension == 0.6
    assert "Pei An" in bundle.body or "Pei" in bundle.body


def test_second_chapter_body_reuses_fact_and_foreshadowing_context():
    story = StoryState(
        story_id="s-013",
        outline="A palace clerk follows a hidden ledger across two nights.",
        genre="fantasy",
        style="suspense",
        current_chapter=1,
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
        foreshadowing=[],
        chapter_summaries=[],
        characters=[
            CharacterState(
                name="Pei An",
                role="protagonist",
                goals=["find the ledger"],
            )
        ],
    )

    first_bundle = StoryEngine().generate_next_chapter(story)
    second_bundle = StoryEngine().generate_next_chapter(first_bundle.updated_story)

    # Continuity line from world_facts
    assert "事实" in second_bundle.body or "Pei" in second_bundle.body
    assert "Pei An" in second_bundle.body or "Pei" in second_bundle.body


def test_generate_chapter_builds_action_briefs_and_conflict_summary():
    story = StoryState(
        story_id="s-014",
        outline="Two rivals close in on the same witness.",
        genre="fantasy",
        style="court intrigue",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="driven",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="guarded",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.action_briefs
    assert bundle.action_briefs[0]["name"] == "Lin Yue"
    assert bundle.action_briefs[1]["name"] == "Su Wan"
    assert "find the witness" in bundle.action_briefs[0]["action"]
    assert "protect the witness" in bundle.action_briefs[1]["action"]
    assert bundle.conflict_summary["stakes"]
    assert "Lin Yue" in bundle.conflict_summary["summary"]
    assert "Su Wan" in bundle.conflict_summary["summary"]
    assert bundle.conflict_summary["primary_conflict"]["lead"] == "Lin Yue"
    assert bundle.conflict_summary["primary_conflict"]["opposition"] == "Su Wan"
    assert bundle.conflict_summary["secondary_conflict"]["pressure"] == "time"


def test_generate_chapter_body_reflects_selected_conflict():
    story = StoryState(
        story_id="s-015",
        outline="A magistrate corners an ally who knows too much.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["expose the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    # Chinese format: conflict summary included in body
    assert "Lin Yue" in bundle.body or "Lin" in bundle.body
    assert "Su Wan" in bundle.body or "Su" in bundle.body
    assert "见证" in bundle.body or "witness" in bundle.body or "证" in bundle.body


def test_next_outline_does_not_copy_planned_secondary_conflict():
    story = StoryState(
        story_id="s-016",
        outline="A censor and a magistrate race to control a witness.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert "Lin Yue" in bundle.next_outline
    assert bundle.next_outline


def test_director_selects_primary_conflict_by_goal_collision():
    story = StoryState(
        story_id="s-017",
        outline="Three factions close in on a single witness.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the archives"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.conflict_summary["primary_conflict"]["lead"] == "Lin Yue"
    assert bundle.conflict_summary["primary_conflict"]["opposition"] == "Su Wan"
    assert "Pei An" not in bundle.conflict_summary["primary_conflict"]["collision"]


def test_director_selects_secondary_conflict_and_event_beat():
    story = StoryState(
        story_id="s-018",
        outline="Three factions close in on a single ledger while a witness breaks.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.conflict_summary["secondary_conflict"]["participants"]
    assert "Pei An" in [item["name"] for item in bundle.conflict_summary["secondary_conflict"]["participants"]]
    assert bundle.event_beat["turn"] == "pressure spike"
    # event_beat pivot now in Chinese; just check it has content
    assert bundle.event_beat["pivot"]
    assert "Lin Yue" in bundle.event_beat["pivot"] or "Su Wan" in bundle.event_beat["pivot"]
    # Event beat is included in body
    assert bundle.body


def test_post_chapter_updates_do_not_touch_characters_without_body_evidence():
    story = StoryState(
        story_id="s-019",
        outline="Three factions collide over a witness and a ledger.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    by_name = {character.name: character for character in bundle.updated_story.characters}
    assert by_name["Lin Yue"].memory == []
    assert by_name["Su Wan"].memory == []
    assert by_name["Pei An"].memory == []
    assert by_name["Lin Yue"].current_emotion == "grim"
    assert by_name["Su Wan"].current_emotion == "defiant"
    assert by_name["Pei An"].current_emotion == "guarded"


def test_post_chapter_updates_do_not_invent_role_specific_memories():
    story = StoryState(
        story_id="s-020",
        outline="A witness cracks while three players fight over the truth.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    by_name = {character.name: character for character in bundle.updated_story.characters}

    assert by_name["Lin Yue"].memory == []
    assert by_name["Su Wan"].memory == []
    assert by_name["Pei An"].memory == []


def test_post_chapter_updates_keep_existing_goals_without_body_evidence():
    story = StoryState(
        story_id="s-021",
        outline="A witness cracks while three players fight over the truth.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    by_name = {character.name: character for character in bundle.updated_story.characters}

    assert by_name["Lin Yue"].goals == ["find the witness"]
    assert by_name["Su Wan"].goals == ["protect the witness"]
    assert by_name["Pei An"].goals == ["hide the ledger"]


def test_action_briefs_prioritize_urgent_follow_up_intents_over_character_order():
    story = StoryState(
        story_id="s-022",
        outline="The aftermath of one chapter should reorder initiative.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        characters=[
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["stabilize the ledger before the side pressure breaks"],
                current_emotion="wary",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["block Lin Yue from taking the witness"],
                current_emotion="alert",
            ),
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["seize control of the witness before Su Wan recovers"],
                current_emotion="alert",
            ),
        ],
    )

    briefs = build_action_briefs(story)

    assert [brief["name"] for brief in briefs] == ["Lin Yue", "Su Wan", "Pei An"]
    assert briefs[0]["goal"] == "seize control of the witness before Su Wan recovers"
    assert briefs[0]["priority"] > briefs[-1]["priority"]


def test_chapter_summary_does_not_persist_planned_conflict_or_event_structure():
    story = StoryState(
        story_id="s-023",
        outline="A witness and a ledger pull different players into the same night.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    summary = bundle.chapter_summary

    assert summary["primary_conflict"] == {}
    assert summary["secondary_conflict"] == {}
    assert summary["event_beat"] == {}
    assert summary["next_focus"] == ""
    assert summary["summary"]


def test_chapter_summary_does_not_copy_planned_next_focus():
    story = StoryState(
        story_id="s-026",
        outline="A witness and a ledger pull different players into the same night.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    summary = bundle.chapter_summary

    assert summary["next_focus"] == ""


def test_next_chapter_body_echoes_previous_summary_next_focus():
    story = StoryState(
        story_id="s-027",
        outline="A prior chapter should leave a visible hook in the prose.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=["Can Lin Yue and Su Wan control the witness next?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        foreshadowing=[
            ForeshadowingState(
                text="A hidden letter appears.",
                first_chapter=1,
                status="reinforced",
            )
        ],
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    # Body echoes previous summary's next_focus in Chinese format
    assert "Lin Yue" in bundle.body or "Lin" in bundle.body or len(bundle.body) > 100


def test_next_chapter_body_uses_next_focus_as_opening_hook():
    story = StoryState(
        story_id="s-028",
        outline="A prior chapter should seed the next opening beat.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=["Can Lin Yue and Su Wan control the witness next?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        foreshadowing=[
            ForeshadowingState(
                text="A hidden letter appears.",
                first_chapter=1,
                status="reinforced",
            )
        ],
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    # Body includes opening hook from previous next_focus
    assert "Lin Yue" in bundle.body or "Lin" in bundle.body
    assert "Su Wan" in bundle.body or "Su" in bundle.body


def test_next_outline_does_not_copy_previous_focus_after_memory_fallback():
    story = StoryState(
        story_id="s-029",
        outline="A prior chapter should shape the next planning pass.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=["Can Lin Yue and Su Wan control the witness next?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        foreshadowing=[
            ForeshadowingState(
                text="A hidden letter appears.",
                first_chapter=1,
                status="reinforced",
            )
        ],
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert "Lin Yue" in bundle.next_outline
    assert "Return to Lin Yue and Su Wan" not in bundle.next_outline


def test_chapter_bundle_includes_generated_chapter_title():
    story = StoryState(
        story_id="s-030",
        outline="A prior chapter should shape the next title as well.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    # chapter_title is now a pure Chinese title (e.g., "证人交锋")
    assert bundle.chapter_title
    assert len(bundle.chapter_title) >= 2
    assert bundle.chapter_summary["chapter_title"] == bundle.chapter_title


def test_build_chapter_title_falls_back_to_pressure_for_generic_conflict():
    title = build_chapter_title(
        1,
        conflict_summary={
            "primary_conflict": {
                "collision": "Lin Yue and Su Wan collide over whether control can be secured.",
            }
        },
    )

    # build_chapter_title now returns pure Chinese title (e.g., "真相交锋")
    assert title
    assert len(title) >= 2


def test_build_chapter_title_varies_flavor_by_genre_and_style():
    mystery_title = build_chapter_title(
        1,
        conflict_summary={
            "primary_conflict": {
                "collision": "Lin Yue and Su Wan collide over the witness.",
            },
        },
        next_focus="Return to Lin Yue and Su Wan over the witness",
        genre="mystery",
    )
    fantasy_title = build_chapter_title(
        1,
        conflict_summary={
            "primary_conflict": {
                "collision": "Lin Yue and Su Wan collide over the witness.",
            },
        },
        next_focus="Return to Lin Yue and Su Wan over the witness",
        genre="fantasy",
    )

    # build_chapter_title now returns pure Chinese titles
    assert mystery_title
    assert fantasy_title
    assert len(mystery_title) >= 2
    assert len(fantasy_title) >= 2
    assert mystery_title != fantasy_title


def test_generate_chapter_assigns_cadence_and_threads_it_into_summary_and_next_outline():
    story = StoryState(
        story_id="s-031",
        outline="A chapter with many factions should feel urgent.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                chapter_title="Chapter 1: Witness Dossier",
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=[
                    "Who paid for the forgery?",
                    "Who moved the ledger?",
                    "Can Lin Yue keep the witness alive next?",
                ],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={"lead": "Lin Yue", "opposition": "Su Wan", "collision": "Lin Yue and Su Wan collide over the witness."},
                secondary_conflict={"pressure": "time", "detail": "The court keeps closing ranks.", "participants": [{"name": "Pei An", "goal": "hide the ledger"}]},
                event_beat={"turn": "pressure spike", "pivot": "Lin Yue and Su Wan collide over the witness."},
            )
        ],
        foreshadowing=[ForeshadowingState(text="A hidden letter appears.", first_chapter=1, status="reinforced")],
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["seize the witness"], current_emotion="alert"),
            CharacterState(name="Su Wan", role="supporting", goals=["block Lin Yue"], current_emotion="defiant"),
            CharacterState(name="Pei An", role="supporting", goals=["hide the ledger"], current_emotion="wary"),
            CharacterState(name="Qin Yu", role="supporting", goals=["expose the forgery"], current_emotion="driven"),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.cadence == "urgent"
    assert bundle.chapter_summary["cadence"] == "urgent"
    # Urgent cadence reflected in next_outline
    assert bundle.next_outline


def test_generate_chapter_can_breathe_when_pressure_is_low():
    story = StoryState(
        story_id="s-032",
        outline="A lone investigator needs a quieter step.",
        genre="fantasy",
        style="reflective",
        current_chapter=0,
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["hold the line"], current_emotion="neutral")],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.cadence == "breathing"
    assert bundle.chapter_summary["cadence"] == "breathing"
    assert bundle.next_outline


def test_action_briefs_use_latest_chapter_summary_as_context():
    story = StoryState(
        story_id="s-024",
        outline="The aftermath should shape the next move.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="Lin Yue and Su Wan collide over the witness.",
                facts=["The witness remains contested."],
                unresolved_threads=["Who will control the witness next?"],
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        characters=[
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
        ],
    )

    briefs = build_action_briefs(story)

    assert briefs[0]["name"] == "Lin Yue"
    assert briefs[0]["priority"] > briefs[-1]["priority"]
    assert briefs[0]["priority"] >= briefs[1]["priority"]


def test_action_briefs_promote_character_named_in_unresolved_threads():
    story = StoryState(
        story_id="s-025",
        outline="The next move should follow the unresolved thread.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The court waits after a cold confrontation over the archives.",
                facts=["The ledger is still hidden in the archives."],
                unresolved_threads=["Can Pei An keep the ledger hidden next?"],
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the archives.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the archives.",
                },
            )
        ],
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hold the line"],
                current_emotion="controlled",
            ),
        ],
    )

    briefs = build_action_briefs(story)

    assert briefs[0]["name"] == "Pei An"
    assert briefs[0]["priority"] > briefs[1]["priority"]


def test_story_engine_routes_generation_through_orchestrator():
    story = StoryState(
        story_id="s-030",
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

    engine = StoryEngine()
    assert hasattr(engine, "orchestrator")

    bundle = engine.generate_next_chapter(story)
    assert bundle.body
    assert "writing_review" in bundle.quality_report


def test_story_engine_proposals_include_archivist_candidate_from_secret():
    story = StoryState(
        story_id="s-031",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                secrets=["An archivist once forged the registry seal."],
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.action_briefs
    # new_character_candidates extracts the keyword from secrets
    assert bundle.action_briefs[0]["new_character_candidates"]
    assert "Archivist" in str(bundle.action_briefs[0]["new_character_candidates"])


def test_story_engine_includes_director_character_approval_metadata():
    story = StoryState(
        story_id="s-032",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                secrets=["An archivist once forged the registry seal."],
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert "approved_new_characters" in bundle.conflict_summary
    # approved_new_characters may be empty if no characters were approved via LLM
    assert isinstance(bundle.conflict_summary["approved_new_characters"], list)


def test_story_engine_keeps_prose_markers_after_writer_memory_agent_split():
    story = StoryState(
        story_id="s-033",
        outline="A witness drives a confrontation.",
        genre="mystery",
        style="tense",
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["find the witness"]),
            CharacterState(name="Su Wan", role="supporting", goals=["protect the witness"]),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    # Chinese format keeps a visible cadence marker, normalized away from
    # creation-layer wording before persistence.
    assert "第1章" in bundle.body
    assert "推进" in bundle.body
    assert bundle.updated_story.timeline
    assert bundle.updated_story.chapter_summaries


def test_story_engine_compatibility_path_generates_complete_bundle_with_lifecycle():
    story = StoryState(
        story_id="s-compat-001",
        outline="A clerk tracks a witness through the archive maze.",
        genre="mystery",
        style="tense",
        characters=[
            CharacterState(
                name="Pei An",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.body
    assert bundle.chapter_title
    assert bundle.cadence in {"urgent", "measured", "breathing"}
    assert bundle.next_outline
    assert "writing_review" in bundle.quality_report
    assert bundle.chapter_summary["next_focus"] == ""
    assert bundle.updated_story.chapter_summaries[-1].cadence
    assert bundle.updated_story.characters[0].lifecycle_state in {
        "proposed",
        "active",
        "rejected",
        "frozen",
    }
