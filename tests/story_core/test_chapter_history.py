from __future__ import annotations

from packages.story_core.chapter_history import (
    apply_chapter_history,
    replace_chapter_record,
)


def test_replace_chapter_record_replaces_structured_and_legacy_entries() -> None:
    items = [
        "Chapter 2: stale manual summary",
        {"chapter_number": 1, "summary": "one"},
        {"chapter_number": 2, "summary": "stale"},
        {"chapter_number": 3, "summary": "three"},
    ]

    result = replace_chapter_record(
        items,
        {"chapter_number": 2, "summary": "fresh"},
    )

    assert result == [
        {"chapter_number": 1, "summary": "one"},
        {"chapter_number": 2, "summary": "fresh"},
        {"chapter_number": 3, "summary": "three"},
    ]


def test_replace_chapter_record_orders_and_trims_to_latest_records() -> None:
    result = replace_chapter_record(
        [
            {"chapter_number": 3, "summary": "three"},
            {"chapter_number": 1, "summary": "one"},
        ],
        {"chapter_number": 2, "summary": "two"},
        limit=2,
    )

    assert [item["chapter_number"] for item in result] == [2, 3]


def test_apply_chapter_history_replaces_duplicates_and_prefers_next_focus() -> None:
    state = {
        "current_chapter": 2,
        "chapter_summaries": [
            {"chapter_number": 3, "summary": "stale summary"},
        ],
        "timeline": [
            {"chapter_number": 3, "summary": "stale", "impact": "stale"},
        ],
        "unrelated": {"keep": True},
    }
    chapter_summary = {
        "chapter_number": 3,
        "summary": "fresh summary",
        "next_focus": "follow the bell",
    }

    result = apply_chapter_history(state, chapter_summary)

    assert result["current_chapter"] == 3
    assert result["chapter_summaries"] == [chapter_summary]
    assert result["timeline"] == [
        {
            "chapter_number": 3,
            "summary": "fresh summary",
            "impact": "follow the bell",
        }
    ]
    assert result["unrelated"] == {"keep": True}
    assert result is not state


def test_apply_chapter_history_uses_summary_as_timeline_impact_fallback() -> None:
    result = apply_chapter_history(
        {"current_chapter": 0, "chapter_summaries": [], "timeline": []},
        {"chapter_number": 1, "summary": "the gate opened", "next_focus": ""},
    )

    assert result["timeline"][0]["impact"] == "the gate opened"
