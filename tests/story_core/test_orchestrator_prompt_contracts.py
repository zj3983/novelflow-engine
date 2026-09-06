import json
from pathlib import Path

import pytest

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


class _StoryCaptured(RuntimeError):
    pass


class _CapturingEngine:
    def __init__(self) -> None:
        self.story: StoryState | None = None

    def generate_next_chapter(self, story: StoryState):
        self.story = story
        raise _StoryCaptured


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _make_outline_project(root: Path, *, current_chapter: int) -> FileProjectStore:
    _write_json(
        root / ".story-system" / "MASTER_SETTING.json",
        {"project": {"project_id": "outline-flow", "title": "Outline Flow"}},
    )
    _write_json(
        root / ".webnovel" / "project.json",
        {
            "project_id": "outline-flow",
            "title": "Outline Flow",
            "active_story_id": "outline-story",
        },
    )
    _write_json(
        root / ".webnovel" / "state.json",
        {
            "story_id": "outline-story",
            "outline": "A serial story.",
            "genre": "fantasy",
            "style": "plain",
            "current_chapter": current_chapter,
            "world_facts": [],
        },
    )
    _write_json(
        root / ".webnovel" / "outline.json",
        {
            "schema_version": "project-outline/v1",
            "overall": {"story": "OVERALL-CONTEXT"},
            "arcs": [
                {
                    "id": "active-arc",
                    "title": "ACTIVE-ARC",
                    "start_chapter": 10,
                    "end_chapter": 15,
                    "goal": "ACTIVE-ARC-GOAL",
                },
                {
                    "id": "future-arc",
                    "title": "FUTURE-ARC-LEAK",
                    "start_chapter": 16,
                    "end_chapter": 20,
                },
            ],
            "chapters": [
                {"chapter_number": 10, "title": "第10章", "goal": "ACTIVE-ARC-START"},
                {"chapter_number": 11, "title": "第11章", "goal": "ACTIVE-ARC-COMMITTED"},
                {"chapter_number": 12, "title": "CHAPTER-12", "goal": "CHAPTER-12-GOAL"},
                {"chapter_number": 13, "title": "CHAPTER-13-LEAK", "goal": "CHAPTER-13-GOAL-LEAK"},
                {"chapter_number": 14, "title": "第14章", "goal": "ACTIVE-ARC-LATE"},
                {"chapter_number": 15, "title": "第15章", "goal": "ACTIVE-ARC-END"},
            ],
        },
    )
    _write_json(
        root / ".story-system" / "chapters" / "0011.json",
        {"chapter_number": 11, "chapter_title": "Previous", "updated_story": {}},
    )
    return FileProjectStore(root)


def test_story_state_outline_context_is_transient_and_reaches_plan_prompt() -> None:
    outline_context = {
        "overall": {"story": "总纲"},
        "active_arc": {"id": "arc-2", "goal": "本阶段目标"},
        "chapter": {"chapter_number": 12, "goal": "本章目标"},
    }
    story = StoryState(
        story_id="prompt-contract",
        outline="旧的一句话梗概",
        genre="玄幻",
        style="白描",
        current_chapter=11,
        outline_context=outline_context,
    )

    prompt = StoryOrchestrator()._plan_prompt(story, 12)

    assert story.outline_context == outline_context
    assert "active_arc" in prompt
    assert "本阶段目标" in prompt
    assert "本章目标" in prompt
    assert "outline_context" not in story.model_dump()


def test_generate_next_chapter_passes_only_target_outline_context(tmp_path: Path) -> None:
    store = _make_outline_project(tmp_path / "novel", current_chapter=11)
    engine = _CapturingEngine()

    with pytest.raises(_StoryCaptured):
        store.generate_next_chapter(engine=engine)

    assert engine.story is not None
    context = engine.story.outline_context
    assert context["overall"]["story"] == "OVERALL-CONTEXT"
    assert context["active_arc"]["id"] == "active-arc"
    assert context["chapter"]["chapter_number"] == 12
    context_text = json.dumps(context, ensure_ascii=False)
    assert "FUTURE-ARC-LEAK" not in context_text
    assert "CHAPTER-13-LEAK" not in context_text
    persisted_state = json.loads((store.root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert "outline_context" not in persisted_state


def test_regenerate_chapter_selects_context_for_rewritten_chapter(tmp_path: Path) -> None:
    store = _make_outline_project(tmp_path / "novel", current_chapter=12)
    engine = _CapturingEngine()

    with pytest.raises(_StoryCaptured):
        store.regenerate_chapter(12, engine=engine)

    assert engine.story is not None
    context = engine.story.outline_context
    assert context["active_arc"]["id"] == "active-arc"
    assert context["chapter"]["title"] == "CHAPTER-12"
    context_text = json.dumps(context, ensure_ascii=False)
    assert "FUTURE-ARC-LEAK" not in context_text
    assert "CHAPTER-13-LEAK" not in context_text
    persisted_state = json.loads((store.root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert "outline_context" not in persisted_state


def test_legacy_writing_packet_projects_only_target_chapter_context(tmp_path: Path) -> None:
    root = tmp_path / "legacy-novel"
    store = _make_outline_project(root, current_chapter=11)
    (root / ".webnovel" / "outline.json").unlink()
    _write_json(
        root / ".webnovel" / "project.json",
        {
            "project_id": "outline-flow",
            "title": "Outline Flow",
            "active_story_id": "outline-story",
            "seed_outline": "LEGACY-OVERALL",
            "world_blueprint": {
                "current_arc": "LEGACY-ACTIVE-ARC",
                "opening_arc": {
                    "chapter_beats": [
                        {
                            "chapter": 12,
                            "title": "LEGACY-CHAPTER-12",
                            "required_payoff": "LEGACY-PAYOFF-12",
                            "ending_hook": "LEGACY-HOOK-12",
                        },
                        {"chapter": 13, "title": "LEGACY-CHAPTER-13-LEAK"},
                    ]
                },
            },
        },
    )

    packet = store.writing_packet(12)

    assert packet["outline_context"]["overall"]["story"] == "LEGACY-OVERALL"
    assert packet["outline_context"]["active_arc"]["goal"] == "LEGACY-ACTIVE-ARC"
    assert packet["outline_context"]["chapter"]["title"] == "LEGACY-CHAPTER-12"
    assert packet["scene_cards"][0]["payoff"] == "LEGACY-PAYOFF-12"
    assert packet["scene_cards"][0]["ending_hook"] == "LEGACY-HOOK-12"
    assert "LEGACY-CHAPTER-13-LEAK" not in json.dumps(packet)
    assert "opening_arc" not in json.dumps(packet)
    assert "current_arc" not in packet["outline_constraints"]
    assert "opening_arc" not in packet["outline_constraints"]
