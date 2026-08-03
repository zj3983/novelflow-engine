import json
from types import SimpleNamespace

import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.memory import build_foreshadowing
from packages.story_core.models import ForeshadowingState, StoryState


def _make_store(tmp_path, *, state=None) -> FileProjectStore:
    root = tmp_path / "novel"
    project = {
        "project_id": "foreshadowing-project",
        "title": "Foreshadowing Novel",
        "active_story_id": "foreshadowing-story",
    }
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"project": project}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(project, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            state
            or {
                "story_id": "foreshadowing-story",
                "current_chapter": 0,
                "world_facts": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return FileProjectStore(root)


def _chapter(
    chapter_number: int,
    unresolved_threads: list[str],
    resolved_threads: list[str] | None = None,
) -> dict:
    return {
        "chapter_number": chapter_number,
        "chapter_title": f"Chapter {chapter_number}",
        "body": f"Body {chapter_number}",
        "chapter_summary": {
            "summary": f"Summary {chapter_number}",
            "facts": [f"Fact {chapter_number}"],
            "unresolved_threads": unresolved_threads,
            "resolved_threads": resolved_threads or [],
        },
    }


def _tree_snapshot(root) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in root.rglob("*")
        if path.is_file()
    }


def test_chapter_sync_adds_reinforces_and_preserves_absent_threads_without_time_regression(tmp_path):
    store = _make_store(tmp_path)
    state = {
        "story_id": "foreshadowing-story",
        "current_chapter": 0,
        "world_facts": [],
        "foreshadowing": [
            {"text": "旧钟为何停摆", "first_chapter": 1, "status": "open"},
        ],
    }

    after_one = store._sync_state_after_chapter(
        state,
        _chapter(1, ["旧钟为何停摆", "密信出自谁手"]),
    )
    after_two = store._sync_state_after_chapter(
        after_one,
        _chapter(2, ["密信出自谁手", "暗门通向何处"]),
    )
    replayed = store._sync_state_after_chapter(
        after_two,
        _chapter(1, ["密信出自谁手"]),
    )

    ledger = {entry["text"]: entry for entry in replayed["foreshadowing"]}
    assert ledger["旧钟为何停摆"]["status"] == "open"
    assert ledger["旧钟为何停摆"]["last_touched_chapter"] == 1
    assert ledger["密信出自谁手"]["status"] == "reinforced"
    assert ledger["密信出自谁手"]["last_touched_chapter"] == 2
    assert ledger["暗门通向何处"]["status"] == "open"
    assert ledger["暗门通向何处"]["first_chapter"] == 2


def test_chapter_sync_resolves_a_thread_and_records_it_in_summary_and_memory_index(tmp_path):
    store = _make_store(tmp_path)
    state = {
        "story_id": "foreshadowing-story",
        "current_chapter": 1,
        "world_facts": [],
        "foreshadowing": [
            {
                "text": "谁改了当年的账册",
                "first_chapter": 1,
                "last_touched_chapter": 1,
                "status": "open",
            }
        ],
    }

    synced = store._sync_state_after_chapter(
        state,
        _chapter(2, [], ["谁改了当年的账册"]),
    )

    assert synced["foreshadowing"] == [
        {
            "text": "谁改了当年的账册",
            "first_chapter": 1,
            "last_touched_chapter": 2,
            "status": "resolved",
            "payoff_plan": "",
            "resolved_chapter": 2,
        }
    ]
    assert synced["chapter_summaries"][-1]["resolved_threads"] == ["谁改了当年的账册"]
    assert synced["memory_index"][-1]["resolved_threads"] == ["谁改了当年的账册"]


def test_historical_regeneration_preserves_api_managed_open_thread_and_payoff_plan(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Rewrite an early chapter.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 2,
        "world_facts": [],
        "foreshadowing": [
            {"text": "old-auto-clue", "first_chapter": 1, "last_touched_chapter": 1, "status": "open"},
        ],
    }
    store = _make_store(tmp_path, state=state)
    store.update_foreshadowing_ledger(
        [
            ForeshadowingState(
                text="人工维护的暗线",
                first_chapter=1,
                last_touched_chapter=2,
                status="open",
                payoff_plan="第五章由旧账册回收",
            ),
            ForeshadowingState(
                text="old-auto-clue",
                first_chapter=1,
                last_touched_chapter=1,
                status="open",
            ),
        ]
    )
    # Simulate the page deleting the automatic clue while retaining the curated one.
    store.update_foreshadowing_ledger(
        [
            ForeshadowingState(
                text="人工维护的暗线",
                first_chapter=1,
                last_touched_chapter=2,
                status="open",
                payoff_plan="第五章由旧账册回收",
            )
        ]
    )

    for chapter_number, threads in ((1, ["old-auto-clue"]), (2, [])):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "saved body",
                "updated_story": {**state, "current_chapter": chapter_number},
                "chapter_summary": {
                    "summary": f"Summary {chapter_number}",
                    "unresolved_threads": threads,
                    "resolved_threads": [],
                },
            },
        )

    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Rewritten Opening",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate({**state, "current_chapter": 1}),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "The old automatic clue is gone.",
            "facts": [],
            "unresolved_threads": [],
            "resolved_threads": [],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    persisted = store.state()
    assert persisted["foreshadowing"] == [
        {
            "text": "人工维护的暗线",
            "first_chapter": 1,
            "last_touched_chapter": 2,
            "status": "open",
            "payoff_plan": "第五章由旧账册回收",
            "resolved_chapter": None,
        }
    ]
    assert persisted["manual_foreshadowing"] == persisted["foreshadowing"]


