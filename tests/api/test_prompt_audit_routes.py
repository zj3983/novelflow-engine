from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.api.routes.prompt_audit as prompt_audit_routes
from apps.api.routes.prompt_audit import init_prompt_audit_routes
from packages.story_core.prompt_audit import audit_prompt
from packages.story_core.prompt_audit_deep import DeepPromptAuditResult
from packages.story_core.file_project_store import FileProjectStore


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(init_prompt_audit_routes())
    return TestClient(app)


def _deep_result(content: str, mode: str = "final_call") -> DeepPromptAuditResult:
    local_result = audit_prompt(mode=mode, content=content)
    return DeepPromptAuditResult.model_validate(
        {
            **local_result.model_dump(),
            "runtime": {
                "provider": "openai",
                "model": "audit-model",
                "elapsed_seconds": 0.125,
                "prompt_characters": len(content),
            },
        }
    )


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _write_prompt_project(root: Path, *, project_id: str, genre: str) -> FileProjectStore:
    project_root = root / project_id
    project = {"project_id": project_id, "title": project_id}
    _write_json(
        project_root / ".story-system" / "MASTER_SETTING.json",
        {"project": project},
    )
    _write_json(project_root / ".webnovel" / "project.json", project)
    _write_json(
        project_root / ".webnovel" / "state.json",
        {
            "story_id": project_id,
            "outline": "A chapter transparency fixture.",
            "genre": genre,
            "style": "serial fiction",
            "current_chapter": 0,
        },
    )
    return FileProjectStore(project_root)


def test_init_routes_is_idempotent():
    first = init_prompt_audit_routes()
    second = init_prompt_audit_routes()

    assert first is second is prompt_audit_routes.router
    paths = [route.path for route in prompt_audit_routes.router.routes]
    assert paths.count("/prompt-audit") == 1
    assert paths.count("/prompt-audit/deep") == 1


def test_local_template_audit_returns_schema_variable_issues_and_content_hash():
    content = "{{output_section}}\n{{unexpected}}\n{{output_section}}"

    response = _client().post(
        "/prompt-audit",
        json={
            "mode": "template",
            "content": content,
            "template_key": "writer",
            "required_variables": ["output_section", "chapter_direction"],
        },
    )

    assert response.status_code == 200
    body = response.json()
    assert body["schema_version"] == "prompt-audit/v1"
    assert body["mode"] == "template"
    assert body["content_sha256"] == sha256(content.encode("utf-8")).hexdigest()
    assert [issue["code"] for issue in body["must_fix"]] == [
        "missing_required_variable",
        "unknown_template_variable",
    ]
    assert any(
        issue["code"] == "repeated_template_variable"
        for issue in body["suggestions"]
    )


def test_local_audit_never_calls_deep_auditor(monkeypatch):
    def fail_if_called(**kwargs):
        raise AssertionError(f"deep auditor called with {kwargs}")

    monkeypatch.setattr(prompt_audit_routes.deep_auditor, "analyze", fail_if_called)

    response = _client().post(
        "/prompt-audit",
        json={"mode": "final_call", "content": "local only"},
    )

    assert response.status_code == 200
    assert response.json()["mode"] == "final_call"


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"mode": "invalid", "content": "text"}, "invalid_prompt_audit_mode"),
        ({"mode": "final_call", "content": " \n\t"}, "content_required"),
        (
            {"mode": "final_call", "content": "x" * 200_001},
            "prompt_audit_content_too_long",
        ),
    ],
)
def test_local_audit_maps_invalid_inputs_to_stable_422(payload, detail):
    response = _client().post("/prompt-audit", json=payload)

    assert response.status_code == 422
    assert response.json() == {"detail": detail}


