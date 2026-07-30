import json
import os
import stat
import threading

import pytest
from pydantic import ValidationError

from packages.story_core import runtime_config
from packages.story_core.runtime_config import (
    ImageRuntimeConfiguration,
    ImageRuntimeConfigurationError,
    OpenAIRuntimeSettings,
    RuntimeConfiguration,
    get_agent_runtime_settings,
    get_runtime_configuration,
    load_runtime_configuration,
    resolve_stage_runtime,
    resolve_image_runtime,
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


def test_image_configuration_is_independent_and_round_trips_with_its_protected_secret(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    data = _configuration_data(provider="codexcli")
    data["image"] = {
        "enabled": True,
        "api_key": "image-secret",
        "base_url": "https://images.example.test/v1/",
        "model": "cover-image-model",
    }
    configuration = RuntimeConfiguration.model_validate(data)

    save_runtime_configuration(configuration, path)
    stored = path.read_text(encoding="utf-8")
    if os.name == "nt":
        assert "image-secret" not in stored
        assert "dpapi:v1:" in stored
    loaded = load_runtime_configuration(path)
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(loaded)

    assert loaded.image == ImageRuntimeConfiguration(**data["image"])
    assert loaded.providers.codexcli.api_key == ""
    assert loaded.providers.openai.api_key == "test-key"
    assert resolve_image_runtime().model == "cover-image-model"
    assert resolve_image_runtime().api_key == "image-secret"
    assert resolve_image_runtime().base_url == "https://images.example.test/v1"


def test_disabled_or_incomplete_image_configuration_has_a_stable_resolution_error(monkeypatch):
    default_configuration = RuntimeConfiguration()
    assert default_configuration.image == ImageRuntimeConfiguration()
    monkeypatch.setattr(runtime_config, "_runtime_configuration", default_configuration)

    with pytest.raises(ImageRuntimeConfigurationError, match="^image_runtime_not_configured$"):
        resolve_image_runtime()

    configuration = RuntimeConfiguration(image={"enabled": True, "api_key": "key"})
    monkeypatch.setattr(runtime_config, "_runtime_configuration", configuration)
    with pytest.raises(ImageRuntimeConfigurationError, match="^image_runtime_not_configured$"):
        resolve_image_runtime()


def test_runtime_configuration_does_not_store_plaintext_api_key_on_windows(tmp_path):
    path = tmp_path / "runtime.json"
    configuration = RuntimeConfiguration.model_validate(_configuration_data(provider="openai"))

    save_runtime_configuration(configuration, path)

    stored = path.read_text(encoding="utf-8")
    if os.name == "nt":
        assert "test-key" not in stored
        assert "dpapi:v1:" in stored
    assert load_runtime_configuration(path).providers.openai.api_key == "test-key"


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
    legacy_bytes = json.dumps(legacy).encode("utf-8")
    path.write_bytes(legacy_bytes)

    migrated = load_runtime_configuration(path)

    assert migrated.provider == "codexcli"
    assert migrated.providers.codexcli.planner == "gpt-5.6-sol"
    assert migrated.providers.codexcli.writer == "gpt-5.6-sol"
    assert migrated.providers.codexcli.memory == "gpt-5.6-terra"
    assert migrated.temperature == 0.2
    assert migrated.new_character_policy == "Auto-approve named candidates"
    assert path.read_bytes() == legacy_bytes
    assert "character_model" not in json.dumps(migrated.model_dump(mode="json"))
    assert "global_model" not in json.dumps(migrated.model_dump(mode="json"))


def test_read_only_legacy_migrates_to_new_file_without_modifying_legacy(tmp_path, monkeypatch):
    legacy_path = tmp_path / "legacy-runtime.json"
    config_path = tmp_path / "runtime.json"
    legacy_bytes = json.dumps(
        {
            "global": {"provider": "codexcli", "codex_command": "legacy-codex"},
            "strategy": {
                "director_model": "qwen3.6-plus",
                "writer_model": "qwen3.6-plus",
                "memory_model": "qwen3.6-plus",
            },
        }
    ).encode("utf-8")
    legacy_path.write_bytes(legacy_bytes)
    legacy_path.chmod(stat.S_IREAD)
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", config_path)
    monkeypatch.setattr(runtime_config, "LEGACY_CONFIG_FILE", legacy_path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())

    try:
        runtime_config._load_config_from_file()
    finally:
        legacy_path.chmod(stat.S_IREAD | stat.S_IWRITE)

    assert legacy_path.read_bytes() == legacy_bytes
    assert config_path.exists()
    migrated = load_runtime_configuration(config_path)
    assert migrated.providers.codexcli.planner == "gpt-5.6-sol"


def test_codexcli_defaults_do_not_use_models_below_gpt_5_5():
    configuration = RuntimeConfiguration()

    assert configuration.providers.codexcli.planner == "gpt-5.6-sol"
    assert configuration.providers.codexcli.writer == "gpt-5.6-sol"
    assert configuration.providers.codexcli.memory == "gpt-5.6-terra"


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


def test_damaged_primary_configuration_stops_legacy_fallback(tmp_path, monkeypatch):
    primary_path = tmp_path / "runtime.json"
    legacy_path = tmp_path / "legacy-runtime.json"
    damaged = b'{"provider": "openai", broken'
    primary_path.write_bytes(damaged)
    legacy_path.write_text(
        json.dumps(
            {
                "global": {"provider": "openai", "api_key": "must-not-load"},
                "strategy": {
                    "director_model": "o3",
                    "writer_model": "gpt-4.1",
                    "memory_model": "gpt-4.1-mini",
                },
            }
        ),
        encoding="utf-8",
    )
    in_memory_default = RuntimeConfiguration()
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", primary_path)
    monkeypatch.setattr(runtime_config, "LEGACY_CONFIG_FILE", legacy_path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration", in_memory_default)

    runtime_config._load_config_from_file()

    assert primary_path.read_bytes() == damaged
    assert get_runtime_configuration() == in_memory_default


def test_legacy_agent_override_is_available_after_migration(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    legacy = {
        "global": {"provider": "codexcli", "codex_command": "codex"},
        "agents": {
            "writer": {
                "api_key": "writer-key",
                "base_url": "https://writer.test/v1",
                "provider": "openai",
                "codex_command": "writer-codex",
            }
        },
        "strategy": {
            "director_model": "gpt-5.4",
            "writer_model": "gpt-5.4",
            "memory_model": "gpt-5.4",
        },
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "LEGACY_CONFIG_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    monkeypatch.setattr(runtime_config, "_agent_runtime_settings", {})

    runtime_config._load_config_from_file()

    assert get_agent_runtime_settings("writer") == OpenAIRuntimeSettings(
        api_key="writer-key",
        base_url="https://writer.test/v1",
        provider="openai",
        codex_command="writer-codex",
    )


def test_set_agent_runtime_settings_persists_across_reload(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "LEGACY_CONFIG_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    monkeypatch.setattr(runtime_config, "_agent_runtime_settings", {})
    save_runtime_configuration(RuntimeConfiguration(), path)

    expected = OpenAIRuntimeSettings(
        api_key="persisted-writer-key",
        base_url="https://persisted-writer.test/v1",
        provider="codexcli",
        codex_command="persisted-codex",
    )
    runtime_config.set_agent_runtime_settings("writer", expected)
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    monkeypatch.setattr(runtime_config, "_agent_runtime_settings", {})

    runtime_config._load_config_from_file()

    assert get_agent_runtime_settings("writer") == expected


def test_concurrent_compatibility_setters_preserve_both_updates(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    set_runtime_configuration(_configuration_data(provider="codexcli"))
    strategy = runtime_config.get_runtime_strategy_settings()
    strategy.writer_model = "thread-writer-model"
    writer_override = OpenAIRuntimeSettings(
        api_key="thread-writer-key",
        base_url="https://thread-writer.test/v1",
        provider="openai",
        codex_command="thread-writer-codex",
    )

    original_atomic_write = runtime_config._atomic_write_configuration
    first_write_entered = threading.Event()
    release_first_write = threading.Event()
    second_write_entered = threading.Event()
    second_thread_started = threading.Event()
    write_call_lock = threading.Lock()
    write_call_count = 0
    errors: list[BaseException] = []

    def synchronized_atomic_write(configuration, config_path):
        nonlocal write_call_count
        with write_call_lock:
            write_call_count += 1
            call_number = write_call_count
        if call_number == 1:
            first_write_entered.set()
            if not release_first_write.wait(timeout=5):
                raise TimeoutError("first write was not released")
        elif call_number == 2:
            second_write_entered.set()
        original_atomic_write(configuration, config_path)

    def run(callable_):
        try:
            callable_()
        except BaseException as exc:
            errors.append(exc)

    monkeypatch.setattr(runtime_config, "_atomic_write_configuration", synchronized_atomic_write)
    agent_thread = threading.Thread(
        target=run,
        args=(lambda: runtime_config.set_agent_runtime_settings("writer", writer_override),),
    )

    def update_strategy():
        second_thread_started.set()
        runtime_config.set_runtime_strategy_settings(strategy)

    strategy_thread = threading.Thread(target=run, args=(update_strategy,))
    threads = [agent_thread, strategy_thread]

    agent_thread.start()
    assert first_write_entered.wait(timeout=5)
    strategy_thread.start()
    assert second_thread_started.wait(timeout=5)
    second_entered_while_first_blocked = second_write_entered.wait(timeout=0.5)
    release_first_write.set()
    for thread in threads:
        thread.join(timeout=10)

    assert not any(thread.is_alive() for thread in threads)
    assert errors == []
    assert second_entered_while_first_blocked is False
    assert write_call_count == 2
    persisted = load_runtime_configuration(path)
    assert persisted.providers.codexcli.writer == "thread-writer-model"
    assert persisted.compatibility.agents["writer"].api_key == "thread-writer-key"


def test_save_revalidates_mutated_configuration_instance_before_writing(tmp_path):
    path = tmp_path / "runtime.json"
    configuration = RuntimeConfiguration.model_validate(_configuration_data(provider="openai"))
    save_runtime_configuration(configuration, path)
    original_bytes = path.read_bytes()
    configuration.providers.openai.writer = None

    with pytest.raises(ValidationError, match="writer"):
        save_runtime_configuration(configuration, path)

    assert path.read_bytes() == original_bytes


def test_explicit_openai_agent_override_wins_over_global_codexcli(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    set_runtime_configuration(_configuration_data(provider="codexcli"))
    runtime_config.set_agent_runtime_settings(
        "writer",
        {
            "api_key": "writer-openai-key",
            "base_url": "https://writer-openai.test/v1",
            "provider": "openai",
            "codex_command": "",
        },
    )

    resolved = runtime_config.resolve_openai_runtime_settings("writer")

    assert resolved.provider == "openai"
    assert resolved.api_key == "writer-openai-key"
    assert resolved.base_url == "https://writer-openai.test/v1"


def test_none_agent_provider_inherits_global_provider(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    set_runtime_configuration(_configuration_data(provider="codexcli"))
    runtime_config.set_agent_runtime_settings(
        "memory",
        {"api_key": "memory-key", "base_url": "", "provider": None, "codex_command": ""},
    )

    assert get_agent_runtime_settings("memory").provider is None
    assert runtime_config.resolve_openai_runtime_settings("memory").provider == "codexcli"


def test_runtime_configuration_error_tracks_failed_and_successful_loads(
    tmp_path,
    monkeypatch,
    caplog,
):
    path = tmp_path / "runtime.json"
    damaged = b'{"api_key": "do-not-log", broken'
    path.write_bytes(damaged)
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "LEGACY_CONFIG_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    monkeypatch.setattr(runtime_config, "_runtime_configuration_error", None, raising=False)
    caplog.set_level("ERROR", logger=runtime_config.__name__)

    runtime_config._load_config_from_file()

    assert "invalid runtime configuration" in runtime_config.get_runtime_configuration_error()
    assert path.read_bytes() == damaged
    assert str(path) in caplog.text
    assert "JSONDecodeError" in caplog.text
    assert "do-not-log" not in caplog.text

    path.write_text(
        json.dumps(RuntimeConfiguration().model_dump(mode="json")),
        encoding="utf-8",
    )
    runtime_config._load_config_from_file()

    assert runtime_config.get_runtime_configuration_error() is None


def test_public_main_configuration_load_updates_error_state(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_bytes(b'{"provider": "openai", broken')
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration_error", None, raising=False)

    with pytest.raises(ValueError, match="invalid runtime configuration"):
        load_runtime_configuration()

    assert str(path) in runtime_config.get_runtime_configuration_error()

    path.write_text(
        json.dumps(RuntimeConfiguration().model_dump(mode="json")),
        encoding="utf-8",
    )
    load_runtime_configuration()

    assert runtime_config.get_runtime_configuration_error() is None


def test_custom_save_preserves_main_error_until_main_save(tmp_path, monkeypatch):
    main_path = tmp_path / "runtime.json"
    export_path = tmp_path / "export.json"
    main_path.write_bytes(b'{"provider": "openai", broken')
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", main_path)
    monkeypatch.setattr(runtime_config, "LEGACY_CONFIG_FILE", tmp_path / "missing.json")
    monkeypatch.setattr(runtime_config, "_runtime_configuration_error", None, raising=False)

    runtime_config._load_config_from_file()
    main_error = runtime_config.get_runtime_configuration_error()

    save_runtime_configuration(RuntimeConfiguration(), export_path)

    assert runtime_config.get_runtime_configuration_error() == main_error
    assert main_path.read_bytes() == b'{"provider": "openai", broken'
    assert export_path.exists()

    save_runtime_configuration(RuntimeConfiguration())

    assert runtime_config.get_runtime_configuration_error() is None


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