def test_historical_projection_replays_later_resolved_threads(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Resolve a clue after an early rewrite.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 2,
        "world_facts": [],
        "foreshadowing": [
            {
                "text": "谁改了当年的账册",
                "first_chapter": 1,
                "last_touched_chapter": 2,
                "status": "resolved",
                "resolved_chapter": 2,
            }
        ],
    }
    store = _make_store(tmp_path, state=state)
    for chapter_number, unresolved, resolved in (
        (1, ["谁改了当年的账册"], []),
        (2, [], ["谁改了当年的账册"]),
    ):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "saved body",
                "updated_story": {**state, "current_chapter": chapter_number},
                "chapter_summary": {
                    "summary": f"Summary {chapter_number}",
                    "unresolved_threads": unresolved,
                    "resolved_threads": resolved,
                },
            },
        )

    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Rewritten Opening",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate({**state, "current_chapter": 1}),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "The rewritten opening keeps the clue.",
            "facts": [],
            "unresolved_threads": ["谁改了当年的账册"],
            "resolved_threads": [],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    assert store.state()["foreshadowing"][0]["status"] == "resolved"
    assert store.state()["foreshadowing"][0]["resolved_chapter"] == 2
    assert store.chapter(2)["updated_story"]["foreshadowing"][0]["status"] == "resolved"


def test_manual_rewrite_of_historical_chapter_reprojects_threads_without_rolling_back_head(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Manual historical rewrite.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 3,
        "world_facts": [],
        "foreshadowing": [
            {"text": "old-target-clue", "first_chapter": 1, "last_touched_chapter": 1, "status": "open"},
            {"text": "later-clue", "first_chapter": 2, "last_touched_chapter": 2, "status": "open"},
        ],
        "manual_foreshadowing": [
            {
                "text": "人工暗线",
                "first_chapter": 1,
                "last_touched_chapter": 3,
                "status": "open",
                "payoff_plan": "终卷回收",
            }
        ],
    }
    store = _make_store(tmp_path, state=state)
    for chapter_number, threads in (
        (1, ["old-target-clue"]),
        (2, ["later-clue"]),
        (3, []),
    ):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "old body",
                "updated_story": {**state, "current_chapter": chapter_number},
                "chapter_summary": {
                    "summary": f"Summary {chapter_number}",
                    "facts": [],
                    "unresolved_threads": threads,
                    "resolved_threads": [],
                    "next_focus": "Continue.",
                },
            },
        )

    store.rewrite_chapter(chapter_number=1, body="重写后的正文，不再出现旧线索。", title="New One")

    persisted = store.state()
    assert persisted["current_chapter"] == 3
    assert {entry["text"] for entry in persisted["foreshadowing"]} == {"人工暗线", "later-clue"}
    rewritten = store.chapter(1)
    assert rewritten["chapter_summary"]["unresolved_threads"] == []
    chapter_three = store.chapter(3)
    assert {entry["text"] for entry in chapter_three["updated_story"]["foreshadowing"]} == {
        "人工暗线",
        "later-clue",
    }


