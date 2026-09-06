from __future__ import annotations

from typing import Any
from urllib.parse import quote

from packages.story_core.novel_type_catalog import (
    normalize_novel_type_ids,
    novel_type_prompt_context,
    runtime_novel_type,
)
from packages.story_core.opening_directions import (
    GeneratedOpeningDirectionSet,
    OpeningBrief,
    OpeningDirectionSet,
    validate_opening_direction_set_primary_tropes,
)
from packages.story_core.persistence.project_locking import with_project_update_lock
from packages.story_core.project_outline import normalize_project_outline
from packages.story_core.story_core_card import (
    StoryCoreCard,
    outline_seed_from_story_core,
    merge_story_core_into_overall,
    story_core_from_direction,
    story_core_from_overall,
    story_core_projection,
)


class OpeningSetupStoreMixin:
    """Opening-direction and story-core persistence for file projects."""

    def opening_brief(self) -> dict[str, Any]:
        path = self.webnovel_dir / "opening_brief.json"
        payload = self._read_json(path, {})
        project = self.project()
        pipeline_stage = str(project.get("pipeline_stage") or "")
        recoverable_legacy_blank = pipeline_stage == "draft" or (
            pipeline_stage in {"direction_ready", "outlining"}
            and (self.webnovel_dir / "opening_directions.json").is_file()
        )
        if not payload and recoverable_legacy_blank:
            blueprint = (
                project.get("world_blueprint")
                if isinstance(project.get("world_blueprint"), dict)
                else {}
            )
            novel_type_ids = normalize_novel_type_ids(
                blueprint.get("genre_plugin_ids")
            )
            if not novel_type_ids:
                state = self._read_json(self.webnovel_dir / "state.json", {})
                novel_type_ids = normalize_novel_type_ids(
                    state.get("genre_plugin_ids")
                )
            title = str(project.get("title") or "未命名作品").strip() or "未命名作品"
            payload = {
                "schema_version": "opening-brief/v1",
                "mode": "blank",
                "novel_type_id": (
                    novel_type_ids[0] if novel_type_ids else "generic_webnovel"
                ),
                "idea": f"请根据书名《{title}》和所选小说类型构思故事。",
                "working_title": title,
            }
            self._write_json_atomic(path, payload)
        return OpeningBrief.model_validate(payload).model_dump(mode="json")

    def opening_directions(self) -> dict[str, Any] | None:
        path = self.webnovel_dir / "opening_directions.json"
        if not path.exists():
            return None
        return OpeningDirectionSet.model_validate(
            self._read_json(path, {})
        ).model_dump(mode="json")

    def opening_setup(self) -> dict[str, Any]:
        project = self.project()
        candidates = self.opening_directions()
        project_id = str(project.get("project_id") or self.root.name)
        public_project_id = (
            project_id if project_id.startswith("file:") else f"file:{project_id}"
        )
        selected_id = str((candidates or {}).get("selected_id") or "")
        pipeline_stage = str(project.get("pipeline_stage") or "idea_pending")
        next_page = (
            "outline" if selected_id or pipeline_stage == "outlining" else "setup"
        )
        return {
            "brief": self.opening_brief(),
            "directions": list((candidates or {}).get("directions") or []),
            "selected_id": selected_id,
            "pipeline_stage": pipeline_stage,
            "next_path": f"/projects/{quote(public_project_id, safe='')}/{next_page}",
        }

    def _selected_opening_direction(self) -> dict[str, Any] | None:
        payload = self.opening_directions()
        selected_id = str((payload or {}).get("selected_id") or "")
        if not selected_id:
            return None
        return next(
            (
                dict(direction)
                for direction in (payload or {}).get("directions") or []
                if isinstance(direction, dict)
                and str(direction.get("id") or "") == selected_id
            ),
            None,
        )

    def story_core(self) -> dict[str, Any]:
        project = self.project()
        outline = dict(self.project_outline())
        outline.pop("source", None)
        overall = dict(outline.get("overall") or {})
        return story_core_from_overall(
            overall,
            title=str(project.get("title") or ""),
        ).model_dump(mode="json")

    def story_core_context(self, stage: str) -> dict[str, Any]:
        return story_core_projection(
            StoryCoreCard.model_validate(self.story_core()),
            stage,
        )

    @with_project_update_lock
    def update_story_core(self, payload: dict[str, Any]) -> dict[str, Any]:
        card = StoryCoreCard.model_validate(payload)
        outline = dict(self.project_outline())
        outline.pop("source", None)
        outline["overall"] = merge_story_core_into_overall(
            outline.get("overall"),
            card,
            overwrite=True,
        )
        saved_outline = self.update_project_outline(outline)
        return story_core_from_overall(
            saved_outline.get("overall"),
            title=str(self.project().get("title") or card.title),
        ).model_dump(mode="json")

    def _opening_direction_trope_candidates(
        self,
        brief: OpeningBrief | dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        validated_brief = OpeningBrief.model_validate(brief or self.opening_brief())
        genre = runtime_novel_type(validated_brief.novel_type_id)
        if genre is None:
            raise ValueError("invalid_novel_type")
        prompt_context = novel_type_prompt_context(genre)
        return [
            dict(item)
            for item in prompt_context.get("genre_trope_templates", [])
            if isinstance(item, dict)
        ]

    def _current_opening_direction_novel_type_id(
        self,
        brief: OpeningBrief | dict[str, Any] | None = None,
    ) -> str:
        validated_brief = OpeningBrief.model_validate(brief or self.opening_brief())
        project = self.project()
        world_blueprint = (
            project.get("world_blueprint")
            if isinstance(project.get("world_blueprint"), dict)
            else {}
        )
        raw_ids = world_blueprint.get("genre_plugin_ids")
        if isinstance(raw_ids, str):
            has_explicit_type = bool(raw_ids.strip())
        elif isinstance(raw_ids, list):
            has_explicit_type = any(str(item).strip() for item in raw_ids)
        else:
            has_explicit_type = False
        normalized_ids = normalize_novel_type_ids(raw_ids)
        if normalized_ids:
            return normalized_ids[0]
        if has_explicit_type:
            raise ValueError("invalid_novel_type")
        return validated_brief.novel_type_id

    @with_project_update_lock
    def generate_opening_directions(
        self,
        generator: Any,
        *,
        guidance: str = "",
    ) -> dict[str, Any]:
        existing = self.opening_directions()
        if existing and existing.get("selected_id"):
            raise ValueError("direction_already_selected")
        brief = OpeningBrief.model_validate(self.opening_brief())
        try:
            current_type_id = self._current_opening_direction_novel_type_id(brief)
            effective_brief = brief.model_copy(
                update={"novel_type_id": current_type_id}
            )
            trope_candidates = self._opening_direction_trope_candidates(effective_brief)
            result = generator.generate(
                effective_brief,
                guidance=guidance.strip(),
            )
            generated_directions = validate_opening_direction_set_primary_tropes(
                GeneratedOpeningDirectionSet.model_validate(result),
                trope_candidates,
            )
            directions = OpeningDirectionSet.model_validate(
                generated_directions.model_dump(mode="json")
            )
        except Exception as exc:
            if isinstance(exc, ValueError) and str(exc) == "invalid_novel_type":
                raise ValueError("opening_direction_generation_failed") from exc
            if (
                isinstance(exc, ValueError)
                and str(exc) == "opening_direction_generation_failed"
            ):
                raise
            raise ValueError("opening_direction_generation_failed") from exc
        project = {**self.project(), "pipeline_stage": "direction_ready"}
        self._replace_json_transaction(
            {
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "opening_directions.json": directions.model_dump(
                    mode="json"
                ),
            }
        )
        return self.opening_setup()

    @with_project_update_lock
    def select_opening_direction(self, direction_id: str) -> dict[str, Any]:
        payload = self.opening_directions()
        if payload is None:
            raise KeyError("direction_not_found")
        directions = OpeningDirectionSet.model_validate(payload)
        if directions.selected_id:
            raise ValueError("direction_already_selected")
        selected = next(
            (
                direction
                for direction in directions.directions
                if direction.id == direction_id
            ),
            None,
        )
        if selected is None:
            raise KeyError("direction_not_found")

        current_project = self.project()
        current_title = str(current_project.get("title") or "").strip()
        title = (
            selected.title
            if not current_title or current_title in {"未命名作品", "Untitled"}
            else current_title
        )
        project = {
            **current_project,
            "title": title,
            "pipeline_stage": "outlining",
        }
        story_core = story_core_from_direction(selected)
        outline = normalize_project_outline(
            outline_seed_from_story_core(
                story_core,
                primary_trope_id=selected.primary_trope_id,
            )
        )
        selected_directions = directions.model_copy(
            update={"selected_id": selected.id}
        )
        self._replace_json_transaction(
            {
                self.webnovel_dir / "project.json": project,
                self.webnovel_dir / "outline.json": outline,
                self.webnovel_dir / "opening_directions.json": (
                    selected_directions.model_dump(mode="json")
                ),
            }
        )
        return self.opening_setup()


__all__ = ["OpeningSetupStoreMixin"]
