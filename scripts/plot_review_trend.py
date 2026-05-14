from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


DEFAULT_LOG = Path("chapter_exports") / "workflow_log.jsonl"


def _load_records(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            records.append(payload)
    return records


def _bar(value: float, *, maximum: float, width: int = 18, fill: str = "#") -> str:
    if maximum <= 0:
        return ""
    count = int(round(max(0.0, min(value, maximum)) / maximum * width))
    return fill * count + "." * (width - count)


def _beats_percent(record: dict[str, Any]) -> str:
    value = record.get("beats_completion")
    if isinstance(value, (int, float)):
        return f"{int(round(float(value) * 100)):3d}%"
    return " n/a"


def render_trend(records: list[dict[str, Any]], *, limit: int = 12) -> str:
    recent = records[-limit:] if limit > 0 else records
    if not recent:
        return "No workflow telemetry records found."

    max_hard = max([int(record.get("hard_count") or 0) for record in recent] + [1])
    max_soft = max([int(record.get("soft_count") or 0) for record in recent] + [1])
    lines = [
        "Review Trend",
        "chapter | op       | hard | soft | beats | hook | failed",
        "-" * 78,
    ]
    for record in recent:
        chapter = str(record.get("chapter") or "?").rjust(7)
        operation = str(record.get("operation") or "")[:8].ljust(8)
        hard = int(record.get("hard_count") or 0)
        soft = int(record.get("soft_count") or 0)
        hook = str(record.get("hook_type") or "-")[:10].ljust(10)
        failed = ",".join(str(item) for item in (record.get("failed_scores") or [])[:4]) or "-"
        lines.append(
            f"{chapter} | {operation} | {hard:>4} {_bar(hard, maximum=max_hard, width=8)} "
            f"| {soft:>4} {_bar(soft, maximum=max_soft, width=8, fill='+')} "
            f"| {_beats_percent(record)} | {hook} | {failed}"
        )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Render workflow review telemetry as an ASCII trend table.")
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG, help="Path to workflow_log.jsonl")
    parser.add_argument("--limit", type=int, default=12, help="Number of recent records to display")
    args = parser.parse_args()

    print(render_trend(_load_records(args.log), limit=args.limit))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
