"""Process-wide safety isolation for the complete test tree."""

import atexit
import os
import shutil
import tempfile
from pathlib import Path


_RUNTIME_CONFIG_TEST_DIRECTORY = (
    Path(tempfile.gettempdir())
    / f"novel-autogrowth-runtime-config-tests-{os.getpid()}"
)
shutil.rmtree(_RUNTIME_CONFIG_TEST_DIRECTORY, ignore_errors=True)
_RUNTIME_CONFIG_TEST_DIRECTORY.mkdir(parents=True)

_RUNTIME_CONFIG_TEST_PATH = _RUNTIME_CONFIG_TEST_DIRECTORY / "runtime_config.json"
os.environ["NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH"] = str(_RUNTIME_CONFIG_TEST_PATH)


def _cleanup_runtime_config_test_directory() -> None:
    shutil.rmtree(_RUNTIME_CONFIG_TEST_DIRECTORY, ignore_errors=True)


atexit.register(_cleanup_runtime_config_test_directory)
