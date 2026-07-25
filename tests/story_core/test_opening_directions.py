import json
import os
import inspect
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

import packages.story_core.opening_directions as opening_directions_module
import packages.story_core.file_project_store as file_project_store_module
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import NovelProject, NovelProjectSummary
from packages.story_core.novel_type_catalog import novel_type_prompt_context, runtime_novel_type
from packages.story_core.opening_directions import (
    LLMOpeningDirectionGenerator,
    OpeningBrief,
    OpeningDirection,
    OpeningDirectionSet,
)
from packages.story_core.project_outline import normalize_project_outline
from packages.story_core.runtime_config import StageRuntimeSettings


def test_generator_constructor_does_not_accept_legacy_strategy_resolver():
    assert "strategy_resolver" not in inspect.signature(LLMOpeningDirectionGenerator).parameters


_AUTO_TROPE = object()


def _urban_primary_trope_ids() -> list[str]:
    return [
        str(item["id"])
        for item in novel_type_prompt_context(runtime_novel_type("urban"))["genre_trope_templates"]
    ]


def direction(
    direction_id: str,
    *,
    title: str | None = None,
    primary_trope_id: object | str | None = _AUTO_TROPE,
) -> dict[str, str | None]:
    if primary_trope_id is _AUTO_TROPE:
        primary_trope_id = _urban_primary_trope_ids()[0]
    return {
        "id": direction_id,
        "title": title or f"Title {direction_id}",
        "hook": f"Hook {direction_id}",
        "protagonist_goal": f"Goal {direction_id}",
        "main_conflict": f"Conflict {direction_id}",
        "growth_path": f"Growth {direction_id}",
        "opening_promise": f"Promise {direction_id}",
        "primary_trope_id": primary_trope_id,
    }


def direction_set(*, selected_id: str = "") -> dict:
    trope_ids = _urban_primary_trope_ids()
    return {
        "schema_version": "opening-directions/v1",
        "directions": [
            direction("direction-1", primary_trope_id=trope_ids[0]),
            direction("direction-2", primary_trope_id=trope_ids[1]),
            direction("direction-3", primary_trope_id=trope_ids[2]),
        ],
        "selected_id": selected_id,
    }


class StaticDirectionGenerator:
    def __init__(self, payload=None):
        self.payload = payload if payload is not None else direction_set()

    def generate(self, brief, *, guidance=""):
        return self.payload


def make_opening_store(tmp_path) -> FileProjectStore:
    root = tmp_path / "opening-project"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir()
    project = {
        "project_id": "p-opening",
        "title": "Original title",
        "seed_outline": "",
        "world_summary": "",
        "current_focus": "",
        "author_constraints": [],
        "character_profiles": [],
        "relationship_graph": [],
        "enabled_skill_ids": [],
        "world_blueprint": {"genre_plugin_ids": ["urban"]},
        "current_chapter": 0,
        "status": "draft",
        "pipeline_stage": "idea_pending",
    }
    state = {
        "story_id": "file:p-opening",
        "outline": "",
        "genre": "Urban",
        "style": "Web novel",
        "current_chapter": 0,
        "world_facts": [],
        "characters": [],
        "enabled_skill_ids": ["SECRET_SKILL"],
    }
    brief = {
        "schema_version": "opening-brief/v1",
        "mode": "inspiration",
        "novel_type_id": "urban",
        "idea": "A courier receives tomorrow's missing-person report.",
        "working_title": "Tomorrow's Courier",
    }
    master = {"schema_version": "story-system-master-setting/v1", "project": project, "state": state}
    payloads = {
        root / ".story-system" / "MASTER_SETTING.json": master,
        root / ".webnovel" / "project.json": project,
        root / ".webnovel" / "state.json": state,
        root / ".webnovel" / "outline.json": normalize_project_outline({}),
        root / ".webnovel" / "opening_brief.json": brief,
    }
    for path, payload in payloads.items():
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    (root / "chapters" / "0001-secret.md").write_text("SECRET_HISTORY_CHAPTER", encoding="utf-8")
    return FileProjectStore(root)


def test_direction_set_requires_exactly_three_unique_candidates_and_forbids_extra_fields():
    with pytest.raises(ValidationError):
        OpeningDirectionSet.model_validate({"directions": [direction("a"), direction("b")]})
    with pytest.raises(ValidationError, match="duplicate_direction_id"):
        OpeningDirectionSet.model_validate(
            {"directions": [direction("a"), direction("a"), direction("c")]}
        )
    invalid = direction_set()
    invalid["directions"][0]["ending_direction"] = "not part of the candidate contract"
    with pytest.raises(ValidationError):
        OpeningDirectionSet.model_validate(invalid)