def test_manual_historical_rewrite_rolls_back_all_managed_files_on_markdown_failure(
    tmp_path,
    monkeypatch,
):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Transactional manual rewrite.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 2,
        "world_facts": [],
        "foreshadowing": [
            {"text": "old-clue", "first_chapter": 1, "last_touched_chapter": 1, "status": "open"},
        ],
    }
    store = _make_store(tmp_path, state=state)
    for chapter_number, threads in ((1, ["old-clue"]), (2, [])):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "old body",
                "updated_story": {**state, "current_chapter": chapter_number},
                "chapter_summary": {
                    "summary": "Old summary",
                    "unresolved_threads": threads,
                    "resolved_threads": [],
                },
            },
        )
    before = _tree_snapshot(store.root)
    real_write_text = store._write_text

    def fail_markdown(path, text):
        if path.parent == store.chapters_dir:
            raise OSError("simulated markdown failure")
        return real_write_text(path, text)

    monkeypatch.setattr(store, "_write_text", fail_markdown)

    with pytest.raises(OSError, match="simulated markdown failure"):
        store.rewrite_chapter(chapter_number=1, body="new body", title="New One")

    assert _tree_snapshot(store.root) == before


def test_writing_packet_exposes_only_eight_recent_unresolved_threads(tmp_path):
    unresolved = [
        {
            "text": f"thread-{index}",
            "first_chapter": index + 1,
            "last_touched_chapter": index + 1,
            "status": "reinforced" if index % 2 else "open",
        }
        for index in range(10)
    ]
    store = _make_store(
        tmp_path,
        state={
            "story_id": "foreshadowing-story",
            "current_chapter": 10,
            "world_facts": [],
            "foreshadowing": [
                *unresolved,
                {
                    "text": "already-resolved",
                    "first_chapter": 1,
                    "last_touched_chapter": 99,
                    "status": "resolved",
                    "resolved_chapter": 99,
                },
            ],
        },
    )

    packet = store.writing_packet(11)

    assert [entry["text"] for entry in packet["foreshadowing_context"]] == [
        f"thread-{index}" for index in range(9, 1, -1)
    ]
    assert "foreshadowing" not in packet["state"]
    assert "already-resolved" not in json.dumps(packet, ensure_ascii=False)


def test_memory_foreshadowing_is_empty_without_real_threads_and_bounded_when_present():
    empty_story = StoryState(
        story_id="empty",
        outline="",
        genre="",
        style="",
    )
    populated_story = StoryState(
        story_id="populated",
        outline="",
        genre="",
        style="",
        foreshadowing=[
            *[
                ForeshadowingState(
                    text=f"thread-{index}",
                    first_chapter=index,
                    last_touched_chapter=index,
                    status="open",
                )
                for index in range(1, 10)
            ],
            ForeshadowingState(
                text="resolved",
                first_chapter=1,
                last_touched_chapter=20,
                status="resolved",
                resolved_chapter=20,
            ),
        ],
    )

    assert build_foreshadowing(empty_story, 1) == []
    assert [entry["text"] for entry in build_foreshadowing(populated_story, 10)] == [
        f"thread-{index}" for index in range(9, 1, -1)
    ]


