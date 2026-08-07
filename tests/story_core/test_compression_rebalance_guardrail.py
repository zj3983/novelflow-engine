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


# The orchestrator no longer runs a separate compression model
# call after the bounded controller — over-length bodies are
# reported as ``length.out_of_range`` blocking findings and
# handed to the same revise pass. The three
# ``test_*_compression_*`` cases that used to drive the
# ``_run_compression`` helper are obsolete. The new contract is
# pinned by
# ``tests/story_core/test_orchestrator.py::test_over_length_body_is_fixed_in_single_revise_without_compression_model_call``.


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
