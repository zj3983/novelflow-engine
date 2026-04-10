from packages.story_core.engine import StoryEngine
from packages.story_core.models import ChapterSummary, CharacterRelationship, CharacterState, ForeshadowingState, StoryState
from packages.story_core.planner import build_action_briefs, build_chapter_title


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
    assert "Pei An" in [item["name"] for item in bundle.conflict_summary["secondary_conflict"]["participants"]]
    assert bundle.event_beat["turn"] == "pressure spike"
    assert "ledger" in bundle.event_beat["pivot"] or "witness" in bundle.event_beat["pivot"]
    assert "Event beat:" in bundle.body


def test_post_chapter_updates_touch_multiple_conflict_participants():
    story = StoryState(
        story_id="s-019",
        outline="Three factions collide over a witness and a ledger.",
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

    by_name = {character.name: character for character in bundle.updated_story.characters}
    assert by_name["Lin Yue"].memory
    assert by_name["Su Wan"].memory
    assert by_name["Pei An"].memory
    assert by_name["Lin Yue"].current_emotion == "alert"
    assert by_name["Su Wan"].current_emotion == "alert"
    assert by_name["Pei An"].current_emotion == "wary"


def test_post_chapter_updates_write_role_specific_memories():
    story = StoryState(
        story_id="s-020",
        outline="A witness cracks while three players fight over the truth.",
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
    by_name = {character.name: character for character in bundle.updated_story.characters}

    assert "main clash" in by_name["Lin Yue"].memory[-1]
    assert "main clash" in by_name["Su Wan"].memory[-1]
    assert "side pressure" in by_name["Pei An"].memory[-1]
    assert "witness" in by_name["Lin Yue"].memory[-1]
    assert "witness" in by_name["Su Wan"].memory[-1]
    assert "ledger" in by_name["Pei An"].memory[-1]


def test_post_chapter_updates_seed_role_specific_follow_up_goals():
    story = StoryState(
        story_id="s-021",
        outline="A witness cracks while three players fight over the truth.",
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
    by_name = {character.name: character for character in bundle.updated_story.characters}

    assert by_name["Lin Yue"].goals[0] == "seize control of the witness before Su Wan recovers"
    assert by_name["Su Wan"].goals[0] == "block Lin Yue from taking the witness"
    assert by_name["Pei An"].goals[0] == "stabilize the ledger before the side pressure breaks"


def test_action_briefs_prioritize_urgent_follow_up_intents_over_character_order():
    story = StoryState(
        story_id="s-022",
        outline="The aftermath of one chapter should reorder initiative.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        characters=[
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["stabilize the ledger before the side pressure breaks"],
                current_emotion="wary",
            ),
            CharacterState(
                name="Su Wan",
                role="supporting",
                goals=["block Lin Yue from taking the witness"],
                current_emotion="alert",
            ),
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["seize control of the witness before Su Wan recovers"],
                current_emotion="alert",
            ),
        ],
    )

    briefs = build_action_briefs(story)

    assert [brief["name"] for brief in briefs] == ["Lin Yue", "Su Wan", "Pei An"]
    assert briefs[0]["goal"] == "seize control of the witness before Su Wan recovers"
    assert briefs[0]["priority"] > briefs[-1]["priority"]


