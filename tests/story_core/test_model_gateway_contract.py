from packages.story_core.model_gateway.contracts import (
    ModelGateway,
    ModelRequest,
    ModelResponse,
    normalize_model_error,
)
from packages.story_core.agent_base import BaseOpenAIProvider


def test_model_response_keeps_provider_model_and_text_metadata():
    request = ModelRequest(
        prompt="写一个章节计划",
        provider="api",
        model="deepseek-chat",
        operation="planning",
    )
    response = ModelResponse.success(
        request,
        text="计划正文",
        request_id="req-1",
        usage={"input_tokens": 10, "output_tokens": 5},
    )

    assert response.ok is True
    assert response.provider == "api"
    assert response.model == "deepseek-chat"
    assert response.text == "计划正文"
    assert response.request_id == "req-1"
    assert response.usage["output_tokens"] == 5
    assert response.operation == "planning"


def test_model_error_is_normalized_without_losing_provider_context():
    request = ModelRequest(
        prompt="写正文",
        provider="codexcli",
        model="writer",
        operation="writing",
    )

    response = ModelResponse.failure(request, "timeout")

    assert response.ok is False
    assert response.text == ""
    assert response.provider == "codexcli"
    assert response.error == "timeout"
    assert normalize_model_error(response) == "codexcli/writer/writing: timeout"


def test_openai_provider_implements_shared_model_gateway_contract():
    class Provider(BaseOpenAIProvider):
        runtime_key = "writer"

        def _runtime_settings(self):
            return type(
                "Settings",
                (),
                {"provider": "deepseek", "api_key": "token", "base_url": "http://model", "codex_command": ""},
            )()

        def _post_json(self, path, payload, settings=None):
            assert path == "/chat/completions"
            assert payload["model"] == "deepseek-chat"
            return {
                "id": "req-7",
                "choices": [{"message": {"content": "生成正文"}}],
                "usage": {"prompt_tokens": 12, "completion_tokens": 8},
            }

    provider = Provider()
    request = ModelRequest(
        prompt="写正文",
        system_prompt="你是写手",
        provider="deepseek",
        model="deepseek-chat",
        operation="writing",
        max_tokens=2000,
    )

    assert isinstance(provider, ModelGateway)
    response = provider.complete(request)

    assert response.ok is True
    assert response.text == "生成正文"
    assert response.request_id == "req-7"
    assert response.usage["completion_tokens"] == 8
