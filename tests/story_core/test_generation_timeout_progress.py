from types import SimpleNamespace

from packages.story_core.generation_progress import generation_progress
from packages.story_core.model_gateway.contracts import ModelResponse
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator, _expansion_timeout_seconds, _failed_bundle, _should_compress_chapter


REAL_CHAT = StoryOrchestrator._chat


def test_chat_passes_stage_timeout_and_reports_progress(monkeypatch):
    captured = {}

    class FakeGateway:
        def complete_resolved(self, settings, request):
            captured["base_url"] = settings.base_url
            captured["timeout"] = request.timeout_seconds
            captured["model"] = request.model
            return ModelResponse.success(request, text="正文")

    monkeypatch.setattr(
        "packages.story_core.orchestrator.resolve_stage_runtime",
        lambda stage: SimpleNamespace(
            provider="openai",
            model="writer-model",
            base_url="https://example.invalid/v1",
            api_key="key",
            codex_command="",
            temperature=0,
        ),
    )
    monkeypatch.setattr(StoryOrchestrator, "_chat", REAL_CHAT)

    progress = []
    story = StoryState(story_id="s-timeout-progress", outline="测试", genre="网文", style="简洁")
    with generation_progress(progress.append):
        text, error = StoryOrchestrator(model_gateway=FakeGateway())._chat(
            story,
            "写一段正文",
            max_tokens=4000,
            json_mode=False,
            agent="writer",
            stage="整章写作 第1章",
            timeout_seconds=123,
        )

    assert text == "正文"
    assert error == ""
    assert captured["timeout"] == 123
    assert captured["model"] == "writer-model"
    assert any("整章写作 第1章" in item and "123" in item for item in progress)
    assert any("模型返回" in item for item in progress)


def test_chat_returns_stage_specific_error_on_timeout(monkeypatch):
    class TimeoutGateway:
        def complete_resolved(self, _settings, request):
            return ModelResponse.failure(request, "request_timed_out")

    monkeypatch.setattr(
        "packages.story_core.orchestrator.resolve_stage_runtime",
        lambda stage: SimpleNamespace(
            provider="openai",
            model="planner-model",
            base_url="https://example.invalid/v1",
            api_key="key",
            codex_command="",
            temperature=0,
        ),
    )
    monkeypatch.setattr(StoryOrchestrator, "_chat", REAL_CHAT)

    progress = []
    story = StoryState(story_id="s-timeout-error", outline="测试", genre="网文", style="简洁")
    with generation_progress(progress.append):
        text, error = StoryOrchestrator(model_gateway=TimeoutGateway())._chat(
            story,
            "规划",
            max_tokens=8000,
            json_mode=True,
            agent="planner",
            stage="剧情计划：第3章",
            timeout_seconds=5,
        )

    assert text == ""
    assert "剧情计划：第3章" in error
    assert "model_request_failed" in error
    assert any("模型请求失败" in item for item in progress)


def test_timed_chat_reports_elapsed_progress():
    class FastOrchestrator(StoryOrchestrator):
        def _chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
            return "正文", ""

    progress = []
    story = StoryState(story_id="s-timed-chat", outline="测试", genre="网文", style="简洁")

    with generation_progress(progress.append):
        text, error = FastOrchestrator()._timed_chat(
            story,
            "写一段正文",
            max_tokens=4000,
            json_mode=False,
            agent="writer",
            stage="正文生成",
        )

    assert text == "正文"
    assert error == ""
    assert any("正文生成耗时" in item for item in progress)


def test_timed_chat_passes_stage_timeout_to_chat():
    captured = {}

    class CapturingOrchestrator(StoryOrchestrator):
        def _chat(
            self,
            story,
            prompt: str,
            *,
            max_tokens: int,
            json_mode: bool,
            agent: str = "director",
            timeout_seconds: int | None = None,
        ):
            captured["timeout_seconds"] = timeout_seconds
            return "正文", ""

    story = StoryState(story_id="s-stage-timeout", outline="测试", genre="网文", style="简洁")

    text, error = CapturingOrchestrator()._timed_chat(
        story,
        "写一段正文",
        max_tokens=4000,
        json_mode=False,
        agent="writer",
        stage="章节扩写",
        timeout_seconds=777,
    )

    assert text == "正文"
    assert error == ""
    assert captured["timeout_seconds"] == 777


def test_expansion_timeout_can_be_overridden(monkeypatch):
    assert _expansion_timeout_seconds() == 720

    monkeypatch.setenv("NOVEL_EXPANSION_TIMEOUT_SECONDS", "901")

    assert _expansion_timeout_seconds() == 901


def test_should_compress_chapter_when_body_exceeds_target_max():
    assert not _should_compress_chapter("正文" * 1000)
    assert not _should_compress_chapter("正" * 5656)
    assert not _should_compress_chapter("正" * 5732)
    assert not _should_compress_chapter("正" * 5950)
    assert _should_compress_chapter("正" * 6001)
    assert _should_compress_chapter("正文" * 3001)


def test_failed_bundle_carries_visible_reason():
    story = StoryState(story_id="s-visible-failure", outline="测试", genre="网文", style="简洁")

    bundle = _failed_bundle(story, 3, "剧情计划：第3章 model_request_failed:timed out")

    assert bundle.chapter_title == "第3章生成失败"
    assert "生成失败" in bundle.body
    assert "timed out" in bundle.body
    assert bundle.quality_report["ok"] is False
    assert any("timed out" in issue for issue in bundle.quality_report["issues"])
