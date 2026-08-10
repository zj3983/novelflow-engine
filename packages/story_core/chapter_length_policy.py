"""Single source of truth for chapter length limits."""

from __future__ import annotations


CHAPTER_HARD_MIN_CHARS = 3800
CHAPTER_TARGET_MIN_CHARS = 4200
CHAPTER_TARGET_MAX_CHARS = 5500
CHAPTER_HARD_MAX_CHARS = 5700
CHAPTER_TARGET_RANGE_TEXT = (
    f"{CHAPTER_TARGET_MIN_CHARS}到{CHAPTER_TARGET_MAX_CHARS}字"
)


def target_chars() -> dict[str, int]:
    return {
        "min": CHAPTER_TARGET_MIN_CHARS,
        "max": CHAPTER_TARGET_MAX_CHARS,
    }


def acceptance_chars() -> dict[str, int]:
    return {
        "min": CHAPTER_HARD_MIN_CHARS,
        "max": CHAPTER_HARD_MAX_CHARS,
    }


__all__ = [
    "CHAPTER_HARD_MIN_CHARS",
    "CHAPTER_TARGET_MIN_CHARS",
    "CHAPTER_TARGET_MAX_CHARS",
    "CHAPTER_HARD_MAX_CHARS",
    "CHAPTER_TARGET_RANGE_TEXT",
    "target_chars",
    "acceptance_chars",
]
