from __future__ import annotations

import ast
from pathlib import Path
from types import SimpleNamespace

from packages.story_core.model_gateway import ModelRequest, ModelResponse
from packages.story_core.orchestrator import StoryOrchestrator


_REAL_CHAT = StoryOrchestrator._chat


class _RecordingGateway:
    def __init__(self) -> None:
        self.calls: list[tuple[str, ModelRequest]] = []

    def complete_stage(self, stage: str, request: ModelRequest) -> ModelResponse:
        self.calls.append((stage, request))
        provider = "deepseek" if stage == "planner" else "anthropic"
        model = "deepseek-chat" if stage == "planner" else "claude-sonnet"
        routed = ModelRequest(
            prompt=request.prompt,
            system_prompt=request.system_prompt,
            provider=provider,
            model=model,
            operation=request.operation,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            json_mode=request.json_mode,
            timeout_seconds=request.timeout_seconds,
        )
        text = '{"ok": true}' if request.json_mode else "chapter body"
        return ModelResponse.success(routed, text=text)


def _runtime(stage: str) -> SimpleNamespace:
    resolved = "planner" if stage == "memory" else stage
    return SimpleNamespace(
        provider_id="deepseek" if resolved == "planner" else "anthropic",
        provider="deepseek" if resolved == "planner" else "anthropic",
        protocol="openai_compatible" if resolved == "planner" else "anthropic",
        model="deepseek-chat" if resolved == "planner" else "claude-sonnet",
        temperature=0.3,
        api_key="token",
        base_url="https://example.test",
        codex_command="",
    )


def test_orchestrator_routes_planner_writer_and_memory_through_stage_gateway(monkeypatch):
    monkeypatch.setattr(StoryOrchestrator, "_chat", _REAL_CHAT)
    gateway = _RecordingGateway()
    orchestrator = StoryOrchestrator(model_gateway=gateway)
    monkeypatch.setattr("packages.story_core.orchestrator.resolve_stage_runtime", _runtime)
    story = SimpleNamespace()

    planner_text, planner_error = orchestrator._chat(
        story, "plan", max_tokens=3000, json_mode=True, agent="planner"
    )
    writer_text, writer_error = orchestrator._chat(
        story, "write", max_tokens=3000, json_mode=False, agent="writer"
    )
    memory_text, memory_error = orchestrator._chat(
        story, "remember", max_tokens=3000, json_mode=True, agent="memory"
    )

    assert planner_error == writer_error == memory_error == ""
    assert planner_text == memory_text == '{"ok": true}'
    assert writer_text == "chapter body"
    assert [stage for stage, _request in gateway.calls] == ["planner", "writer", "planner"]
    assert gateway.calls[0][1].operation == "planner"
    assert gateway.calls[1][1].operation == "writer"
    assert gateway.calls[2][1].operation == "memory"


def test_production_text_modules_do_not_call_legacy_chat_completions_transport():
    root = Path(__file__).resolve().parents[2] / "packages" / "story_core"
    violations: list[str] = []
    excluded_transport_modules = {
        "codex_cli_provider.py",
        "cover_image_provider.py",
        "http_retry.py",
    }
    for path in root.glob("*.py"):
        if path.name in excluded_transport_modules:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if not any(
                isinstance(argument, ast.Constant)
                and argument.value == "/chat/completions"
                for argument in node.args
            ):
                continue
            name = ""
            if isinstance(node.func, ast.Name):
                name = node.func.id
            elif isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if "post_json" in name:
                violations.append(f"{path.relative_to(root)}:{node.lineno}")

    assert violations == []
