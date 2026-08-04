from packages.story_core.model_gateway.model_discovery import discover_provider_models
from packages.story_core.runtime_config import StageRuntimeSettings


def _runtime(provider_id: str, protocol: str, base_url: str = "https://api.example/v1"):
    return StageRuntimeSettings(
        provider_id=provider_id,
        protocol=protocol,
        model="test-model",
        api_key="secret-key",
        base_url=base_url,
        codex_command="codex",
        temperature=0.7,
        new_character_policy="Director review",
    )


def test_openai_compatible_model_discovery_uses_bearer_and_data_ids():
    captured = {}

    def transport(**kwargs):
        captured.update(kwargs)
        return {"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]}

    models = discover_provider_models(
        _runtime("deepseek", "openai_compatible", "https://api.deepseek.com/v1"),
        transport=transport,
    )

    assert models == [
        {
            "model_id": "deepseek-chat",
            "compatibility": "supported",
            "endpoint": "/chat/completions",
            "reason": "内置文本模型",
        },
        {
            "model_id": "deepseek-reasoner",
            "compatibility": "supported",
            "endpoint": "/chat/completions",
            "reason": "内置文本模型",
        },
    ]
    assert captured["url"] == "https://api.deepseek.com/v1/models"
    assert captured["headers"]["Authorization"] == "Bearer secret-key"


def test_anthropic_model_discovery_uses_native_headers():
    captured = {}

    def transport(**kwargs):
        captured.update(kwargs)
        return {"data": [{"id": "claude-sonnet-4"}]}

    models = discover_provider_models(
        _runtime("anthropic", "anthropic", "https://api.anthropic.com"),
        transport=transport,
    )

    assert models[0]["model_id"] == "claude-sonnet-4"
    assert models[0]["compatibility"] == "supported"
    assert models[0]["endpoint"] == "/v1/messages"
    assert captured["url"] == "https://api.anthropic.com/v1/models"
    assert captured["headers"]["x-api-key"] == "secret-key"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"


def test_gemini_model_discovery_strips_models_prefix_and_filters_non_generation_models():
    def transport(**kwargs):
        return {
            "models": [
                {"name": "models/gemini-2.5-pro", "supportedGenerationMethods": ["generateContent"]},
                {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            ]
        }

    models = discover_provider_models(
        _runtime("gemini", "gemini", "https://generativelanguage.googleapis.com/v1beta"),
        transport=transport,
    )

    assert models == [
        {
            "model_id": "gemini-2.5-pro",
            "compatibility": "supported",
            "endpoint": ":generateContent",
            "reason": "支持 generateContent",
        },
        {
            "model_id": "text-embedding-004",
            "compatibility": "unsupported",
            "endpoint": ":generateContent",
            "reason": "不支持 generateContent",
        },
    ]


def test_antigravity_model_discovery_uses_configured_cli_command(monkeypatch):
    captured = {}

    def fake_models(command):
        captured["command"] = command
        return ["gemini-3.6-flash-high", "gemini-3.1-pro-high"]

    monkeypatch.setattr(
        "packages.story_core.antigravity_cli_provider.read_antigravity_cli_models",
        fake_models,
    )
    runtime = _runtime("antigravity", "antigravity_cli", "")
    runtime.codex_command = "D:/Tools/Antigravity/launcher/agy.cmd"

    models = discover_provider_models(runtime)

    assert captured["command"] == "D:/Tools/Antigravity/launcher/agy.cmd"
    assert [item["model_id"] for item in models] == [
        "gemini-3.1-pro-high",
        "gemini-3.6-flash-high",
    ]
    assert all(item["endpoint"] == "antigravity-cli" for item in models)


def test_openai_discovery_marks_non_writing_models_unavailable_and_unknown_models_for_testing():
    def transport(**kwargs):
        return {
            "data": [
                {"id": "text-embedding-3-large"},
                {"id": "vendor-new-chat-model"},
            ]
        }

    models = discover_provider_models(
        _runtime("openai", "openai_compatible", "https://api.openai.com/v1"),
        transport=transport,
    )

    assert models[0]["compatibility"] == "unsupported"
    assert models[1]["compatibility"] == "unknown"
