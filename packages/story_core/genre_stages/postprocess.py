from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from packages.story_core.prose_style_review import sanitize_prose_style


@dataclass(frozen=True)
class PostprocessContext:
    story: Any
    body: str
    chapter_number: int
    scene_cards: list[dict[str, Any]]
    outline_anchor: Any = None


def _limit_metaphor_markers(body: str, *, max_like: int = 2) -> str:
    matches = list(re.finditer(r"仿佛|好像", body))
    if len(matches) <= max_like:
        return body
    cleaned = body
    for match in reversed(matches[max(0, max_like) :]):
        cleaned = cleaned[: match.start()] + cleaned[match.end() :]
    return cleaned


def _merge_overfragmented_paragraphs(body: str) -> str:
    paragraphs = [part.strip() for part in body.replace("\r", "\n").split("\n\n") if part.strip()]
    if len(paragraphs) < 40:
        return body

    sentence_marks = re.compile(r"[\u3002\uff01\uff1f!?]")

    def sentence_count(paragraph: str) -> int:
        return len([piece for piece in sentence_marks.split(paragraph) if piece.strip()])

    short_count = sum(1 for part in paragraphs if sentence_count(part) <= 2)
    if short_count / max(1, len(paragraphs)) < 0.45:
        return body

    merged: list[str] = []
    buffer: list[str] = []
    buffer_sentences = 0

    def flush() -> None:
        nonlocal buffer, buffer_sentences
        if buffer:
            merged.append("".join(buffer))
            buffer = []
            buffer_sentences = 0

    for paragraph in paragraphs:
        sentences = sentence_count(paragraph)
        is_opening_dialogue = paragraph.startswith(("\u201c", "\u300e", "\u300c"))
        if sentences <= 2 and not is_opening_dialogue:
            buffer.append(paragraph)
            buffer_sentences += max(1, sentences)
            if buffer_sentences >= 4 or sum(len(item) for item in buffer) >= 260 or len(buffer) >= 5:
                flush()
            continue
        flush()
        merged.append(paragraph)
    flush()
    return "\n\n".join(merged)


def normalize_generated_body(*, context: PostprocessContext) -> str:
    cleaned = sanitize_prose_style(context.body)
    cleaned = re.sub(
        r"(?<=[\u4e00-\u9fff。！？】》])\?(?=[\u4e00-\u9fff【《])",
        "",
        cleaned,
    )
    cleaned = _limit_metaphor_markers(cleaned)
    return _merge_overfragmented_paragraphs(cleaned)
