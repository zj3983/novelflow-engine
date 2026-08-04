import json

import pytest

from packages.story_core.outline_templates import (
    copy_outline_template,
    normalize_outline_template,
)
from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type


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


def test_game_outline_template_has_four_scalable_pacing_stages_only_for_game_genre() -> None:
    game = copy_outline_template("game_webnovel")
    xuanhuan = copy_outline_template("xuanhuan")

    stages = game["arc"]["pacing_stages"]
    assert [stage["id"] for stage in stages] == [
        "newcomer_rise",
        "server_dominance",
        "dual_world_escalation",
        "truth_and_final_war",
    ]
    assert [stage["reference_range"] for stage in stages] == [
        "1-50",
        "51-150",
        "151-300",
        "300+",
    ]
    assert all(stage["game_line"] and stage["reality_line"] for stage in stages)
    assert "pacing_stages" not in xuanhuan["arc"]


def test_outline_template_rejects_duplicate_or_incomplete_pacing_stages() -> None:
    template = copy_outline_template("game_webnovel")
    template["arc"]["pacing_stages"][1]["id"] = "newcomer_rise"

    with pytest.raises(ValueError, match="pacing_stage"):
        normalize_outline_template(template)

    template = copy_outline_template("game_webnovel")
    template["arc"]["pacing_stages"][0].pop("mystery_progress")

    with pytest.raises(ValueError, match="pacing_stage"):
        normalize_outline_template(template)


def test_game_pacing_stages_survive_prompt_context_compaction() -> None:
    context = novel_type_prompt_context(runtime_novel_type("game_webnovel"))

    stages = context["genre_outline_template"]["arc"]["pacing_stages"]
    assert len(stages) == 4
    assert stages[0]["id"] == "newcomer_rise"
    assert stages[-1]["id"] == "truth_and_final_war"

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
