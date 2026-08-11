from __future__ import annotations

from types import SimpleNamespace

from packages.story_core.agents.contracts import DirectorArtifact
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import StoryState
from packages.story_core.modular_bundle_adapter import adapt_modular_bundle_to_legacy


def test_adapt_modular_bundle_to_legacy_preserves_workbench_contract() -> None:
    story = StoryState.model_validate(
        {
            "story_id": "adapter-test",
            "outline": "A traveler enters the mountain.",
            "genre": "fantasy",
            "style": "concise",
            "current_chapter": 1,
            "chapter_summaries": [
                {"chapter_number": 1, "summary": "The journey begins."},
            ],
            "timeline": [
                {
                    "chapter_number": 1,
                    "summary": "The journey begins.",
                    "impact": "The mountain is ahead.",
                }
            ],
        }
    )
    director_artifact = DirectorArtifact.model_validate(
        {
            "chapter_number": 2,
            "chapter_title": "The Bell at Dusk",
            "chapter_goal": "Reach the abandoned shrine.",
            "opening_state": "Rain closes in.",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "mountain path",
                    "action": "climb through the rain",
                    "result": "the shrine comes into view",
                },
                {
                    "order": 2,
                    "location": "shrine gate",
                    "action": "push open the gate",
                    "result": "a hidden bell rings",
                },
            ],
            "ending_state": "The gate stands open.",
            "hook": "Footsteps answer the bell.",
            "entity_requirements": [
                {
                    "kind": "character",
                    "name": "the traveler",
                    "importance": 8,
                }
            ],
        }
    )
    continuity_delta = SimpleNamespace(chapter_number=2)
    modular_bundle = SimpleNamespace(
        director_artifact=director_artifact,
        body="The traveler climbed until the old bell rang.",
        consistency_findings=[],
        canon_preflight={"ok": True},
        continuity_delta=continuity_delta,
    )

    result = adapt_modular_bundle_to_legacy(
        story=story,
        modular_bundle=modular_bundle,
        chapter_number=2,
    )

    assert isinstance(result, ChapterBundle)
    assert result.chapter_title == "The Bell at Dusk"
    assert result.body == modular_bundle.body
    assert result.chapter_summary["facts"] == [
        "the shrine comes into view",
        "a hidden bell rings",
    ]
    assert result.chapter_summary["next_focus"] == "Footsteps answer the bell."
    assert result.next_outline == "Footsteps answer the bell."
    assert result.updated_story.current_chapter == 2
    assert [item.chapter_number for item in result.updated_story.chapter_summaries] == [1, 2]
    assert result.updated_story.timeline[-1].impact == "Footsteps answer the bell."
    assert result.continuity_delta is continuity_delta