def test_historical_rewrite_persists_ledger_rebuilt_from_saved_chapter_summaries(tmp_path):
    award = {"level": 2, "points": 5, "chapter": 2}
    old_allocation = {
        "chapter": 2,
        "allocations": {"Strength": 5},
        "remaining": 0,
        "reason": "old build",
    }
    protagonist = {
        "level": "Lv.2",
        "attributes": {"Strength": 10},
        "unallocated_attribute_points": 0,
        "attribute_point_awards": [award],
        "attribute_allocations": [old_allocation],
    }
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Rewrite an early clue without losing later continuity.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 3,
        "world_facts": [],
        "progression_ledger": {"protagonist": protagonist},
        "foreshadowing": [
            {"text": "old-target-clue", "first_chapter": 2, "last_touched_chapter": 2, "status": "open"},
            {"text": "shared-future-clue", "first_chapter": 2, "last_touched_chapter": 3, "status": "reinforced"},
            {"text": "future-only-clue", "first_chapter": 3, "last_touched_chapter": 3, "status": "open"},
            {
                "text": "manual-terminal-note",
                "first_chapter": 1,
                "last_touched_chapter": 3,
                "status": "resolved",
                "resolved_chapter": 3,
            },
        ],
    }
    store = _make_store(tmp_path, state=state)
    project = store.project()
    project["world_blueprint"] = {
        "power_system_spec": {
            "attribute_allocation": {
                "mode": "free",
                "points_per_level": 5,
                "starting_level": 1,
                "base_attributes": {"Strength": 5},
                "allow_carry": True,
                "respec_rule": "Respec between chapters.",
            }
        }
    }
    store._write_json(store.webnovel_dir / "project.json", project)
    store._write_json(
        store.story_system_dir / "MASTER_SETTING.json",
        {"project": project},
    )

    def snapshot(chapter_number: int) -> dict:
        return {
            "story_id": state["story_id"],
            "outline": state["outline"],
            "genre": state["genre"],
            "style": state["style"],
            "current_chapter": chapter_number,
            "progression_ledger": {"protagonist": protagonist},
            "foreshadowing": state["foreshadowing"],
        }

    saved_threads = {
        1: [],
        2: ["old-target-clue", "shared-future-clue"],
        3: ["shared-future-clue", "future-only-clue"],
    }
    for chapter_number in range(1, 4):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "saved body",
                "updated_story": snapshot(chapter_number),
                "chapter_summary": {
                    "summary": f"Summary {chapter_number}",
                    "unresolved_threads": saved_threads[chapter_number],
                },
            },
        )

    rewritten_story = snapshot(2)
    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="Rewritten Chapter Two",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate(rewritten_story),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "Chapter two now plants a different clue.",
            "facts": ["The old clue is removed from chapter two."],
            "unresolved_threads": ["new-target-clue"],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    persisted = json.loads((store.webnovel_dir / "state.json").read_text(encoding="utf-8"))
    expected = {
        "manual-terminal-note": ("resolved", 3),
        "new-target-clue": ("open", 2),
        "shared-future-clue": ("open", 3),
        "future-only-clue": ("open", 3),
    }
    assert {
        entry["text"]: (entry["status"], entry["last_touched_chapter"])
        for entry in persisted["foreshadowing"]
    } == expected
    assert store.state()["foreshadowing"] == persisted["foreshadowing"]

    chapter_two = store._read_json(store.story_system_dir / "chapters" / "0002.json")
    chapter_three = store._read_json(store.story_system_dir / "chapters" / "0003.json")
    chapter_two_threads = {
        entry["text"] for entry in chapter_two["updated_story"]["foreshadowing"]
    }
    chapter_three_threads = {
        entry["text"] for entry in chapter_three["updated_story"]["foreshadowing"]
    }
    assert chapter_two_threads == {"new-target-clue"}
    assert chapter_three_threads == set(expected)

    regeneration_base = store._regeneration_base_state(3, store.state())
    assert {
        entry["text"] for entry in regeneration_base["foreshadowing"]
    } == {"new-target-clue"}


