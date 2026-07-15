from __future__ import annotations

from packages.story_core.relationship_graph import (
    apply_relationship_updates,
    graph_from_character_cards,
    merge_relationship_graph,
    normalize_relationship_graph,
    select_relationship_subgraph,
)


def test_legacy_edges_receive_stable_ids_and_defaults() -> None:
    first = normalize_relationship_graph(
        [{"source": "林照", "target": "赵衡", "bond": "管事与杂役", "trust": 20, "tension": 75}]
    )
    reversed_edge = normalize_relationship_graph(
        [{"source": "赵衡", "target": "林照", "bond": "管事与杂役", "trust": 20, "tension": 75}]
    )

    assert first[0]["id"].startswith("rel-")
    assert first[0]["id"] == reversed_edge[0]["id"]
    assert first[0]["relation_type"] == "管事与杂役"
    assert first[0]["status"] == "active"
    assert first[0]["changes"] == []


def test_character_notes_merge_both_perspectives_into_one_edge() -> None:
    graph = graph_from_character_cards(
        [
            {
                "name": "林照",
                "relationship_notes": [
                    {
                        "target": "赵衡",
                        "relation_type": "上下级",
                        "history": "赵衡曾审问林照的父亲",
                        "current_attitude": "表面顺从，实际提防",
                        "shared_interest_or_conflict": "旧名册",
                        "known_facts": ["赵衡不想重查旧案"],
                        "unknown_facts": ["赵衡受顾长老指使"],
                    }
                ],
            },
            {
                "name": "赵衡",
                "relationship_notes": [
                    {
                        "target": "林照",
                        "relation_type": "上下级",
                        "current_attitude": "想把他赶出祖祠",
                        "known_facts": ["林照在查旧名册"],
                    }
                ],
            },
        ]
    )

    assert len(graph) == 1
    edge = graph[0]
    assert edge["source"] == "林照"
    assert edge["target"] == "赵衡"
    assert edge["source_knowledge"] == ["赵衡不想重查旧案"]
    assert edge["target_knowledge"] == ["林照在查旧名册"]
    assert edge["private_notes"] == ["赵衡受顾长老指使"]


def test_merge_preserves_existing_details_and_fills_blanks() -> None:
    existing = normalize_relationship_graph(
        [{"source": "林照", "target": "赵衡", "current_state": "作者确认的敌对", "trust": 10}]
    )
    generated = normalize_relationship_graph(
        [{"source": "赵衡", "target": "林照", "current_state": "互相提防", "tension": 80}]
    )

    merged = merge_relationship_graph(existing, generated)

    assert len(merged) == 1
    assert merged[0]["current_state"] == "作者确认的敌对"
    assert merged[0]["trust"] == 10
    assert merged[0]["tension"] == 80


def test_cast_subgraph_requires_both_endpoints_and_hides_private_notes() -> None:
    graph = normalize_relationship_graph(
        [
            {"source": "林照", "target": "赵衡", "private_notes": ["赵衡受顾长老指使"]},
            {"source": "赵衡", "target": "顾长老", "bond": "受命办事"},
            {"source": "周满", "target": "林照", "bond": "朋友"},
        ]
    )

    selected = select_relationship_subgraph(graph, ["林照", "赵衡"])

    assert [(edge["source"], edge["target"]) for edge in selected] == [("林照", "赵衡")]
    assert "private_notes" not in selected[0]


def test_apply_relationship_updates_overwrites_dynamic_state_and_keeps_static_history() -> None:
    existing = normalize_relationship_graph(
        [{"source": "Lin Zhao", "target": "Zhao Heng", "origin": "first conflict", "trust": 40, "tension": 30}]
    )
    updated = apply_relationship_updates(
        existing,
        [
            {
                "source": "Zhao Heng",
                "target": "Lin Zhao",
                "bond": "open rivals",
                "current_state": "on guard",
                "trust": 10,
                "tension": 85,
                "last_changed_chapter": 3,
                "changes": [{"chapter_number": 3, "summary": "public conflict", "trust": 10, "tension": 85}],
            }
        ],
    )

    assert updated[0]["source"] == "Lin Zhao"
    assert updated[0]["origin"] == "first conflict"
    assert updated[0]["bond"] == "open rivals"
    assert updated[0]["trust"] == 10
    assert updated[0]["tension"] == 85
    assert updated[0]["last_changed_chapter"] == 3
    assert updated[0]["changes"][-1]["summary"] == "public conflict"


def test_graph_from_character_cards_reads_dynamic_relationship_mapping() -> None:
    graph = graph_from_character_cards(
        [
            {
                "name": "Lin Zhao",
                "relationships": {
                    "Zhao Heng": {"target": "Zhao Heng", "bond": "mutual suspicion", "trust": 15, "tension": 70}
                },
            }
        ]
    )

    assert graph[0]["target"] == "Zhao Heng"
    assert graph[0]["bond"] == "mutual suspicion"
    assert graph[0]["trust"] == 15
