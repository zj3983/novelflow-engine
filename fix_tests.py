"""Compatibility entry point for scripts/maintenance/fix_tests.py."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).parent / "scripts" / "maintenance" / "fix_tests.py"), run_name="__main__")