def test_plain_historical_rewrite_rebuilds_persisted_ledger_without_attribute_rules(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "A plain project rewrites its opening clue.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 2,
        "world_facts": [],
        "foreshadowing": [
            {"text": "removed-opening-clue", "first_chapter": 1, "last_touched_chapter": 1, "status": "open"},
            {"text": "later-clue", "first_chapter": 2, "last_touched_chapter": 2, "status": "open"},
            {
                "text": "manual-resolution",
                "first_chapter": 1,
                "last_touched_chapter": 2,
                "status": "resolved",
                "resolved_chapter": 2,
            },
        ],
    }
    store = _make_store(tmp_path, state=state)

    def snapshot(chapter_number: int) -> dict:
        return {
            "story_id": state["story_id"],
            "outline": state["outline"],
            "genre": state["genre"],
            "style": state["style"],
            "current_chapter": chapter_number,
            "foreshadowing": state["foreshadowing"],
        }

    for chapter_number, threads in (
        (1, ["removed-opening-clue"]),
        (2, ["later-clue"]),
    ):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "saved body",
                "updated_story": snapshot(chapter_number),
                "chapter_summary": {
                    "summary": f"Summary {chapter_number}",
                    "unresolved_threads": threads,
                },
            },
        )

    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Rewritten Opening",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate(snapshot(1)),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "The opening now plants a replacement clue.",
            "facts": ["The original opening clue is gone."],
            "unresolved_threads": ["replacement-opening-clue"],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    persisted = json.loads((store.webnovel_dir / "state.json").read_text(encoding="utf-8"))
    assert {
        entry["text"]: entry["status"]
        for entry in persisted["foreshadowing"]
    } == {
        "manual-resolution": "resolved",
        "replacement-opening-clue": "open",
        "later-clue": "open",
    }
    assert store.state()["foreshadowing"] == persisted["foreshadowing"]


@pytest.mark.parametrize("failure_point", ["chapter_json", "markdown", "commit"])
def test_plain_historical_rewrite_rolls_back_every_managed_file_on_failure(
    tmp_path,
    monkeypatch,
    failure_point,
):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Transactional plain rewrite.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 2,
        "world_facts": ["original global state"],
        "foreshadowing": [
            {"text": "old-clue", "first_chapter": 1, "status": "open"},
        ],
    }
    store = _make_store(tmp_path, state=state)

    def snapshot(chapter_number: int) -> dict:
        return {
            "story_id": state["story_id"],
            "outline": state["outline"],
            "genre": state["genre"],
            "style": state["style"],
            "current_chapter": chapter_number,
            "foreshadowing": state["foreshadowing"],
        }

    for chapter_number in (1, 2):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Old Chapter {chapter_number}",
                "body": "old body",
                "updated_story": snapshot(chapter_number),
                "chapter_summary": {
                    "summary": "Old summary",
                    "unresolved_threads": ["old-clue"] if chapter_number == 1 else [],
                },
            },
        )
    store._write_json(store.story_system_dir / "reviews" / "0001.json", {"old": "review"})
    store._write_text(store.chapters_dir / "0001-Old Chapter 1.md", "old markdown")
    before = _tree_snapshot(store.root)

    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="New Chapter One",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate(snapshot(1)),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "Replacement summary.",
            "facts": ["Replacement fact."],
            "unresolved_threads": ["new-clue"],
            "next_focus": "Continue.",
        },
    )

    if failure_point == "chapter_json":
        original_replace_json = store._replace_json_transaction

        def fail_after_json_replace(payloads):
            original_replace_json(payloads)
            raise OSError("injected_chapter_json_failure")

        monkeypatch.setattr(store, "_replace_json_transaction", fail_after_json_replace)
        expected = "injected_chapter_json_failure"
    elif failure_point == "markdown":
        original_write_text = store._write_text

        def fail_markdown(path, text):
            if path.parent == store.chapters_dir:
                raise OSError("injected_markdown_failure")
            return original_write_text(path, text)

        monkeypatch.setattr(store, "_write_text", fail_markdown)
        expected = "injected_markdown_failure"
    else:
        original_commit = store.commit

        def fail_after_commit(**kwargs):
            original_commit(**kwargs)
            raise RuntimeError("injected_commit_failure")

        monkeypatch.setattr(store, "commit", fail_after_commit)
        expected = "injected_commit_failure"

    with pytest.raises((OSError, RuntimeError), match=expected):
        store.persist_bundle(bundle, operation="regenerate")

    assert _tree_snapshot(store.root) == before


