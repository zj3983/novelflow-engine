from packages.story_core.foreshadowing import (
    normalize_foreshadowing_text,
    reconcile_foreshadowing,
    select_unresolved_foreshadowing,
)
from packages.story_core.models import ForeshadowingState


def test_legacy_entry_defaults_last_touched_to_first_chapter():
    entry = ForeshadowingState.model_validate(
        {"text": "The sealed letter", "first_chapter": 3, "status": "open"}
    )

    assert entry.last_touched_chapter == 3
    assert entry.payoff_plan == ""
    assert entry.resolved_chapter is None


def test_normalization_is_deterministic_without_fuzzy_matching():
    assert normalize_foreshadowing_text("  ＳＥＡＬＥＤ\t Letter  ") == "sealed letter"
    assert normalize_foreshadowing_text("sealed letters") != "sealed letter"


def test_new_unresolved_thread_becomes_one_open_entry():
    ledger = reconcile_foreshadowing(
        [],
        chapter_number=4,
        unresolved_threads=["  The sealed letter ", "Ｔｈｅ sealed   letter"],
    )

    assert ledger == [
        ForeshadowingState(
            text="The sealed letter",
            first_chapter=4,
            last_touched_chapter=4,
            status="open",
        )
    ]


def test_repeated_thread_is_reinforced_without_duplication():
    original = ForeshadowingState(
        text="The sealed letter",
        first_chapter=2,
        last_touched_chapter=2,
        status="open",
        payoff_plan="Open it after the trial.",
    )

    ledger = reconcile_foreshadowing(
        [original],
        chapter_number=5,
        unresolved_threads=[" the   sealed letter "],
    )

    assert len(ledger) == 1
    assert ledger[0].status == "reinforced"
    assert ledger[0].last_touched_chapter == 5
    assert ledger[0].payoff_plan == "Open it after the trial."
    assert original.status == "open"
    assert original.last_touched_chapter == 2


def test_absent_thread_keeps_its_existing_state():
    original = ForeshadowingState(
        text="The sealed letter",
        first_chapter=2,
        last_touched_chapter=4,
        status="reinforced",
    )

    ledger = reconcile_foreshadowing(
        [original],
        chapter_number=6,
        unresolved_threads=["A key beneath the altar"],
    )

    assert ledger[0] == original
    assert ledger[0].status == "reinforced"
    assert ledger[0].resolved_chapter is None


def test_explicit_resolution_records_the_chapter():
    original = ForeshadowingState(
        text="The sealed letter",
        first_chapter=2,
        last_touched_chapter=4,
        status="reinforced",
    )

    ledger = reconcile_foreshadowing(
        [original],
        chapter_number=7,
        unresolved_threads=[],
        resolved_threads=["ＴＨＥ SEALED LETTER"],
    )

    assert ledger[0].status == "resolved"
    assert ledger[0].resolved_chapter == 7
    assert ledger[0].last_touched_chapter == 7


def test_selection_returns_only_unresolved_entries_most_recent_first():
    ledger = [
        ForeshadowingState(text="old", first_chapter=1, last_touched_chapter=2, status="open"),
        ForeshadowingState(text="resolved", first_chapter=2, last_touched_chapter=9, status="resolved"),
        ForeshadowingState(text="expired", first_chapter=3, last_touched_chapter=8, status="expired"),
        ForeshadowingState(text="recent", first_chapter=4, last_touched_chapter=7, status="reinforced"),
        ForeshadowingState(text="middle", first_chapter=5, last_touched_chapter=5, status="open"),
    ]

    selected = select_unresolved_foreshadowing(ledger, limit=2)

    assert [entry.text for entry in selected] == ["recent", "middle"]


def test_selection_with_non_positive_limit_is_empty():
    ledger = [ForeshadowingState(text="thread", first_chapter=1, status="open")]

    assert select_unresolved_foreshadowing(ledger, limit=0) == []
