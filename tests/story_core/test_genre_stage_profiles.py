import subprocess
import sys
from dataclasses import fields, is_dataclass
from inspect import Parameter, signature
from pathlib import Path
from types import SimpleNamespace
from typing import get_type_hints

import pytest

from packages.story_core.genre_stages.base import (
    BodyPostprocessor,
    ChapterReviewer,
    ChapterPhaseRenderer,
    DirectorRenderer,
    DirectorPlanReviewer,
    GenreStageProfile,
    LengthPromptRenderer,
    RevisionRenderer,
    SceneCardPreparer,
    WriterContextPreparer,
    WriterRenderer,
)
from packages.story_core.genre_stages.registry import genre_stage_profile_for
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def _story(*, story_id: str, outline: str, genre: str, genre_plugin_ids=None) -> StoryState:
    return StoryState(
        story_id=story_id,
        outline=outline,
        genre=genre,
        genre_plugin_ids=genre_plugin_ids or [],
        style="",
    )


def test_registry_returns_game_profile_only_for_game_story():
    game = _story(story_id="game", outline="玩家进入虚拟世界", genre="网游")

    assert genre_stage_profile_for(game).profile_id == "game_webnovel"


@pytest.mark.parametrize("genre", ["修仙", "玄幻", "都市", "悬疑"])
def test_registry_returns_generic_profile_for_non_game_genres(genre):
    story = _story(story_id=genre, outline="故事开场", genre=genre)

    assert genre_stage_profile_for(story).profile_id == "generic"


def test_registry_uses_normalized_explicit_story_type():
    game = _story(
        story_id="explicit-game",
        outline="新世界开启",
        genre="",
        genre_plugin_ids=["game_webnovel"],
    )
    non_game = _story(
        story_id="explicit-suspense",
        outline="玩家进入虚拟世界",
        genre="网游",
        genre_plugin_ids=["suspense"],
    )

    assert genre_stage_profile_for(game, plan={"genre": "suspense"}).profile_id == "game_webnovel"
    assert genre_stage_profile_for(non_game).profile_id == "generic"


def test_profile_contract_exposes_generation_and_postprocess_stages():
    profile = genre_stage_profile_for(
        _story(story_id="generic", outline="旧案重查", genre="悬疑")
    )

    assert callable(profile.render_director_prompt)
    assert callable(profile.render_writer_prompt)
    assert callable(profile.review_chapter)
    assert callable(profile.render_revision_prompt)
    assert callable(profile.render_expansion_prompt)
    assert callable(profile.render_compression_prompt)
    assert callable(profile.postprocess_body)
    assert callable(profile.chapter_phase)
    assert callable(profile.review_director_plan)
    assert callable(profile.prepare_scene_cards)
    assert callable(profile.prepare_writer_context)


def test_profile_contract_is_frozen_dataclass_with_exact_stage_fields():
    assert is_dataclass(GenreStageProfile)
    assert GenreStageProfile.__dataclass_params__.frozen is True
    assert tuple(field.name for field in fields(GenreStageProfile)) == (
        "profile_id",
        "director_template_key",
        "render_director_prompt",
        "render_writer_prompt",
        "review_chapter",
        "render_revision_prompt",
        "render_expansion_prompt",
        "render_compression_prompt",
        "postprocess_body",
        "chapter_phase",
        "review_director_plan",
        "prepare_scene_cards",
        "prepare_writer_context",
        "stage_modules",
    )

    type_hints = get_type_hints(GenreStageProfile)
    assert type_hints == {
        "profile_id": str,
        "director_template_key": str,
        "render_director_prompt": DirectorRenderer,
        "render_writer_prompt": WriterRenderer,
        "review_chapter": ChapterReviewer,
        "render_revision_prompt": RevisionRenderer,
        "render_expansion_prompt": LengthPromptRenderer,
        "render_compression_prompt": LengthPromptRenderer,
        "postprocess_body": BodyPostprocessor,
        "chapter_phase": ChapterPhaseRenderer,
        "review_director_plan": DirectorPlanReviewer,
        "prepare_scene_cards": SceneCardPreparer,
        "prepare_writer_context": WriterContextPreparer,
        "stage_modules": dict[str, tuple[str, ...]],
    }


@pytest.mark.parametrize(
    ("genre", "expected"),
    [
        (
            "悬疑",
            {
                "director": ("generic.director",),
                "writer": ("common.writer",),
                "review": ("generic.review",),
                "revision": ("common.revision",),
                "length": ("generic.length",),
                "postprocess": ("common.postprocess",),
            },
        ),
        (
            "网游",
            {
                "director": ("game_webnovel.director",),
                "writer": ("game_webnovel.writer",),
                "review": ("game_webnovel.review",),
                "revision": ("game_webnovel.revision",),
                "length": ("game_webnovel.length",),
                "postprocess": ("game_webnovel.postprocess",),
            },
        ),
    ],
)
def test_profiles_are_the_single_source_for_stage_specific_runtime_modules(genre, expected):
    profile = genre_stage_profile_for(
        _story(story_id=f"modules-{genre}", outline="故事开场", genre=genre)
    )

    assert {stage: profile.modules_for(stage) for stage in expected} == expected
    assert profile.modules_for("unknown") == ()


