from __future__ import annotations

import argparse
import json
import time
import traceback
from pathlib import Path

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.generation_progress import generation_progress


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate a file-backed novel project chapter.")
    parser.add_argument("project_root", help="Path to the exported file project root.")
    parser.add_argument("--chapter", type=int, default=1)
    parser.add_argument("--variant", default=None)
    parser.add_argument("--commit-message", default=None)
    args = parser.parse_args()

    root = Path(args.project_root)

    def reporter(message: str) -> None:
        print(f"{time.strftime('%H:%M:%S')} {message}", flush=True)

    try:
        print(f"{time.strftime('%H:%M:%S')} current-code regeneration started", flush=True)
        with generation_progress(reporter):
            result = FileProjectStore(root).regenerate_chapter(
                args.chapter,
                variant=args.variant,
                commit_message=args.commit_message,
            )
        print("RESULT_JSON " + json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception:
        print("ERROR", flush=True)
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
