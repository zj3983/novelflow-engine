import json

from packages.story_core import orchestrator as orchestrator_module
from packages.story_core.genre_stages.game_webnovel import review as game_review_module
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator, _chapter_char_count, _review_chapter_body


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
    retry_body: str | None = None,
):
    monkeypatch.setattr(orchestrator_module, "_should_expand_chapter", lambda *_args, **_kwargs: False)
    monkeypatch.setattr(
        orchestrator_module,
        "_review_chapter_body",
        lambda *_args, **_kwargs: {"pass": True, "issues": [], "revision_plan": []},
    )
    initial_body = _body("原", 7801)
    calls: list[tuple[str, str, str]] = []
    orchestrator = StoryOrchestrator()

    def fake_timed_chat(_story_state, prompt, *, agent, stage, **_kwargs):
        calls.append((agent, stage, prompt))
        if agent == "planner":
            return json.dumps(_plan(), ensure_ascii=False), ""
        if agent == "writer" and stage.startswith("整章写作"):
            return initial_body, ""
        if agent == "writer" and stage.startswith("章节压缩重试"):
            assert retry_body is not None
            return retry_body, ""
        if agent == "writer" and stage.startswith("章节压缩"):
            return compressed_body, ""
        if agent == "memory":
            return json.dumps(_memory_payload(), ensure_ascii=False), ""
        raise AssertionError((agent, stage))

    monkeypatch.setattr(orchestrator, "_timed_chat", fake_timed_chat)
    bundle = orchestrator.generate_next_chapter(_story(story_id))
    return bundle, calls, initial_body


def test_short_compression_candidate_does_not_retry_under_bounded_flow(monkeypatch):
    """The new bounded flow runs exactly one compression attempt; the
    original body is kept when the candidate is too short."""
    compressed_body = _body("短", 3991)
    retry_body = _body("保", 5300)

    bundle, calls, _initial_body = _run_compression(
        monkeypatch,
        story_id="s-compression-no-retry",
        compressed_body=compressed_body,
        retry_body=retry_body,
    )

    compression_calls = [
        (agent, stage) for agent, stage, _prompt in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    assert len(compression_calls) == 1
    assert compression_calls[0][1] == "章节压缩 第2章 第1轮"
    # No retry stage should fire under the bounded flow.
    assert not any(stage.startswith("章节压缩重试") for _agent, stage, _prompt in calls)
    # The body should be the original, not the short candidate, because
    # the bounded flow keeps the original when compression cannot produce
    # an acceptable result in a single attempt.
    assert _chapter_char_count(bundle.body) == 7801


def test_failed_compression_keeps_original_for_final_length_gate(monkeypatch):
    """Under the bounded flow, compression runs exactly once; if the candidate
    fails the length check, the original body is kept and no retry is
    attempted."""
    bundle, calls, initial_body = _run_compression(
        monkeypatch,
        story_id="s-compression-retry-failure",
        compressed_body=_body("短", 3991),
        retry_body=_body("涨", 8212),
    )

    compression_stages = [
        stage for agent, stage, _prompt in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    assert compression_stages == ["章节压缩 第2章 第1轮"]
    assert not any(stage.startswith("章节压缩重试") for _agent, stage, _prompt in calls)
    assert bundle.body == initial_body
    assert _chapter_char_count(bundle.body) == 7801
    assert "body_too_long" in bundle.quality_report["issues"]


def test_normal_compression_does_not_add_rebalance_call(monkeypatch):
    compressed_body = _body("正", 5000)

    bundle, calls, _initial_body = _run_compression(
        monkeypatch,
        story_id="s-compression-normal-call-count",
        compressed_body=compressed_body,
    )

    compression_stages = [
        stage for agent, stage, _prompt in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    assert compression_stages == ["章节压缩 第2章 第1轮"]
    assert bundle.body == compressed_body


def test_explicit_xuanhuan_context_skips_web_game_review_for_generic_terms(monkeypatch):
    calls = {"web_game": 0}

    def fake_web_game_review(**_kwargs):
        calls["web_game"] += 1
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    monkeypatch.setattr(game_review_module, "review_web_game_chapter", fake_web_game_review)
    body = "宗门任务已列入执事堂系统，弟子等级决定领取顺序。"

    review = _review_chapter_body(
        2,
        body,
        {"next_focus": "完成宗门任务"},
        genre_context={"genre": "xuanhuan", "genre_plugin_ids": ["xuanhuan"]},
    )

    assert calls["web_game"] == 0
    assert review["active_genre_reviews"] == {}
    assert "web_game_review" not in review


def test_review_without_genre_context_does_not_infer_game_from_body(monkeypatch):
    calls = {"web_game": 0}

    def fake_web_game_review(**_kwargs):
        calls["web_game"] += 1
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    monkeypatch.setattr(game_review_module, "review_web_game_chapter", fake_web_game_review)
    body = "宗门任务已列入执事堂系统，弟子等级决定领取顺序。"

    review = _review_chapter_body(2, body, {"next_focus": "完成宗门任务"})

    assert calls["web_game"] == 0
    assert review["active_genre_reviews"] == {}
    assert "web_game_review" not in review


def test_explicit_game_story_state_activates_web_game_review(monkeypatch):
    calls = {"web_game": 0}

    def fake_web_game_review(**_kwargs):
        calls["web_game"] += 1
        return {
            "reviewer": "web_game/test",
            "pass": True,
            "scores": {},
            "issues": [],
            "revision_plan": [],
        }

    monkeypatch.setattr(game_review_module, "review_web_game_chapter", fake_web_game_review)
    game_story = StoryState(
        story_id="explicit-game-review",
        outline="A player enters a persistent online world.",
        genre="game_webnovel",
        genre_plugin_ids=["game_webnovel"],
        style="",
    )

    review = _review_chapter_body(
        2,
        "The protagonist checks the quest system and continues leveling.",
        {"next_focus": "continue the quest"},
        genre_context=game_story,
    )

    assert calls["web_game"] == 1
    assert "web_game_review" in review["active_genre_reviews"]
    assert review["web_game_review"] is review["active_genre_reviews"]["web_game_review"]
