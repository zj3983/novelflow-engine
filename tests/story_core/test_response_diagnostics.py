import hashlib
import json
from pathlib import Path

from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.model_gateway import ModelRequest, ModelResponse
from packages.story_core.models import NovelProject
from packages.story_core.prompt_call_log import PromptCallLog, classify_json_response
from packages.story_core.world_build.runner import WorldBuildGraphRunner
from packages.story_core.world_build.tasks import parse_task_payload


def test_prompt_call_log_persists_safe_completion_diagnostics(tmp_path):
    log = PromptCallLog(tmp_path, project_id="file:p-test")
    call_id = log.start(
        chapter_number=0,
        stage="planner",
        agent="world_build_world_society",
        user_prompt="prompt",
        requested_max_tokens=2600,
        json_mode=True,
        provider="custom_openai",
        protocol="openai_compatible",
        model="k3",
        temperature=1.0,
    )
    output = '{"world_systems":{"rules":["one"]},"padding":"' + ("x" * 400) + '"}'
    raw = {
        "model": "resolved-k3",
        "choices": [{"finish_reason": "length", "message": {"content": output}}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 2600, "total_tokens": 2700},
        "Authorization": "Bearer secret",
        "api_key": "secret",
        "url": "https://provider.example/v1/chat/completions?api_key=secret",
    }

    log.finish(
        call_id,
        status="success",
        provider="custom_openai",
        model="resolved-k3",
        resolved_model="resolved-k3",
        output=output,
        raw=raw,
        usage=raw["usage"],
        temperature_omitted=False,
    )

    saved = log.get(call_id)
    assert saved["requested_max_tokens"] == 2600
    assert saved["json_mode"] is True
    assert saved["temperature_omitted"] is False
    assert saved["resolved_model"] == "resolved-k3"
    assert saved["finish_reason"] == "length"
    assert saved["usage"] == raw["usage"]
    assert saved["output_prefix"] == output[:300]
    assert saved["output_suffix"] == output[-300:]
    assert saved["output_summary"] == output[:300]
    assert saved["output_sha256"] == hashlib.sha256(output.encode("utf-8")).hexdigest()
    assert saved["json_diagnostic"]["classification"] == "json.valid_object"
    serialized = json.dumps(saved, ensure_ascii=False)
    assert "Authorization" not in serialized
    assert "api_key" not in serialized
    assert "Bearer secret" not in serialized
    assert "api_key=secret" not in serialized


def test_json_response_classification_distinguishes_safe_shapes():
    truncated = '{"faction_rules":["one"],"world_systems":{'
    assert classify_json_response(truncated) == {
        "classification": "json.unterminated_object",
        "starts_with_object": True,
        "ends_with_object": False,
        "json_error_position": len(truncated),
        "json_error_kind": "unterminated_object",
    }

    assert classify_json_response("[1, 2, 3]")["classification"] == "json.valid_non_object"
    assert classify_json_response("plain text")["classification"] == "json.no_object_boundary"
    assert classify_json_response('{"ok":true} trailing prose')["classification"] == "json.trailing_content"


def test_existing_task_parser_accepts_complete_json_with_trailing_text():
    payload, diagnostics = parse_task_payload(
        '{"locations": [{"name": "旧档案馆", "description": "保存记录。"}]} trailing prose',
        ("locations",),
    )

    assert payload == {"locations": [{"name": "旧档案馆", "description": "保存记录。"}]}
    assert diagnostics == ()


class _DiagnosticGateway:
    def complete_stage(self, _stage: str, request: ModelRequest) -> ModelResponse:
        output = '{"economy_rules":["one"]}'
        return ModelResponse.success(
            request,
            text=output,
            usage={"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18},
            raw={
                "model": "resolved-k3",
                "choices": [{"finish_reason": "stop", "message": {"content": output}}],
            },
        )


def test_world_build_runner_passes_request_and_response_diagnostics_to_log(tmp_path: Path):
    root = tmp_path / "project"
    root.mkdir()
    project = NovelProject(
        project_id="file:diagnostics",
        title="诊断项目",
        world_blueprint={"genre_plugin_ids": ["urban"]},
    )
    store = FileProjectStore(root)
    store.snapshot_store.replace_json_transaction(
        {
            store.webnovel_dir / "project.json": project.model_dump(mode="json"),
            store.webnovel_dir / "state.json": {"genre_plugin_ids": ["urban"]},
        }
    )

    runner = WorldBuildGraphRunner(project, store=store, model_gateway=_DiagnosticGateway())
    response, call_id = runner._call_model("world_economy", "diagnostic prompt")

    assert response.ok
    assert call_id
    detail = store.prompt_call_log().get(call_id)
    assert detail["requested_max_tokens"] == 1800
    assert detail["json_mode"] is True
    assert detail["resolved_model"] == "resolved-k3"
    assert detail["finish_reason"] == "stop"
    assert detail["usage"] == {"prompt_tokens": 11, "completion_tokens": 7, "total_tokens": 18}
    assert detail["json_diagnostic"]["classification"] == "json.valid_object"
