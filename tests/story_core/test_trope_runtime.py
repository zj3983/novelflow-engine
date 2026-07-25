from __future__ import annotations

from copy import deepcopy

from packages.story_core.trope_runtime import (
    compact_trope_candidates,
    merge_trope_templates,
    resolve_trope_contract,
)


def test_merge_trope_templates_prefers_specific_duplicate_and_appends_generic_only_ids():
    generic = [
        {
            "id": "shared",
            "name": "Generic Shared",
            "trigger": "generic trigger",
            "beats": ["generic beat"],
            "payoff": "generic payoff",
            "avoid": ["generic avoid"],
        },
        {
            "id": "generic_only",
            "name": "Generic Only",
            "trigger": "generic only trigger",
            "beats": ["generic only beat"],
            "payoff": "generic only payoff",
            "avoid": ["generic only avoid"],
        },
    ]
    specific = [
        {
            "id": "shared",
            "name": "Specific Shared",
            "trigger": "specific trigger",
            "beats": ["specific beat"],
            "payoff": "specific payoff",
            "avoid": ["specific avoid"],
        },
        {
            "id": "specific_only",
            "name": "Specific Only",
            "trigger": "specific only trigger",
            "beats": ["specific only beat"],
            "payoff": "specific only payoff",
            "avoid": ["specific only avoid"],
        },
    ]

    merged = merge_trope_templates([specific, generic])

    assert [template["id"] for template in merged] == [
        "shared",
        "specific_only",
        "generic_only",
    ]
    assert merged[0]["name"] == "Specific Shared"


def test_resolve_trope_contract_returns_exact_contract_fields_for_known_template_and_beat():
    templates = [
        {
            "id": "trial",
            "name": "Trial by Fire",
            "trigger": "A public challenge appears.",
            "beats": ["accept the challenge", "win with a cost"],
            "payoff": "The crowd sees the protagonist differently.",
            "avoid": ["free victory", "off-screen resolution"],
            "extra": "should not leak",
        }
    ]

    contract = resolve_trope_contract(templates, "trial", " win with a cost ")

    assert contract == {
        "template_id": "trial",
        "name": "Trial by Fire",
        "trigger": "A public challenge appears.",
        "current_beat": "win with a cost",
        "payoff": "The crowd sees the protagonist differently.",
        "avoid": ["free victory", "off-screen resolution"],
    }


def test_resolve_trope_contract_keeps_known_template_when_current_beat_is_none_or_blank():
    templates = [
        {
            "id": "trial",
            "name": "Trial by Fire",
            "trigger": "A public challenge appears.",
            "beats": ["accept the challenge", "win with a cost"],
            "payoff": "The crowd sees the protagonist differently.",
            "avoid": ["free victory", "off-screen resolution"],
        }
    ]

    assert resolve_trope_contract(templates, "trial", None) == {
        "template_id": "trial",
        "name": "Trial by Fire",
        "trigger": "A public challenge appears.",
        "current_beat": "",
        "payoff": "The crowd sees the protagonist differently.",
        "avoid": ["free victory", "off-screen resolution"],
    }
    assert resolve_trope_contract(templates, "trial", "   ") == {
        "template_id": "trial",
        "name": "Trial by Fire",
        "trigger": "A public challenge appears.",
        "current_beat": "",
        "payoff": "The crowd sees the protagonist differently.",
        "avoid": ["free victory", "off-screen resolution"],
    }


def test_resolve_trope_contract_returns_empty_dict_for_unknown_template_or_beat():
    templates = [
        {
            "id": "trial",
            "name": "Trial by Fire",
            "trigger": "A public challenge appears.",
            "beats": ["accept the challenge"],
            "payoff": "The crowd sees the protagonist differently.",
            "avoid": ["free victory"],
        }
    ]

    assert resolve_trope_contract(templates, "missing", "accept the challenge") == {}
    assert resolve_trope_contract(templates, "trial", "wrong beat") == {}


def test_merge_and_resolve_compare_full_normalized_ids_and_beats_without_compacted_prefix_collisions():
    shared_prefix_id = "template-" + ("A" * 100)
    shared_prefix_beat = "beat-" + ("B" * 395)
    exact_template_id = shared_prefix_id + "-exact"
    duplicate_after_compaction_id = shared_prefix_id + "-different"
    exact_beat = shared_prefix_beat + "-exact"
    different_beat = shared_prefix_beat + "-different"

    merged = merge_trope_templates(
        [
            [
                {
                    "id": f"  {exact_template_id}  ",
                    "name": "Exact Template",
                    "trigger": "specific trigger",
                    "beats": [exact_beat],
                    "payoff": "specific payoff",
                    "avoid": ["specific avoid"],
                }
            ],
            [
                {
                    "id": duplicate_after_compaction_id,
                    "name": "Generic Variant",
                    "trigger": "generic trigger",
                    "beats": [different_beat],
                    "payoff": "generic payoff",
                    "avoid": ["generic avoid"],
                }
            ],
        ]
    )

    assert [template["id"] for template in merged] == [
        exact_template_id,
        duplicate_after_compaction_id,
    ]
    assert resolve_trope_contract(merged, exact_template_id, exact_beat)["current_beat"] == exact_beat
    assert resolve_trope_contract(merged, exact_template_id, different_beat) == {}


