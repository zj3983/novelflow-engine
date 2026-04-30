from __future__ import annotations

import re
from typing import Any


def apply_spot_fix_patches(original: str, patches: list[dict[str, str]]) -> dict[str, Any]:
    """Apply exact, local text replacements.

    Ambiguous targets are skipped instead of guessed. This keeps patching in the
    expression layer and avoids accidental changes to unrelated facts.
    """

    current = original
    applied = 0
    skipped = 0
    touched_chars = 0

    for patch in patches:
        target = str(patch.get("target_text") or "")
        replacement = str(patch.get("replacement_text") or "")
        if not target:
            skipped += 1
            continue

        result = _replace_unique(current, target, replacement)
        if result is None:
            result = _replace_unique_normalized(current, target, replacement)

        if result is None:
            skipped += 1
            continue

        current = result
        applied += 1
        touched_chars += len(target)

    return {
        "applied": applied > 0 and current != original,
        "revised_content": current,
        "applied_patch_count": applied,
        "skipped_patch_count": skipped,
        "touched_chars": touched_chars,
        "rejected_reason": "No patches could be matched uniquely." if applied == 0 and patches else None,
    }


def _replace_unique(content: str, target: str, replacement: str) -> str | None:
    start = content.find(target)
    if start < 0:
        return None
    if content.find(target, start + len(target)) >= 0:
        return None
    return content[:start] + replacement + content[start + len(target) :]


def _replace_unique_normalized(content: str, target: str, replacement: str) -> str | None:
    normalized_target = _normalize_spaces(target)
    if len(normalized_target) < 10:
        return None

    spans = _normalized_spans(content)
    normalized_content = "".join(item[0] for item in spans).strip()
    match_start = normalized_content.find(normalized_target)
    if match_start < 0:
        return None
    if normalized_content.find(normalized_target, match_start + len(normalized_target)) >= 0:
        return None

    original_start = _map_normalized_index(spans, match_start)
    original_end = _map_normalized_index(spans, match_start + len(normalized_target), end=True)
    if original_start is None or original_end is None:
        return None
    return content[:original_start] + replacement + content[original_end:]


def _normalize_spaces(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _normalized_spans(content: str) -> list[tuple[str, int, int]]:
    spans: list[tuple[str, int, int]] = []
    in_space = False
    space_start = 0
    for index, char in enumerate(content):
        if char.isspace():
            if not in_space:
                in_space = True
                space_start = index
            continue
        if in_space:
            spans.append((" ", space_start, index))
            in_space = False
        spans.append((char, index, index + 1))
    if in_space:
        spans.append((" ", space_start, len(content)))
    while spans and spans[0][0] == " ":
        spans.pop(0)
    while spans and spans[-1][0] == " ":
        spans.pop()
    return spans


def _map_normalized_index(spans: list[tuple[str, int, int]], index: int, *, end: bool = False) -> int | None:
    if index == len(spans):
        return spans[-1][2] if spans else 0
    if index < 0 or index > len(spans):
        return None
    _, start, finish = spans[index]
    return finish if end else start
