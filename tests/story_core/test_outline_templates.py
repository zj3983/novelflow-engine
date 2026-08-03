import json

import pytest

from packages.story_core.outline_templates import (
    copy_outline_template,
    normalize_outline_template,
)


def test_builtin_outline_templates_are_complete_and_genre_specific() -> None:
    game = copy_outline_template("game_webnovel")
    xuanhuan = copy_outline_template("xuanhuan")

    assert set(game) == {"schema_version", "overall", "arc", "chapter"}
    assert game["schema_version"] == "novel-outline-template/v1"
    assert game["overall"]["long_term_lines"]
    assert game["arc"]["minimum_arc_count"] >= 3
    assert game["chapter"]["opening_window_size"] == 10
    assert game != xuanhuan
    assert "游戏" in json.dumps(game, ensure_ascii=False)
    assert "游戏" not in json.dumps(xuanhuan, ensure_ascii=False)


def test_outline_template_copies_are_isolated() -> None:
    first = copy_outline_template("urban")
    second = copy_outline_template("urban")

    first["overall"]["instructions"].append("只存在于副本")

    assert "只存在于副本" not in second["overall"]["instructions"]


def test_outline_template_rejects_missing_layers_and_invalid_limits() -> None:
    template = copy_outline_template("generic_webnovel")
    template.pop("chapter")

    with pytest.raises(ValueError, match="chapter"):
        normalize_outline_template(template)

    template = copy_outline_template("generic_webnovel")
    template["arc"]["minimum_arc_count"] = 1

    with pytest.raises(ValueError, match="minimum_arc_count"):
        normalize_outline_template(template)
