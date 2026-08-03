"""Compatibility entry point for scripts/import/sync_outline_to_workbench.py."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).parent / "scripts" / "import" / "sync_outline_to_workbench.py"), run_name="__main__")
