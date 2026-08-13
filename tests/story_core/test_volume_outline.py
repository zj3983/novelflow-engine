from __future__ import annotations

import pytest

from packages.story_core.volume_outline import (
    DETAIL_BATCH_SIZE,
    MIN_VOLUME_CHAPTERS,
    STORY_NODE_INTERVAL,
    derive_volume_workflow,
    find_next_volume,
    find_volume_for_chapter,
    validate_volume_structure,
    volume_detail_batches,
)


def node(start_chapter: int, end_chapter: int) -> dict[str, object]:
    return {
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "objective": f"objective-{start_chapter}",
        "pressure": f"pressure-{start_chapter}",
        "turn": f"turn-{start_chapter}",
        "payoff": f"payoff-{start_chapter}",
        "next_effect": f"next-{start_chapter}",
    }


def arc_payload(
    *,
    arc_id: str = "opening",
    start_chapter: int = 1,
    end_chapter: int = 60,
    is_final_arc: bool = False,
    story_nodes: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    if story_nodes is None:
        story_nodes = [
            node(start, min(start + STORY_NODE_INTERVAL - 1, end_chapter))
            for start in range(start_chapter, end_chapter + 1, STORY_NODE_INTERVAL)
        ]
    return {
        "id": arc_id,
        "start_chapter": start_chapter,
        "end_chapter": end_chapter,
        "is_final_arc": is_final_arc,
        "story_nodes": story_nodes,
    }


def test_volume_constants_define_the_domain_limits() -> None:
    assert MIN_VOLUME_CHAPTERS == 50
    assert STORY_NODE_INTERVAL == 15
    assert DETAIL_BATCH_SIZE == 15


def test_volume_detail_batches_cover_the_range_without_crossing_batch_size() -> None:
    assert volume_detail_batches(153, 187) == [
        list(range(153, 168)),
        list(range(168, 183)),
        list(range(183, 188)),
    ]


def test_volume_detail_batches_reject_an_inverted_range() -> None:
    with pytest.raises(ValueError, match="invalid_volume_range"):
        volume_detail_batches(10, 9)


def test_non_final_volume_must_have_at_least_fifty_chapters() -> None:
    arc = arc_payload(end_chapter=49)

    with pytest.raises(ValueError, match="volume_too_short:opening"):
        validate_volume_structure([arc], core_ending_chapter=120)


def test_final_volume_may_be_shorter_than_fifty_chapters() -> None:
    arc = arc_payload(
        start_chapter=101,
        end_chapter=120,
        is_final_arc=True,
    )

    assert validate_volume_structure([arc], core_ending_chapter=120)[0]["id"] == "opening"


def test_story_nodes_cover_volume_without_more_than_fifteen_chapter_gap() -> None:
    arc = arc_payload(
        end_chapter=60,
        is_final_arc=True,
        story_nodes=[node(1, 15), node(16, 30), node(31, 45), node(46, 60)],
    )

    assert validate_volume_structure([arc], core_ending_chapter=60)[0]["id"] == "opening"


@pytest.mark.parametrize(
    ("arcs", "error"),
    [
        (
            [
                arc_payload(end_chapter=60),
                arc_payload(
                    arc_id="second",
                    start_chapter=62,
                    end_chapter=120,
                    is_final_arc=True,
                ),
            ],
            "volume_gap:opening:second",
        ),
        (
            [
                arc_payload(end_chapter=60),
                arc_payload(
                    arc_id="second",
                    start_chapter=60,
                    end_chapter=120,
                    is_final_arc=True,
                ),
            ],
            "volume_overlap:opening:second",
        ),
    ],
)
def test_volume_ranges_must_be_contiguous(
    arcs: list[dict[str, object]], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        validate_volume_structure(arcs, core_ending_chapter=120)


@pytest.mark.parametrize(
    ("story_nodes", "error"),
    [
        ([node(1, 15), node(17, 60)], "story_node_gap:opening"),
        (
            [node(1, 15), node(15, 29), node(30, 44), node(45, 59), node(60, 60)],
            "story_node_overlap:opening",
        ),
        (
            [node(1, 16), node(17, 30), node(31, 45), node(46, 60)],
            "story_node_too_long:opening",
        ),
    ],
)
def test_story_node_ranges_are_exact_and_bounded(
    story_nodes: list[dict[str, object]], error: str
) -> None:
    arc = arc_payload(end_chapter=60, is_final_arc=True, story_nodes=story_nodes)

    with pytest.raises(ValueError, match=error):
        validate_volume_structure([arc], core_ending_chapter=60)


@pytest.mark.parametrize(
    "field", ["objective", "pressure", "turn", "payoff", "next_effect"]
)
def test_story_node_content_fields_must_be_non_empty(field: str) -> None:
    story_nodes = [node(1, 15), node(16, 30), node(31, 45), node(46, 60)]
    story_nodes[0][field] = "  "
    arc = arc_payload(end_chapter=60, is_final_arc=True, story_nodes=story_nodes)

    with pytest.raises(ValueError, match=f"story_node_content_missing:opening:{field}"):
        validate_volume_structure([arc], core_ending_chapter=60)


def test_final_volume_must_be_last_and_end_at_the_core_ending() -> None:
    arcs = [
        arc_payload(end_chapter=60, is_final_arc=True),
        arc_payload(arc_id="second", start_chapter=61, end_chapter=120),
    ]
    with pytest.raises(ValueError, match="final_volume_not_last:opening"):
        validate_volume_structure(arcs, core_ending_chapter=120)

    final = arc_payload(start_chapter=101, end_chapter=119, is_final_arc=True)
    with pytest.raises(ValueError, match="final_volume_end_mismatch:opening"):
        validate_volume_structure([final], core_ending_chapter=120)


def test_volume_structure_requires_exactly_one_final_volume() -> None:
    non_final = arc_payload(end_chapter=60)
    with pytest.raises(ValueError, match="final_volume_missing"):
        validate_volume_structure([non_final], core_ending_chapter=60)

    arcs = [
        arc_payload(end_chapter=60, is_final_arc=True),
        arc_payload(
            arc_id="second",
            start_chapter=61,
            end_chapter=120,
            is_final_arc=True,
        ),
    ]
    with pytest.raises(ValueError, match="multiple_final_volumes"):
        validate_volume_structure(arcs, core_ending_chapter=120)


def test_volume_lookup_helpers_find_containing_and_successor_volumes() -> None:
    arcs = [
        arc_payload(end_chapter=60),
        arc_payload(
            arc_id="second",
            start_chapter=61,
            end_chapter=120,
            is_final_arc=True,
        ),
    ]

    assert find_volume_for_chapter(arcs, 75)["id"] == "second"
    assert find_volume_for_chapter(arcs, 121) is None
    assert find_next_volume(arcs, 60)["id"] == "second"
    assert find_next_volume(arcs, 120) is None


@pytest.mark.parametrize(
    ("arcs", "target_chapter", "detail_chapters", "confirmed_max", "expected"),
    [
        ([arc_payload(end_chapter=60)], 61, [], 60, "volume_missing"),
        (
            [arc_payload(arc_id="second", start_chapter=61, end_chapter=120)],
            61,
            [],
            60,
            "volume_plan_ready",
        ),
        (
            [arc_payload(arc_id="second", start_chapter=61, end_chapter=120)],
            61,
            list(range(61, 76)),
            60,
            "detail_partial",
        ),
        (
            [arc_payload(arc_id="second", start_chapter=61, end_chapter=120)],
            61,
            list(range(61, 121)),
            60,
            "ready_to_write",
        ),
        ([arc_payload(end_chapter=60)], 60, list(range(1, 61)), 60, "volume_complete"),
        (
            [arc_payload(end_chapter=60, is_final_arc=True)],
            60,
            list(range(1, 61)),
            60,
            "book_complete",
        ),
    ],
)
def test_derive_volume_workflow_covers_every_status(
    arcs: list[dict[str, object]],
    target_chapter: int,
    detail_chapters: list[int],
    confirmed_max: int,
    expected: str,
) -> None:
    assert derive_volume_workflow(
        arcs,
        target_chapter=target_chapter,
        detail_chapter_numbers=detail_chapters,
        confirmed_chapter_max=confirmed_max,
    ) == expected
