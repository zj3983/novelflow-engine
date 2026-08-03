"""Primary body generation, one empty retry, and optional expansion."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


WriterModelCall = Callable[[str, str, float | None], tuple[str, str]]
WritingEvent = Callable[[str, dict[str, Any]], None]


@dataclass(frozen=True)
class WritingStageResult:
    ok: bool
    body: str = ""
    error: str = ""
    expanded: bool = False


def generate_chapter_body(
    *,
    body_prompt: str,
    chapter_number: int,
    writer_plan: dict[str, Any],
    call_model: WriterModelCall,
    postprocess: Callable[[str], str],
    should_expand: Callable[[str, dict[str, Any]], bool],
    build_expansion_prompt: Callable[[str], str],
    expansion_is_acceptable: Callable[[str, str], bool],
    expansion_timeout_seconds: float,
    on_event: WritingEvent | None = None,
) -> WritingStageResult:
    body, body_error = call_model(body_prompt, f"整章写作 第{chapter_number}章", None)
    if not body.strip() and (not body_error or "正文返回为空" in body_error):
        if on_event:
            on_event("empty_retry", {"error": body_error or "body_empty"})
        retry_prompt = "\n".join(
            [
                body_prompt,
                "上一次没有返回正文。请重新完成本章，只输出完整小说正文，不要解释、提纲或代码块。",
            ]
        )
        body, body_error = call_model(retry_prompt, f"整章写作重试 第{chapter_number}章", None)
    if body_error or not body.strip():
        return WritingStageResult(ok=False, error=body_error or "body_empty")

    body = postprocess(body)
    expanded = False
    if should_expand(body, writer_plan):
        if on_event:
            on_event("expansion_start", {"body": body})
        expanded_body, expand_error = call_model(
            build_expansion_prompt(body),
            f"章节扩写 第{chapter_number}章",
            expansion_timeout_seconds,
        )
        if expand_error:
            return WritingStageResult(ok=False, error=f"章节扩写失败：{expand_error}")
        candidate_body = postprocess(expanded_body)
        if expansion_is_acceptable(body, candidate_body):
            if on_event:
                on_event("expansion_complete", {"before": body, "after": candidate_body})
            body = candidate_body
            expanded = True
    return WritingStageResult(ok=True, body=body, expanded=expanded)
