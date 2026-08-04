import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.story_core import runtime_config
from packages.story_core.runtime_config import (
    ImageRuntimeConfiguration,
    ImageRuntimeConfigurationError,
    OpenAIRuntimeSettings,
    ProviderAccount,
    RuntimeConfiguration,
    RuntimeProvider,
    StageBinding,
    get_agent_runtime_settings,
    get_runtime_configuration,
    load_runtime_configuration,
    resolve_image_runtime,
    resolve_stage_runtime,
    save_runtime_configuration,
    set_runtime_configuration,
)


def _v2_data() -> dict:
    return {
        "schema_version": "runtime-config/v2",
        "accounts": {
            "codexcli": {
                "api_key": "",
                "base_url": "",
                "custom_models": ["codex-custom"],
                "codex_command": "codex --quiet",
            },
            "deepseek": {
                "api_key": "deepseek-key",
                "base_url": "https://api.deepseek.com/v1/",
                "custom_models": ["my-deepseek"],
                "codex_command": "",
            },
        },
        "stages": {
            "planner": {"provider_id": "deepseek", "model": "my-deepseek"},
            "writer": {"provider_id": "codexcli", "model": "codex-custom"},
        },
        "temperature": 0.35,
        "new_character_policy": "Manual review",
    }


def test_root_conftest_isolates_story_core_runtime_config_before_module_import():
    configured = Path(os.environ["NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH"])

    assert runtime_config.CONFIG_FILE == configured
    assert Path(tempfile.gettempdir()) in configured.parents
    assert str(os.getpid()) in str(configured)
    assert configured != runtime_config.DEFAULT_CONFIG_FILE


