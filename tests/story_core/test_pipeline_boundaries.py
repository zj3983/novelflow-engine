"""Architectural boundary tests for the modular pipeline.

These tests pin the boundaries the migration plan commits to:

* ``StoryEngine`` is a thin entry point that calls the coordinator
  once.
* ``StoryOrchestrator`` carries no provider-specific CLI / API
  branching.
* Writer prompt construction lives only under
  ``packages/story_core/agents/writer``.
* Director prompt construction lives only under
  ``packages/story_core/agents/director``.
* No agent module writes project files directly.
* Generic writer modules do not mention game-only terms such as
  level / inventory / equipment durability / auction-house rules.
"""

from __future__ import annotations

import inspect
import re

import pytest

import packages.story_core.engine as engine_module
import packages.story_core.orchestrator as orchestrator_module


# --- StoryEngine is a thin coordinator --------------------------------------


def test_story_engine_invokes_coordinator_once(monkeypatch):
    """``StoryEngine`` is a thin entry point that delegates to ``StoryOrchestrator``.

    The test stubs out the orchestrator with a recorder and
    asserts the engine calls it once. It does not exercise the
    full pipeline (that is the job of the larger orchestrator and
    pipeline tests).
    """
    calls = {"n": 0, "args": None}

    class _StubOrchestrator:
        def __init__(self, *args, **kwargs):
            pass

        def generate_next_chapter(self, story):
            calls["n"] += 1
            calls["args"] = story
            return object()  # the body is irrelevant for this test

    monkeypatch.setattr(engine_module, "StoryOrchestrator", _StubOrchestrator)
    engine = engine_module.StoryEngine()
    sentinel_story = object()
    engine.generate_next_chapter(sentinel_story)
    assert calls["n"] == 1, "StoryEngine must call the orchestrator exactly once"
    assert calls["args"] is sentinel_story


# --- StoryOrchestrator carries no provider-specific branching ----------------


def test_orchestrator_does_not_import_cli_or_http_branches():
    """The orchestrator must not know about CLI args or HTTP transport.

    Any ``argparse``, ``urllib``, ``requests``, or ``httpx`` import
    is a boundary violation: agent calls go through the gateway.
    """
    source = inspect.getsource(orchestrator_module)
    forbidden = (
        "import argparse",
        "from argparse",
        "import urllib",
        "from urllib",
        "import requests",
        "from requests",
        "import httpx",
        "from httpx",
        "import aiohttp",
        "from aiohttp",
    )
    for needle in forbidden:
        assert needle not in source, (
            f"StoryOrchestrator must not import {needle!r}; route through the model gateway."
        )


# --- Prompt construction lives in the agent modules --------------------------


def test_writer_prompt_construction_lives_under_agents_writer():
    from packages.story_core.agents.writer import build_writer_prompt
    from packages.story_core.agents.contracts import DirectorArtifact, WriterRequest

    director_artifact = DirectorArtifact(
        chapter_number=1,
        chapter_goal="",
        opening_state="",
        scene_beats=[],
        ending_state="",
        hook="",
        entity_requirements=[],
    )
    request = WriterRequest(
        chapter_number=1,
        director_artifact=director_artifact,
        previous_tail="",
        continuity_facts=[],
        character_cards=[],
        entity_cards=[],
        world_rules=[],
        craft_modules=[],
    )
    sample = build_writer_prompt(request)
    assert isinstance(sample, str)
    assert sample.strip()


