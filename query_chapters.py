"""Compatibility entry point for scripts/maintenance/query_chapters.py."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).parent / "scripts" / "maintenance" / "query_chapters.py"), run_name="__main__")
