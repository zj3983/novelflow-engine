"""Create a disposable, synthetic project at a valid confirmed volume boundary."""

from __future__ import annotations

import json
import sys
import types
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

package = types.ModuleType("tests")
package.__path__ = [str(REPOSITORY_ROOT / "tests")]
package.__package__ = "tests"
sys.modules["tests"] = package

from packages.story_core.opening_build import runtime  # noqa: E402
from tests.story_core.test_ongoing_planning import (  # noqa: E402
    _confirm_through,
    two_volume_store,
)


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("usage: seed_end_of_volume.py <isolated-projects-root>")
    projects_root = Path(sys.argv[1]).resolve()
    projects_root.mkdir(parents=True, exist_ok=True)
    run_root = projects_root.parent
    staging_root = run_root / "fixture-staging"
    # The API resolves file:generic_webnovel to this root. The fixture remains
    # explicitly labeled in its test output and project metadata, not inferred
    # from the storage-directory name.
    final_root = projects_root / "generic_webnovel"
    if final_root.exists() or staging_root.exists():
        raise RuntimeError("The per-run fixture location must be new and empty.")

    staging_root.mkdir(parents=True)
    store = two_volume_store(staging_root)
    engine = _confirm_through(store, 50)
    if engine.calls != 50 or int(store.state().get("current_chapter") or 0) != 50:
        raise AssertionError("The fixture must confirm exactly chapters 1 through 50.")
    config = runtime.settings(store)
    if int(config.get("chapter_count") or 0) != 50:
        raise AssertionError("The fixture must publish the first 50-chapter volume.")
    if int((config.get("execution") or {}).get("confirmed_through") or 0) != 50:
        raise AssertionError("The Opening Graph execution ledger must confirm chapter 50.")
    plan = runtime.canonical_plan(store).outline
    if not any(arc.start_chapter == 51 and arc.end_chapter == 60 for arc in plan.arcs):
        raise AssertionError("The fixture must contain a valid planned second volume.")

    store.root.rename(final_root)
    print(
        json.dumps(
            {
                "label": "SYNTHETIC VALID END-OF-VOLUME FIXTURE",
                "project_id": "file:generic_webnovel",
                "confirmed_through": 50,
                "next_volume": [51, 60],
                "root_name": final_root.name,
                "generator_calls": engine.calls,
                "real_provider_calls": 0,
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
