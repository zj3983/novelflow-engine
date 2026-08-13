from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from typing import Any, Literal, cast


MIN_VOLUME_CHAPTERS = 50
STORY_NODE_INTERVAL = 15
DETAIL_BATCH_SIZE = 15

VolumeWorkflowStatus = Literal[
    "volume_missing",
    "volume_plan_ready",
    "detail_partial",
    "ready_to_write",
    "volume_complete",
    "book_complete",
]

_NODE_CONTENT_FIELDS = ("objective", "pressure", "turn", "payoff", "next_effect")


def _as_mapping(value: object) -> Mapping[str, Any]:
    if isinstance(value, Mapping):
        return value
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        payload = model_dump()
        if isinstance(payload, Mapping):
            return payload
    raise ValueError("invalid_volume")


def _positive_chapter(value: object, *, error: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(error)
    return value


def _volume_id(volume: Mapping[str, Any]) -> str:
    value = volume.get("id")
    if not isinstance(value, str) or not value.strip():
        raise ValueError("invalid_volume_id")
    return value


def _normalized_volumes(volumes: Sequence[object]) -> list[dict[str, Any]]:
    return [dict(_as_mapping(volume)) for volume in volumes]


def volume_detail_batches(start: int, end: int) -> list[list[int]]:
    start_chapter = _positive_chapter(start, error="invalid_volume_range")
    end_chapter = _positive_chapter(end, error="invalid_volume_range")
    if end_chapter < start_chapter:
        raise ValueError("invalid_volume_range")
    numbers = list(range(start_chapter, end_chapter + 1))
    return [
        numbers[index : index + DETAIL_BATCH_SIZE]
        for index in range(0, len(numbers), DETAIL_BATCH_SIZE)
    ]


def validate_volume_structure(
    volumes: Sequence[object],
    *,
    core_ending_chapter: int,
) -> list[dict[str, Any]]:
    core_ending = _positive_chapter(
        core_ending_chapter,
        error="invalid_core_ending_chapter",
    )
    normalized = _normalized_volumes(volumes)
    if not normalized:
        raise ValueError("volume_missing")

    previous: tuple[str, int] | None = None
    final_volumes: list[tuple[int, str, int]] = []
    for index, volume in enumerate(normalized):
        volume_id = _volume_id(volume)
        start = _positive_chapter(
            volume.get("start_chapter"),
            error=f"invalid_volume_range:{volume_id}",
        )
        end = _positive_chapter(
            volume.get("end_chapter"),
            error=f"invalid_volume_range:{volume_id}",
        )
        if end < start:
            raise ValueError(f"invalid_volume_range:{volume_id}")

        if previous is not None:
            previous_id, previous_end = previous
            if start <= previous_end:
                raise ValueError(f"volume_overlap:{previous_id}:{volume_id}")
            if start != previous_end + 1:
                raise ValueError(f"volume_gap:{previous_id}:{volume_id}")
        previous = (volume_id, end)

        is_final = volume.get("is_final_arc", False)
        if not isinstance(is_final, bool):
            raise ValueError(f"invalid_final_volume_marker:{volume_id}")
        if is_final:
            final_volumes.append((index, volume_id, end))
        elif end - start + 1 < MIN_VOLUME_CHAPTERS:
            raise ValueError(f"volume_too_short:{volume_id}")

        raw_nodes = volume.get("story_nodes", [])
        if not isinstance(raw_nodes, list) or not raw_nodes:
            raise ValueError(f"story_nodes_missing:{volume_id}")
        expected_start = start
        for raw_node in raw_nodes:
            node = _as_mapping(raw_node)
            node_start = _positive_chapter(
                node.get("start_chapter"),
                error=f"invalid_story_node_range:{volume_id}",
            )
            node_end = _positive_chapter(
                node.get("end_chapter"),
                error=f"invalid_story_node_range:{volume_id}",
            )
            if node_end < node_start:
                raise ValueError(f"invalid_story_node_range:{volume_id}")
            if node_start < expected_start:
                raise ValueError(f"story_node_overlap:{volume_id}")
            if node_start > expected_start:
                raise ValueError(f"story_node_gap:{volume_id}")
            if node_end - node_start + 1 > STORY_NODE_INTERVAL:
                raise ValueError(f"story_node_too_long:{volume_id}")
            for field in _NODE_CONTENT_FIELDS:
                value = node.get(field)
                if not isinstance(value, str) or not value.strip():
                    raise ValueError(f"story_node_content_missing:{volume_id}:{field}")
            expected_start = node_end + 1
        if expected_start <= end:
            raise ValueError(f"story_node_gap:{volume_id}")
        if expected_start != end + 1:
            raise ValueError(f"story_node_overlap:{volume_id}")

    if not final_volumes:
        raise ValueError("final_volume_missing")
    if len(final_volumes) > 1:
        raise ValueError("multiple_final_volumes")
    final_index, final_id, final_end = final_volumes[0]
    if final_index != len(normalized) - 1:
        raise ValueError(f"final_volume_not_last:{final_id}")
    if final_end != core_ending:
        raise ValueError(f"final_volume_end_mismatch:{final_id}")
    return normalized


def find_volume_for_chapter(
    volumes: Sequence[object], chapter_number: int
) -> dict[str, Any] | None:
    chapter = _positive_chapter(chapter_number, error="invalid_chapter_number")
    for volume in _normalized_volumes(volumes):
        start = _positive_chapter(
            volume.get("start_chapter"), error="invalid_volume_range"
        )
        end = _positive_chapter(
            volume.get("end_chapter"), error="invalid_volume_range"
        )
        if start <= chapter <= end:
            return volume
    return None


def find_next_volume(
    volumes: Sequence[object], chapter_number: int
) -> dict[str, Any] | None:
    chapter = _positive_chapter(chapter_number, error="invalid_chapter_number")
    candidates = [
        volume
        for volume in _normalized_volumes(volumes)
        if _positive_chapter(volume.get("start_chapter"), error="invalid_volume_range")
        > chapter
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda volume: cast(int, volume["start_chapter"]))


def derive_volume_workflow(
    volumes: Sequence[object],
    *,
    target_chapter: int,
    detail_chapter_numbers: Iterable[int],
    confirmed_chapter_max: int,
) -> VolumeWorkflowStatus:
    target = _positive_chapter(target_chapter, error="invalid_chapter_number")
    if (
        not isinstance(confirmed_chapter_max, int)
        or isinstance(confirmed_chapter_max, bool)
        or confirmed_chapter_max < 0
    ):
        raise ValueError("invalid_confirmed_chapter_max")

    normalized = _normalized_volumes(volumes)
    volume = find_volume_for_chapter(normalized, target)
    if volume is None:
        final_volumes = [
            volume for volume in normalized if volume.get("is_final_arc") is True
        ]
        if final_volumes:
            final_end = max(
                _positive_chapter(
                    volume.get("end_chapter"), error="invalid_volume_range"
                )
                for volume in final_volumes
            )
            if target > final_end and confirmed_chapter_max >= final_end:
                return "book_complete"
        return "volume_missing"

    start = _positive_chapter(
        volume.get("start_chapter"), error="invalid_volume_range"
    )
    end = _positive_chapter(volume.get("end_chapter"), error="invalid_volume_range")
    if confirmed_chapter_max >= end:
        return (
            "book_complete"
            if volume.get("is_final_arc") is True
            else "volume_complete"
        )

    detailed = {
        chapter
        for chapter in detail_chapter_numbers
        if isinstance(chapter, int)
        and not isinstance(chapter, bool)
        and start <= chapter <= end
    }
    if not detailed:
        return "volume_plan_ready"
    if detailed == set(range(start, end + 1)):
        return "ready_to_write"
    return "detail_partial"
