from packages.story_core.engine import StoryEngine
from packages.story_core.models import CharacterRelationship, CharacterState, StoryState


def test_generate_chapter_updates_state_and_returns_bundle():
    story = StoryState(
        story_id="s-001",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                traits={"impulsive": 0.6},
                goals=["find the culprit"],
            )
        ],
    )
    engine = StoryEngine()
    bundle = engine.generate_next_chapter(story)

    assert bundle.chapter_number == 1
    assert bundle.body
    assert bundle.next_outline
    assert bundle.updated_story.current_chapter == 1
    assert bundle.updated_story.characters[0].memory
    assert bundle.updated_story.timeline
    assert bundle.updated_story.chapter_summaries
    assert bundle.updated_story.foreshadowing
    assert bundle.updated_story.chapter_summaries[0].facts


def test_generate_chapter_does_not_mutate_frozen_character_state():
    story = StoryState(
        story_id="s-010",
        outline="A careful archivist hides a dangerous ledger.",
        genre="fantasy",
        style="political suspense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Shen Li",
                role="archivist",
                goals=["protect the ledger"],
                memory=["The ledger must stay hidden."],
                current_emotion="guarded",
                location="sealed vault",
                frozen=True,
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    frozen_character = bundle.updated_story.characters[0]

    assert frozen_character.memory == ["The ledger must stay hidden."]
    assert frozen_character.current_emotion == "guarded"
    assert frozen_character.location == "sealed vault"


def test_generate_chapter_evolves_lead_relationships():
    story = StoryState(
        story_id="s-011",
        outline="Two investigators circle the same ledger from opposite ends of the court.",
        genre="fantasy",
        style="court intrigue",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["expose the forgery"],
                relationships={
                    "Su Wan": CharacterRelationship(
                        target="Su Wan",
                        trust=0.4,
                        tension=0.9,
                        bond="uneasy alliance",
                    )
                },
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the family name"],
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    relationship = bundle.updated_story.characters[0].relationships["Su Wan"]

    assert relationship.trust == 0.3
    assert relationship.tension == 1.0
    assert "needles the alliance" in bundle.body


def test_generate_chapter_can_reduce_tension_for_protective_goal():
    story = StoryState(
        story_id="s-012",
        outline="A clerk protects an ally while hiding the ledger.",
        genre="fantasy",
        style="court intrigue",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Pei An",
                role="protagonist",
                goals=["protect Su Wan"],
                relationships={
                    "Su Wan": CharacterRelationship(
                        target="Su Wan",
                        trust=0.4,
                        tension=0.6,
                        bond="fragile trust",
                    )
                },
            )
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)
    relationship = bundle.updated_story.characters[0].relationships["Su Wan"]

    assert relationship.trust == 0.5
    assert relationship.tension == 0.5
    assert "works in fragile step with Su Wan" in bundle.body
