"""Compatibility entry point for scripts/maintenance/check_status.py."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).parent / "scripts" / "maintenance" / "check_status.py"), run_name="__main__")
