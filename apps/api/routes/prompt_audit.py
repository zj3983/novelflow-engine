from __future__ import annotations

from typing import NoReturn

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from packages.story_core.prompt_audit import PromptAuditResult, audit_prompt
from packages.story_core.prompt_audit_deep import (
    DeepPromptAuditResult,
    DeepPromptAuditor,
)


router = APIRouter()
deep_auditor = DeepPromptAuditor()

_BAD_GATEWAY_ERRORS = {
    "prompt_audit_deep_failed",
    "prompt_audit_deep_invalid_response",
}
_SAFE_UNPROCESSABLE_ERRORS = {
    "content_required",
    "invalid_prompt_audit_mode",
    "prompt_audit_content_too_long",
    "prompt_audit_deep_content_too_long",
    "prompt_audit_deep_payload_too_long",
    "prompt_audit_local_result_invalid",
    "prompt_audit_local_result_mismatch",
}


class PromptAuditRequest(BaseModel):
    mode: str
    content: str
    template_key: str = ""
    required_variables: list[str] = Field(default_factory=list)


class DeepPromptAuditRequest(PromptAuditRequest):
    local_result: PromptAuditResult


def _raise_audit_http_error(exc: ValueError) -> NoReturn:
    error_code = str(exc)
    if error_code == "runtime_unavailable":
        raise HTTPException(status_code=503, detail=error_code) from exc
    if error_code in _BAD_GATEWAY_ERRORS:
        raise HTTPException(status_code=502, detail=error_code) from exc
    detail = (
        error_code
        if error_code in _SAFE_UNPROCESSABLE_ERRORS
        else "prompt_audit_invalid_request"
    )
    raise HTTPException(status_code=422, detail=detail) from exc


def init_prompt_audit_routes() -> APIRouter:
    @router.post("/prompt-audit", response_model=PromptAuditResult)
    def run_prompt_audit(payload: PromptAuditRequest) -> PromptAuditResult:
        try:
            return audit_prompt(
                mode=payload.mode,
                content=payload.content,
                template_key=payload.template_key,
                required_variables=payload.required_variables,
            )
        except ValueError as exc:
            _raise_audit_http_error(exc)

    @router.post("/prompt-audit/deep", response_model=DeepPromptAuditResult)
    def run_deep_prompt_audit(payload: DeepPromptAuditRequest) -> DeepPromptAuditResult:
        try:
            if payload.local_result.mode != payload.mode:
                raise ValueError("prompt_audit_local_result_mismatch")
            return deep_auditor.analyze(
                content=payload.content,
                local_result=payload.local_result,
            )
        except ValueError as exc:
            _raise_audit_http_error(exc)

    return router
