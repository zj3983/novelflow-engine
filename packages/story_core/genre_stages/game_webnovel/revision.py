from __future__ import annotations

import json
from typing import Any

from packages.story_core.agent_base import compact_list
from packages.story_core.genre_stages.common_revision import RevisionContext, render_common_revision_prompt
from packages.story_core.genre_stages.game_webnovel.writer import render_game_writer_prompt_raw
from packages.story_core.web_game_author_craft import web_game_revision_fact_lock
from packages.story_core.web_game_economy import normalize_legacy_economy_prompt_value
from packages.story_core.web_game_review import FIRST_CHAPTER_FORBIDDEN_TERMS


def _game_revision_forbidden_terms(review: dict[str, Any]) -> list[str]:
    review_text = json.dumps(review, ensure_ascii=False)
    terms = [term for term in FIRST_CHAPTER_FORBIDDEN_TERMS if term in review_text]
    if "第一章提前展开交易线" in review_text:
        terms.extend(("匿名寄售", "寄售成功", "上架成功", "成交", "到账", "手续费", "第一笔铜币落袋", "赵胖子", "盯盘", "商人"))
    if "第一章外部压力过早" in review_text:
        terms.extend(("白袍", "公会", "论坛", "清场", "后勤", "异常低价", "观察名单", "商人脚本"))
    return compact_list(terms, max_items=32, item_chars=24)


def render_game_revision_prompt(*, context: RevisionContext) -> str:
    review = context.review if isinstance(context.review, dict) else {}
    rendered = render_common_revision_prompt(
        context=context,
        base_prompt=render_game_writer_prompt_raw(context=context.writer_context),
        fact_lock=web_game_revision_fact_lock(),
        extra_forbidden_terms=_game_revision_forbidden_terms(review),
    )
    return normalize_legacy_economy_prompt_value(
        rendered,
        game_context=True,
        chapter_number=context.chapter_number,
    )
