from __future__ import annotations

import json
from typing import Any


def first_chapter_trade_authorized(
    event_plan: dict[str, Any] | None = None,
    world_facts: list[str] | None = None,
) -> bool:
    """Return whether this project's chapter-one contract requires a real trade payoff."""

    context = "\n".join(
        [
            json.dumps(event_plan or {}, ensure_ascii=False),
            *[str(item) for item in (world_facts or [])],
        ]
    )
    strong_markers = (
        "第一章必须通过裂纹狼心担保交易",
        "第一章必须解决现实急账",
        "第一章通过裂纹狼心担保交易解决",
        "第一章的裂纹狼心担保交易",
        "第一章已经通过担保交易解决现实急账",
        "第一章已通过担保交易解决现实急账",
    )
    return any(marker in context for marker in strong_markers)
