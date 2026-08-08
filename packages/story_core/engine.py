from __future__ import annotations

from pydantic import BaseModel, Field

from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


class ChapterBundle(BaseModel):
    chapter_number: int
    body: str
    chapter_title: str = ""
    cadence: str = "measured"
    chapter_intent: dict = Field(default_factory=dict)
    character_moves: list[dict] = Field(default_factory=list)
    memory_constraints: dict = Field(default_factory=dict)
    event_plan: dict = Field(default_factory=dict)
    chapter_seed: dict = Field(default_factory=dict)
    simulation_plan: dict = Field(default_factory=dict)
    world_events: list[dict] = Field(default_factory=list)
    scene_cards: list[dict] = Field(default_factory=list)
    simulation_status: dict = Field(default_factory=dict)
    action_briefs: list[dict] = Field(default_factory=list)
    conflict_summary: dict = Field(default_factory=dict)
    event_beat: dict = Field(default_factory=dict)
    character_cards: list[dict] = Field(default_factory=list)
    foreshadowing: list[dict] = Field(default_factory=list)
    next_outline: str
    updated_story: StoryState
    chapter_summary: dict = Field(default_factory=dict)
    quality_report: dict = Field(default_factory=dict)
    pipeline_stages: list[str] = Field(default_factory=list)
    context_snapshot_id: str = ""


class StoryEngine:
    def __init__(
        self,
        orchestrator: StoryOrchestrator | None = None,
        *,
        use_modular_agents: bool = False,
        project_root: Any | None = None,
    ) -> None:
        # The engine is a thin coordinator. When the caller
        # passes an orchestrator we keep its flags untouched;
        # when we build a default orchestrator we forward the
        # engine's flags so a single ``StoryEngine(use_modular_agents=True,
        # project_root=...)`` flips the whole chapter flow.
        if orchestrator is None and (
            use_modular_agents or project_root is not None
        ):
            orchestrator = StoryOrchestrator(
                use_modular_agents=use_modular_agents,
                project_root=project_root,
            )
        self.orchestrator = orchestrator or StoryOrchestrator()

    def generate_next_chapter(
        self,
        story: StoryState,
        *,
        project_root: Any | None = None,
        director_runtime: Any | None = None,
        writer_runtime: Any | None = None,
        fact_extractor: Any | None = None,
    ) -> ChapterBundle:
        # The engine stores the ``project_root`` itself when
        # ``use_modular_agents=True``; the call site does not
        # need to forward it. We still forward the runtime
        # overrides because those are per-call. We use
        # ``inspect.signature`` so test doubles that pre-date
        # the modular main flow keep working — the legacy
        # ``generate_next_chapter`` signature only takes
        # ``story``.
        import inspect

        sig = inspect.signature(self.orchestrator.generate_next_chapter)
        kwargs: dict[str, Any] = {}
        for key, value in (
            ("project_root", project_root),
            ("director_runtime", director_runtime),
            ("writer_runtime", writer_runtime),
            ("fact_extractor", fact_extractor),
        ):
            if key in sig.parameters:
                kwargs[key] = value
        return self.orchestrator.generate_next_chapter(story, **kwargs)