def test_chapter_summary_captures_conflict_and_event_structure():
    story = StoryState(
        story_id="s-023",
        outline="A witness and a ledger pull different players into the same night.",
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
    summary = bundle.chapter_summary

    assert summary["primary_conflict"]["lead"] == "Lin Yue"
    assert summary["primary_conflict"]["opposition"] == "Su Wan"
    assert "Pei An" in [item["name"] for item in summary["secondary_conflict"]["participants"]]
    assert summary["event_beat"]["turn"] == "pressure spike"
    assert "witness" in summary["event_beat"]["pivot"] or "ledger" in summary["event_beat"]["pivot"]
    assert summary["next_focus"]
    assert "Lin Yue" in summary["next_focus"] or "Su Wan" in summary["next_focus"]


def test_chapter_summary_next_focus_points_to_primary_conflict_follow_up():
    story = StoryState(
        story_id="s-026",
        outline="A witness and a ledger pull different players into the same night.",
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
    summary = bundle.chapter_summary

    assert summary["next_focus"]
    assert "Lin Yue" in summary["next_focus"]
    assert "Su Wan" in summary["next_focus"]


def test_next_chapter_body_echoes_previous_summary_next_focus():
    story = StoryState(
        story_id="s-027",
        outline="A prior chapter should leave a visible hook in the prose.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=["Can Lin Yue and Su Wan control the witness next?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        foreshadowing=[
            ForeshadowingState(
                text="A hidden letter appears.",
                first_chapter=1,
                status="reinforced",
            )
        ],
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
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

    assert "Next focus:" in bundle.body
    assert "Return to Lin Yue and Su Wan over the witness" in bundle.body


def test_next_chapter_body_uses_next_focus_as_opening_hook():
    story = StoryState(
        story_id="s-028",
        outline="A prior chapter should seed the next opening beat.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=["Can Lin Yue and Su Wan control the witness next?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        foreshadowing=[
            ForeshadowingState(
                text="A hidden letter appears.",
                first_chapter=1,
                status="reinforced",
            )
        ],
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
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

    assert bundle.body.startswith("Chapter 2 body. Opening hook:")
    assert "Return to Lin Yue and Su Wan over the witness" in bundle.body


def test_next_outline_uses_previous_summary_next_focus():
    story = StoryState(
        story_id="s-029",
        outline="A prior chapter should shape the next planning pass.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=["Can Lin Yue and Su Wan control the witness next?"],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        foreshadowing=[
            ForeshadowingState(
                text="A hidden letter appears.",
                first_chapter=1,
                status="reinforced",
            )
        ],
        world_facts=["Chapter 1 confirms the investigation is still unfolding."],
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

    assert bundle.next_outline.startswith("Chapter 3:")
    assert "Return to Lin Yue and Su Wan over the witness" in bundle.next_outline


def test_chapter_bundle_includes_generated_chapter_title():
    story = StoryState(
        story_id="s-030",
        outline="A prior chapter should shape the next title as well.",
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

    assert bundle.chapter_title.startswith("Chapter 1:")
    assert "Witness" in bundle.chapter_title
    assert bundle.chapter_summary["chapter_title"] == bundle.chapter_title


def test_build_chapter_title_falls_back_to_pressure_for_generic_conflict():
    title = build_chapter_title(
        1,
        conflict_summary={
            "primary_conflict": {
                "collision": "Lin Yue and Su Wan collide over whether control can be secured.",
            }
        },
    )

    assert title == "Chapter 1: Pressure Crossroads"


def test_build_chapter_title_varies_flavor_by_genre_and_style():
    mystery_title = build_chapter_title(
        1,
        conflict_summary={
            "genre": "mystery",
            "style": "tense",
            "primary_conflict": {
                "collision": "Lin Yue and Su Wan collide over the witness.",
            },
        },
        next_focus="Return to Lin Yue and Su Wan over the witness",
    )
    fantasy_title = build_chapter_title(
        1,
        conflict_summary={
            "genre": "fantasy",
            "style": "noir",
            "primary_conflict": {
                "collision": "Lin Yue and Su Wan collide over the witness.",
            },
        },
        next_focus="Return to Lin Yue and Su Wan over the witness",
    )

    assert mystery_title.startswith("Chapter 1:")
    assert fantasy_title.startswith("Chapter 1:")
    assert "Witness" in mystery_title
    assert "Witness" in fantasy_title
    assert mystery_title != fantasy_title


def test_generate_chapter_assigns_cadence_and_threads_it_into_summary_and_next_outline():
    story = StoryState(
        story_id="s-031",
        outline="A chapter with many factions should feel urgent.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                chapter_title="Chapter 1: Witness Dossier",
                summary="The first clash leaves the witness unresolved.",
                facts=["The witness is still contested."],
                unresolved_threads=[
                    "Who paid for the forgery?",
                    "Who moved the ledger?",
                    "Can Lin Yue keep the witness alive next?",
                ],
                next_focus="Return to Lin Yue and Su Wan over the witness",
                primary_conflict={"lead": "Lin Yue", "opposition": "Su Wan", "collision": "Lin Yue and Su Wan collide over the witness."},
                secondary_conflict={"pressure": "time", "detail": "The court keeps closing ranks.", "participants": [{"name": "Pei An", "goal": "hide the ledger"}]},
                event_beat={"turn": "pressure spike", "pivot": "Lin Yue and Su Wan collide over the witness."},
            )
        ],
        foreshadowing=[ForeshadowingState(text="A hidden letter appears.", first_chapter=1, status="reinforced")],
        characters=[
            CharacterState(name="Lin Yue", role="protagonist", goals=["seize the witness"], current_emotion="alert"),
            CharacterState(name="Su Wan", role="supporting", goals=["block Lin Yue"], current_emotion="defiant"),
            CharacterState(name="Pei An", role="supporting", goals=["hide the ledger"], current_emotion="wary"),
            CharacterState(name="Qin Yu", role="supporting", goals=["expose the forgery"], current_emotion="driven"),
        ],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.cadence == "urgent"
    assert bundle.chapter_summary["cadence"] == "urgent"
    assert "move fast" in bundle.next_outline.lower()


def test_generate_chapter_can_breathe_when_pressure_is_low():
    story = StoryState(
        story_id="s-032",
        outline="A lone investigator needs a quieter step.",
        genre="fantasy",
        style="reflective",
        current_chapter=0,
        characters=[CharacterState(name="Lin Yue", role="protagonist", goals=["hold the line"], current_emotion="neutral")],
    )

    bundle = StoryEngine().generate_next_chapter(story)

    assert bundle.cadence == "breathing"
    assert bundle.chapter_summary["cadence"] == "breathing"
    assert "breathe" in bundle.next_outline.lower()


def test_action_briefs_use_latest_chapter_summary_as_context():
    story = StoryState(
        story_id="s-024",
        outline="The aftermath should shape the next move.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="Lin Yue and Su Wan collide over the witness.",
                facts=["The witness remains contested."],
                unresolved_threads=["Who will control the witness next?"],
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the witness.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the witness.",
                },
            )
        ],
        characters=[
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
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
                current_emotion="grim",
            ),
        ],
    )

    briefs = build_action_briefs(story)

    assert briefs[0]["name"] == "Lin Yue"
    assert briefs[0]["priority"] > briefs[-1]["priority"]
    assert briefs[0]["priority"] >= briefs[1]["priority"]


