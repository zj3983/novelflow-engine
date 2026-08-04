from __future__ import annotations

from typing import Any

from packages.story_core.genre_stages.base import GenreStageProfile


def genre_stage_profile_for(story: Any, plan: Any = None) -> GenreStageProfile:
    from packages.story_core.novel_type_catalog import is_game_story_type

    if is_game_story_type(story):
        from packages.story_core.genre_stages.game_webnovel import GAME_WEBNOVEL_STAGES

        return GAME_WEBNOVEL_STAGES

    from packages.story_core.genre_stages.generic import GENERIC_STAGES

    return GENERIC_STAGES
