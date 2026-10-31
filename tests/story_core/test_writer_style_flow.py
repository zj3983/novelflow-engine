"""Book voice reaches the production writer without changing committed chapters."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core.agents.contracts import DirectorArtifact, SceneBeat
from packages.story_core.agents.pipeline import (
    _build_writer_request,
    _ensure_writer_context,
    run_writer,
)
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.context.writer_context import build_writer_context
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import NovelProject, StoryState
from packages.story_core.orchestrator import StoryOrchestrator


PREFERENCES = {
    "writing_style": "幽默",
    "writing_guidance": "嘴上吐槽，行动谨慎。GUIDANCE-MARKER",
    "writing_reference": "我超威，这给我干哪来了？REFERENCE-MARKER",
}


def _write(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")


def _artifact(number: int = 2) -> DirectorArtifact:
    return DirectorArtifact(
        chapter_number=number,
        chapter_goal="陈砺打捞淡水",
        opening_state="陈砺趴在浮板上",
        scene_beats=[
            SceneBeat(order=1, location="海面", action="陈砺伸出捞杆", result="捞到木箱")
        ],
        ending_state="木箱放在浮板上",
    )


def _project(root: Path, *, canonical: bool = False) -> None:
    folder = ".story-system" if canonical else ".webnovel"
    _write(root / folder / "project.json", {"title": "海上求生", "world_blueprint": PREFERENCES})
    _write(root / folder / "state.json", {"story_id": "s-style", "world_facts": []})
    (root / ".story-system").mkdir(exist_ok=True)


@pytest.mark.parametrize("canonical", [False, True])
def test_persisted_book_voice_reaches_the_final_writer_prompt(tmp_path: Path, canonical: bool) -> None:
    _project(tmp_path, canonical=canonical)
    artifact = _artifact()
    context = _ensure_writer_context(project_root=tmp_path, chapter_number=2, director_artifact=artifact)
    request = _build_writer_request(context=context, director_artifact=artifact)
    prompt = build_writer_prompt(request)

    assert "幽默：" in prompt
    assert PREFERENCES["writing_guidance"] in prompt
    assert PREFERENCES["writing_reference"] in prompt
    assert "不照抄" in prompt
    assert "不作为本章已发生的事实" in prompt


def test_canonical_writer_context_reads_book_voice(tmp_path: Path) -> None:
    _project(tmp_path, canonical=True)
    context = build_writer_context(project=tmp_path, chapter_number=2, director_artifact=_artifact())
    assert {key: context.model_dump().get(key) for key in PREFERENCES} == PREFERENCES


def test_current_settings_and_explicit_clear_override_old_canonical_voice(tmp_path: Path) -> None:
    _project(tmp_path, canonical=True)
    _project(tmp_path)
    cleared = {key: "" for key in PREFERENCES}
    _write(tmp_path / ".webnovel" / "project.json", {"title": "海上求生", "world_blueprint": cleared})
    _write(tmp_path / ".webnovel" / "state.json", {"style": "幽默", "world_facts": []})
    context = _ensure_writer_context(project_root=tmp_path, chapter_number=2, director_artifact=_artifact())
    prompt = build_writer_prompt(_build_writer_request(context=context, director_artifact=_artifact()))
    assert "幽默：" not in prompt
    assert "GUIDANCE-MARKER" not in prompt
    assert "REFERENCE-MARKER" not in prompt


def test_custom_voice_works_without_a_preset(tmp_path: Path) -> None:
    _project(tmp_path)
    _write(tmp_path / ".webnovel" / "project.json", {
        "world_blueprint": {**PREFERENCES, "writing_style": ""},
    })
    context = _ensure_writer_context(project_root=tmp_path, chapter_number=2, director_artifact=_artifact())
    prompt = build_writer_prompt(_build_writer_request(context=context, director_artifact=_artifact()))
    assert "幽默：" not in prompt
    assert "GUIDANCE-MARKER" in prompt
    assert "REFERENCE-MARKER" in prompt


def test_voice_save_and_clear_preserve_existing_chapter_bytes(tmp_path: Path) -> None:
    _project(tmp_path)
    body_path = tmp_path / "chapters" / "0001-original.md"
    body_path.parent.mkdir()
    body_path.write_text("原有正文，不得覆盖。", encoding="utf-8")
    chapter_path = tmp_path / ".story-system" / "chapters" / "0001.json"
    _write(chapter_path, {"chapter_number": 1, "body": "原有正文，不得覆盖。"})
    before = {path: path.read_bytes() for path in (body_path, chapter_path)}
    store = FileProjectStore(tmp_path)

    store.update_project({"world_blueprint": PREFERENCES})
    assert all(path.read_bytes() == content for path, content in before.items())
    store.update_project({"world_blueprint": {key: "" for key in PREFERENCES}})
    context = _ensure_writer_context(project_root=tmp_path, chapter_number=2, director_artifact=_artifact())
    assert {key: context.model_dump().get(key) for key in PREFERENCES} == {key: "" for key in PREFERENCES}
    assert all(path.read_bytes() == content for path, content in before.items())


@pytest.mark.parametrize("key, value", [
    ("writing_guidance", {"bad": "not text"}),
    ("writing_reference", ["not text"]),
    ("writing_guidance", "x" * 2001),
    ("writing_reference", "x" * 4001),
], ids=["guidance-object", "reference-list", "guidance-too-long", "reference-too-long"])
def test_invalid_voice_input_does_not_change_project(tmp_path: Path, key: str, value: object) -> None:
    _project(tmp_path)
    path = tmp_path / ".webnovel" / "project.json"
    before = path.read_bytes()
    with pytest.raises(ValueError, match="invalid_writing_preferences"):
        FileProjectStore(tmp_path).update_project({"world_blueprint": {key: value}})
    assert path.read_bytes() == before


class _WriterRuntime:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, request):
        self.prompts.append(request.prompt)
        return SimpleNamespace(text="陈砺趴在板上，伸手捞住木箱。", finish_reason="stop")


def test_next_continuous_and_rewrite_writer_calls_read_current_voice(tmp_path: Path) -> None:
    _project(tmp_path)
    runtime = _WriterRuntime()
    run_writer(project_root=tmp_path, chapter_number=2, director_artifact=_artifact(), runtime=runtime)
    FileProjectStore(tmp_path).update_project({"world_blueprint": {"writing_guidance": "UPDATED-VOICE"}})
    run_writer(project_root=tmp_path, chapter_number=3, director_artifact=_artifact(3), runtime=runtime)
    run_writer(project_root=tmp_path, chapter_number=1, director_artifact=_artifact(1), runtime=runtime,
               rewrite_guidance="ONE-OFF-REWRITE")
    assert "GUIDANCE-MARKER" in runtime.prompts[0]
    assert "UPDATED-VOICE" in runtime.prompts[1]
    assert "GUIDANCE-MARKER" not in runtime.prompts[1]
    assert "UPDATED-VOICE" in runtime.prompts[2]
    assert "ONE-OFF-REWRITE" in runtime.prompts[2]
    assert all("REFERENCE-MARKER" in prompt for prompt in runtime.prompts)


def test_old_project_generation_and_revision_include_custom_voice() -> None:
    from apps.api.storage import _sync_project_generation_context

    story = StoryState(story_id="s-style", outline="打捞淡水", genre="通用网文", style="")
    project = NovelProject(project_id="p-style", title="海上求生", world_blueprint=PREFERENCES)
    _sync_project_generation_context(story, project, has_history=True)
    orchestrator = StoryOrchestrator()
    for prompt in (
        orchestrator._body_prompt(story, 2, {"goal": "打捞淡水"}),
        orchestrator._revision_prompt(story, 2, "陈砺抓住捞杆。", {"goal": "打捞淡水"}, {}),
    ):
        assert "GUIDANCE-MARKER" in prompt
        assert "REFERENCE-MARKER" in prompt
    project.world_blueprint = {key: "" for key in PREFERENCES}
    _sync_project_generation_context(story, project, has_history=True)
    prompt = orchestrator._body_prompt(story, 2, {"goal": "打捞淡水"})
    assert "GUIDANCE-MARKER" not in prompt
    assert "REFERENCE-MARKER" not in prompt
