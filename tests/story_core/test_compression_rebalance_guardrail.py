import json

from packages.story_core import orchestrator as orchestrator_module
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


def test_short_compression_candidate_retries_from_original_into_normal_range(monkeypatch):
    compressed_body = _body("短", 3991)
    retry_body = _body("保", 5300)

    bundle, calls, initial_body = _run_compression(
        monkeypatch,
        story_id="s-compression-retry-success",
        compressed_body=compressed_body,
        retry_body=retry_body,
    )

    compression_stages = [
        stage for agent, stage, _prompt in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    retry_prompt = next(prompt for agent, stage, prompt in calls if agent == "writer" and stage.startswith("章节压缩重试"))
    assert compression_stages == ["章节压缩 第2章 第1轮", "章节压缩重试 第2章"]
    assert initial_body in retry_prompt
    assert compressed_body not in retry_prompt
    assert "上次压缩到3991字" in retry_prompt
    assert "保留更多" in retry_prompt
    assert "正常范围4200到5500字" in retry_prompt
    assert "建议5200到5500字" in retry_prompt
    assert bundle.body == retry_body
    assert 4200 <= _chapter_char_count(bundle.body) <= 5500


def test_failed_compression_retry_keeps_original_for_final_length_gate(monkeypatch):
    bundle, calls, initial_body = _run_compression(
        monkeypatch,
        story_id="s-compression-retry-failure",
        compressed_body=_body("短", 3991),
        retry_body=_body("涨", 8212),
    )

    compression_stages = [
        stage for agent, stage, _prompt in calls if agent == "writer" and stage.startswith("章节压缩")
    ]
    assert compression_stages == ["章节压缩 第2章 第1轮", "章节压缩重试 第2章"]
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

    monkeypatch.setattr(orchestrator_module, "review_web_game_chapter", fake_web_game_review)
    body = "宗门任务已列入执事堂系统，弟子等级决定领取顺序。"

    review = _review_chapter_body(
        2,
        body,
        {"next_focus": "完成宗门任务"},
        genre_context={"genre": "xuanhuan", "genre_plugin_ids": ["xuanhuan"]},
    )

    assert calls["web_game"] == 0
    assert review["web_game_review"]["pass"] is True


def test_legacy_review_without_genre_context_keeps_text_heuristic(monkeypatch):
    calls = {"web_game": 0}

    def fake_web_game_review(**_kwargs):
        calls["web_game"] += 1
        return {"pass": True, "scores": {}, "issues": [], "revision_plan": []}

    monkeypatch.setattr(orchestrator_module, "review_web_game_chapter", fake_web_game_review)
    body = "宗门任务已列入执事堂系统，弟子等级决定领取顺序。"

    _review_chapter_body(2, body, {"next_focus": "完成宗门任务"})

    assert calls["web_game"] == 1