def test_writer_prompt_keeps_planning_title_strategy_out_of_writer_boundary():
    from packages.story_core.agents.writer import build_writer_prompt
    from packages.story_core.agents.contracts import (
        DirectorArtifact,
        SceneBeat,
        WriterRequest,
    )

    director_artifact = DirectorArtifact(
        chapter_number=12,
        chapter_title="余烬照夜",
        chapter_goal="顾临在钟楼熄灭前救出被困的守夜人",
        opening_state="钟楼起火，楼梯已经断裂。",
        scene_beats=[
            SceneBeat(
                order=1,
                location="旧钟楼",
                action="顾临沿外墙攀上钟室",
                result="他找到守夜人并确认唯一出口",
            )
        ],
        ending_state="两人落到相邻屋顶，钟楼在身后坍塌。",
        hook="守夜人交出一枚刻着王室徽记的钥匙。",
    )
    request = WriterRequest(
        chapter_number=12,
        project_title="诸天薪火",
        director_artifact=director_artifact,
    )

    prompt = build_writer_prompt(request)

    assert "诸天薪火" in prompt
    assert director_artifact.chapter_goal in prompt
    assert director_artifact.opening_state in prompt
    assert director_artifact.scene_beats[0].action in prompt
    assert director_artifact.scene_beats[0].result in prompt
    assert director_artifact.ending_state in prompt
    assert director_artifact.hook in prompt
    for planning_only_text in (
        "核心卖点/能力",
        "章节标题必须对应",
        "满级魔龙",
        "chapter_title_strategy",
        "book_title_candidates",
        "三个候选",
    ):
        assert planning_only_text not in prompt


def test_director_prompt_construction_lives_under_agents_director():
    from packages.story_core.agents.director import build_director_prompt
    from packages.story_core.context.director_context import DirectorContext

    context = DirectorContext(
        chapter_number=1,
        volume={},
        book_outline_summary="",
        previous_chapter_summary="",
        previous_chapter_tail="",
        continuity_ledger=[],
        foreshadowing=[],
        character_cards=[],
        rewrite_guidance="事故只保留关键结果，不展开伤情细节。",
    )
    sample = build_director_prompt(context)
    assert isinstance(sample, str)
    assert sample.strip()
    assert "本次写作指导" in sample
    assert "不展开伤情细节" in sample


# --- No agent writes project files directly ----------------------------------


def test_agent_modules_do_not_write_project_files():
    """Agent modules only build prompts / call the gateway; they
    never touch the filesystem on their own.

    The migration lifts file writes into ``FileProjectStore`` /
    persistence modules; agents stay in-memory.
    """
    forbidden = (
        "_write_json",
        "_write_text",
        "write_json",
        "write_text",
        "write_json_atomic",
        "replace_json_transaction",
        "snapshot_managed_files",
        "restore_managed_files",
    )
    for module_path in (
        "packages/story_core/agents/writer/runtime.py",
        "packages/story_core/agents/writer/agent.py",
        "packages/story_core/agents/writer/prompt.py",
        "packages/story_core/agents/director/runtime.py",
        "packages/story_core/agents/director/agent.py",
        "packages/story_core/agents/director/prompt.py",
        "packages/story_core/agents/consistency/agent.py",
        "packages/story_core/agents/fact_extractor/agent.py",
    ):
        try:
            source = open(module_path, encoding="utf-8").read()
        except FileNotFoundError:
            continue
        for needle in forbidden:
            assert needle not in source, (
                f"{module_path} must not call {needle!r}; that belongs to the persistence layer."
            )


# --- No game-only terms in generic writer modules ---------------------------


_GAME_ONLY_TERMS = (
    "等级",
    "inventory",
    "durability",
    "拍卖行",
    "经验值",
    "HP",
    "MP",
)


@pytest.mark.parametrize("module_path", [
    "packages/story_core/agents/writer/prompt.py",
    "packages/story_core/agents/writer/agent.py",
    "packages/story_core/agents/writer/runtime.py",
])
def test_generic_writer_modules_avoid_game_only_terms(module_path):
    """The generic writer module is genre-agnostic. Game-specific
    vocabulary belongs in genre profiles, not in the shared writer.

    ``HP`` and ``MP`` are allowed only as part of larger identifiers
    (e.g. ``SHIP``) so the regex uses word boundaries.
    """
    import os

    if not os.path.exists(module_path):
        pytest.skip(f"module {module_path} not on disk")
    source = open(module_path, encoding="utf-8").read()
    for term in _GAME_ONLY_TERMS:
        # Word-boundary search for the latin abbreviations so we
        # don't false-positive on identifiers like ``chip``.
        if re.match(r"^[A-Z]+$", term):
            pattern = rf"\b{term}\b"
        else:
            pattern = term
        assert not re.search(pattern, source), (
            f"{module_path} contains game-only term {term!r}; "
            "move it to a genre profile."
        )
