import inspect
import json

import pytest

import packages.story_core.genre_stages.game_webnovel.director as game_director_module
import packages.story_core.orchestrator as orchestrator_module
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator


GAME_DIRECTOR_TERMS = (
    "游戏ID",
    "等级",
    "背包",
    "装备耐久",
    "任务进度",
    "outsider_misread",
)


def _story(genre: str) -> StoryState:
    return StoryState(
        story_id=f"director-isolation-{genre}",
        outline="主角追查一条失踪线索",
        genre=genre,
        style="克制",
    )


@pytest.mark.parametrize("genre", ["修仙", "玄幻", "都市", "悬疑"])
def test_generic_director_prompt_excludes_game_contract(genre: str) -> None:
    prompt = StoryOrchestrator()._plan_prompt(_story(genre), 2)

    for term in GAME_DIRECTOR_TERMS:
        assert term not in prompt


def test_game_director_prompt_keeps_game_contract() -> None:
    prompt = StoryOrchestrator()._plan_prompt(_story("网游"), 2)

    for term in ("游戏ID", "等级", "任务进度", "outsider_misread"):
        assert term in prompt


def test_generic_director_does_not_compute_attribute_allocation(monkeypatch) -> None:
    calls: list[str] = []

    def track(story):
        calls.append(story.genre)
        return {"available_points": 7, "rule": {"mode": "free"}}

    monkeypatch.setattr(game_director_module, "attribute_allocation_context", track)

    StoryOrchestrator()._plan_prompt(_story("悬疑"), 2)
    assert calls == []

    prompt = StoryOrchestrator()._plan_prompt(_story("网游"), 2)

    assert calls == ["网游"]
    assert '"attribute_allocation": {"available_points": 7' in prompt


def test_generic_director_prompt_has_no_empty_game_ledger_skeleton() -> None:
    prompt = StoryOrchestrator()._plan_prompt(_story("悬疑"), 2)

    assert '"ledger"' not in prompt
    assert '"protagonist": {}' not in prompt
    assert '"economy": {}' not in prompt
    assert '"quests": {}' not in prompt


def test_xianxia_director_keeps_bounded_world_pulse_without_game_fields() -> None:
    story = _story("修仙")
    story.progression_ledger = {
        "world_pulse": {
            "latest": {
                "pulse_index": 9,
                "chapter_number": 8,
                "summary": "执法堂封锁后山并询问守门弟子",
                "visible_traces": ["山门新增两队巡查弟子"],
                "game_id": "residual-game-id",
                "game_panel": {"level": "Lv.99"},
            },
            "threads": [
                {
                    "summary": "旧印来源仍在宗门内部发酵",
                    "status": "active",
                    "game_state": {"quest": "residual-game-quest"},
                }
            ],
        },
        "protagonist": {"game_id": "residual-ledger-id"},
    }

    prompt = StoryOrchestrator()._plan_prompt(story, 9)

    for retained in (
        "执法堂封锁后山并询问守门弟子",
        "山门新增两队巡查弟子",
        "旧印来源仍在宗门内部发酵",
    ):
        assert retained in prompt
    for leaked in (
        "residual-game-id",
        "Lv.99",
        "residual-game-quest",
        "residual-ledger-id",
        '"game_panel"',
        '"game_state"',
    ):
        assert leaked not in prompt


def test_orchestrator_director_prompt_region_has_no_game_ledger_fields() -> None:
    source = "\n".join(
        (
            inspect.getsource(orchestrator_module._director_prompt_snapshot),
            inspect.getsource(orchestrator_module._director_snapshot_summary),
            inspect.getsource(orchestrator_module._director_prompt_outline_context),
            inspect.getsource(orchestrator_module._director_prompt_character_cards),
            inspect.getsource(orchestrator_module._director_context_payload),
            inspect.getsource(StoryOrchestrator._render_plan_prompt),
        )
    )

    for field in (
        "game_id",
        "level",
        "class_path",
        "exp",
        "hp",
        "mp",
        "weapon_durability",
        "game_currency",
        "inventory",
        "backpack",
        "real_balance",
        "quests",
        "game_panel",
        "game_line_payoff",
        "reality_line_payoff",
    ):
        assert f'"{field}"' not in source


def test_generic_director_ignores_residual_game_identity_and_panel() -> None:
    story = _story("悬疑")
    story.characters = [
        CharacterState(
            name="林照",
            role="主角",
            game_id="残留游戏ID",
            game_panel={"level": "Lv.99", "class_path": "残留职业"},
        )
    ]

    prompt = StoryOrchestrator()._plan_prompt(story, 2)

    for leaked_value in ("残留游戏ID", "Lv.99", "残留职业", '"game_panel"'):
        assert leaked_value not in prompt