def test_opening_brief_is_strict_and_trims_required_text():
    brief = OpeningBrief(
        mode="inspiration",
        novel_type_id="urban",
        idea="  a compact idea  ",
        working_title="  Working title  ",
    )
    assert brief.idea == "a compact idea"
    assert brief.working_title == "Working title"
    with pytest.raises(ValidationError):
        OpeningBrief.model_validate(
            {"mode": "inspiration", "novel_type_id": "urban", "idea": " ", "character": "secret"}
        )


def test_opening_direction_primary_trope_id_trims_strings_and_preserves_none():
    trimmed = OpeningDirection.model_validate(
        {**direction("direction-1"), "primary_trope_id": "  chosen-trope  "}
    )
    none_value = OpeningDirection.model_validate(
        {**direction("direction-1"), "primary_trope_id": None}
    )

    assert trimmed.primary_trope_id == "chosen-trope"
    assert none_value.primary_trope_id is None


@pytest.mark.parametrize("pipeline_stage", ["direction_ready", "outlining"])
def test_project_pipeline_types_accept_opening_stages(pipeline_stage):
    payload = {
        "project_id": "p-opening",
        "title": "Opening project",
        "pipeline_stage": pipeline_stage,
    }

    assert NovelProject.model_validate(payload).pipeline_stage == pipeline_stage
    assert NovelProjectSummary.model_validate(payload).pipeline_stage == pipeline_stage


def test_generator_prompt_contains_only_brief_genre_and_empty_guidance():
    captured = {}
    runtime_calls = []

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured.update(
            {"base_url": base_url, "path": path, "payload": payload, "api_key": api_key, "kwargs": kwargs}
        )
        return {
            "choices": [
                {"message": {"content": json.dumps({"directions": direction_set()["directions"]})}}
            ]
        }

    generator = LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=lambda name: runtime_calls.append(name) or StageRuntimeSettings(
            provider="codexcli",
            model="direction-test-model",
            base_url="http://runtime.test",
            codex_command="codex-test",
            temperature=0.31,
        ),
    )
    result = generator.generate(
        OpeningBrief(
            mode="inspiration",
            novel_type_id="urban",
            idea="SECRET_IDEA",
            working_title="SECRET_WORKING_TITLE",
        )
    )

    assert len(result.directions) == 3
    assert runtime_calls == ["planner"]
    assert captured["path"] == "/chat/completions"
    assert captured["payload"]["model"] == "direction-test-model"
    assert captured["payload"]["temperature"] == 0.31
    assert captured["payload"]["response_format"] == {"type": "json_object"}
    prompt_context = json.loads(captured["payload"]["messages"][1]["content"])
    assert set(prompt_context) == {
        "genre_label",
        "genre_description",
        "genre_core_promises",
        "genre_rulebook",
        "genre_quality_checks",
        "genre_trope_templates",
        "working_title",
        "idea",
        "regeneration_guidance",
    }
    assert prompt_context["idea"] == "SECRET_IDEA"
    assert prompt_context["working_title"] == "SECRET_WORKING_TITLE"
    assert prompt_context["regeneration_guidance"] == ""
    assert prompt_context["genre_trope_templates"]
    assert "genre_trope_templates" in captured["payload"]["messages"][1]["content"]
    system_prompt = captured["payload"]["messages"][0]["content"]
    assert "primary_trope_id" in system_prompt
    assert "choose one listed primary_trope_id" in system_prompt
    assert "Return null only when candidate list empty" in system_prompt
    entire_prompt = json.dumps(captured["payload"]["messages"], ensure_ascii=False)
    assert "SECRET_CHARACTER_CARD" not in entire_prompt
    assert "SECRET_HISTORY_CHAPTER" not in entire_prompt
    assert "SECRET_SKILL" not in entire_prompt


def test_generator_adds_trimmed_one_time_guidance_to_prompt():
    captured = {}

    def fake_post(base_url, path, payload, api_key, **kwargs):
        captured["payload"] = payload
        return {
            "choices": [
                {"message": {"content": json.dumps({"directions": direction_set()["directions"]})}}
            ]
        }

    generator = LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=lambda _: StageRuntimeSettings(
            provider="codexcli",
            model="direction-test-model",
            base_url="http://runtime.test",
            codex_command="codex-test",
        ),
    )

    generator.generate(
        OpeningBrief(novel_type_id="urban", idea="Original idea"),
        guidance="  ONLY_FOR_THIS_REGENERATION  ",
    )

    prompt = json.loads(captured["payload"]["messages"][1]["content"])
    assert prompt["regeneration_guidance"] == "ONLY_FOR_THIS_REGENERATION"


