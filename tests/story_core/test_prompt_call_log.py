from packages.story_core.prompt_call_log import (
    PromptCallLog,
    finish_prompt_call,
    prompt_call_recording,
    start_prompt_call,
)
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import StoryOrchestrator
from packages.story_core.prompt_templates import get_default_prompt_template, prompt_template_scope


def test_prompt_call_records_exact_prompt_and_success(tmp_path):
    log = PromptCallLog(tmp_path, project_id="file:p-test")

    call_id = log.start(
        chapter_number=1,
        stage="正文写作",
        agent="writer",
        user_prompt="真实 prompt",
        module_keys=["core_context"],
    )
    log.finish(
        call_id,
        status="succeeded",
        provider="openai",
        model="deepseek-v4-flash",
        elapsed_seconds=1.2,
        output="正文内容",
    )

    saved = log.get(call_id)
    assert saved["status"] == "succeeded"
    assert saved["user_prompt"] == "真实 prompt"
    assert saved["provider"] == "openai"
    assert saved["model"] == "deepseek-v4-flash"
    assert saved["output_chars"] == 4
    assert saved["module_keys"] == ["core_context"]


def test_each_retry_gets_distinct_call_id_and_attempt(tmp_path):
    log = PromptCallLog(tmp_path, project_id="file:p-test")

    first = log.start(chapter_number=1, stage="导演规划", agent="planner", user_prompt="first")
    second = log.start(chapter_number=1, stage="导演规划", agent="planner", user_prompt="second")

    assert first != second
    assert log.get(first)["attempt"] == 1
    assert log.get(second)["attempt"] == 2


def test_context_local_recorder_routes_lifecycle_to_project_log(tmp_path):
    log = PromptCallLog(tmp_path, project_id="file:p-test")

    with prompt_call_recording(log):
        call_id = start_prompt_call(
            chapter_number=2,
            stage="审稿改稿",
            agent="writer",
            user_prompt="改稿 prompt",
        )
        finish_prompt_call(call_id, status="failed", error="model timeout")

    saved = log.get(call_id)
    assert saved["status"] == "failed"
    assert saved["error"] == "model timeout"
    assert start_prompt_call(chapter_number=2, stage="正文", agent="writer", user_prompt="outside") is None


def test_list_calls_returns_latest_state_not_duplicate_lifecycle_events(tmp_path):
    log = PromptCallLog(tmp_path, project_id="file:p-test")
    call_id = log.start(chapter_number=3, stage="正文写作", agent="writer", user_prompt="prompt")
    log.finish(call_id, status="succeeded", output="done")

    calls = log.list(chapter_number=3)

    assert len(calls) == 1
    assert calls[0]["call_id"] == call_id
    assert calls[0]["status"] == "succeeded"


def test_orchestrator_timed_chat_records_exact_prompt_and_runtime(tmp_path, monkeypatch):
    from packages.story_core import orchestrator as orchestrator_module

    log = PromptCallLog(tmp_path, project_id="file:p-test")
    orchestrator = StoryOrchestrator()
    story = StoryState(story_id="s-call", outline="测试", genre="都市", style="白描", current_chapter=1)
    monkeypatch.setattr(orchestrator, "_chat", lambda *args, **kwargs: ("模型输出", ""))
    monkeypatch.setattr(
        orchestrator_module,
        "resolve_stage_runtime",
        lambda stage: type("Runtime", (), {"provider": "openai", "model": "deepseek-v4-flash"})(),
    )

    with prompt_template_scope(lambda key: get_default_prompt_template(key), lambda key: "project_override"):
        with prompt_call_recording(log):
            text, error = orchestrator._timed_chat(
                story,
                "EXACT PROMPT",
                max_tokens=10,
                json_mode=False,
                agent="writer",
                stage="正文写作",
            )

    assert text == "模型输出"
    assert error == ""
    detail = log.get(log.list(chapter_number=1)[0]["call_id"])
    assert detail["user_prompt"] == "EXACT PROMPT"
    assert detail["status"] == "succeeded"
    assert detail["provider"] == "openai"
    assert detail["model"] == "deepseek-v4-flash"
    assert detail["template_source"] == "project_override"


def test_orchestrator_records_returned_model_error(tmp_path, monkeypatch):
    from packages.story_core import orchestrator as orchestrator_module

    log = PromptCallLog(tmp_path, project_id="file:p-test")
    orchestrator = StoryOrchestrator()
    story = StoryState(story_id="s-call-error", outline="测试", genre="都市", style="白描", current_chapter=2)
    monkeypatch.setattr(orchestrator, "_chat", lambda *args, **kwargs: ("", "model timeout"))
    monkeypatch.setattr(
        orchestrator_module,
        "resolve_stage_runtime",
        lambda stage: type("Runtime", (), {"provider": "openai", "model": "deepseek-v4-flash"})(),
    )

    with prompt_call_recording(log):
        orchestrator._timed_chat(
            story,
            "FAILED PROMPT",
            max_tokens=10,
            json_mode=False,
            agent="writer",
            stage="审稿改稿",
        )

    detail = log.get(log.list(chapter_number=2)[0]["call_id"])
    assert detail["status"] == "failed"
    assert detail["error"] == "model timeout"
