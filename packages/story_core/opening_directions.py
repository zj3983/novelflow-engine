from __future__ import annotations

import json
from typing import Any, Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.story_core.agent_base import parse_json_message_content
from packages.story_core.http_retry import post_json_with_retry
from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type
from packages.story_core.runtime_config import (
    StageRuntimeSettings,
    resolve_stage_runtime,
)


class _StrictOpeningModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class OpeningBrief(_StrictOpeningModel):
    schema_version: Literal["opening-brief/v1"] = "opening-brief/v1"
    mode: Literal["inspiration"] = "inspiration"
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

    @field_validator(
        "id",
        "title",
        "hook",
        "protagonist_goal",
        "main_conflict",
        "growth_path",
        "opening_promise",
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


class LLMOpeningDirectionGenerator:
    def __init__(
        self,
        *,
        post_json: Callable[..., dict[str, Any]] = post_json_with_retry,
        runtime_resolver: Callable[[str], StageRuntimeSettings] = resolve_stage_runtime,
    ) -> None:
        self._post_json = post_json
        self._runtime_resolver = runtime_resolver

    def generate(self, brief: OpeningBrief, *, guidance: str = "") -> OpeningDirectionSet:
        validated_brief = OpeningBrief.model_validate(brief)
        genre = runtime_novel_type(validated_brief.novel_type_id)
        if genre is None:
            raise ValueError("invalid_novel_type")
        normalized_guidance = guidance.strip()
        if len(normalized_guidance) > 1000:
            raise ValueError("regeneration_guidance_too_long")

        try:
            runtime = self._runtime_resolver("planner")
            if runtime.provider != "codexcli" and not runtime.api_key:
                raise ValueError("runtime_unavailable")

            prompt_context = {
                **novel_type_prompt_context(genre),
                "working_title": validated_brief.working_title,
                "idea": validated_brief.idea,
                "regeneration_guidance": normalized_guidance,
            }
            payload = {
                "model": runtime.model,
                "messages": [
                    {
                        "role": "system",
                        "content": (
                            "Create exactly three distinct Chinese webnovel opening directions from the supplied "
                            "brief. Return JSON only with a directions array. Each item must contain only id, title, "
                            "hook, protagonist_goal, main_conflict, growth_path, and opening_promise."
                        ),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(prompt_context, ensure_ascii=False),
                    },
                ],
                "response_format": {"type": "json_object"},
                "temperature": float(runtime.temperature),
            }
            response = self._post_json(
                runtime.base_url,
                "/chat/completions",
                payload,
                runtime.api_key,
                provider=runtime.provider,
                codex_command=runtime.codex_command,
            )
            parsed = parse_json_message_content(response)
            if parsed is None:
                raise ValueError("invalid_json")
            return OpeningDirectionSet.model_validate(parsed)
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "opening_direction_generation_failed":
                raise
            raise ValueError("opening_direction_generation_failed") from exc