def test_normal_append_skips_malformed_legacy_foreshadowing_entry(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Append safely.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 0,
        "foreshadowing": [
            {"text": "broken-without-first-chapter", "status": "open"},
            {"text": "valid-existing", "first_chapter": 1, "status": "open"},
        ],
    }
    store = _make_store(tmp_path, state=state)
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Chapter One",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story={},
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "A new clue appears.",
            "facts": ["A fact."],
            "unresolved_threads": ["new-clue"],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="generate")

    assert {
        entry["text"] for entry in store.state()["foreshadowing"]
    } == {"valid-existing", "new-clue"}


def test_historical_rebuild_skips_malformed_legacy_foreshadowing_entry(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "Rewrite safely.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 2,
        "foreshadowing": [
            {"text": "broken-without-first-chapter", "status": "open"},
            {"text": "valid-terminal", "first_chapter": 1, "status": "resolved", "resolved_chapter": 2},
        ],
    }
    store = _make_store(tmp_path, state=state)
    valid_snapshot = {
        "story_id": state["story_id"],
        "outline": state["outline"],
        "genre": state["genre"],
        "style": state["style"],
        "current_chapter": 1,
        "foreshadowing": [],
    }
    for chapter_number in (1, 2):
        chapter_snapshot = {**valid_snapshot, "current_chapter": chapter_number}
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "saved body",
                "updated_story": chapter_snapshot,
                "chapter_summary": {"summary": "Saved", "unresolved_threads": []},
            },
        )
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Rewritten One",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate(valid_snapshot),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "Rewrite adds a clue.",
            "facts": ["A fact."],
            "unresolved_threads": ["rewrite-clue"],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    assert {
        entry["text"] for entry in store.state()["foreshadowing"]
    } == {"valid-terminal", "rewrite-clue"}


def test_writing_packet_skips_malformed_legacy_foreshadowing_entry(tmp_path):
    store = _make_store(
        tmp_path,
        state={
            "story_id": "foreshadowing-story",
            "current_chapter": 1,
            "world_facts": [],
            "foreshadowing": [
                {"text": "broken-without-first-chapter", "status": "open"},
                {"text": "valid-context", "first_chapter": 1, "status": "open"},
            ],
        },
    )

    packet = store.writing_packet(2)

    assert [entry["text"] for entry in packet["foreshadowing_context"]] == ["valid-context"]


def test_historical_rewrite_preserves_unresolved_ledger_when_chapter_evidence_is_incomplete(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "A missing chapter makes reconstruction uncertain.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 3,
        "foreshadowing": [
            {"text": "old-opening-clue", "first_chapter": 1, "status": "open"},
            {"text": "missing-chapter-clue", "first_chapter": 2, "status": "reinforced"},
        ],
    }
    store = _make_store(tmp_path, state=state)
    base_snapshot = {
        "story_id": state["story_id"],
        "outline": state["outline"],
        "genre": state["genre"],
        "style": state["style"],
        "foreshadowing": state["foreshadowing"],
    }
    for chapter_number, threads in (
        (1, ["old-opening-clue"]),
        (3, ["visible-future-clue"]),
    ):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "saved body",
                "updated_story": {**base_snapshot, "current_chapter": chapter_number},
                "chapter_summary": {
                    "summary": f"Summary {chapter_number}",
                    "unresolved_threads": threads,
                },
            },
        )
    rewritten_snapshot = {
        **base_snapshot,
        "current_chapter": 1,
        "foreshadowing": [],
    }
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Rewritten Opening",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate(rewritten_snapshot),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "The rewrite plants another clue.",
            "facts": ["A replacement fact."],
            "unresolved_threads": ["replacement-clue"],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    assert {
        entry["text"] for entry in store.state()["foreshadowing"]
    } == {
        "old-opening-clue",
        "missing-chapter-clue",
        "replacement-clue",
        "visible-future-clue",
    }