def test_deep_audit_calls_analyze_once_with_supplied_local_result(monkeypatch):
    content = "deep endpoint content"
    local_result = audit_prompt(mode="final_call", content=content)
    expected = _deep_result(content)
    calls = []

    def analyze(**kwargs):
        calls.append(kwargs)
        return expected

    monkeypatch.setattr(prompt_audit_routes.deep_auditor, "analyze", analyze)

    response = _client().post(
        "/prompt-audit/deep",
        json={
            "mode": "final_call",
            "content": content,
            "template_key": "ignored",
            "required_variables": ["also_ignored"],
            "local_result": local_result.model_dump(),
        },
    )

    assert response.status_code == 200
    assert calls == [{"content": content, "local_result": local_result}]
    assert response.json()["runtime"] == expected.runtime.model_dump()
    assert response.json()["content_sha256"] == local_result.content_sha256


def test_deep_mode_mismatch_is_rejected_without_calling_analyze(monkeypatch):
    local_result = audit_prompt(mode="template", content="{{chapter}}")
    calls = []
    monkeypatch.setattr(
        prompt_audit_routes.deep_auditor,
        "analyze",
        lambda **kwargs: calls.append(kwargs),
    )

    response = _client().post(
        "/prompt-audit/deep",
        json={
            "mode": "final_call",
            "content": "{{chapter}}",
            "local_result": local_result.model_dump(),
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "prompt_audit_local_result_mismatch"}
    assert calls == []


@pytest.mark.parametrize(
    ("error_code", "status_code"),
    [
        ("runtime_unavailable", 503),
        ("prompt_audit_deep_failed", 502),
        ("prompt_audit_deep_invalid_response", 502),
        ("content_required", 422),
        ("invalid_prompt_audit_mode", 422),
        ("prompt_audit_deep_content_too_long", 422),
        ("prompt_audit_local_result_invalid", 422),
        ("prompt_audit_local_result_mismatch", 422),
        ("prompt_audit_deep_payload_too_long", 422),
    ],
)
def test_deep_audit_maps_value_errors(monkeypatch, error_code, status_code):
    content = "deep error mapping"
    local_result = audit_prompt(mode="final_call", content=content)

    def fail(**kwargs):
        raise ValueError(error_code)

    monkeypatch.setattr(prompt_audit_routes.deep_auditor, "analyze", fail)

    response = _client().post(
        "/prompt-audit/deep",
        json={
            "mode": "final_call",
            "content": content,
            "local_result": local_result.model_dump(),
        },
    )

    assert response.status_code == status_code
    assert response.json() == {"detail": error_code}


def test_unknown_value_error_does_not_leak_internal_text(monkeypatch):
    content = "deep private failure"
    local_result = audit_prompt(mode="final_call", content=content)

    def fail(**kwargs):
        raise ValueError("database password was visible")

    monkeypatch.setattr(prompt_audit_routes.deep_auditor, "analyze", fail)

    app = FastAPI()
    app.include_router(init_prompt_audit_routes())
    response = TestClient(app, raise_server_exceptions=False).post(
        "/prompt-audit/deep",
        json={
            "mode": "final_call",
            "content": content,
            "local_result": local_result.model_dump(),
        },
    )

    assert response.status_code == 500
    assert response.json() == {"detail": "prompt_audit_internal_error"}


def test_request_models_forbid_unknown_fields(monkeypatch):
    content = "strict request"
    local_result = audit_prompt(mode="final_call", content=content)
    monkeypatch.setattr(
        prompt_audit_routes.deep_auditor,
        "analyze",
        lambda **kwargs: pytest.fail(f"analyze called with {kwargs}"),
    )

    local_response = _client().post(
        "/prompt-audit",
        json={"mode": "final_call", "content": content, "contnet": "typo"},
    )
    deep_response = _client().post(
        "/prompt-audit/deep",
        json={
            "mode": "final_call",
            "content": content,
            "local_result": local_result.model_dump(),
            "contnet": "typo",
        },
    )

    assert local_response.status_code == 422
    assert deep_response.status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        {"template_key": "x" * 201},
        {"required_variables": [f"variable_{index}" for index in range(201)]},
        {"required_variables": ["x" * 201]},
    ],
)
def test_request_model_rejects_oversized_template_metadata(field):
    response = _client().post(
        "/prompt-audit",
        json={"mode": "final_call", "content": "text", **field},
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "path",
    ["/prompt-audit", "/prompt-audit/deep"],
)
def test_required_request_fields_remain_framework_422(path):
    response = _client().post(path, json={})

    assert response.status_code == 422


