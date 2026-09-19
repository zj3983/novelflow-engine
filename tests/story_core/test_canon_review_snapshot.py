from __future__ import annotations

from packages.story_core.canon.registry import CanonRegistry
from packages.story_core.canon.review_snapshot import build_canon_review_snapshot
from packages.story_core.continuity.snapshot import ChapterSnapshot
from packages.story_core.continuity.store import ContinuityStore


def _snapshot(chapter: int, state_after: dict) -> ChapterSnapshot:
    return ChapterSnapshot(
        chapter_number=chapter,
        candidate_id=f"candidate-{chapter}",
        operation="generate",
        confirmed_at="2026-09-19T00:00:00+00:00",
        body_sha256=f"sha-{chapter}",
        body_chars=4000,
        state_after=state_after,
    )


def test_review_snapshot_uses_previous_chapter_state_and_filters_future_canon(tmp_path):
    store = ContinuityStore(tmp_path)
    store.write_snapshot(
        _snapshot(
            2,
            {
                "current_chapter": 2,
                "characters": [
                    {
                        "name": "林昭",
                        "role": "protagonist",
                        "current_state": {
                            "current": {
                                "location": "山腰",
                                "inventory": {"旧令牌": 1},
                            }
                        },
                        "knowledge_boundary": ["知道旧令牌来自祖祠"],
                    }
                ],
                "world_facts": ["宗门夜间宵禁"],
                "continuity_facts": [
                    {
                        "subject": "林昭",
                        "field": "伤势",
                        "value": "右臂轻伤",
                        "chapter_number": 2,
                        "source_sentence": "他右臂仍在渗血。",
                    }
                ],
            },
        )
    )
    store.write_snapshot(
        _snapshot(4, {"current_chapter": 4, "characters": [], "world_facts": []})
    )

    registry = CanonRegistry()
    registry.add_character(
        name="林昭",
        entity_id="char-lin",
        lifecycle="active",
        extensions={
            "location": "山顶",
            "inventory": {"未来法器": {"quantity": 1, "last_chapter": 4}},
        },
    )
    registry.add_character(
        name="苏婉",
        entity_id="char-su",
        lifecycle="active",
        extensions={},
    )
    registry.add_character(
        name="未来使者",
        entity_id="char-future",
        lifecycle="active",
        extensions={"introduced_chapter": 4, "location": "山顶"},
    )

    registry.add_relationship(
        subject_id="char-lin",
        predicate="trusts",
        object_id="char-su",
        polarity="added",
        chapter_number=2,
        source_sentence="林昭把旧令牌交给苏婉查看。",
    )
    registry.add_relationship(
        subject_id="char-future",
        predicate="knows",
        object_id="char-lin",
        polarity="added",
        chapter_number=4,
        source_sentence="未来使者在第四章才认识林昭。",
    )
    registry.add_timeline_marker(
        marker="入夜",
        chapter_number=2,
        source_sentence="山门钟响三声。",
    )
    registry.add_timeline_marker(
        marker="次日清晨",
        chapter_number=4,
        source_sentence="第四章天亮。",
    )

    snapshot = build_canon_review_snapshot(
        project_root=tmp_path,
        chapter_number=3,
        registry=registry,
        continuity_facts=[{"subject": "林昭", "field": "位置", "value": "山顶"}],
        character_cards=[
            {
                "name": "林昭",
                "current_state": {"current": {"location": "山顶"}},
            }
        ],
        world_rules=["第四章新增加的世界规则"],
    )

    assert snapshot["historical_rewrite"] is True
    assert snapshot["state_source"] == "continuity_snapshot"
    assert snapshot["as_of_chapter"] == 2
    assert snapshot["characters"][0]["current_state"]["current"]["location"] == "山腰"
    rendered = str(snapshot)
    assert "右臂轻伤" in rendered
    assert "宗门夜间宵禁" in rendered
    assert "第四章新增加的世界规则" not in rendered
    assert "未来法器" not in rendered
    assert "未来使者" not in [item["name"] for item in snapshot["entities"]]
    assert [item["chapter_number"] for item in snapshot["relationships"]] == [2]
    assert [item["chapter_number"] for item in snapshot["timeline"]] == [2]
    assert snapshot["diagnostics"]["filtered_future_relationships"] == 1
    assert snapshot["diagnostics"]["filtered_future_timeline"] == 1


def test_review_snapshot_falls_back_to_writer_context_for_new_project(tmp_path):
    registry = CanonRegistry()
    registry.add_character(
        name="林昭",
        entity_id="char-lin",
        lifecycle="active",
        extensions={"occupation_or_role": "守祠杂役"},
    )

    snapshot = build_canon_review_snapshot(
        project_root=tmp_path,
        chapter_number=1,
        registry=registry,
        continuity_facts=[
            {"subject": "林昭", "field": "身份", "value": "守祠杂役"}
        ],
        character_cards=[
            {
                "name": "林昭",
                "role": "protagonist",
                "identity_profile": {"occupation": "守祠杂役"},
            }
        ],
        world_rules=["祖祠夜间不得点明火"],
    )

    assert snapshot["historical_rewrite"] is False
    assert snapshot["state_source"] == "chapter_start"
    assert snapshot["characters"][0]["name"] == "林昭"
    assert snapshot["facts"][0]["value"] == "守祠杂役"
    assert snapshot["world_rules"] == ["祖祠夜间不得点明火"]
    assert snapshot["entities"][0]["name"] == "林昭"


def test_review_snapshot_excludes_unconfirmed_proposed_entities(tmp_path):
    registry = CanonRegistry()
    registry.add_character(
        name="已确认角色",
        entity_id="char-active",
        lifecycle="active",
    )
    registry.add_character(
        name="仅导演提议角色",
        entity_id="char-proposed",
        lifecycle="proposed",
    )

    snapshot = build_canon_review_snapshot(
        project_root=tmp_path,
        chapter_number=1,
        registry=registry,
    )

    names = {item["name"] for item in snapshot["entities"]}
    assert "已确认角色" in names
    assert "仅导演提议角色" not in names


def test_historical_rewrite_without_bounded_state_refuses_live_context(tmp_path):
    state_path = tmp_path / ".webnovel" / "state.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text('{"current_chapter": 5}', encoding="utf-8")

    registry = CanonRegistry()
    registry.add_character(
        name="林昭",
        entity_id="char-lin",
        lifecycle="active",
        extensions={"location": "第五章地点"},
    )

    snapshot = build_canon_review_snapshot(
        project_root=tmp_path,
        chapter_number=3,
        registry=registry,
        character_cards=[
            {
                "name": "林昭",
                "current_state": {"current": {"location": "第五章地点"}},
            }
        ],
        continuity_facts=[{"field": "location", "value": "第五章地点"}],
    )

    assert snapshot["historical_rewrite"] is True
    assert snapshot["bounded_state_available"] is False
    assert snapshot["state_source"] == "unavailable"
    assert snapshot["characters"] == []
    assert snapshot["facts"] == []
    assert "第五章地点" not in str(snapshot)
