"""Source-bound permission for review corrections, never a replacement for Canon."""
from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
from typing import Any

from packages.story_core.contextual_prose_review import chapter_review_plan


def with_previous_confirmed_prose(store: Any, snapshot: dict, chapter_number: int) -> dict:
    """Include the actual previous chapter when compact Canon omits a detail."""
    result = deepcopy(snapshot)
    previous = chapter_number - 1
    if previous < 1 or result.get("as_of_chapter") != previous or result.get("stale_base_state"):
        return result
    # chapter() reads committed chapter storage, never the candidate directory.
    body = str(store.chapter(previous).get("body") or "")
    # A bounded, verbatim tail supplies ending-state details without duplicating
    # the entire previous chapter in the consistency prompt. Omission is not
    # proof of absence; this is explicitly an excerpt, not a full inventory.
    excerpt = body[-600:]
    if len(body) > 600:
        boundary = excerpt.find("\n")
        if boundary < 0:
            boundary = excerpt.find("。")
        excerpt = excerpt[boundary + 1:] if boundary >= 0 else ""
    excerpt = excerpt.strip()
    if excerpt:
        result.setdefault("facts", []).append({
            "field": "confirmed_prose_tail_excerpt_not_full_inventory", "chapter_number": previous,
            "source": f"confirmed_chapter_body:{previous:04d}:tail",
            "value": excerpt, "evidence": excerpt,
        })
    return result


def correction_contract(root: Any, chapter_number: int, quality: dict, body: str) -> dict:
    plan = chapter_review_plan(root, chapter_number)
    findings = []
    seen = set()
    for name in ("contextual_prose_review", "writing_review", "review_result", "simplified_review"):
        report = quality.get(name) or {}
        if not isinstance(report, dict):
            continue
        for field in ("annotations", "findings", "issues", "blocking", "revision_plan"):
            for raw in report.get(field) or []:
                item = raw if isinstance(raw, dict) else {"message": str(raw)}
                message = str(item.get("message") or item.get("suggestion") or "").strip()
                # A stale length finding cannot authorize story changes.
                code = str(item.get("code") or "")
                if not message or message in seen or "length" in code or code in {"body_too_short", "body_too_long"}:
                    continue
                seen.add(message)
                findings.append({"ref": f"review:{len(findings)}", **{
                    k: deepcopy(item[k]) for k in ("code", "message", "suggestion", "evidence", "quotes") if k in item}})
    return {
        "schema": "review-correction/v1",
        "mode": "review_correction" if plan and findings else "expression_only",
        "chapter_number": chapter_number,
        "source_body_sha256": sha256(body.encode("utf-8")).hexdigest(),
        "review_findings": findings,
        "plan_sources": [{"ref": f"plan:{key}", "value": deepcopy(value)} for key, value in plan.items()],
    }


CORRECTION_RULE = (
    "模式为review_correction时，允许修正审查指出且本章章纲明确支持的错误；"
    "每个事实改动必须有review引用作为问题依据，并有plan引用或章前Canon作为正确内容依据，且不得违反章前Canon。"
    "修正本章前后自相矛盾时，也可依据原稿中明确实际发生的动作原句，不能以有歧义的概述或角色猜测作为事实；"
    "字词计数、章节编号泄漏等可直接核验的文字错误不需要章纲另行授权。"
    "章纲只规定本章允许发生什么，不证明事情已经发生；新事实必须在新正文中实际发生。"
    "表达等价比较以剧情与状态事实为准：改问号、明确原有对话对象、展开已有动作，"
    "若未改变知情边界、判断结果、数量、位置、因果或事件顺序，不算新增剧情事实；不能机械判为越界。"
    "没有双重依据的部分只能润色，保留人物、事件顺序、动作结果、伤势、数字、物品和章末落点。"
    "不得自行新增数字、危机、惩罚、损失或补写计划外情节。无法确定的冲突交给复审，不可虚称修好。"
)
