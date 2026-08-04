"""Compatibility entry point for scripts/export/export_chapters.py."""
from pathlib import Path
import runpy

runpy.run_path(str(Path(__file__).parent / "scripts" / "export" / "export_chapters.py"), run_name="__main__")