def test_generator_rejects_guidance_longer_than_1000_after_trimming():
    runtime_calls = []
    generator = LLMOpeningDirectionGenerator(
        runtime_resolver=lambda name: runtime_calls.append(name),
    )

    with pytest.raises(ValueError, match="^regeneration_guidance_too_long$"):
        generator.generate(
            OpeningBrief(novel_type_id="urban", idea="Original idea"),
            guidance=f"  {'x' * 1001}  ",
        )

    assert runtime_calls == []


def test_generator_accepts_known_primary_trope_choices(monkeypatch):
    candidates = [{"id": "trope-a"}, {"id": "trope-b"}]
    monkeypatch.setattr(
        opening_directions_module,
        "runtime_novel_type",
        lambda _: SimpleNamespace(id="urban"),
    )
    monkeypatch.setattr(
        opening_directions_module,
        "novel_type_prompt_context",
        lambda _: {
            "genre_label": "Urban",
            "genre_description": "desc",
            "genre_core_promises": [],
            "genre_rulebook": {},
            "genre_quality_checks": [],
            "genre_trope_templates": candidates,
        },
    )
    generator = LLMOpeningDirectionGenerator(
        post_json=lambda *args, **kwargs: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "directions": [
                                    direction("direction-1", primary_trope_id="trope-a"),
                                    direction("direction-2", primary_trope_id="trope-b"),
                                    direction("direction-3", primary_trope_id="trope-a"),
                                ]
                            }
                        )
                    }
                }
            ]
        },
        runtime_resolver=lambda _: StageRuntimeSettings(
            provider="codexcli",
            model="direction-test-model",
            base_url="http://runtime.test",
            codex_command="codex-test",
        ),
    )

    result = generator.generate(OpeningBrief(novel_type_id="urban", idea="Known trope"))

    assert [item.primary_trope_id for item in result.directions] == ["trope-a", "trope-b", "trope-a"]


@pytest.mark.parametrize("primary_trope_id", [None, "", "unknown-trope"])
def test_generator_rejects_missing_blank_or_unknown_primary_trope_when_candidates_exist(
    monkeypatch,
    primary_trope_id,
):
    monkeypatch.setattr(
        opening_directions_module,
        "runtime_novel_type",
        lambda _: SimpleNamespace(id="urban"),
    )
    monkeypatch.setattr(
        opening_directions_module,
        "novel_type_prompt_context",
        lambda _: {
            "genre_label": "Urban",
            "genre_description": "desc",
            "genre_core_promises": [],
            "genre_rulebook": {},
            "genre_quality_checks": [],
            "genre_trope_templates": [{"id": "trope-a"}],
        },
    )
    generator = LLMOpeningDirectionGenerator(
        post_json=lambda *args, **kwargs: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "directions": [
                                    direction("direction-1", primary_trope_id=primary_trope_id),
                                    direction("direction-2", primary_trope_id="trope-a"),
                                    direction("direction-3", primary_trope_id="trope-a"),
                                ]
                            }
                        )
                    }
                }
            ]
        },
        runtime_resolver=lambda _: StageRuntimeSettings(
            provider="codexcli",
            model="direction-test-model",
            base_url="http://runtime.test",
            codex_command="codex-test",
        ),
    )

    with pytest.raises(ValueError, match="^opening_direction_generation_failed$"):
        generator.generate(OpeningBrief(novel_type_id="urban", idea="Unknown trope"))


def test_generator_allows_null_primary_trope_only_when_candidate_list_empty(monkeypatch):
    monkeypatch.setattr(
        opening_directions_module,
        "runtime_novel_type",
        lambda _: SimpleNamespace(id="urban"),
    )
    monkeypatch.setattr(
        opening_directions_module,
        "novel_type_prompt_context",
        lambda _: {
            "genre_label": "Urban",
            "genre_description": "desc",
            "genre_core_promises": [],
            "genre_rulebook": {},
            "genre_quality_checks": [],
            "genre_trope_templates": [],
        },
    )
    generator = LLMOpeningDirectionGenerator(
        post_json=lambda *args, **kwargs: {
            "choices": [
                {
                    "message": {
                        "content": json.dumps(
                            {
                                "directions": [
                                    direction("direction-1", primary_trope_id=None),
                                    direction("direction-2", primary_trope_id=None),
                                    direction("direction-3", primary_trope_id=None),
                                ]
                            }
                        )
                    }
                }
            ]
        },
        runtime_resolver=lambda _: StageRuntimeSettings(
            provider="codexcli",
            model="direction-test-model",
            base_url="http://runtime.test",
            codex_command="codex-test",
        ),
    )

    result = generator.generate(OpeningBrief(novel_type_id="urban", idea="No trope choices"))

    assert [item.primary_trope_id for item in result.directions] == [None, None, None]