def test_main_app_keeps_health_root_and_project_independent_routes(monkeypatch):
    from apps.api.main import app

    monkeypatch.setenv("NOVEL_AUTOGROWTH_FRONTEND_URL", "http://localhost:3100/")
    client = TestClient(app)

    assert client.get("/health").json() == {"ok": True}
    root = client.get("/", follow_redirects=False)
    assert root.status_code == 307
    assert root.headers["location"] == "http://localhost:3100/projects"
    audit = client.post(
        "/prompt-audit",
        json={"mode": "final_call", "content": "no project id"},
    )
    assert audit.status_code == 200
    paths = [route.path for route in app.routes]
    assert paths.count("/prompt-audit") == 1
    assert paths.count("/prompt-audit/deep") == 1


@pytest.mark.parametrize(
    ("project_id", "genre", "profile_id", "expected_modules"),
    [
        (
            "prompt-stage-game",
            "网游",
            "game_webnovel",
            {
                "director": ["game_webnovel.director"],
                "writer": ["game_webnovel.writer"],
                "review": ["game_webnovel.review"],
                "revision": ["game_webnovel.revision"],
                "length": ["game_webnovel.length"],
            },
        ),
        (
            "prompt-stage-xianxia",
            "仙侠",
            "generic",
            {
                "director": ["generic.director"],
                "writer": ["common.writer"],
                "review": ["generic.review"],
                "revision": ["common.revision"],
                "length": ["generic.length"],
            },
        ),
    ],
)
def test_file_project_prompt_artifacts_and_actual_calls_expose_active_genre_stage_modules(
    tmp_path: Path,
    monkeypatch,
    project_id: str,
    genre: str,
    profile_id: str,
    expected_modules: dict[str, list[str]],
):
    from apps.api.main import app

    export_root = tmp_path / "exported-projects"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(export_root))
    store = _write_prompt_project(export_root, project_id=project_id, genre=genre)
    call_log = store.prompt_call_log()
    call_ids = {
        stage_name: call_log.start(
            chapter_number=1,
            stage=f"{stage_name} runtime",
            agent="planner" if stage_name == "director" else stage_name,
            genre_stage=stage_name,
            user_prompt=f"Run the {stage_name} stage.",
        )
        for stage_name in ("director", "writer", "review", "revision")
    }
    client = TestClient(app)

    preview_response = client.get(
        f"/file-projects/file:{project_id}/prompt-preview?chapter_number=1"
    )
    call_responses = {
        stage_name: client.get(
            f"/file-projects/file:{project_id}/prompt-calls/{call_id}"
        )
        for stage_name, call_id in call_ids.items()
    }

    assert preview_response.status_code == 200
    assert all(response.status_code == 200 for response in call_responses.values())
    preview = preview_response.json()
    prompt_artifacts = preview["prompts"]
    assert prompt_artifacts
    assert {item["genre_stage_profile"] for item in prompt_artifacts} == {profile_id}
    artifact_stages = {
        "director_plan": "director",
        "writer_body": "writer",
        "writing_taskbook": "writer",
        "revision": "revision",
        "expansion": "length",
        "compression": "length",
        "review_agents": "review",
    }
    for artifact in prompt_artifacts:
        assert artifact["genre_stage_modules"] == expected_modules[artifact_stages[artifact["key"]]]
    calls = {stage_name: response.json() for stage_name, response in call_responses.items()}
    for stage_name, call in calls.items():
        assert call["genre_stage_profile"] == profile_id
        assert call["genre_stage_modules"] == expected_modules[stage_name]

    if profile_id == "generic":
        serialized = json.dumps(
            {
                "preview_metadata": [
                    {
                        "genre_stage_profile": item["genre_stage_profile"],
                        "genre_stage_modules": item["genre_stage_modules"],
                    }
                    for item in prompt_artifacts
                ],
                "call_metadata": calls,
            },
            ensure_ascii=False,
        )
        assert "game_webnovel" not in serialized
        assert "游戏" not in serialized
        assert "网游" not in serialized
