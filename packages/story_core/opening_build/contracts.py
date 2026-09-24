"""Typed opening outputs; canonical domain models remain authoritative."""
from pydantic import BaseModel, ConfigDict, Field

from packages.story_core.story_core_card import StoryCoreCard
from packages.story_core.outline_planning import PlanningCharacterCard
from packages.story_core.outline_planning_generation import PlanningCharacterSeed
from packages.story_core.project_outline import OverallOutline, ArcOutline, StoryNode, ChapterPlan
from packages.story_core.relationship_graph import RelationshipEdge


class Output(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StoryCoreOutput(Output):
    story_core: StoryCoreCard


class CharacterSeedsOutput(Output):
    character_seeds: list[PlanningCharacterSeed] = Field(min_length=4, max_length=6)


class CharactersOutput(Output):
    characters: list[PlanningCharacterCard] = Field(min_length=4, max_length=6)


class RelationshipsOutput(Output):
    relationships: list[RelationshipEdge] = Field(min_length=1, max_length=30)


class StoryEngine(Output):
    core_loop: str = Field(min_length=1, max_length=1000)
    escalation: list[str] = Field(min_length=1, max_length=12)
    relationship_pressure: list[str] = Field(min_length=1, max_length=12)
    ending_payoff: str = Field(min_length=1, max_length=1000)


class StoryEngineOutput(Output):
    story_engine: StoryEngine


class BookOutput(Output):
    overall: OverallOutline


class VolumesOutput(Output):
    arcs: list[ArcOutline] = Field(min_length=1, max_length=20)


class EventChain(Output):
    arc_id: str = Field(min_length=1)
    nodes: list[StoryNode] = Field(min_length=1, max_length=30)


class EventsOutput(Output):
    event_chains: list[EventChain] = Field(min_length=1, max_length=20)


class ChapterOutput(Output):
    chapter: ChapterPlan


MODELS = {
    "story_core": StoryCoreOutput,
    "character_seeds": CharacterSeedsOutput,
    "detailed_characters": CharactersOutput,
    "relationships": RelationshipsOutput,
    "longform_story_engine": StoryEngineOutput,
    "book_outline": BookOutput,
    "volume_plan": VolumesOutput,
    "event_chains": EventsOutput,
}


def output_model(task_id):
    return ChapterOutput if task_id.startswith("chapter_outline_") else MODELS.get(task_id)