def test_overlong_trope_ids_are_ignored_by_projection_merge_and_resolution():
    valid_id = "v" * 120
    overlong_id = "o" * 121
    templates = [
        {
            "id": overlong_id,
            "name": "Overlong Template",
            "trigger": "should be ignored",
            "beats": ["beat"],
            "payoff": "ignored",
            "avoid": ["ignored"],
        },
        {
            "id": valid_id,
            "name": "Valid Template",
            "trigger": "kept",
            "beats": ["beat"],
            "payoff": "payoff",
            "avoid": ["avoid"],
        },
    ]

    assert compact_trope_candidates(templates) == [
        {
            "id": valid_id,
            "name": "Valid Template",
            "trigger": "kept",
            "beats": ["beat"],
            "payoff": "payoff",
            "avoid": ["avoid"],
        }
    ]
    assert merge_trope_templates([templates]) == [
        {
            "id": valid_id,
            "name": "Valid Template",
            "trigger": "kept",
            "beats": ["beat"],
            "payoff": "payoff",
            "avoid": ["avoid"],
        }
    ]
    assert resolve_trope_contract(templates, overlong_id, "beat") == {}
    assert resolve_trope_contract(templates, valid_id, "beat") == {
        "template_id": valid_id,
        "name": "Valid Template",
        "trigger": "kept",
        "current_beat": "beat",
        "payoff": "payoff",
        "avoid": ["avoid"],
    }


def test_compact_trope_candidates_retains_contract_fields_and_bounds_text_and_lists():
    templates = [
        {
            "id": "  long-id  ",
            "name": "  " + ("N" * 500) + "  ",
            "trigger": "  " + ("T" * 500) + "  ",
            "beats": [f" beat {index} " for index in range(1, 8)],
            "payoff": "  " + ("P" * 500) + "  ",
            "avoid": [f" avoid {index} " for index in range(1, 8)],
            "ignored": "value",
        }
    ]

    compacted = compact_trope_candidates(templates)

    assert len(compacted) == 1
    assert set(compacted[0]) == {"id", "name", "trigger", "beats", "payoff", "avoid"}
    assert compacted[0]["id"] == "long-id"
    assert len(compacted[0]["name"]) <= 400
    assert len(compacted[0]["trigger"]) <= 400
    assert len(compacted[0]["payoff"]) <= 400
    assert compacted[0]["beats"] == ["beat 1", "beat 2", "beat 3", "beat 4"]
    assert compacted[0]["avoid"] == ["avoid 1", "avoid 2", "avoid 3", "avoid 4"]


def test_merge_and_resolve_return_deep_copy_isolated_data():
    templates = [
        {
            "id": "trial",
            "name": "Trial by Fire",
            "trigger": "A public challenge appears.",
            "beats": ["accept the challenge"],
            "payoff": "The crowd sees the protagonist differently.",
            "avoid": ["free victory"],
        }
    ]

    merged = merge_trope_templates([templates])
    merged[0]["beats"].append("mutated")
    merged[0]["avoid"].append("mutated")

    fresh_merged = merge_trope_templates([templates])
    assert fresh_merged == [
        {
            "id": "trial",
            "name": "Trial by Fire",
            "trigger": "A public challenge appears.",
            "beats": ["accept the challenge"],
            "payoff": "The crowd sees the protagonist differently.",
            "avoid": ["free victory"],
        }
    ]

    contract = resolve_trope_contract(templates, "trial", None)
    contract["avoid"].append("mutated")

    fresh_contract = resolve_trope_contract(templates, "trial", None)
    assert fresh_contract["avoid"] == ["free victory"]


def test_compact_trope_candidates_ignores_malformed_values_and_returns_deep_copy_isolated_data():
    source = [
        {
            "id": "  ",
            "name": "ignored blank id",
            "trigger": "ignored",
            "beats": ["ignored"],
            "payoff": "ignored",
            "avoid": ["ignored"],
        },
        {
            "id": "clean",
            "name": object(),
            "trigger": None,
            "beats": [" first beat ", "", None, "second beat", {"nested": "value"}],
            "payoff": 42,
            "avoid": " lone avoid ",
        },
    ]
    original_beats = list(source[1]["beats"])
    original_avoid = source[1]["avoid"]

    compacted = compact_trope_candidates(source)

    assert compacted == [
        {
            "id": "clean",
            "name": "",
            "trigger": "",
            "beats": ["first beat", "second beat"],
            "payoff": "42",
            "avoid": ["lone avoid"],
        }
    ]

    compacted[0]["beats"].append("mutated")
    compacted[0]["avoid"].append("mutated")

    assert source[0]["id"] == "  "
    assert source[1]["beats"] == original_beats
    assert source[1]["avoid"] == original_avoid
    fresh = compact_trope_candidates(source)
    assert fresh[0]["beats"] == ["first beat", "second beat"]
    assert fresh[0]["avoid"] == ["lone avoid"]
