from packages.story_core.model_gateway.contracts import (
    ModelGateway,
    ModelRequest,
    ModelResponse,
    normalize_model_error,
)
from packages.story_core.agent_base import BaseLLMAgent, BaseOpenAIProvider


class RecordingStageGateway:
    def __init__(self, text: str) -> None:
        self.text = text
        self.stages: list[str] = []

    def complete_stage(self, stage: str, request: ModelRequest) -> ModelResponse:
        self.stages.append(stage)
        return ModelResponse.success(request, text=self.text, request_id="req-7")


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


def test_model_request_builds_messages_from_legacy_prompts():
    request = ModelRequest(
        prompt="write a chapter",
        system_prompt="You are the writer",
        provider="openai",
        model="gpt-5",
        operation="writer",
        json_mode=True,
        timeout_seconds=45,
    )

    assert request.normalized_messages() == (
        {"role": "system", "content": "You are the writer"},
        {"role": "user", "content": "write a chapter"},
    )
    assert request.json_mode is True
    assert request.timeout_seconds == 45


def test_explicit_messages_take_precedence_without_losing_system_prompt():
    request = ModelRequest(
        prompt="legacy prompt",
        system_prompt="system",
        messages=({"role": "user", "content": "current prompt"},),
        provider="anthropic",
        model="claude-sonnet-4",
        operation="planner",
    )

    assert request.normalized_messages() == (
        {"role": "system", "content": "system"},
        {"role": "user", "content": "current prompt"},
    )


def test_openai_provider_implements_shared_model_gateway_contract():
    class Provider(BaseOpenAIProvider):
        runtime_key = "writer"

    gateway = RecordingStageGateway("生成正文")
    provider = Provider(model_gateway=gateway)
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
    assert gateway.stages == ["writer"]


def test_base_llm_agent_routes_memory_to_planner_before_parsing_json():
    class Agent(BaseLLMAgent[dict]):
        agent_name = "MemoryAgent"
        runtime_key = "memory"

        def _runtime_settings(self, story):
            return type("Settings", (), {"provider": "deepseek"})()

        def _resolve_model(self, story):
            return "deepseek-chat"

        def _build_prompt(self, story, **kwargs):
            return "extract memory"

        def _parse_response(self, story, parsed, **kwargs):
            return parsed

    gateway = RecordingStageGateway('{"summary": "done"}')
    story = type(
        "Story",
        (),
        {"agent_settings": type("AgentSettings", (), {"temperature": 0.2})()},
    )()

    result = Agent(model_gateway=gateway).call_llm(story)

    assert result == {"summary": "done"}
    assert gateway.stages == ["planner"]