def test_profiles_own_director_template_keys():
    generic = genre_stage_profile_for(
        _story(story_id="generic-template", outline="旧案重查", genre="悬疑")
    )
    game = genre_stage_profile_for(
        _story(story_id="game-template", outline="进入虚拟世界", genre="网游")
    )

    assert generic.director_template_key == "director_generic"
    assert game.director_template_key == "director"


@pytest.mark.parametrize(
    ("renderer", "parameter_names"),
    [
        (DirectorRenderer, ("story", "chapter_number", "plan", "values")),
        (WriterRenderer, ("context",)),
        (ChapterReviewer, ("context",)),
        (RevisionRenderer, ("context",)),
        (LengthPromptRenderer, ("context",)),
        (BodyPostprocessor, ("context",)),
        (DirectorPlanReviewer, ("context",)),
        (SceneCardPreparer, ("context",)),
    ],
)
def test_stage_protocols_require_named_keyword_only_arguments(renderer, parameter_names):
    parameters = tuple(signature(renderer.__call__).parameters.values())[1:]

    assert tuple(parameter.name for parameter in parameters) == parameter_names
    assert all(parameter.kind is Parameter.KEYWORD_ONLY for parameter in parameters)


def test_profiles_use_real_implementations_for_all_four_stages():
    for genre in ("悬疑", "网游"):
        profile = genre_stage_profile_for(
            _story(story_id=f"real-stages-{genre}", outline="故事开场", genre=genre)
        )
        for stage_name in (
            "render_director_prompt",
            "render_writer_prompt",
            "review_chapter",
            "render_revision_prompt",
            "render_expansion_prompt",
            "render_compression_prompt",
            "postprocess_body",
            "chapter_phase",
            "review_director_plan",
            "prepare_scene_cards",
        ):
            stage = getattr(profile, stage_name)
            assert callable(stage)
            assert not stage.__name__.startswith("inactive_")


def test_importing_registry_does_not_eagerly_import_stage_profiles():
    script = """
import importlib
import sys

importlib.import_module("packages.story_core.genre_stages.registry")

eager_modules = {
    "packages.story_core.genre_stages.generic",
    "packages.story_core.genre_stages.game_webnovel",
}
loaded_eager_modules = eager_modules.intersection(sys.modules)
if loaded_eager_modules:
    raise RuntimeError(f"eager stage imports: {sorted(loaded_eager_modules)}")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


@pytest.mark.parametrize(
    ("genre", "expected_profile", "module_that_must_remain_unloaded"),
    [
        ("悬疑", "generic", "packages.story_core.genre_stages.game_webnovel"),
        ("网游", "game_webnovel", "packages.story_core.genre_stages.generic"),
    ],
)
def test_registry_resolution_imports_only_the_selected_profile(
    genre, expected_profile, module_that_must_remain_unloaded
):
    script = f"""
import sys

from packages.story_core.genre_stages.registry import genre_stage_profile_for

story = {{"genre": {genre!r}, "genre_plugin_ids": []}}
profile = genre_stage_profile_for(story)
if profile.profile_id != {expected_profile!r}:
    raise RuntimeError(f"unexpected profile: {{profile.profile_id}}")
if {module_that_must_remain_unloaded!r} in sys.modules:
    raise RuntimeError("unselected profile module was imported")
"""
    result = subprocess.run(
        [sys.executable, "-B", "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def _revision_context(genre: str) -> SimpleNamespace:
    story = _story(story_id=f"revision-{genre}", outline="故事开场", genre=genre)
    plan = {"target_chars": {"min": 4200, "max": 5000}}
    return SimpleNamespace(
        story=story,
        chapter_number=1,
        body="原正文。",
        plan=plan,
        review={"issues": ["补足行动反馈。"], "revision_plan": ["局部补出可见后果。"]},
        writer_context=StoryOrchestrator()._build_writer_context(story, 1, plan),
    )


def test_generic_revision_stage_keeps_game_fact_locks_out_of_xianxia_prompt():
    profile = genre_stage_profile_for(
        _story(story_id="generic-revision", outline="雪山神殿重校器纹", genre="修仙")
    )

    prompt = profile.render_revision_prompt(context=_revision_context("修仙"))
    fact_lock = prompt.split("事实锁硬规则：", 1)[1].split("；", 1)[0]

    assert "人物身份、能力、伤势、持有物、关系、地点和各自知情范围" in fact_lock
    for game_term in ("职业", "余额", "库存", "任务", "装备", "NPC"):
        assert game_term not in fact_lock


def test_game_revision_stage_retains_web_game_fact_locks():
    profile = genre_stage_profile_for(
        _story(story_id="game-revision", outline="玩家进入虚拟世界", genre="网游")
    )

    prompt = profile.render_revision_prompt(context=_revision_context("网游"))

    assert "职业、余额、库存、任务、装备和NPC能知道什么/不知道什么" in prompt


def test_generic_review_stage_returns_empty_genre_contribution():
    profile = genre_stage_profile_for(
        _story(story_id="generic-review", outline="故事开场", genre="悬疑")
    )

    assert profile.review_chapter(context={}) == {
        "pass": True,
        "scores": {},
        "issues": [],
        "revision_plan": [],
        "active_genre_reviews": {},
    }
