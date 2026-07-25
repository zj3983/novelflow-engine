from __future__ import annotations

from hashlib import sha256

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

import apps.api.routes.prompt_audit as prompt_audit_routes
from apps.api.routes.prompt_audit import init_prompt_audit_routes
from packages.story_core.prompt_audit import audit_prompt
from packages.story_core.prompt_audit_deep import DeepPromptAuditResult


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

    response = _client().post(
        "/prompt-audit/deep",
        json={
            "mode": "final_call",
            "content": content,
            "local_result": local_result.model_dump(),
        },
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "prompt_audit_invalid_request"}


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
