"""Compatibility entry point for scripts/maintenance/get_ch1.py."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).parent / "scripts" / "maintenance" / "get_ch1.py"), run_name="__main__")
