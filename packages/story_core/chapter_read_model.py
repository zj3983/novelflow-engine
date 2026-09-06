from __future__ import annotations

from copy import deepcopy
import json
import re
from typing import Any

from packages.story_core.character_profiles import remove_cross_character_aliases
from packages.story_core.world_state import normalize_world_context

def _normalize_chapter_title(title: str, chapter_number: int) -> str:
    cleaned = str(title or "").strip()
    cleaned = re.sub(rf"^\s*第\s*{chapter_number}\s*章[：:\s、.-]*", "", cleaned).strip()
    cleaned = re.sub(r"^\s*第\s*[零一二三四五六七八九十百千万]+\s*章[：:\s、.-]*", "", cleaned).strip()
    return cleaned or str(title or "").strip() or f"Chapter {chapter_number}"


def _usable_chapter_title(value: Any, chapter_number: int) -> str:
    """Return a real title, excluding serialized nulls and UI placeholders."""

    if value is None:
        return ""
    text = str(value).strip()
    if not text:
        return ""
    lowered = text.casefold()
    if lowered in {"none", "null", "undefined", "未命名", "未命名章节"}:
        return ""
    return _normalize_chapter_title(text, chapter_number)


def _chapter_payload_title(chapter: Any, chapter_number: int) -> str:
    """Read a persisted title without consulting outline storage."""

    if not isinstance(chapter, dict):
        return ""
    candidates = [chapter.get("chapter_title")]
    for key in ("chapter_intent", "event_plan", "chapter_summary"):
        nested = chapter.get(key)
        if isinstance(nested, dict):
            candidates.append(nested.get("chapter_title") or nested.get("title"))
    for candidate in candidates:
        title = _usable_chapter_title(candidate, chapter_number)
        if title:
            return title
    return ""

