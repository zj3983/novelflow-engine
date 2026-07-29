import packages.story_core.foreshadowing as foreshadowing_module
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


def test_last_touched_chapter_is_optional_in_json_schema():
    schema = ForeshadowingState.model_json_schema()
    required = schema.get("required", [])

    assert "last_touched_chapter" not in required
    assert schema["properties"]["last_touched_chapter"].get("default") is None
    assert isinstance(ForeshadowingState(text="thread", first_chapter=2).last_touched_chapter, int)


def test_explicit_none_defaults_last_touched_without_replacing_zero():
    defaulted = ForeshadowingState(
        text="defaulted thread",
        first_chapter=4,
        last_touched_chapter=None,
    )
    explicit_zero = ForeshadowingState(
        text="zero thread",
        first_chapter=4,
        last_touched_chapter=0,
    )

    assert defaulted.last_touched_chapter == 4
    assert defaulted.model_dump()["last_touched_chapter"] == 4
    assert isinstance(defaulted.model_dump()["last_touched_chapter"], int)
    assert explicit_zero.last_touched_chapter == 0


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


def test_resolution_is_idempotent_and_preserves_terminal_history():
    resolved = ForeshadowingState(
        text="The sealed letter",
        first_chapter=2,
        last_touched_chapter=7,
        status="resolved",
        resolved_chapter=7,
    )
    expired = ForeshadowingState(
        text="The rusted key",
        first_chapter=1,
        last_touched_chapter=8,
        status="expired",
    )

    ledger = reconcile_foreshadowing(
        [resolved, expired],
        chapter_number=10,
        unresolved_threads=[],
        resolved_threads=["the sealed letter", "the rusted key"],
    )

    assert {entry.text: entry for entry in ledger} == {
        resolved.text: resolved,
        expired.text: expired,
    }


def test_existing_normalized_duplicates_are_canonicalized_deterministically():
    entries = [
        ForeshadowingState(
            text=" The sealed letter ",
            first_chapter=4,
            last_touched_chapter=9,
            status="resolved",
            resolved_chapter=8,
        ),
        ForeshadowingState(
            text="Ｔｈｅ sealed   letter",
            first_chapter=2,
            last_touched_chapter=7,
            status="expired",
            payoff_plan="Reveal the sender.",
        ),
        ForeshadowingState(
            text="the sealed letter",
            first_chapter=3,
            last_touched_chapter=10,
            status="reinforced",
            resolved_chapter=9,
        ),
    ]

    forward = reconcile_foreshadowing(
        entries, chapter_number=11, unresolved_threads=["the sealed letter"]
    )
    reverse = reconcile_foreshadowing(
        list(reversed(entries)), chapter_number=11, unresolved_threads=["the sealed letter"]
    )

    assert forward == reverse
    assert len(forward) == 1
    assert forward[0].first_chapter == 2
    assert forward[0].last_touched_chapter == 10
    assert forward[0].status == "expired"
    assert forward[0].payoff_plan == "Reveal the sender."
    assert forward[0].resolved_chapter == 9


def test_out_of_order_replay_does_not_advance_or_resolve_a_thread():
    original = ForeshadowingState(
        text="The sealed letter",
        first_chapter=2,
        last_touched_chapter=8,
        status="open",
    )

    unresolved_replay = reconcile_foreshadowing(
        [original],
        chapter_number=5,
        unresolved_threads=["the sealed letter"],
    )
    resolution_replay = reconcile_foreshadowing(
        [original],
        chapter_number=5,
        unresolved_threads=[],
        resolved_threads=["the sealed letter"],
    )

    assert unresolved_replay == [original]
    assert resolution_replay == [original]


def test_newer_replay_advances_open_thread_but_same_chapter_does_not():
    original = ForeshadowingState(
        text="The sealed letter",
        first_chapter=2,
        last_touched_chapter=8,
        status="open",
    )

    same_chapter = reconcile_foreshadowing(
        [original], chapter_number=8, unresolved_threads=["the sealed letter"]
    )
    newer_chapter = reconcile_foreshadowing(
        [original], chapter_number=9, unresolved_threads=["the sealed letter"]
    )

    assert same_chapter == [original]
    assert newer_chapter[0].status == "reinforced"
    assert newer_chapter[0].last_touched_chapter == 9


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


def test_module_does_not_expose_misleading_open_selection_alias():
    assert not hasattr(foreshadowing_module, "select_open_foreshadowing")
