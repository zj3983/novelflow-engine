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


def test_second_chapter_body_reuses_fact_and_foreshadowing_context():
    story = StoryState(
        story_id="s-013",
        outline="A palace clerk follows a hidden ledger across two nights.",
        genre="fantasy",
        style="suspense",
        current_chapter=1,
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
        foreshadowing=[],
        chapter_summaries=[],
        characters=[
            CharacterState(
                name="Pei An",
                role="protagonist",
                goals=["find the ledger"],
            )
        ],
    )

    first_bundle = StoryEngine().generate_next_chapter(story)
    second_bundle = StoryEngine().generate_next_chapter(first_bundle.updated_story)

    assert "Carries forward" in second_bundle.body
    assert "A hidden letter appears." in second_bundle.body


def test_generate_chapter_builds_action_briefs_and_conflict_summary():
    story = StoryState(
        story_id="s-014",
        outline="Two rivals close in on the same witness.",
        genre="fantasy",
        style="court intrigue",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="driven",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="guarded",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.action_briefs
    assert bundle.action_briefs[0]["name"] == "Lin Yue"
    assert bundle.action_briefs[1]["name"] == "Su Wan"
    assert "find the witness" in bundle.action_briefs[0]["action"]
    assert "protect the witness" in bundle.action_briefs[1]["action"]
    assert bundle.conflict_summary["stakes"]
    assert "Lin Yue" in bundle.conflict_summary["summary"]
    assert "Su Wan" in bundle.conflict_summary["summary"]
    assert bundle.conflict_summary["primary_conflict"]["lead"] == "Lin Yue"
    assert bundle.conflict_summary["primary_conflict"]["opposition"] == "Su Wan"
    assert bundle.conflict_summary["secondary_conflict"]["pressure"] == "time"


def test_generate_chapter_body_reflects_selected_conflict():
    story = StoryState(
        story_id="s-015",
        outline="A magistrate corners an ally who knows too much.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["expose the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert "Conflict:" in bundle.body
    assert "Lin Yue" in bundle.body
    assert "Su Wan" in bundle.body
    assert "witness" in bundle.body
    assert "Secondary pressure:" in bundle.body


def test_next_outline_reflects_primary_and_secondary_conflicts():
    story = StoryState(
        story_id="s-016",
        outline="A censor and a magistrate race to control a witness.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert "Lin Yue" in bundle.next_outline
    assert "Su Wan" in bundle.next_outline
    assert "time" in bundle.next_outline
    assert "witness" in bundle.next_outline


def test_director_selects_primary_conflict_by_goal_collision():
    story = StoryState(
        story_id="s-017",
        outline="Three factions close in on a single witness.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the archives"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.conflict_summary["primary_conflict"]["lead"] == "Lin Yue"
    assert bundle.conflict_summary["primary_conflict"]["opposition"] == "Su Wan"
    assert "Pei An" not in bundle.conflict_summary["primary_conflict"]["collision"]


def test_director_selects_secondary_conflict_and_event_beat():
    story = StoryState(
        story_id="s-018",
        outline="Three factions close in on a single ledger while a witness breaks.",
        genre="mystery",
        style="tense",
        current_chapter=0,
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hide the ledger"],
                current_emotion="guarded",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["protect the witness"],
                current_emotion="defiant",
            ),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.conflict_summary["secondary_conflict"]["participants"]
    assert "Pei An" in bundle.conflict_summary["secondary_conflict"]["participants"]
    assert bundle.event_beat["turn"] == "pressure spike"
    assert "ledger" in bundle.event_beat["pivot"] or "witness" in bundle.event_beat["pivot"]
    assert "Event beat:" in bundle.body
