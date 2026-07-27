import json

from packages.story_core import orchestrator as orchestrator_module
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator, _chapter_char_count


def _plan() -> dict:
    return {
        "character_moves": [
            {
                "name": "林照",
                "goal": "查清断香炉异动",
                "emotion": "警惕",
                "action": "检查第三块青砖",
                "priority": 1,
            }
        ],
        "chapter_intent": {"chapter_title": "砖下回声", "next_focus": "查清砖下异物"},
        "event_plan": {
            "ordered_actions": [
                {"name": "林照", "action": "检查第三块青砖"},
            ],
            "chapter_satisfaction": {
                "core_event": "林照确认砖下确有异物",
                "obstacle": "赵管事不许移动供桌",
                "visible_payoff": "砖缝露出一截红线",
                "cost": "赵管事开始留意林照",
                "state_change": "异常范围缩小到第三块青砖",
                "next_hook": "红线另一端突然绷紧",
            },
            "chapter_end_hook": {
                "type": "悬念钩",
                "strength": "strong",
                "content": "红线另一端突然绷紧",
            },
            "next_focus": "查清砖下异物",
        },
    }


def _memory_payload() -> dict:
    return {
        "summary": "林照确认第三块青砖下压着异物。",
        "facts": [{"text": "第三块青砖下压着异物", "evidence": "砖缝里露出红线"}],
        "unresolved_threads": [{"text": "红线连接什么", "evidence": "红线另一端突然绷紧"}],
        "next_focus": "查清红线另一端",
        "chapter_title": "砖下回声",
        "character_updates": [],
        "ledger_updates": {},
        "ledger_evidence": {},
    }


def _body(fill: str, size: int) -> str:
    prefix = "林照检查第三块青砖，砖缝里露出红线，红线另一端突然绷紧。"
    return prefix + fill * (size - len(prefix))


def _story(story_id: str) -> StoryState:
    return StoryState(
        story_id=story_id,
        outline="林照看守祖祠断香炉，逐步查清第三块青砖下的秘密。",
        genre="xuanhuan",
        genre_plugin_ids=["xuanhuan"],
        style="白描",
        current_chapter=1,
        characters=[CharacterState(name="林照", role="主角", location="祖祠")],
    )


def _run_compression(
    monkeypatch,
    *,
    story_id: str,
    compressed_body: str,
    rebalanced_body: str | None = None,
):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": True, "issues": [], "revision_plan": []},
    )
    initial_body = _body("原", 5983)
    calls: list[tuple[str, str]] = []
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story_state, _prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage))
        if agent == "planner":
            return json.dumps(_plan(), ensure_ascii=False), ""
        if agent == "writer" and stage.startswith("整章写作"):
            return initial_body, ""
        if agent == "writer" and stage.startswith("章节压缩回补"):
            assert rebalanced_body is not None
            return rebalanced_body, ""
        if agent == "writer" and stage.startswith("章节压缩"):
            return compressed_body, ""
        if agent == "memory":
            return json.dumps(_memory_payload(), ensure_ascii=False), ""
        raise AssertionError((agent, stage))

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(_story(story_id))
    return bundle, calls


def test_short_compression_candidate_is_rebalanced_once_into_normal_range(monkeypatch):
    rebalanced_body = _body("补", 4300)

    bundle, calls = _run_compression(
        monkeypatch,
        story_id="s-compression-rebalance-success",
        compressed_body=_body("短", 4059),
        rebalanced_body=rebalanced_body,
    )

    compression_stages = [
        stage for agent, stage in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    assert compression_stages == ["章节压缩 第2章 第1轮", "章节压缩回补 第2章"]
    assert bundle.body == rebalanced_body
    assert 4180 <= _chapter_char_count(bundle.body) <= 5700


def test_failed_rebalance_keeps_original_for_final_length_gate(monkeypatch):
    bundle, calls = _run_compression(
        monkeypatch,
        story_id="s-compression-rebalance-failure",
        compressed_body=_body("短", 4059),
        rebalanced_body=_body("仍", 4100),
    )

    compression_stages = [
        stage for agent, stage in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    assert compression_stages == ["章节压缩 第2章 第1轮", "章节压缩回补 第2章"]
    assert _chapter_char_count(bundle.body) == 5983
    assert "body_too_long" in bundle.quality_report["issues"]


def test_normal_compression_does_not_add_rebalance_call(monkeypatch):
    compressed_body = _body("正", 5000)

    bundle, calls = _run_compression(
        monkeypatch,
        story_id="s-compression-normal-call-count",
        compressed_body=compressed_body,
    )

    compression_stages = [
        stage for agent, stage in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    assert compression_stages == ["章节压缩 第2章 第1轮"]
    assert bundle.body == compressed_body
