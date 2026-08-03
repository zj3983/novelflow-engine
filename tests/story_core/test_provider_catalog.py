from dataclasses import FrozenInstanceError

import pytest

from packages.story_core.model_gateway import (
    BUILTIN_PROVIDER_IDS,
    ProviderDefinition,
    provider_definition,
    provider_id_for_base_url,
)


EXPECTED_PROVIDER_IDS = (
    "openai",
    "deepseek",
    "kimi",
    "qwen",
    "glm",
    "doubao",
    "minimax",
    "siliconflow",
    "openrouter",
    "xai",
    "anthropic",
    "gemini",
    "ollama",
    "codexcli",
    "custom_openai",
)


def test_builtin_provider_ids_are_stable_and_unique():
    assert BUILTIN_PROVIDER_IDS == EXPECTED_PROVIDER_IDS
    assert len(BUILTIN_PROVIDER_IDS) == len(set(BUILTIN_PROVIDER_IDS))


def test_provider_definitions_are_frozen_and_use_all_supported_protocols():
    definitions = [provider_definition(provider_id) for provider_id in BUILTIN_PROVIDER_IDS]

    assert all(isinstance(definition, ProviderDefinition) for definition in definitions)
    assert {definition.protocol for definition in definitions} == {
        "openai_compatible",
        "anthropic",
        "gemini",
        "codex_cli",
    }
    with pytest.raises(FrozenInstanceError):
        definitions[0].name = "changed"


@pytest.mark.parametrize(
    ("base_url", "expected_provider_id"),
    [
        ("https://api.deepseek.com/v1", "deepseek"),
        ("https://api.moonshot.cn/v1", "kimi"),
        ("https://dashscope.aliyuncs.com/compatible-mode/v1", "qwen"),
        ("https://open.bigmodel.cn/api/paas/v4", "glm"),
        ("https://ark.cn-beijing.volces.com/api/v3", "doubao"),
        ("https://api.minimax.chat/v1", "minimax"),
        ("https://api.siliconflow.cn/v1", "siliconflow"),
        ("https://openrouter.ai/api/v1", "openrouter"),
        ("https://api.x.ai/v1", "xai"),
        ("https://api.anthropic.com/v1", "anthropic"),
        ("https://generativelanguage.googleapis.com/v1beta", "gemini"),
        ("http://LOCALHOST:11434/v1", "ollama"),
    ],
)
def test_known_base_urls_resolve_to_builtin_provider(base_url, expected_provider_id):
    assert provider_id_for_base_url(base_url) == expected_provider_id


@pytest.mark.parametrize(
    "base_url",
    [
        "https://models.example.com/v1",
        "https://api.deepseek.com.evil.test/v1",
        "https://notopenrouter.ai/v1",
        "https://moonshot.cn.attacker.example/v1",
        "https://billing.volces.com/v1",
    ],
)
def test_unknown_and_deceptively_similar_hosts_resolve_to_custom_openai(base_url):
    assert provider_id_for_base_url(base_url) == "custom_openai"


def test_malformed_base_url_resolves_to_custom_openai():
    assert provider_id_for_base_url("http://[::1") == "custom_openai"


def test_default_base_urls_resolve_back_to_their_provider():
    for provider_id in BUILTIN_PROVIDER_IDS:
        definition = provider_definition(provider_id)
        if definition.default_base_url:
            assert (
                provider_id_for_base_url(definition.default_base_url) == provider_id
            )


def test_presets_have_complete_metadata_and_model_suggestions():
    for provider_id in BUILTIN_PROVIDER_IDS:
        definition = provider_definition(provider_id)
        assert definition.provider_id == provider_id
        assert definition.name
        assert definition.help_text
        if provider_id not in {"codexcli", "custom_openai"}:
            assert definition.host_patterns
        if provider_id != "custom_openai":
            assert definition.planner_models
            assert definition.writer_models

    assert provider_definition("codexcli").requires_api_key is False
    assert provider_definition("ollama").requires_api_key is False
    assert provider_definition("ollama").base_url_editable is True
    assert provider_definition("custom_openai").base_url_editable is True