class FileProjectReadMixin:
    """Read-only chapter and workbench projections for a file project."""
    def _read_chapter_records(
        self,
        *,
        ignore_errors: bool = False,
    ) -> list[tuple[int, dict[str, Any]]]:
        records: list[tuple[int, dict[str, Any]]] = []
        for number in self.chapter_numbers():
            try:
                chapter = self._read_json(
                    self.story_system_dir / "chapters" / f"{number:04d}.json",
                    {},
                )
            except (OSError, ValueError, json.JSONDecodeError):
                if not ignore_errors:
                    raise
                chapter = {}
            records.append((number, chapter if isinstance(chapter, dict) else {}))
        return records

    def _visible_state_from_chapters(
        self,
        state: dict[str, Any],
        project: dict[str, Any],
        chapters: list[dict[str, Any]],
    ) -> dict[str, Any]:
        sanitized = self._sanitize_story_state(state)
        additions: list[dict[str, Any]] = []
        saved_characters = sanitized.get("characters") if isinstance(sanitized.get("characters"), list) else []
        project_profiles = {
            str(card.get("name") or "").strip(): card
            for card in project.get("character_profiles", [])
            if isinstance(card, dict) and str(card.get("name") or "").strip()
        }
        for index, saved in enumerate(saved_characters):
            if not isinstance(saved, dict):
                continue
            profile = project_profiles.get(str(saved.get("name") or "").strip())
            if not isinstance(profile, dict):
                continue
            if str(profile.get("character_tier") or "").strip().casefold() == "protagonist":
                promoted = dict(saved)
                promoted["role"] = "protagonist"
                promoted["character_tier"] = "protagonist"
                saved_characters[index] = promoted
        sanitized["characters"] = saved_characters
        protagonist_indexes = [
            index
            for index, card in enumerate(saved_characters)
            if isinstance(card, dict)
            and (
                str(card.get("role") or "").strip().casefold() in {"protagonist", "主角"}
                or str(card.get("character_tier") or "").strip().casefold() == "protagonist"
            )
        ]
        is_game_story = self._is_game_story_payload(project, sanitized)
        if protagonist_indexes and is_game_story:
            ledger = sanitized.get("progression_ledger") if isinstance(sanitized.get("progression_ledger"), dict) else {}
            real = ledger.get("real") if isinstance(ledger.get("real"), dict) else {}
            real_balance = real.get("end_balance") or real.get("balance")
            for index in protagonist_indexes:
                card = dict(saved_characters[index])
                self._sync_game_character_from_ledger(
                    card,
                    ledger,
                    chapter_number=int(sanitized.get("current_chapter") or 0),
                )
                if real_balance:
                    real_state = dict(card.get("real_state") or {})
                    current_real = dict(real_state.get("current") or {})
                    current_real["balance"] = real_balance
                    real_state["current"] = current_real
                    real_state.setdefault("recent_changes", [])
                    card["real_state"] = real_state
                saved_characters[index] = card
            sanitized["characters"] = saved_characters
        elif not protagonist_indexes and is_game_story:
            protagonist_card = self._protagonist_character_card(sanitized, project)
            if protagonist_card:
                additions.append(protagonist_card)
        if is_game_story:
            additions.extend(self._proposed_character_cards_from_outline(sanitized, project))
            for chapter in chapters:
                additions.extend(self._chapter_entity_cards(chapter))
        if additions:
            sanitized["characters"] = self._merge_character_cards(list(sanitized.get("characters") or []), additions)
        characters = sanitized.get("characters") if isinstance(sanitized.get("characters"), list) else []
        characters = self._without_replaced_baseline_protagonists(
            item for item in characters if isinstance(item, dict)
        )
        characters = remove_cross_character_aliases(
            item for item in characters if isinstance(item, dict)
        )
        genre = str(sanitized.get("genre") or project.get("genre") or "")
        sanitized["characters"] = [
            self._completed_character_card(dict(item), genre=genre)
            for item in characters
            if isinstance(item, dict) and self._is_character_card(item)
        ]
        return sanitized

    def state(self) -> dict[str, Any]:
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        project = self.project()
        records = self._read_chapter_records(ignore_errors=True)
        visible = self._visible_state_from_chapters(
            state if isinstance(state, dict) else {},
            project,
            [chapter for _, chapter in records],
        )
        normalized_world = normalize_world_context(
            blueprint=project.get("world_blueprint"),
            state=visible,
            current_focus=project.get("current_focus"),
        )
        visible["world_snapshot"] = normalized_world.world_snapshot
        visible["continuity_facts"] = normalized_world.continuity_facts
        return visible

    def persisted_state(self) -> dict[str, Any]:
        """Return the canonical saved state without rebuilding derived character cards."""
        state = self._read_json(self.webnovel_dir / "state.json", {}) or {}
        return state if isinstance(state, dict) else {}

    def chapter_numbers(self) -> list[int]:
        return self.chapter_store.chapter_numbers()

    def _has_chapter_files(self) -> bool:
        return self.chapter_store.has_chapters()

    def chapter(self, chapter_number: int | None = None) -> dict[str, Any]:
        if chapter_number is not None and chapter_number > 0:
            path = self.story_system_dir / "chapters" / f"{chapter_number:04d}.json"
            chapter = self._read_json(path)
            if not isinstance(chapter, dict):
                if not self._has_chapter_files():
                    raise FileNotFoundError("no_chapters")
                raise FileNotFoundError(f"chapter_not_found:{chapter_number}")
            chapter = self._hydrate_chapter_body(chapter)
            return self._hydrate_chapter_display_fields(chapter, state=self.persisted_state())

        numbers = self.chapter_numbers()
        if not numbers:
            raise FileNotFoundError("no_chapters")
        target = chapter_number or numbers[-1]
        path = self.story_system_dir / "chapters" / f"{target:04d}.json"
        chapter = self._read_json(path)
        if not isinstance(chapter, dict):
            raise FileNotFoundError(f"chapter_not_found:{target}")
        chapter = self._hydrate_chapter_body(chapter)
        return self._hydrate_chapter_display_fields(chapter)

    def _hydrate_chapter_body(self, chapter: dict[str, Any]) -> dict[str, Any]:
        """Re-add a Markdown-canonical chapter's ``body`` field.

        After the Markdown migration the chapter JSON no longer
        carries the prose; consumers that still read ``chapter['body']``
        (the inventory parser, the opening-baseline rebuild, the
        workbench previews) get a hydrated copy through this
        helper.
        """
        if not isinstance(chapter, dict) or "body" in chapter:
            return chapter
        body_path_value = chapter.get("body_path")
        if not body_path_value:
            return chapter
        markdown_path = self.root / str(body_path_value)
        if not markdown_path.is_file():
            return chapter
        hydrated = dict(chapter)
        hydrated["body"] = markdown_path.read_text(encoding="utf-8")
        return hydrated

    def _chapter_index_from_records(
        self,
        records: list[tuple[int, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        entries: list[dict[str, Any]] = []
        for number, chapter in records:
            try:
                payload_chapter_number = int(chapter.get("chapter_number") or number)
            except (TypeError, ValueError):
                payload_chapter_number = number
            chapter_summary = chapter.get("chapter_summary")
            summary = chapter_summary if isinstance(chapter_summary, dict) else {}
            summary_text = self._compact_text(summary.get("summary") or "", 320)
            next_focus = self._compact_text(
                chapter.get("next_outline") or summary.get("next_focus") or "",
                220,
            )
            quality_report = chapter.get("quality_report")
            simulation_status = chapter.get("simulation_status")
            display_title = _chapter_payload_title(chapter, payload_chapter_number)
            if not display_title:
                display_title = f"第{payload_chapter_number}章"
            entries.append(
                {
                    "chapter_number": payload_chapter_number,
                    "chapter_title": display_title,
                    "body_chars": self._chapter_body_chars(chapter),
                    "summary": summary_text,
                    "next_focus": next_focus,
                    "has_quality_report": isinstance(quality_report, dict) and bool(quality_report),
                    "has_simulation": isinstance(simulation_status, dict) and bool(simulation_status),
                }
            )
        return entries

    def _chapter_body_chars(self, chapter: dict[str, Any]) -> int:
        """Return the compact character count without hydrating a full chapter."""
        body = chapter.get("body")
        if isinstance(body, str):
            return len("".join(body.split()))

        cached = chapter.get("body_chars")
        if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
            return cached

        body_path = chapter.get("body_path")
        if not body_path:
            return 0
        markdown_path = self.root / str(body_path)
        if not markdown_path.is_file():
            return 0
        try:
            markdown_body = markdown_path.read_text(encoding="utf-8")
        except OSError:
            return 0
        return len("".join(markdown_body.split()))

    def chapter_index(self) -> list[dict[str, Any]]:
        signature = self.chapter_store.metadata_signature()
        cache_path = self.story_system_dir / "chapter-index.json"
        cached = self._read_json(cache_path, {}) or {}
        if (
            isinstance(cached, dict)
            and cached.get("schema_version") == "chapter-index/v1"
            and cached.get("signature") == signature
            and isinstance(cached.get("chapters"), list)
        ):
            return [dict(item) for item in cached["chapters"] if isinstance(item, dict)]

        chapters = self._chapter_index_from_records(self._read_chapter_records())
        self._write_json_atomic(
            cache_path,
            {
                "schema_version": "chapter-index/v1",
                "signature": signature,
                "chapters": chapters,
            },
        )
        return chapters

    def _cache_chapter_index(
        self,
        records: list[tuple[int, dict[str, Any]]],
    ) -> list[dict[str, Any]]:
        chapters = self._chapter_index_from_records(records)
        self._write_json_atomic(
            self.story_system_dir / "chapter-index.json",
            {
                "schema_version": "chapter-index/v1",
                "signature": self.chapter_store.metadata_signature(),
                "chapters": chapters,
            },
        )
        return chapters

    def story_overview_data(self) -> dict[str, Any]:
        state = self.persisted_state()
        project = self.project()
        saved_characters = state.get("characters")
        needs_character_backfill = not (
            isinstance(saved_characters, list)
            and any(isinstance(item, dict) and item.get("name") for item in saved_characters)
        )
        if needs_character_backfill:
            records = self._read_chapter_records()
            chapters = self._cache_chapter_index(records)
        else:
            records = []
            chapters = self.chapter_index()
        visible_state = self._visible_state_from_chapters(
            state,
            project,
            [chapter for _, chapter in records],
        )
        normalized_world = normalize_world_context(
            blueprint=project.get("world_blueprint"),
            state=visible_state,
            current_focus=project.get("current_focus"),
        )
        visible_state["world_snapshot"] = normalized_world.world_snapshot
        visible_state["continuity_facts"] = normalized_world.continuity_facts
        return {
            "project": project,
            "state": visible_state,
            "chapters": chapters,
        }
