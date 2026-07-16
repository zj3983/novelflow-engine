import json

import pytest
from pydantic import ValidationError

from packages.story_core import runtime_config
from packages.story_core.runtime_config import (
    RuntimeConfiguration,
    get_runtime_configuration,
    load_runtime_configuration,
    resolve_stage_runtime,
    save_runtime_configuration,
    set_runtime_configuration,
)


def _configuration_data(*, provider: str = "codexcli") -> dict:
    return {
        "provider": provider,
        "providers": {
            "codexcli": {
                "api_key": "",
                "base_url": "",
                "codex_command": "codex --quiet",
                "planner": "gpt-5.4",
                "writer": "gpt-5.4",
                "memory": "gpt-5.4-mini",
            },
            "openai": {
                "api_key": "test-key",
                "base_url": "https://example.test/v1/",
                "codex_command": "",
                "planner": "o3",
                "writer": "gpt-4.1",
                "memory": "gpt-4.1-mini",
            },
        },
        "temperature": 0.35,
        "new_character_policy": "Manual review",
    }


def test_new_configuration_round_trips_and_resolves_selected_stage(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    configuration = RuntimeConfiguration.model_validate(_configuration_data(provider="openai"))

    save_runtime_configuration(configuration, path)
    loaded = load_runtime_configuration(path)
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(loaded)

    assert get_runtime_configuration() == configuration
    resolved = resolve_stage_runtime("planner")
    assert resolved.provider == "openai"
    assert resolved.model == "o3"
    assert resolved.api_key == "test-key"
    assert resolved.base_url == "https://example.test/v1"
    assert resolved.temperature == 0.35
    assert resolved.new_character_policy == "Manual review"


def test_load_migrates_codexcli_qwen_stage_models_and_discards_obsolete_models(tmp_path):
    path = tmp_path / "runtime.json"
    legacy = {
        "global": {
            "provider": "codexcli",
            "api_key": "legacy-key",
            "base_url": "https://legacy.test/v1",
            "codex_command": "legacy-codex",
        },
        "strategy": {
            "global_model": "discard-me",
            "character_model": "discard-me-too",
            "director_model": "qwen3.6-plus",
            "writer_model": "qwen3.6-plus",
            "memory_model": "qwen3.6-plus",
            "temperature": 0.2,
            "new_character_policy": "Auto-approve named candidates",
        },
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = load_runtime_configuration(path)
    persisted = json.loads(path.read_text(encoding="utf-8"))

    assert migrated.provider == "codexcli"
    assert migrated.providers.codexcli.planner == "gpt-5.4"
    assert migrated.providers.codexcli.writer == "gpt-5.4"
    assert migrated.providers.codexcli.memory == "gpt-5.4"
    assert migrated.temperature == 0.2
    assert migrated.new_character_policy == "Auto-approve named candidates"
    assert "strategy" not in persisted
    assert "character_model" not in json.dumps(persisted)
    assert "global_model" not in json.dumps(persisted)


def test_openai_migration_preserves_non_qwen_stage_models(tmp_path):
    path = tmp_path / "runtime.json"
    legacy = {
        "global": {"provider": "openai", "api_key": "key", "base_url": "https://api.test/v1"},
        "strategy": {
            "director_model": "o3",
            "writer_model": "gpt-4.1",
            "memory_model": "gpt-4.1-mini",
        },
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = load_runtime_configuration(path)

    assert migrated.providers.openai.planner == "o3"
    assert migrated.providers.openai.writer == "gpt-4.1"
    assert migrated.providers.openai.memory == "gpt-4.1-mini"


def test_migration_is_idempotent(tmp_path):
    path = tmp_path / "runtime.json"
    legacy = {
        "global": {"provider": "codexcli", "codex_command": "codex"},
        "strategy": {
            "director_model": "qwen3.6-plus",
            "writer_model": "qwen3.6-plus",
            "memory_model": "qwen3.6-plus",
        },
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    first = load_runtime_configuration(path)
    first_bytes = path.read_bytes()
    second = load_runtime_configuration(path)

    assert second == first
    assert path.read_bytes() == first_bytes


@pytest.mark.parametrize(
    "mutation",
    [
        lambda data: data.update({"unexpected": True}),
        lambda data: data["providers"]["openai"].update({"unexpected": True}),
        lambda data: data["providers"].update({"unexpected": {}}),
    ],
)
def test_new_configuration_rejects_unknown_fields(mutation):
    data = _configuration_data()
    mutation(data)

    with pytest.raises(ValidationError):
        RuntimeConfiguration.model_validate(data)


@pytest.mark.parametrize("stage", ["planner", "writer", "memory"])
def test_selected_provider_rejects_blank_stage_models(stage):
    data = _configuration_data(provider="openai")
    data["providers"]["openai"][stage] = "   "

    with pytest.raises(ValidationError, match=stage):
        RuntimeConfiguration.model_validate(data)


def test_damaged_configuration_is_not_overwritten(tmp_path):
    path = tmp_path / "runtime.json"
    damaged = b'{"provider": "openai", broken'
    path.write_bytes(damaged)

    with pytest.raises(ValueError, match="runtime configuration"):
        load_runtime_configuration(path)

    assert path.read_bytes() == damaged


def test_legacy_interfaces_project_new_configuration(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(_configuration_data(provider="codexcli"))

    connection = runtime_config.resolve_openai_runtime_settings("director")
    strategy = runtime_config.get_runtime_strategy_settings()

    assert connection.provider == "codexcli"
    assert connection.codex_command == "codex --quiet"
    assert strategy.director_model == "gpt-5.4"
    assert strategy.writer_model == "gpt-5.4"
    assert strategy.memory_model == "gpt-5.4-mini"
    assert strategy.temperature == 0.35
    assert strategy.new_character_policy == "Manual review"
