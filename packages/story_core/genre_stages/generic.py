from __future__ import annotations

from packages.story_core.genre_stages.base import (
    GenreStageProfile,
)
from packages.story_core.genre_stages.common_revision import render_common_revision_prompt
from packages.story_core.genre_stages.length_prompts import (
    empty_director_plan_review,
    identity_scene_cards,
    render_generic_compression_prompt,
    render_generic_expansion_prompt,
)
from packages.story_core.genre_stages.postprocess import normalize_generated_body
from packages.story_core.prompt_templates import (
    get_effective_prompt_template,
    render_prompt_template,
)
from packages.story_core.genre_stages.common_writer import build_common_writer_sections


DIRECTOR_TEMPLATE_KEY = "director_generic"


def prepare_generic_writer_context(*, context):
    return context


def render_generic_writer_prompt_raw(*, context) -> str:
    sections = build_common_writer_sections(context)
    return render_prompt_template(
        get_effective_prompt_template("writer"),
        {key: "\n".join(lines) for key, lines in sections.items()},
    ).strip()


def render_generic_writer_prompt(*, context) -> str:
    return render_generic_writer_prompt_raw(context=context)


def review_generic_chapter(*, context) -> dict:
    return {
        "pass": True,
        "scores": {},
        "issues": [],
        "revision_plan": [],
        "active_genre_reviews": {},
    }


def render_generic_revision_prompt(*, context) -> str:
    return render_common_revision_prompt(
        context=context,
        base_prompt=render_generic_writer_prompt_raw(context=context.writer_context),
    )


def _generic_chapter_phase(chapter_number: int) -> str:
    if chapter_number <= 3:
        return f"黄金三章第{chapter_number}章：推进当前核心矛盾，兑现一个具体进展，并留下下一步行动"
    return "常规连载章节：目标、行动、结果、代价和章末钩子"


def render_generic_director_prompt(
    *,
    story,
    chapter_number: int = 0,
    plan=None,
    values=None,
) -> str:
    prompt_values = {
        "chapter_number": str(chapter_number),
        "chapter_phase": _generic_chapter_phase(chapter_number),
        "project_snapshot": values["project_snapshot"],
        "chapter_seed": values["chapter_seed"],
        "character_cards": values["character_cards"],
    }
    return render_prompt_template(
        get_effective_prompt_template(DIRECTOR_TEMPLATE_KEY),
        prompt_values,
    )


GENERIC_STAGES = GenreStageProfile(
    profile_id="generic",
    director_template_key=DIRECTOR_TEMPLATE_KEY,
    render_director_prompt=render_generic_director_prompt,
    render_writer_prompt=render_generic_writer_prompt,
    review_chapter=review_generic_chapter,
    render_revision_prompt=render_generic_revision_prompt,
    render_expansion_prompt=render_generic_expansion_prompt,
    render_compression_prompt=render_generic_compression_prompt,
    postprocess_body=normalize_generated_body,
    chapter_phase=_generic_chapter_phase,
    review_director_plan=empty_director_plan_review,
    prepare_scene_cards=identity_scene_cards,
    prepare_writer_context=prepare_generic_writer_context,
    stage_modules={
        "director": ("generic.director",),
        "writer": ("common.writer",),
        "review": ("generic.review",),
        "revision": ("common.revision",),
        "length": ("generic.length",),
        "postprocess": ("common.postprocess",),
    },
)
