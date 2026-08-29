from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def test_canon_service_imports_in_a_fresh_process_without_agent_cycle() -> None:
    root = Path(__file__).resolve().parents[2]
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from packages.story_core.canon.service import CanonService; "
                "from packages.story_core.agents import run_modular_pipeline; "
                "print(CanonService.__name__, callable(run_modular_pipeline))"
            ),
        ],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert "CanonService True" in result.stdout
