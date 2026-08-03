import os
import tempfile
from pathlib import Path

from apps.api.main import app
from packages.story_core import runtime_config


def test_api_import_uses_process_isolated_runtime_configuration():
    configured = Path(os.environ["NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH"])

    assert app is not None
    assert runtime_config.CONFIG_FILE == configured
    assert Path(tempfile.gettempdir()) in configured.parents
    assert str(os.getpid()) in str(configured)
    assert configured != runtime_config.DEFAULT_CONFIG_FILE