def test_store_passes_trimmed_guidance_without_persisting_it(tmp_path):
    store = make_opening_store(tmp_path)
    secret = "ONLY_FOR_THIS_REGENERATION"
    secret_bytes = secret.encode("utf-8")
    calls = []

    class RecordingGenerator:
        def generate(self, brief, *, guidance=""):
            calls.append(guidance)
            return direction_set()

    files_before = {path for path in store.root.rglob("*") if path.is_file()}
    assert all(secret_bytes not in path.read_bytes() for path in files_before)

    store.generate_opening_directions(RecordingGenerator(), guidance=f"  {secret}  ")

    assert calls == [secret]
    files_after = {path for path in store.root.rglob("*") if path.is_file()}
    assert store.webnovel_dir / "opening_directions.json" in files_after - files_before
    assert all(secret_bytes not in path.read_bytes() for path in files_after)


@pytest.mark.parametrize(
    "runtime,response",
    [
        (StageRuntimeSettings(provider="openai", model="planner-model", api_key=""), None),
        (
            StageRuntimeSettings(provider="codexcli", model="planner-model", codex_command="codex"),
            {"choices": [{"message": {"content": json.dumps({"directions": [direction("only")]})}}]},
        ),
        (StageRuntimeSettings(provider="codexcli", model="planner-model", codex_command="codex"), {"choices": []}),
    ],
)
def test_generator_unifies_unavailable_runtime_and_invalid_output(runtime, response):
    def fake_post(*args, **kwargs):
        if response is None:
            raise AssertionError("unavailable runtime must not be called")
        return response

    generator = LLMOpeningDirectionGenerator(
        post_json=fake_post,
        runtime_resolver=lambda name: runtime,
    )

    with pytest.raises(ValueError, match="^opening_direction_generation_failed$"):
        generator.generate(OpeningBrief(novel_type_id="urban", idea="An idea"))


def test_generate_updates_project_and_candidates_in_one_transaction(tmp_path, monkeypatch):
    store = make_opening_store(tmp_path)
    directions_path = store.webnovel_dir / "opening_directions.json"
    directions_path.write_text(json.dumps(direction_set(), indent=2), encoding="utf-8")
    project_path = store.webnovel_dir / "project.json"
    before = {path: path.read_bytes() for path in (project_path, directions_path)}
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(file_project_store_module.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        store.generate_opening_directions(StaticDirectionGenerator())

    assert {path: path.read_bytes() for path in before} == before


def test_select_rolls_back_project_outline_and_directions_on_replace_failure(tmp_path, monkeypatch):
    store = make_opening_store(tmp_path)
    directions_path = store.webnovel_dir / "opening_directions.json"
    directions_path.write_text(json.dumps(direction_set(), indent=2), encoding="utf-8")
    paths = (
        store.webnovel_dir / "project.json",
        store.webnovel_dir / "outline.json",
        directions_path,
    )
    before = {path: path.read_bytes() for path in paths}
    real_replace = os.replace
    calls = 0

    def fail_second_replace(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected replace failure")
        return real_replace(source, target)

    monkeypatch.setattr(file_project_store_module.os, "replace", fail_second_replace)

    with pytest.raises(OSError, match="injected replace failure"):
        store.select_opening_direction("direction-2")

    assert {path: path.read_bytes() for path in paths} == before


def test_invalid_generated_payload_preserves_previous_candidates(tmp_path):
    store = make_opening_store(tmp_path)
    directions_path = store.webnovel_dir / "opening_directions.json"
    directions_path.write_text(json.dumps(direction_set(), indent=2), encoding="utf-8")
    before = directions_path.read_bytes()

    with pytest.raises(ValueError):
        store.generate_opening_directions(
            StaticDirectionGenerator({"directions": [direction("a"), direction("b")]})
        )

    assert directions_path.read_bytes() == before


def test_store_rejects_fake_generator_with_unknown_primary_trope_without_overwriting_candidates(tmp_path):
    store = make_opening_store(tmp_path)
    directions_path = store.webnovel_dir / "opening_directions.json"
    directions_path.write_text(json.dumps(direction_set(), indent=2), encoding="utf-8")
    before = directions_path.read_bytes()

    with pytest.raises(ValueError, match="^opening_direction_generation_failed$"):
        store.generate_opening_directions(
            StaticDirectionGenerator(
                {
                    "schema_version": "opening-directions/v1",
                    "directions": [
                        direction("direction-1", primary_trope_id="not-a-real-trope"),
                        direction("direction-2"),
                        direction("direction-3"),
                    ],
                    "selected_id": "",
                }
            )
        )

    assert directions_path.read_bytes() == before
