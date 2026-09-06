from __future__ import annotations

from packages.story_core.genre_stages.base import (
    GenreStageProfile,
)
from packages.story_core.genre_stages.game_webnovel.director import (
    DIRECTOR_TEMPLATE_KEY,
    game_chapter_phase,
    prepare_game_scene_cards,
    render_game_director_prompt,
    review_game_director_plan,
)
from packages.story_core.genre_stages.game_webnovel.length import (
    render_game_compression_prompt,
    render_game_expansion_prompt,
    render_game_polish_prompt,
)
from packages.story_core.genre_stages.game_webnovel.postprocess import postprocess_game_body
from packages.story_core.genre_stages.game_webnovel.writer import (
    prepare_game_writer_context,
    render_game_writer_prompt,
)
from packages.story_core.genre_stages.game_webnovel.review import review_game_chapter
from packages.story_core.genre_stages.game_webnovel.revision import render_game_revision_prompt


GAME_WEBNOVEL_STAGES = GenreStageProfile(
    profile_id="game_webnovel",
    director_template_key=DIRECTOR_TEMPLATE_KEY,
    render_director_prompt=render_game_director_prompt,
    render_writer_prompt=render_game_writer_prompt,
    review_chapter=review_game_chapter,
    render_revision_prompt=render_game_revision_prompt,
    render_expansion_prompt=render_game_expansion_prompt,
    render_compression_prompt=render_game_compression_prompt,
    render_polish_prompt=render_game_polish_prompt,
    postprocess_body=postprocess_game_body,
    chapter_phase=game_chapter_phase,
    review_director_plan=review_game_director_plan,
    prepare_scene_cards=prepare_game_scene_cards,
    prepare_writer_context=prepare_game_writer_context,
    stage_modules={
        "director": ("game_webnovel.director",),
        "writer": ("game_webnovel.writer",),
        "review": ("game_webnovel.review",),
        "revision": ("game_webnovel.revision",),
        "length": ("game_webnovel.length",),
        "postprocess": ("game_webnovel.postprocess",),
    },
)