def test_first_import_migrates_legacy_agent_settings_in_new_process(tmp_path):
    path = tmp_path / "runtime.json"
    path.write_text(
        json.dumps(
            {
                "global": {
                    "provider": "openai",
                    "api_key": "global-key",
                    "base_url": "https://api.openai.com/v1",
                },
                "agents": {
                    "director": {
                        "provider": "deepseek",
                        "api_key": "planner-key",
                        "base_url": "https://api.deepseek.com/v1",
                    },
                    "writer": {
                        "provider": "kimi",
                        "api_key": "writer-key",
                        "base_url": "https://api.moonshot.cn/v1",
                    },
                },
                "strategy": {
                    "director_model": "deepseek-planner",
                    "writer_model": "kimi-writer",
                },
            }
        ),
        encoding="utf-8",
    )
    script = """
import json
from packages.story_core import runtime_config

configuration = runtime_config.get_runtime_configuration()
print(json.dumps({
    "error": runtime_config.get_runtime_configuration_error(),
    "planner_provider": configuration.stages.planner.provider_id,
    "planner_model": configuration.stages.planner.model,
    "writer_provider": configuration.stages.writer.provider_id,
    "writer_model": configuration.stages.writer.model,
}))
"""
    environment = os.environ.copy()
    environment["NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH"] = str(path)

    result = subprocess.run(
        [sys.executable, "-c", script],
        cwd=Path(__file__).resolve().parents[2],
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    migrated = json.loads(result.stdout.strip().splitlines()[-1])
    assert migrated == {
        "error": None,
        "planner_provider": "deepseek",
        "planner_model": "deepseek-planner",
        "writer_provider": "kimi",
        "writer_model": "kimi-writer",
    }


def test_v2_round_trips_and_resolves_different_stage_providers(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    configuration = RuntimeConfiguration.model_validate(_v2_data())

    save_runtime_configuration(configuration, path)
    loaded = load_runtime_configuration(path)
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(loaded)

    planner = resolve_stage_runtime("planner")
    writer = resolve_stage_runtime("writer")
    assert loaded.schema_version == "runtime-config/v2"
    assert planner.provider_id == "deepseek"
    assert planner.provider == "deepseek"
    assert planner.protocol == "openai_compatible"
    assert planner.model == "my-deepseek"
    assert planner.api_key == "deepseek-key"
    assert planner.base_url == "https://api.deepseek.com/v1"
    assert writer.provider_id == "codexcli"
    assert writer.protocol == "codex_cli"
    assert writer.codex_command == "codex --quiet"


def test_memory_is_an_internal_alias_for_planner(monkeypatch):
    configuration = RuntimeConfiguration.model_validate(_v2_data())
    monkeypatch.setattr(runtime_config, "_runtime_configuration", configuration)

    assert resolve_stage_runtime("memory") == resolve_stage_runtime("planner")


def test_public_runtime_stage_excludes_memory_and_runtime_provider_symbol_remains_importable():
    assert runtime_config.RuntimeStage == runtime_config.Literal["planner", "writer"]
    assert RuntimeProvider is not None


def test_defaults_prefer_codex_cli_and_catalog_accounts_have_endpoints_without_keys():
    configuration = RuntimeConfiguration()

    assert configuration.stages.planner.provider_id == "codexcli"
    assert configuration.stages.writer.provider_id == "codexcli"
    assert configuration.accounts["deepseek"].base_url == "https://api.deepseek.com/v1"
    assert configuration.accounts["kimi"].base_url == "https://api.moonshot.cn/v1"
    assert configuration.accounts["deepseek"].api_key == ""
    assert configuration.accounts["kimi"].api_key == ""


@pytest.mark.parametrize(
    ("base_url", "provider_id"),
    [
        ("https://api.deepseek.com/v1", "deepseek"),
        ("https://api.moonshot.cn/v1", "kimi"),
        ("https://unknown.example/v1", "custom_openai"),
    ],
)
def test_v1_openai_slot_migrates_by_base_url_and_preserves_key_and_models(
    tmp_path, base_url, provider_id
):
    path = tmp_path / "runtime.json"
    legacy = {
        "provider": "openai",
        "providers": {
            "codexcli": {"codex_command": "codex", "planner": "cp", "writer": "cw", "memory": "cm"},
            "openai": {
                "api_key": "current-deepseek-key",
                "base_url": base_url,
                "planner": "legacy-planner",
                "writer": "legacy-writer",
                "memory": "legacy-memory",
            },
        },
        "temperature": 0.2,
        "new_character_policy": "Manual review",
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = load_runtime_configuration(path)

    assert migrated.accounts[provider_id].api_key == "current-deepseek-key"
    assert migrated.stages.planner == StageBinding(provider_id=provider_id, model="legacy-planner")
    assert migrated.stages.writer == StageBinding(provider_id=provider_id, model="legacy-writer")
    assert "memory" not in migrated.model_dump(mode="json")["stages"]


def test_v1_codexcli_migration_uses_codex_account_and_only_memory_fills_blank_planner(tmp_path):
    path = tmp_path / "runtime.json"
    legacy = {
        "provider": "codexcli",
        "providers": {
            "codexcli": {
                "codex_command": "legacy-codex",
                "planner": "   ",
                "writer": "legacy-writer",
                "memory": "memory-fallback",
            },
            "openai": {"api_key": "ds-key", "base_url": "https://api.deepseek.com/v1"},
        },
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = load_runtime_configuration(path)

    assert migrated.accounts["codexcli"].codex_command == "legacy-codex"
    assert migrated.accounts["deepseek"].api_key == "ds-key"
    assert migrated.stages.planner.model == "memory-fallback"
    assert migrated.stages.writer.model == "legacy-writer"


def test_older_global_strategy_migrates_one_provider_to_both_bindings(tmp_path):
    path = tmp_path / "runtime.json"
    legacy = {
        "global": {
            "provider": "openai",
            "api_key": "kimi-key",
            "base_url": "https://api.moonshot.cn/v1",
        },
        "strategy": {
            "director_model": "planner-model",
            "writer_model": "writer-model",
            "memory_model": "ignored-memory-model",
            "temperature": 0.1,
        },
    }
    path.write_text(json.dumps(legacy), encoding="utf-8")

    migrated = load_runtime_configuration(path)

    assert migrated.accounts["kimi"].api_key == "kimi-key"
    assert migrated.stages.planner == StageBinding(provider_id="kimi", model="planner-model")
    assert migrated.stages.writer == StageBinding(provider_id="kimi", model="writer-model")


def test_migration_is_idempotent(tmp_path):
    legacy_path = tmp_path / "legacy.json"
    v2_path = tmp_path / "v2.json"
    legacy_path.write_text(
        json.dumps({
            "global": {"provider": "openai", "api_key": "key", "base_url": "https://api.deepseek.com/v1"},
            "strategy": {"director_model": "p", "writer_model": "w", "memory_model": "m"},
        }),
        encoding="utf-8",
    )

    once = load_runtime_configuration(legacy_path)
    save_runtime_configuration(once, v2_path)
    twice = load_runtime_configuration(v2_path)

    assert twice == once
    assert twice.model_dump(mode="json") == once.model_dump(mode="json")


def test_account_and_image_keys_are_protected_in_storage(tmp_path):
    path = tmp_path / "runtime.json"
    data = _v2_data()
    data["image"] = {
        "enabled": True,
        "api_key": "image-secret",
        "base_url": "https://images.example/v1",
        "model": "image-model",
    }

    save_runtime_configuration(RuntimeConfiguration.model_validate(data), path)
    stored = path.read_text(encoding="utf-8")

    if os.name == "nt":
        assert "deepseek-key" not in stored
        assert "image-secret" not in stored
        assert stored.count("dpapi:v1:") == 2
    loaded = load_runtime_configuration(path)
    assert loaded.accounts["deepseek"].api_key == "deepseek-key"
    assert loaded.image.api_key == "image-secret"


def test_storage_transform_protects_keys_before_json_masking(monkeypatch):
    monkeypatch.setattr(runtime_config, "_protect_api_key", lambda value: f"protected:{value}")

    stored = runtime_config._configuration_storage_data(RuntimeConfiguration.model_validate(_v2_data()))

    assert stored["accounts"]["deepseek"]["api_key"] == "protected:deepseek-key"
    assert "providers" not in stored
    assert "provider" not in stored
    assert "memory" not in stored["stages"]


def test_explicit_pre_v2_backup_is_created_once(tmp_path):
    path = tmp_path / "runtime_config.json"
    backup = tmp_path / "runtime_config.pre-provider-v2.json"
    path.write_text("first", encoding="utf-8")

    runtime_config._backup_pre_provider_v2(path)
    path.write_text("second", encoding="utf-8")
    runtime_config._backup_pre_provider_v2(path)

    assert backup.read_text(encoding="utf-8") == "first"


def test_custom_save_path_does_not_automatically_create_fixed_backup(tmp_path):
    path = tmp_path / "runtime_config.json"
    path.write_text("legacy", encoding="utf-8")

    save_runtime_configuration(RuntimeConfiguration(), path)

    assert not (tmp_path / "runtime_config.pre-provider-v2.json").exists()


def test_existing_v2_default_file_does_not_create_pre_v2_backup(tmp_path, monkeypatch):
    path = tmp_path / "runtime_config.json"
    path.write_text(json.dumps(_v2_data()), encoding="utf-8")
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)

    save_runtime_configuration(RuntimeConfiguration.model_validate(_v2_data()))

    assert not (tmp_path / "runtime_config.pre-provider-v2.json").exists()


def test_first_v2_save_to_default_config_file_creates_backup_once(tmp_path, monkeypatch):
    path = tmp_path / "runtime_config.json"
    backup = tmp_path / "runtime_config.pre-provider-v2.json"
    legacy = json.dumps({"provider": "codexcli", "providers": {}})
    path.write_text(legacy, encoding="utf-8")
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)

    save_runtime_configuration(RuntimeConfiguration())
    save_runtime_configuration(RuntimeConfiguration())

    assert backup.read_text(encoding="utf-8") == legacy


def test_explicit_save_to_config_file_creates_pre_v2_backup(tmp_path, monkeypatch):
    path = tmp_path / "runtime_config.json"
    backup = tmp_path / "runtime_config.pre-provider-v2.json"
    legacy = json.dumps({"provider": "codexcli", "providers": {}})
    path.write_text(legacy, encoding="utf-8")
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)

    save_runtime_configuration(RuntimeConfiguration(), runtime_config.CONFIG_FILE)

    assert backup.read_text(encoding="utf-8") == legacy


def test_legacy_fallback_backs_up_source_before_writing_v2(tmp_path, monkeypatch):
    config_path = tmp_path / "new" / "runtime_config.json"
    legacy_path = tmp_path / "old" / "runtime_config.json"
    legacy_path.parent.mkdir()
    legacy = json.dumps({
        "global": {"provider": "codexcli", "codex_command": "legacy-codex"},
        "strategy": {"director_model": "planner", "writer_model": "writer"},
    })
    legacy_path.write_text(legacy, encoding="utf-8")
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", config_path)
    monkeypatch.setattr(runtime_config, "LEGACY_CONFIG_FILE", legacy_path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())

    runtime_config._load_config_from_file()

    backup = config_path.with_name("runtime_config.pre-provider-v2.json")
    assert backup.read_text(encoding="utf-8") == legacy
    assert load_runtime_configuration(config_path).schema_version == "runtime-config/v2"


@pytest.mark.parametrize(
    "mutation,match",
    [
        (lambda data: data["stages"]["planner"].update(model="  "), "model"),
        (lambda data: data["stages"]["planner"].update(provider_id="missing"), "missing"),
        (lambda data: data["accounts"].pop("deepseek"), "deepseek"),
    ],
)
def test_v2_rejects_blank_models_unknown_providers_and_missing_accounts(mutation, match):
    data = _v2_data()
    mutation(data)

    with pytest.raises(ValidationError, match=match):
        RuntimeConfiguration.model_validate(data)


def test_custom_model_name_need_not_be_in_catalog_presets():
    configuration = RuntimeConfiguration.model_validate(_v2_data())

    assert configuration.stages.planner.model == "my-deepseek"
    assert configuration.accounts["deepseek"] == ProviderAccount(
        api_key="deepseek-key",
        base_url="https://api.deepseek.com/v1/",
        custom_models=["my-deepseek"],
        codex_command="",
    )


def test_image_runtime_behavior_is_unchanged(monkeypatch):
    configuration = RuntimeConfiguration(
        image=ImageRuntimeConfiguration(
            enabled=True,
            api_key=" image-key ",
            base_url=" https://images.example/v1/// ",
            model=" image-model ",
        )
    )
    monkeypatch.setattr(runtime_config, "_runtime_configuration", configuration)
    assert resolve_image_runtime().base_url == "https://images.example/v1"

    monkeypatch.setattr(runtime_config, "_runtime_configuration", RuntimeConfiguration())
    with pytest.raises(ImageRuntimeConfigurationError, match="^image_runtime_not_configured$"):
        resolve_image_runtime()


def test_compatibility_functions_project_only_planner_and_writer(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(_v2_data())

    assert runtime_config.get_runtime_settings().provider == "deepseek"
    assert get_agent_runtime_settings("director").provider == "deepseek"
    assert get_agent_runtime_settings("memory").provider == "deepseek"
    assert get_agent_runtime_settings("writer").provider == "codexcli"
    strategy = runtime_config.get_runtime_strategy_settings()
    assert strategy.director_model == "my-deepseek"
    assert strategy.writer_model == "codex-custom"
    assert strategy.memory_model == "my-deepseek"

    strategy.director_model = "new-planner"
    strategy.writer_model = "new-writer"
    strategy.memory_model = "must-not-persist"
    runtime_config.set_runtime_strategy_settings(strategy)
    dumped = get_runtime_configuration().model_dump(mode="json")
    assert dumped["stages"]["planner"]["model"] == "new-planner"
    assert dumped["stages"]["writer"]["model"] == "new-writer"
    assert "memory" not in dumped["stages"]


def test_global_compatibility_setter_rebinds_both_stages(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(_v2_data())

    result = runtime_config.set_runtime_settings(
        OpenAIRuntimeSettings(
            provider="openai",
            api_key="qwen-key",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1/",
        )
    )

    configuration = get_runtime_configuration()
    assert result.provider == "qwen"
    assert configuration.stages.planner.provider_id == "qwen"
    assert configuration.stages.writer.provider_id == "qwen"
    assert configuration.accounts["qwen"].api_key == "qwen-key"


def test_compatibility_agent_setter_rebinds_its_mapped_stage(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(_v2_data())

    runtime_config.set_agent_runtime_settings(
        "writer",
        OpenAIRuntimeSettings(
            provider="openai",
            api_key="kimi-key",
            base_url="https://api.moonshot.cn/v1/",
        ),
    )

    configuration = get_runtime_configuration()
    assert configuration.stages.writer.provider_id == "kimi"
    assert configuration.accounts["kimi"].api_key == "kimi-key"
    assert runtime_config.resolve_openai_runtime_settings("writer").provider == "kimi"
    assert runtime_config.resolve_openai_runtime_settings("writer").base_url == "https://api.moonshot.cn/v1"


def test_set_all_runtime_settings_keeps_memory_as_planner_alias(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    set_runtime_configuration(_v2_data())
    strategy = runtime_config.get_runtime_strategy_settings()
    strategy.director_model = "all-planner"
    strategy.writer_model = "all-writer"
    strategy.memory_model = "ignored-memory"

    runtime_config.set_all_runtime_settings({"strategy": strategy})

    configuration = get_runtime_configuration()
    assert configuration.stages.planner.model == "all-planner"
    assert configuration.stages.writer.model == "all-writer"
    assert runtime_config.get_all_runtime_settings()["strategy"].memory_model == "all-planner"


def test_damaged_configuration_is_not_overwritten(tmp_path):
    path = tmp_path / "runtime.json"
    damaged = b'{"schema_version": "runtime-config/v2", broken'
    path.write_bytes(damaged)

    with pytest.raises(ValueError, match="runtime configuration"):
        load_runtime_configuration(path)

    assert path.read_bytes() == damaged


def test_runtime_configuration_error_tracks_main_load_failure(tmp_path, monkeypatch):
    path = tmp_path / "runtime.json"
    path.write_bytes(b'{"schema_version": "runtime-config/v2", broken')
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", path)
    monkeypatch.setattr(runtime_config, "_runtime_configuration_error", None)

    runtime_config._load_config_from_file()

    assert str(path) in runtime_config.get_runtime_configuration_error()
