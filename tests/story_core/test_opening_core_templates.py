from __future__ import annotations

import json

from packages.story_core.opening_core_templates import opening_core_reference


def test_game_opening_core_reference_contains_three_game_specific_dimensions() -> None:
    reference = opening_core_reference("game_webnovel")

    assert set(reference) == {"core_advantage", "central_mystery", "initial_drive"}
    assert len(reference["core_advantage"]["examples"]) == 3
    assert len(reference["central_mystery"]["examples"]) == 3
    assert len(reference["initial_drive"]["examples"]) == 3
    serialized = json.dumps(reference, ensure_ascii=False)
    assert "高倍爆率" in serialized
    assert "游戏影响现实" in serialized


def test_non_game_opening_core_reference_does_not_receive_game_examples() -> None:
    assert opening_core_reference("xuanhuan") == {}
    assert opening_core_reference("urban") == {}
    assert opening_core_reference("generic_webnovel") == {}


def test_opening_core_reference_returns_an_isolated_copy() -> None:
    first = opening_core_reference("game_webnovel")
    second = opening_core_reference("game_webnovel")

    first["core_advantage"]["examples"].append("只存在于副本")

    assert "只存在于副本" not in second["core_advantage"]["examples"]
