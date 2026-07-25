from __future__ import annotations

from typing import Any

from packages.story_core.web_game_economy import first_chapter_market_exchange_authorized


def first_chapter_trade_authorized(
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
) -> bool:
    """Compatibility alias for the chapter-one market/exchange authorization."""

    return first_chapter_market_exchange_authorized(event_plan, world_facts)