def test_historical_rewrite_treats_missing_chapter_one_as_incomplete_evidence(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "The visible history starts too late.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 3,
        "foreshadowing": [
            {"text": "prefix-clue", "first_chapter": 1, "status": "open"},
        ],
    }
    store = _make_store(tmp_path, state=state)
    snapshot = {
        "story_id": state["story_id"],
        "outline": state["outline"],
        "genre": state["genre"],
        "style": state["style"],
        "foreshadowing": state["foreshadowing"],
    }
    for chapter_number, threads in ((2, ["old-two"]), (3, ["future-three"])):
        store._write_json(
            store.story_system_dir / "chapters" / f"{chapter_number:04d}.json",
            {
                "chapter_number": chapter_number,
                "chapter_title": f"Chapter {chapter_number}",
                "body": "saved body",
                "updated_story": {**snapshot, "current_chapter": chapter_number},
                "chapter_summary": {
                    "summary": "Saved summary.",
                    "unresolved_threads": threads,
                },
            },
        )
    rewritten_snapshot = {**snapshot, "current_chapter": 2, "foreshadowing": []}
    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="Rewritten Two",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate(rewritten_snapshot),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "Chapter two changes.",
            "facts": ["A changed fact."],
            "unresolved_threads": ["replacement-two"],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    assert {
        entry["text"] for entry in store.state()["foreshadowing"]
    } == {"prefix-clue", "replacement-two", "future-three"}


def test_historical_rewrite_treats_non_numeric_saved_chapter_number_as_incomplete(tmp_path):
    state = {
        "story_id": "foreshadowing-story",
        "outline": "A saved chapter has damaged structure.",
        "genre": "fantasy",
        "style": "plain",
        "current_chapter": 3,
        "foreshadowing": [
            {"text": "structural-clue", "first_chapter": 2, "status": "open"},
        ],
    }
    store = _make_store(tmp_path, state=state)
    snapshot = {
        "story_id": state["story_id"],
        "outline": state["outline"],
        "genre": state["genre"],
        "style": state["style"],
        "foreshadowing": state["foreshadowing"],
    }
    for file_number, payload_number, threads in (
        (1, 1, ["old-opening"]),
        (2, "not-a-number", ["damaged-middle"]),
        (3, 3, ["future-three"]),
    ):
        store._write_json(
            store.story_system_dir / "chapters" / f"{file_number:04d}.json",
            {
                "chapter_number": payload_number,
                "chapter_title": f"Chapter {file_number}",
                "body": "saved body",
                "updated_story": {**snapshot, "current_chapter": file_number},
                "chapter_summary": {
                    "summary": "Saved summary.",
                    "unresolved_threads": threads,
                },
            },
        )
    rewritten_snapshot = {**snapshot, "current_chapter": 1, "foreshadowing": []}
    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Rewritten Opening",
        body="正文。" * 1400,
        cadence="measured",
        next_outline="Continue.",
        updated_story=StoryState.model_validate(rewritten_snapshot),
        quality_report={"ok": True, "issues": []},
        chapter_summary={
            "summary": "The opening changes.",
            "facts": ["A changed fact."],
            "unresolved_threads": ["replacement-opening"],
            "next_focus": "Continue.",
        },
    )

    store.persist_bundle(bundle, operation="regenerate")

    assert {
        entry["text"] for entry in store.state()["foreshadowing"]
    } == {"structural-clue", "replacement-opening", "future-three"}
