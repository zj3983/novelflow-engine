from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from packages.story_core.models import StoryState
from packages.story_core.persistence.project_locking import with_project_update_lock
from packages.story_core.prompt_call_log import PromptCallLog
from packages.story_core.prompt_templates import (
    PromptTemplate,
    get_global_prompt_template,
    list_default_prompt_templates,
    prompt_template_applicability,
    validate_prompt_template,
)


class PromptTemplateStoreMixin:
    """Project prompt overrides and prompt-call log construction."""

    root: Path
    story_system_dir: Path
    webnovel_dir: Path

    @property
    def prompt_template_overrides_path(self) -> Path:
        return self.story_system_dir / "prompt_templates.json"

    def _prompt_template_overrides(self) -> dict[str, dict[str, Any]]:
        payload = self._read_json(self.prompt_template_overrides_path, {}) or {}
        templates = payload.get("templates", {}) if isinstance(payload, dict) else {}
        return templates if isinstance(templates, dict) else {}

    def effective_prompt_template(self, key: str) -> dict[str, Any]:
        template, source = self._effective_prompt_template_object(key)
        return {**template.as_dict(), "source": source}

    def _effective_prompt_template_object(self, key: str) -> tuple[PromptTemplate, str]:
        global_template = get_global_prompt_template(key)
        override = self._prompt_template_overrides().get(key)
        if isinstance(override, dict) and isinstance(override.get("content"), str):
            template = PromptTemplate(
                key=global_template.key,
                title=global_template.title,
                stage=global_template.stage,
                content=override["content"],
                required_variables=global_template.required_variables,
            )
            validate_prompt_template(template)
            source = "project_override"
        else:
            template = global_template
            default_content = next(
                item.content for item in list_default_prompt_templates() if item.key == key
            )
            source = "global_default" if template.content == default_content else "global_override"
        return template, source

    def prompt_template_object(self, key: str) -> PromptTemplate:
        return self._effective_prompt_template_object(key)[0]

    def prompt_template_source(self, key: str) -> str:
        return self._effective_prompt_template_object(key)[1]

    def prompt_templates(self) -> list[dict[str, Any]]:
        project = self.project()
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        is_game_story = self._is_game_story_payload(project, state)
        templates: list[dict[str, Any]] = []
        for item in list_default_prompt_templates():
            applicability = prompt_template_applicability(item.key)
            active_for_project = (
                applicability == "all"
                or (applicability == "game_only" and is_game_story)
                or (applicability == "non_game_only" and not is_game_story)
            )
            templates.append(
                {
                    **self.effective_prompt_template(item.key),
                    "applicability": applicability,
                    "active_for_project": active_for_project,
                }
            )
        return templates

    def prompt_call_log(self) -> PromptCallLog:
        from packages.story_core.genre_stages.registry import genre_stage_profile_for

        project_id = str(self.project().get("project_id") or self.root.name)
        if not project_id.startswith("file:"):
            project_id = f"file:{project_id}"
        project = self.project()
        state = self.state()
        chapter_number = max(1, int(state.get("current_chapter") or 0) + 1)
        story = StoryState.model_validate(
            self._story_state_payload_for_direction(state, project, chapter_number)
        )
        return PromptCallLog(
            self.story_system_dir,
            project_id=project_id,
            profile=genre_stage_profile_for(story),
        )

    @with_project_update_lock
    def set_prompt_template_override(self, key: str, content: str) -> dict[str, Any]:
        base = get_global_prompt_template(key)
        candidate = PromptTemplate(
            key=base.key,
            title=base.title,
            stage=base.stage,
            content=str(content),
            required_variables=base.required_variables,
        )
        validate_prompt_template(candidate)
        overrides = self._prompt_template_overrides()
        overrides[key] = {
            "content": candidate.content,
            "version": candidate.version,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_json_atomic(
            self.prompt_template_overrides_path,
            {"schema_version": "project-prompt-templates/v1", "templates": overrides},
        )
        return self.effective_prompt_template(key)

    @with_project_update_lock
    def delete_prompt_template_override(self, key: str) -> dict[str, Any]:
        get_global_prompt_template(key)
        overrides = self._prompt_template_overrides()
        overrides.pop(key, None)
        self._write_json_atomic(
            self.prompt_template_overrides_path,
            {"schema_version": "project-prompt-templates/v1", "templates": overrides},
        )
        return self.effective_prompt_template(key)
