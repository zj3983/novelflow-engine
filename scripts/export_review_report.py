#!/usr/bin/env python3
"""Export a markdown review report for an exported chapter.

Usage:
    python scripts/export_review_report.py path/to/chapter_body.txt

Looks for a sibling ``*_metadata*.json`` (same stem prefix) to pull the
chapter metadata. Constructs a minimal ``StoryState`` plus an ``event_plan``
shim, runs ``_review_chapter_body``, and writes ``<stem>_review.md`` next to
the source file.

Designed for the ``chapter_exports/`` audit loop: any time a chapter is
exported via the orchestrator's manual flow, this script can produce a
one-glance reviewer verdict without re-running generation.
"""
from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from packages.story_core.models import CharacterState, StoryState  # noqa: E402
from packages.story_core.orchestrator import _review_chapter_body  # noqa: E402
from packages.story_core.review_report import format_review_report  # noqa: E402


def _find_sidecar_metadata(body_path: Path) -> Path | None:
    """Find a sibling metadata.json file.

    Common chapter_exports naming pattern is::

        rewrite_ch1_regen_20260507.txt
        rewrite_ch1_regen_metadata_20260507.json

    We try (in order):
      1. ``{stem}_metadata.json`` (no infix)
      2. ``{stem-without-trailing-date}_metadata_{date}.json`` (date moved)
      3. ``{stem}.metadata.json``

    Strict matches only — no fuzzy glob fallback (which causes wrong-file
    pickups when multiple chapter exports share token prefixes).
    """
    stem = body_path.stem
    parent = body_path.parent
    candidates: list[Path] = []

    # 1. Direct suffix
    candidates.append(parent / f"{stem}_metadata.json")
    # 2. Trailing date pattern: split off a final _YYYYMMDD chunk and re-insert
    parts = stem.rsplit("_", 1)
    if len(parts) == 2 and parts[1].isdigit() and len(parts[1]) >= 6:
        head, date = parts
        candidates.append(parent / f"{head}_metadata_{date}.json")
    # 3. Dot-separated metadata convention
    candidates.append(parent / f"{stem}.metadata.json")

    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def _build_story_and_event_plan(metadata: dict) -> tuple[StoryState, dict, int]:
    summary = metadata.get("summary") or {}
    chapter_number = int(summary.get("chapter_number") or metadata.get("chapter_number") or 1)
    facts = list(summary.get("facts") or [])
    next_focus = str(summary.get("next_focus") or metadata.get("next_outline") or "").strip()
    title = str(summary.get("chapter_title") or metadata.get("title") or "").strip()

    # Heuristic: pull protagonist hint from facts text.
    name = "苏叶"
    game_id = "夜烬"
    facts_blob = "\n".join(str(f) for f in facts)
    for token in ("苏叶", "夜烬"):
        if token in facts_blob:
            pass  # default already covers this demo project

    story = StoryState(
        story_id="cli-review",
        outline=next_focus[:500],
        genre="网游",
        style="升级流",
        characters=[CharacterState(name=name, role="主角", game_id=game_id)],
        world_facts=facts,
    )

    primary_conflict = summary.get("primary_conflict") or {}
    event_beat = summary.get("event_beat") or {}
    event_plan = {
        "chapter_title": title,
        "turn": event_beat.get("turn", ""),
        "pivot": event_beat.get("pivot", ""),
        "next_focus": next_focus,
        "explicit_chapter_end_hook": next_focus
        or primary_conflict.get("collision", ""),
        "world_reactions": [],
    }
    return story, event_plan, chapter_number


def main() -> int:
    parser = argparse.ArgumentParser(description="Export a markdown review report for a chapter body file.")
    parser.add_argument("body_path", type=Path, help="Path to the chapter body .txt file")
    parser.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Optional explicit metadata.json path (auto-detected by default)",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=None,
        help="Output markdown path (default: <body>_review.md alongside body)",
    )
    args = parser.parse_args()

    if not args.body_path.exists():
        print(f"error: body file not found: {args.body_path}", file=sys.stderr)
        return 2

    metadata_path = args.metadata or _find_sidecar_metadata(args.body_path)
    if metadata_path is None or not metadata_path.exists():
        print(
            "error: no metadata.json found alongside body file. Pass --metadata explicitly.",
            file=sys.stderr,
        )
        return 2

    body = io.open(args.body_path, encoding="utf-8").read()
    metadata = json.load(io.open(metadata_path, encoding="utf-8"))
    story, event_plan, chapter_number = _build_story_and_event_plan(metadata)

    review = _review_chapter_body(
        chapter_number=chapter_number,
        body=body,
        event_plan=event_plan,
        world_facts=story.world_facts,
        story=story,
    )

    body_chars = len("".join(body.split()))
    md = format_review_report(review, chapter_number=chapter_number, body_chars=body_chars)

    out_path = args.out or args.body_path.with_name(f"{args.body_path.stem}_review.md")
    io.open(out_path, "w", encoding="utf-8").write(md)
    print(f"wrote review report → {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
