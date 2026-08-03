from __future__ import annotations

import json
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.model_gateway import ModelRequest, RuntimeModelGateway
from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type
from packages.story_core.runtime_config import (
    StageRuntimeSettings,
    resolve_stage_runtime,
)


def _runtime_gateway_for_legacy_injection(
    post_json: Callable[..., dict[str, Any]],
    runtime_resolver: Callable[[str], StageRuntimeSettings],
) -> RuntimeModelGateway:
    if post_json is post_json_with_retry:
        return RuntimeModelGateway(runtime_resolver=runtime_resolver)
    active: dict[str, Any] = {}

    def compatible_runtime(stage: str) -> StageRuntimeSettings:
        runtime = runtime_resolver(stage)
        active["runtime"] = runtime
        provider = str(getattr(runtime, "provider_id", getattr(runtime, "provider", "")))
        protocol = getattr(runtime, "protocol", "openai_compatible")
        if protocol == "codex_cli" or provider == "codexcli":
            provider, protocol = "custom_openai", "openai_compatible"
        return StageRuntimeSettings(
            provider_id=provider,
            protocol=protocol,
            model=runtime.model,
            api_key=runtime.api_key or ("legacy-injected" if provider == "custom_openai" else ""),
            base_url=runtime.base_url or "http://legacy-injected.invalid",
            codex_command=runtime.codex_command,
            temperature=runtime.temperature,
        )

    def transport(*, url: str, payload: dict[str, Any], headers: dict[str, str], config: Any) -> dict[str, Any]:
        runtime = active["runtime"]
        base_url = str(runtime.base_url).rstrip("/")
        path = url[len(base_url) :] if url.startswith(base_url) else url
        return post_json(base_url, path, payload, runtime.api_key, provider=runtime.provider, codex_command=runtime.codex_command)

    return RuntimeModelGateway(runtime_resolver=compatible_runtime, transport=transport)


class _StrictOpeningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpeningBrief(_StrictOpeningModel):
    schema_version: Literal["opening-brief/v1"] = "opening-brief/v1"
    mode: Literal["blank", "inspiration"] = "inspiration"
    novel_type_id: str = Field(min_length=1, max_length=100)
    idea: str = Field(min_length=1, max_length=1000)
    working_title: str = Field(default="", max_length=120)

    @field_validator("novel_type_id", "idea", "working_title", mode="before")
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class OpeningDirection(_StrictOpeningModel):
    id: str = Field(min_length=1, max_length=120)
    title: str = Field(min_length=1, max_length=120)
    hook: str = Field(min_length=1, max_length=500)
    protagonist_goal: str = Field(min_length=1, max_length=500)
    main_conflict: str = Field(min_length=1, max_length=500)
    growth_path: str = Field(min_length=1, max_length=500)
    opening_promise: str = Field(min_length=1, max_length=500)
    primary_trope_id: str | None = Field(default=None, max_length=120)

    @field_validator(
        "id",
        "title",
        "hook",
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "opening_promise",
        "primary_trope_id",
        mode="before",
    )
    @classmethod
    def trim_text(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value


class OpeningDirectionSet(_StrictOpeningModel):
    schema_version: Literal["opening-directions/v1"] = "opening-directions/v1"
    directions: list[OpeningDirection] = Field(min_length=3, max_length=3)
    selected_id: str = Field(default="", max_length=120)

    @field_validator("selected_id", mode="before")
    @classmethod
    def trim_selected_id(cls, value: Any) -> Any:
        return value.strip() if isinstance(value, str) else value

    @model_validator(mode="after")
    def validate_direction_ids(self) -> "OpeningDirectionSet":
        ids = [direction.id for direction in self.directions]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_direction_id")
        if self.selected_id and self.selected_id not in ids:
            raise ValueError("selected_direction_not_found")
        return self


def validate_opening_direction_set_primary_tropes(
    directions: OpeningDirectionSet,
    trope_candidates: Any,
) -> OpeningDirectionSet:
    candidate_ids = {
        str(item.get("id") or "").strip()
        for item in (trope_candidates if isinstance(trope_candidates, list) else [])
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    }
    for direction in directions.directions:
        if candidate_ids:
            if direction.primary_trope_id not in candidate_ids:
                raise ValueError(f"invalid_primary_trope_id:{direction.id}")
            continue
        if direction.primary_trope_id is not None:
            raise ValueError(f"invalid_primary_trope_id:{direction.id}")
    return directions


class LLMOpeningDirectionGenerator:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
        model_gateway: RuntimeModelGateway | None = None,
    ) -> None:
        self._model_gateway = model_gateway or _runtime_gateway_for_legacy_injection(
            post_json, runtime_resolver
        )

    def generate(self, brief: OpeningBrief, *, guidance: str = "") -> OpeningDirectionSet:
        validated_brief = OpeningBrief.model_validate(brief)
        genre = runtime_novel_type(validated_brief.novel_type_id)
        if genre is None:
            raise ValueError("invalid_novel_type")
        normalized_guidance = guidance.strip()
        if len(normalized_guidance) > 1000:
            raise ValueError("regeneration_guidance_too_long")

        try:
            prompt_context = {
                **novel_type_prompt_context(genre),
                "working_title": validated_brief.working_title,
                "idea": validated_brief.idea,
                "regeneration_guidance": normalized_guidance,
            }
            trope_candidates = prompt_context.get("genre_trope_templates", [])
            system_prompt = (
                "Create exactly three distinct Chinese webnovel opening directions from the supplied "
                "brief. Return JSON only with a directions array. Each item must contain only id, title, "
                "hook, protagonist_goal, main_conflict, growth_path, opening_promise, and primary_trope_id. "
                "choose one listed primary_trope_id for every direction. Return null only when candidate list empty."
            )
            response = self._model_gateway.complete_stage(
                "planner",
                ModelRequest(
                    prompt=json.dumps(prompt_context, ensure_ascii=False),
                    system_prompt=system_prompt,
                    provider="",
                    model="",
                    operation="opening_directions",
                    json_mode=True,
                ),
            )
            if not response.ok:
                raise ValueError(response.error or "model_call_failed")
            parsed = parse_json_message_content(
                {"choices": [{"message": {"content": response.text}}]}
            )
            if parsed is None:
                raise ValueError("invalid_json")
            directions = OpeningDirectionSet.model_validate(parsed)
            return validate_opening_direction_set_primary_tropes(directions, trope_candidates)
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "opening_direction_generation_failed":
                raise
            raise ValueError("opening_direction_generation_failed") from exc