def test_game_director_restores_raw_game_inputs() -> None:
    story = _story("网游")
    story.characters = [
        CharacterState(
            name="苏叶",
            role="主角",
            game_id="夜烬",
            game_panel={"level": "Lv.8", "class_path": "元素法师"},
        )
    ]
    story.progression_ledger = {
        "protagonist": {"game_id": "夜烬", "level": "Lv.8"},
        "economy": {"game_currency": "77铜"},
        "quests": {"清道夫": {"status": "进行中"}},
    }
    story.outline_context = {
        "active_arc": {
            "title": "灰狼坡",
            "game_line_payoff": "拿到技能前置",
            "reality_line_payoff": "缓解现实急账",
        }
    }

    prompt = StoryOrchestrator()._plan_prompt(story, 2)

    for retained_value in (
        "夜烬",
        "Lv.8",
        "元素法师",
        "77铜",
        "清道夫",
        "拿到技能前置",
        "缓解现实急账",
    ):
        assert retained_value in prompt


def test_custom_director_context_falls_back_to_story_raw_game_inputs() -> None:
    story = _story("网游")
    story.characters = [CharacterState(name="苏叶", role="主角", game_id="夜烬")]
    story.progression_ledger = {
        "protagonist": {"game_id": "夜烬", "level": "Lv.8"},
        "economy": {"game_currency": "77铜"},
    }
    story.outline_context = {
        "active_arc": {
            "game_line_payoff": "拿到技能前置",
            "reality_line_payoff": "缓解现实急账",
        }
    }
    director_context = {
        "project_snapshot": {"outline": "自定义导演快照"},
        "chapter_seed": {},
        "character_cards": {
            "cards": [{"identity": {"name": "苏叶", "role": "主角"}}]
        },
    }

    prompt = StoryOrchestrator()._plan_prompt(story, 2, director_context)

    for retained_value in ("夜烬", "Lv.8", "77铜", "拿到技能前置", "缓解现实急账"):
        assert retained_value in prompt


def test_game_prompt_compactor_enforces_json_safe_hard_budgets() -> None:
    class UnstableValue:
        def __str__(self) -> str:
            raise AssertionError("unsupported values must not be stringified")

    source = {
        **{f"key_{index}": index for index in range(20)},
        "long_text": "x" * 500,
        "long_list": list(range(20)),
        "deep": {"a": {"b": {"c": {"d": {"e": {"f": "too deep"}}}}}},
        "unsupported": UnstableValue(),
    }

    compacted = game_director_module._compact_game_value(source)

    assert list(compacted) == [f"key_{index}" for index in range(12)]
    assert json.loads(json.dumps(compacted, ensure_ascii=False)) == compacted

    bounded = game_director_module._compact_game_value(
        {
            "long_text": "x" * 500,
            "long_list": list(range(20)),
            "deep": {"a": {"b": {"c": {"d": {"e": {"f": "too deep"}}}}}},
            "unsupported": UnstableValue(),
        }
    )
    assert len(bounded["long_text"]) == 180
    assert bounded["long_list"] == list(range(8))
    assert "too deep" not in json.dumps(bounded["deep"], ensure_ascii=False)
    assert bounded["unsupported"] is None


def test_game_prompt_compactor_enforces_shared_node_and_serialized_char_budgets() -> None:
    def nested(depth: int) -> object:
        value: object = "终点" * 200
        for _ in range(depth):
            value = {
                f"branch_{index}": [value] * 12
                for index in range(12)
            }
        return value

    def node_count(value: object) -> int:
        if isinstance(value, dict):
            return 1 + sum(node_count(item) for item in value.values())
        if isinstance(value, list):
            return 1 + sum(node_count(item) for item in value)
        return 1

    pressure = {"ledger": nested(8), "characters": nested(7), "outline": nested(6)}

    compacted = game_director_module._compact_game_value(pressure)
    bounded_additions = game_director_module._bounded_game_additions(pressure)
    serialized = json.dumps(bounded_additions, ensure_ascii=False)

    assert node_count(compacted) <= game_director_module._MAX_COMPACT_NODES
    assert len(serialized) <= game_director_module._MAX_GAME_ADDITIONS_CHARS
    assert json.loads(serialized) == bounded_additions