def test_action_briefs_promote_character_named_in_unresolved_threads():
    story = StoryState(
        story_id="s-025",
        outline="The next move should follow the unresolved thread.",
        genre="mystery",
        style="tense",
        current_chapter=1,
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="The court waits after a cold confrontation over the archives.",
                facts=["The ledger is still hidden in the archives."],
                unresolved_threads=["Can Pei An keep the ledger hidden next?"],
                primary_conflict={
                    "lead": "Lin Yue",
                    "opposition": "Su Wan",
                    "collision": "Lin Yue and Su Wan collide over the archives.",
                },
                secondary_conflict={
                    "pressure": "time",
                    "detail": "The court keeps closing ranks.",
                    "participants": [{"name": "Pei An", "goal": "hide the ledger"}],
                },
                event_beat={
                    "turn": "pressure spike",
                    "pivot": "Lin Yue and Su Wan collide over the archives.",
                },
            )
        ],
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
            CharacterState(
                name="Pei An",
                role="supporting",
                goals=["hold the line"],
                current_emotion="controlled",
            ),
        ],
    )

    briefs = build_action_briefs(story)

    assert briefs[0]["name"] == "Pei An"
    assert briefs[0]["priority"] > briefs[1]["priority"]


def test_story_engine_routes_generation_through_orchestrator():
    story = StoryState(
        story_id="s-030",
        outline="A detective prince uncovers palace crimes.",
        genre="fantasy",
        style="noir",
        characters=[
            CharacterState(
                name="Lin Yue",
                role="protagonist",
                goals=["find the witness"],
            )
        ],
    )

    engine = StoryEngine()
    assert hasattr(engine, "orchestrator")

    bundle = engine.generate_next_chapter(story)
    assert bundle.body
    assert bundle.quality_report["ok"] is True
