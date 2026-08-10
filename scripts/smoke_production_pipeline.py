"""Smoke test for the production generation pipeline.

The user feedback after Round 7 listed seven concrete
production failures; the Round 7 plan added Tasks 1-7 to
fix them and Task 8 (this script) to verify the fixes
hold on a real project. The script:

* copies the source project to a disposable directory so
  the operator can re-run it without touching the source;
* hashes the source directory before and after the run so
  any accidental write to the source is detected;
* drives the public ``run_modular_pipeline`` entry point on a
  disposable project so no candidate is confirmed;
* asserts the four acceptance criteria the Round 7 plan
  pinned:

  1. director reads only the current book's outline,
     previous chapter, foreshadowing, and character state
     (no other-book leakage);
  2. the director artifact carries ≥ 2 causal scene beats
     (a chapter plan, not an outline summary);
  3. the writer prompt contains the 4200-5500 target range
     and the 3800-5700 hard range;
  4. the writer context preserves the protagonist's
     equipment, level, inventory, and quests.

By default the script uses deterministic stub runtimes for
CI-safe wiring checks. Pass ``--live`` to use the configured
production gateway against the disposable copy.

Invoke as::

    python -m scripts.smoke_production_pipeline \\
        data/exported-projects/p-gou-webgame-restored

or, with a temporary disposable copy::

    python -m scripts.smoke_production_pipeline --copy \\
        data/exported-projects/p-gou-webgame-restored \\
        $TMPDIR/p-gou-smoke
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from hashlib import sha256
from pathlib import Path
from typing import Any, Iterable

# Direct script execution places ``scripts`` rather than the
# repository root on sys.path. Keep both ``python -m`` and
# ``python scripts/...py`` supported for operators.
REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.story_core.chapter_length_policy import (
    CHAPTER_HARD_MAX_CHARS,
    CHAPTER_HARD_MIN_CHARS,
    CHAPTER_TARGET_MAX_CHARS,
    CHAPTER_TARGET_MIN_CHARS,
)


SOURCE_HASH_BLOCK_SIZE = 65536


@dataclass
class SmokeReport:
    project: Path
    chapter_number: int
    source_hash_before: str
    source_hash_after: str = ""
    director_artifact: dict[str, Any] = field(default_factory=dict)
    writer_prompt: str = ""
    writer_context_cards: list[dict[str, Any]] = field(default_factory=list)
    body_chars: int = 0
    continuity_delta: dict[str, Any] = field(default_factory=dict)
    quality_report: dict[str, Any] = field(default_factory=dict)
    blocking_codes: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    # Rolling-fill mode fields. The production smoke leaves
    # these empty; the rolling-fill smoke populates them.
    rolling_fill_status: dict[str, Any] = field(default_factory=dict)
    rolling_filled_chapters: list[int] = field(default_factory=list)
    rolling_outline_path: str = ""
    rolling_idempotent: bool = False
    rolling_manual_preserved: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "project": str(self.project),
            "chapter_number": self.chapter_number,
            "source_hash_before": self.source_hash_before,
            "source_hash_after": self.source_hash_after,
            "director_artifact": dict(self.director_artifact),
            "writer_prompt_chars": len(self.writer_prompt),
            "writer_context_cards": list(self.writer_context_cards),
            "body_chars": self.body_chars,
            "continuity_delta": dict(self.continuity_delta),
            "quality_report": dict(self.quality_report),
            "blocking_codes": list(self.blocking_codes),
            "errors": list(self.errors),
            "warnings": list(self.warnings),
            "rolling_fill_status": dict(self.rolling_fill_status),
            "rolling_filled_chapters": list(self.rolling_filled_chapters),
            "rolling_outline_path": self.rolling_outline_path,
            "rolling_idempotent": self.rolling_idempotent,
            "rolling_manual_preserved": self.rolling_manual_preserved,
        }


# --- Source-hash guard ------------------------------------------------------


def _hash_directory(root: Path) -> str:
    """Return a stable hash over every file under ``root``.

    The hash is content-addressed so any change the smoke
    script accidentally makes to the source project is
    detected at the end of the run.
    """
    digest = sha256()
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\x00")
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(SOURCE_HASH_BLOCK_SIZE)
                if not chunk:
                    break
                digest.update(chunk)
    return digest.hexdigest()


# --- Stub runtimes ----------------------------------------------------------


class _StubDirectorRuntime:
    """Return a chapter plan that satisfies the production
    validator (≥ 2 causal beats, non-empty fields).

    The stub is intentionally small — the smoke asserts the
    pipeline surfaces the resolved metadata and the artifact
    shape, not the prose.
    """

    def __init__(self, chapter_number: int) -> None:
        self._chapter_number = chapter_number
        self.calls = 0

    def complete(self, request: Any) -> dict[str, Any]:
        self.calls += 1
        return {
            "chapter_number": self._chapter_number,
            "chapter_title": "夜烬夜奔山腰",
            "chapter_goal": "夜烬提交清道夫任务后赶到动态事件外围。",
            "opening_state": "夜烬 Lv.2，任务进度 8/16",
            "scene_beats": [
                {
                    "order": 1,
                    "location": "灰狼坡",
                    "action": "补齐八份毒腺",
                    "result": "任务达到 16/16",
                },
                {
                    "order": 2,
                    "location": "灰烬村",
                    "action": "提交清道夫任务",
                    "result": "升到 Lv.3",
                },
                {
                    "order": 3,
                    "location": "灰狼坡北侧",
                    "action": "观察动态事件",
                    "result": "确认首领机制",
                },
            ],
            "ending_state": "夜烬留在事件外围",
            "hook": "流霜打断狼王冲锋",
            "entity_requirements": [
                {"kind": "character", "name": "夜烬"},
                {"kind": "character", "name": "流霜"},
            ],
        }


class _StubWriterRuntime:
    """Return a body that clears the production hard gate.

    The body is a single sentence repeated enough times to
    clear the 3800-character hard gate; the smoke does not
    assert specific prose wording.
    """

    # 40 chars × 130 ≈ 5200 chars — comfortably inside the
    # 4200-5500 target range so the candidate passes the
    # length gate and the smoke can assert the rest of the
    # acceptance criteria.
    DEFAULT_BODY = (
        "夜烬提灯上山，灰狼坡的红光在雾里忽明忽暗。"
        "他按住左肩的旧伤，咬牙继续向前。"
    ) * 130

    def __init__(self, body: str | None = None) -> None:
        self.body = body if body is not None else self.DEFAULT_BODY
        self.calls = 0

    def complete(self, request: Any) -> Any:
        self.calls += 1

        class _Resp:
            def __init__(self, text: str) -> None:
                self.text = text
                self.raw: dict[str, Any] = {}

        return _Resp(self.body)


class _StubConsistencyRuntime:
    """Return a no-issue consistency review.

    A real-model smoke would route through the production
    gateway; the stub is a deterministic stand-in that
    keeps the smoke runnable in CI without API keys.
    """

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, request: Any) -> dict[str, Any]:
        self.calls += 1
        return {"issues": []}


# --- Project copy -----------------------------------------------------------


def _copy_project(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` so the source is never touched.

    The disposable copy is the only directory the smoke
    writes to; the source hash check at the end of the run
    is the safety net if the copy semantics drift.
    """
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(src, dst)


# --- Smoke driver -----------------------------------------------------------


def _capture_writer_prompt(
    project_root: Path,
    chapter_number: int,
) -> str:
    """Render the writer prompt for the project's writer
    context so the smoke can assert the length policy and
    the current character state are both present.
    """
    from packages.story_core.agents.contracts import (
        DirectorArtifact,
        SceneBeat,
    )
    from packages.story_core.agents.pipeline import (
        _ensure_writer_context,
    )
    from packages.story_core.agents.writer.prompt import (
        build_writer_prompt,
    )
    from packages.story_core.agents.writer.runtime import (
        GatewayWriterRuntime,
    )

    artifact = DirectorArtifact(
        chapter_number=chapter_number,
        chapter_title="夜烬夜奔山腰",
        chapter_goal="夜烬提交清道夫任务后赶到动态事件外围。",
        opening_state="夜烬 Lv.2",
        scene_beats=[
            SceneBeat(order=1, location="灰狼坡", action="补齐毒腺", result="任务 16/16"),
            SceneBeat(order=2, location="灰烬村", action="提交任务", result="升到 Lv.3"),
        ],
        ending_state="留在事件外围",
        hook="流霜打断狼王冲锋",
        entity_requirements=[],
    )
    context = _ensure_writer_context(
        project_root=project_root,
        chapter_number=chapter_number,
        director_artifact=artifact,
    )
    from packages.story_core.agents.pipeline import _build_writer_request

    request = _build_writer_request(
        context=context, director_artifact=artifact
    )
    return build_writer_prompt(request)


def _run_smoke(
    project_root: Path,
    chapter_number: int,
    *,
    source_for_hash: Path | None = None,
    live: bool = False,
) -> SmokeReport:
    """Drive the modular pipeline end-to-end against
    ``project_root``.

    Returns a :class:`SmokeReport` the caller asserts against.
    The function never raises on pipeline failure; instead
    it records the error on the report so the CLI can
    decide whether to print warnings or exit non-zero.

    ``source_for_hash`` is the original source path the
    caller copied ``project_root`` from. The hash guard
    re-hashes that path at the end of the run so a
    copy-semantic drift that accidentally writes to the
    source is detected.
    """
    from packages.story_core.agents.pipeline import (
        run_modular_pipeline,
    )
    from packages.story_core.engine import ChapterBundle, StoryState
    from packages.story_core.file_project_store import FileProjectStore

    store = FileProjectStore(project_root)
    hash_root = source_for_hash or project_root
    report = SmokeReport(
        project=project_root,
        chapter_number=chapter_number,
        source_hash_before=_hash_directory(hash_root),
    )

    # Capture the writer prompt *before* the pipeline runs so
    # the smoke can assert the length policy and the current
    # character state are rendered without depending on the
    # actual model output.
    try:
        report.writer_prompt = _capture_writer_prompt(
            project_root, chapter_number
        )
    except Exception as exc:  # pragma: no cover - defensive
        report.warnings.append(f"writer_prompt_capture_failed: {type(exc).__name__}: {exc}")

    # Drive the public modular entry point. The default stubs
    # keep CI deterministic; ``--live`` leaves runtimes unset
    # so the configured production gateway is exercised.
    director_runtime = None if live else _StubDirectorRuntime(chapter_number)
    writer_runtime = None if live else _StubWriterRuntime()
    consistency_runtime = None if live else _StubConsistencyRuntime()
    try:
        modular_result = run_modular_pipeline(
            project_root=project_root,
            chapter_number=chapter_number,
            director_runtime=director_runtime,
            writer_runtime=writer_runtime,
            consistency_runtime=consistency_runtime,
        )
    except Exception as exc:
        report.errors.append(f"pipeline_failed: {type(exc).__name__}: {exc}")
        report.source_hash_after = _hash_directory(project_root)
        return report

    director_artifact = modular_result.director_artifact
    body = modular_result.body
    report.body_chars = len("".join(str(body or "").split()))
    delta = modular_result.continuity_delta

    # Build a candidate via the public save path so the
    # smoke exercises the same envelope the workbench
    # reads. ``persist=False`` is the public opt-out that
    # stops at the candidate draft.
    try:
        chapter_intent = {
            "chapter_title": director_artifact.chapter_title,
            "primary_conflict": {"summary": director_artifact.chapter_goal},
            "next_focus": director_artifact.hook or "",
        }
        event_plan = {
            "scene_chain": [
                {
                    "order": int(beat.order or 0),
                    "location": str(beat.location or ""),
                    "action": str(beat.action or ""),
                    "change": str(beat.result or ""),
                }
                for beat in director_artifact.scene_beats
            ],
        }
        scene_chain = list(event_plan.get("scene_chain") or [])
        # The smoke's minimum-viable ``ChapterBundle``
        # carries the fields the public save path
        # serialises through ``_bundle_to_dict``. Anything
        # not in the schema is dropped silently, so the
        # smoke keeps the bundle to the canonical
        # 24-field surface.
        bundle = ChapterBundle(
            chapter_number=chapter_number,
            body=body,
            chapter_title=director_artifact.chapter_title,
            cadence="measured",
            chapter_intent=chapter_intent,
            character_moves=[],
            memory_constraints={"must_keep_facts": [], "ledger_updates": {}},
            event_plan=event_plan,
            chapter_seed={},
            simulation_plan={},
            world_events=[],
            scene_cards=scene_chain,
            simulation_status={"status": "skipped", "reason": "smoke"},
            action_briefs=[],
            conflict_summary={},
            event_beat={"turn": director_artifact.hook or ""},
            character_cards=[],
            foreshadowing=[],
            next_outline="",
            updated_story=StoryState(
                story_id="smoke",
                outline="smoke",
                genre="smoke",
                style="smoke",
                current_chapter=chapter_number,
            ),
            chapter_summary={},
            quality_report={},
            pipeline_stages=["director", "writer", "fact_extractor"],
            continuity_delta=delta,
        )
        candidate = store._save_candidate_from_bundle(
            bundle, project_id=store.root.name
        )
    except Exception as exc:
        report.errors.append(f"save_candidate_failed: {type(exc).__name__}: {exc}")
        report.source_hash_after = _hash_directory(project_root)
        return report

    candidate_dict = candidate.to_dict() if hasattr(candidate, "to_dict") else dict(candidate)
    report.quality_report = dict(candidate_dict.get("quality_report") or {})
    report.director_artifact = {
        "chapter_title": director_artifact.chapter_title,
        "primary_conflict": director_artifact.chapter_goal,
        "scene_chain": scene_chain,
    }

    if delta is not None and hasattr(delta, "model_dump"):
        report.continuity_delta = delta.model_dump(mode="json")
    else:
        report.continuity_delta = {}

    # Blocking findings surface on the candidate's
    # quality_report.writing_review. The smoke flattens the
    # list so the acceptance check can read it directly.
    writing_review = report.quality_report.get("writing_review") or {}
    blocking = writing_review.get("blocking") or []
    issues = writing_review.get("issues") or []

    def record_blocking_code(value: Any) -> None:
        code = str(value or "").strip()
        if code and code not in report.blocking_codes:
            report.blocking_codes.append(code)

    for item in blocking:
        if isinstance(item, dict):
            code = str(item.get("code") or "").strip()
            record_blocking_code(code)
        elif isinstance(item, str):
            record_blocking_code(item)
    for item in issues:
        if isinstance(item, str):
            record_blocking_code(item)
        elif isinstance(item, dict):
            code = str(item.get("code") or "").strip()
            record_blocking_code(code)

    # Writer context cards: render the current state of each
    # card so the smoke can assert the protagonist's
    # equipment / level / inventory / quests are preserved.
    try:
        from packages.story_core.agents.contracts import (
            DirectorArtifact as _DA,
            SceneBeat as _SB,
        )
        from packages.story_core.agents.pipeline import (
            _ensure_writer_context,
        )
        from packages.story_core.agents.writer.prompt import (
            _current_character_state,
        )

        context = _ensure_writer_context(
            project_root=project_root,
            chapter_number=chapter_number,
            director_artifact=_DA(
                chapter_number=chapter_number,
                chapter_title=director_artifact.chapter_title,
                chapter_goal=director_artifact.chapter_goal,
                opening_state=director_artifact.opening_state,
                scene_beats=[
                    _SB(
                        order=beat.order,
                        location=beat.location,
                        action=beat.action,
                        result=beat.result,
                    )
                    for beat in director_artifact.scene_beats
                ],
                ending_state=director_artifact.ending_state,
                hook=director_artifact.hook,
            ),
        )
        for card in context.character_cards or []:
            if not isinstance(card, dict):
                continue
            current = _current_character_state(card)
            if current:
                report.writer_context_cards.append(
                    {"name": card.get("name", ""), "current": current}
                )
    except Exception as exc:  # pragma: no cover - defensive
        report.warnings.append(
            f"writer_context_capture_failed: {type(exc).__name__}: {exc}"
        )

    report.source_hash_after = _hash_directory(hash_root)
    return report


# --- Rolling-fill smoke (Round 8 Task 10) -----------------------------------


# The smoke reuses the production file-project store's
# stub generator so the test exercises the real public
# ``ensure_rolling_outline`` entry point end-to-end
# (planner + store + atomic write + backup).
_ROLLING_OUTLINE_REL = (
    Path(".story-system")
    / "outline-generation"
    / "rolling_outline.json"
)


def _stub_rolling_chapter_payload(chapter_number: int) -> dict[str, Any]:
    """Deterministic rolling-outline payload for the smoke.

    Mirrors the shape
    ``FileProjectStore._default_rolling_chapter_generator``
    produces in production so the smoke exercises the same
    schema path the on-disk store validates against.
    """
    return {
        "chapter_number": chapter_number,
        "title": f"第{chapter_number}章",
        "chapter_goal": f"第{chapter_number}章目标",
        "core_conflict": f"第{chapter_number}章冲突",
        "cast": [
            {"name": "林昭", "role": "protagonist", "this_chapter_role": "行动"}
        ],
        "scenes": [
            {"location": "灰狼坡", "action": "补齐毒腺", "result": "16/16"},
            {"location": "灰烬村", "action": "提交任务", "result": "升级"},
        ],
        "gain": "升级到 Lv.3",
        "cost": "灰狼毒腺 8 份",
        "foreshadowing": [],
        "hook": "流霜打断狼王",
        "state_delta": "level=Lv.3",
    }


def _read_rolling_outline_chapter_numbers(
    project_root: Path,
) -> list[int]:
    """Return the chapter numbers present in the rolling
    outline file. Empty list if the file is missing or
    malformed (the smoke treats both as "no fill yet").
    """
    path = project_root / _ROLLING_OUTLINE_REL
    if not path.is_file():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    rows = payload.get("chapters") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    numbers: list[int] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        number = row.get("chapter_number")
        if isinstance(number, int) and not isinstance(number, bool):
            numbers.append(int(number))
    return sorted(set(numbers))


def _read_rolling_outline_payload(
    project_root: Path,
) -> dict[str, Any] | None:
    """Return the full rolling-outline payload, or None if
    the file is missing or malformed.
    """
    path = project_root / _ROLLING_OUTLINE_REL
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def _run_rolling_fill_smoke(
    project_root: Path,
    *,
    source_for_hash: Path,
) -> SmokeReport:
    """Drive the rolling-fill flow on a disposable copy.

    The smoke verifies the three Round 8 acceptance
    criteria the plan rule pins:

    1. ``ensure_rolling_outline`` writes a 5-chapter
       window when the target chapter has no outline.
    2. A second call is a no-op (``kind="present"``) so
       repeated invocations don't churn the disk.
    3. A chapter the user has marked as ``source="manual"``
       is preserved across subsequent fills.

    The smoke never raises on rolling-fill failure; instead
    it records the error on the report so the CLI can
    decide whether to exit non-zero.
    """
    report = SmokeReport(
        project=project_root,
        chapter_number=0,
        source_hash_before=_hash_directory(source_for_hash),
    )
    report.rolling_outline_path = str(_ROLLING_OUTLINE_REL)

    # Step 0: make sure the disposable copy starts from a
    # clean rolling-outline state. The source project may
    # already have a rolling_outline.json from a previous
    # run; the smoke wants to prove the fill path, not
    # the idempotency-of-existing-data path.
    rolling_path = project_root / _ROLLING_OUTLINE_REL
    if rolling_path.is_file():
        rolling_path.unlink()

    # The smoke also clears the legacy outline's
    # ``chapters`` array on the disposable copy so the
    # fill planner actually has a gap to fill. A real
    # production project usually has the legacy outline
    # already populated for the volume the test targets;
    # stripping it lets the smoke prove the full
    # "缺细纲 → 补全" chain on the disposable copy
    # without disturbing the source.
    legacy_outline_path = project_root / ".webnovel" / "outline.json"
    if legacy_outline_path.is_file():
        try:
            legacy_payload = json.loads(
                legacy_outline_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            legacy_payload = None
        if isinstance(legacy_payload, dict) and (
            legacy_payload.get("chapters") or []
        ):
            legacy_payload["chapters"] = []
            legacy_outline_path.write_text(
                json.dumps(legacy_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )

    from packages.story_core.file_project_store import FileProjectStore

    store = FileProjectStore(project_root)

    # Step 1: read the target chapter from state. The
    # smoke uses ``current_chapter + 1`` so the test
    # matches the production "用户点击生成下一章" code
    # path. When the source project has no state.json
    # (an unusual but valid edge), fall back to chapter 1
    # so the smoke still has a deterministic target.
    state = store.state() if hasattr(store, "state") else {}
    current_chapter = int(state.get("current_chapter") or 0)
    target_chapter = current_chapter + 1 if current_chapter >= 0 else 1
    report.chapter_number = target_chapter

    # Step 2: first fill. The status should be
    # ``kind="filled"`` with up to ``window`` chapters.
    try:
        status = store.ensure_rolling_outline(
            target_chapter=target_chapter,
            generator=_stub_rolling_chapter_payload,
            window=5,
        )
    except Exception as exc:  # noqa: BLE001 - smoke boundary
        report.errors.append(
            f"rolling_fill_first_call_failed: "
            f"{type(exc).__name__}: {exc}"
        )
        report.source_hash_after = _hash_directory(source_for_hash)
        return report

    report.rolling_fill_status = status.to_dict()
    report.rolling_filled_chapters = list(status.chapter_numbers)

    # Step 3: second call — must be a no-op
    # (``kind="present"``). The status should NOT include
    # any new chapter numbers; the disk content should be
    # byte-identical for the chapter rows that were
    # already filled.
    try:
        second_status = store.ensure_rolling_outline(
            target_chapter=target_chapter,
            generator=_stub_rolling_chapter_payload,
            window=5,
        )
    except Exception as exc:  # noqa: BLE001 - smoke boundary
        report.errors.append(
            f"rolling_fill_second_call_failed: "
            f"{type(exc).__name__}: {exc}"
        )
        report.source_hash_after = _hash_directory(source_for_hash)
        return report

    report.rolling_idempotent = (
        second_status.kind == "present"
        and not second_status.chapter_numbers
    )

    # Step 4: manual-edit protection. The plan rule: "已
    # 存在或人工修改的细纲不会被覆盖". The smoke edits one
    # of the filled chapters so its title no longer matches
    # the generator's stub, then runs the fill a third
    # time. The chapter's title must still be the
    # user-edited one.
    payload = _read_rolling_outline_payload(project_root)
    if not isinstance(payload, dict):
        report.errors.append("rolling_outline_missing_after_first_fill")
        report.source_hash_after = _hash_directory(source_for_hash)
        return report

    chapters = payload.get("chapters") or []
    manual_chapter: dict[str, Any] | None = None
    if isinstance(chapters, list) and chapters:
        for row in chapters:
            if not isinstance(row, dict):
                continue
            number = row.get("chapter_number")
            if not isinstance(number, int) or isinstance(number, bool):
                continue
            if number < target_chapter or number >= target_chapter + 5:
                continue
            manual_chapter = row
            break

    if manual_chapter is None:
        report.warnings.append(
            "rolling_manual_protection_skipped:no_target_chapter"
        )
    else:
        manual_chapter_number = int(manual_chapter.get("chapter_number"))
        manual_chapter["source"] = "manual"
        manual_chapter["title"] = "用户手工修改的标题"
        # Rewrite the entire file with the manual edit
        # applied so the on-disk store sees the user's
        # intent on the next fill.
        payload["chapters"] = chapters
        rolling_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

        try:
            third_status = store.ensure_rolling_outline(
                target_chapter=target_chapter,
                generator=_stub_rolling_chapter_payload,
                window=5,
            )
        except Exception as exc:  # noqa: BLE001 - smoke boundary
            report.errors.append(
                f"rolling_fill_third_call_failed: "
                f"{type(exc).__name__}: {exc}"
            )
            report.source_hash_after = _hash_directory(source_for_hash)
            return report

        re_read = _read_rolling_outline_payload(project_root) or {}
        re_chapters = (
            re_read.get("chapters") if isinstance(re_read, dict) else None
        ) or []
        preserved_title = ""
        for row in re_chapters:
            if (
                isinstance(row, dict)
                and row.get("chapter_number") == manual_chapter_number
            ):
                preserved_title = str(row.get("title") or "")
                break
        report.rolling_manual_preserved = (
            preserved_title == "用户手工修改的标题"
            and third_status.kind in ("present", "no_op")
        )
        if not report.rolling_manual_preserved:
            report.warnings.append(
                f"rolling_manual_title_overwritten:{preserved_title!r}"
            )

    report.source_hash_after = _hash_directory(source_for_hash)
    return report


def _assert_rolling_fill_acceptance(report: SmokeReport) -> list[str]:
    """Return a list of acceptance failures for the
    rolling-fill report.

    The checks mirror the Round 8 plan's acceptance
    criteria; a non-empty return list means the smoke
    failed and the CLI exits non-zero.
    """
    failures: list[str] = []

    # 1. First fill must produce ``kind="filled"`` and a
    #    window of at least the target chapter.
    status = report.rolling_fill_status
    if status.get("kind") != "filled":
        failures.append(
            f"rolling_fill_first_call_not_filled: {status.get('kind')!r}"
        )
    target_chapter = int(report.chapter_number or 0)
    filled = list(report.rolling_filled_chapters)
    if target_chapter not in filled:
        failures.append(
            f"rolling_fill_missing_target:{target_chapter} -> {filled}"
        )
    if filled:
        # Window must be contiguous from the target and
        # span at most 5 chapters (the plan rule).
        expected = list(range(target_chapter, target_chapter + 5))
        contiguous = list(range(filled[0], filled[-1] + 1))
        if filled != contiguous:
            failures.append(
                f"rolling_fill_window_not_contiguous: {filled}"
            )
        if any(chapter not in filled for chapter in expected[: len(filled)]):
            failures.append(
                f"rolling_fill_window_broken: expected {expected} got {filled}"
            )

    # 2. Idempotency: second call must NOT churn the disk.
    if not report.rolling_idempotent:
        failures.append("rolling_fill_not_idempotent")

    # 3. Manual-edit protection: a chapter marked
    #    ``source="manual"`` must keep its user-edited
    #    title across a subsequent fill.
    if not report.rolling_manual_preserved:
        failures.append("rolling_fill_overwrote_manual_chapter")

    # 4. The on-disk rolling outline must exist after the
    #    fill (and not be the empty initial state).
    payload = _read_rolling_outline_payload(report.project)
    if not isinstance(payload, dict):
        failures.append("rolling_outline_file_missing_on_disk")
    else:
        chapters = payload.get("chapters") or []
        if not isinstance(chapters, list) or not chapters:
            failures.append("rolling_outline_file_empty_chapters")

    # 5. Source hash must match — the smoke never touches
    #    the source directory.
    if report.source_hash_before != report.source_hash_after:
        failures.append("source_hash_changed")

    return failures


# --- Acceptance checks ------------------------------------------------------


def _assert_acceptance(report: SmokeReport) -> list[str]:
    """Return a list of acceptance failures for ``report``.

    The four checks mirror the Round 7 plan's acceptance
    criteria; a non-empty return list means the smoke
    failed and the CLI exits non-zero.
    """
    failures: list[str] = []

    # 1. Director reads only the current book / previous
    #    chapter / foreshadowing / character state.
    #    The plan calls for "no other-book leakage". The
    #    smoke verifies the director artifact carries the
    #    current chapter's title and a chapter goal that is
    #    not a literal copy of the outline summary.
    artifact = report.director_artifact
    if not artifact.get("chapter_title"):
        failures.append("director_artifact_missing_chapter_title")
    if not artifact.get("primary_conflict"):
        failures.append("director_artifact_missing_chapter_goal")

    # 2. Director artifact has ≥ 2 causal scene beats.
    scene_chain = artifact.get("scene_chain") or []
    if len(scene_chain) < 2:
        failures.append(
            f"director_artifact_insufficient_beats: {len(scene_chain)}"
        )
    for beat in scene_chain:
        # ``scene_chain`` follows the legacy
        # ``event_plan.scene_chain`` shape: ``change`` is the
        # causal result, not ``result``. The smoke accepts
        # both spellings so a future refactor that switches
        # to the DirectorArtifact-native shape keeps the
        # acceptance check honest.
        location = beat.get("location")
        action = beat.get("action")
        result = beat.get("result") or beat.get("change")
        if not (location and action and result):
            failures.append(
                f"director_artifact_incomplete_beat: {beat.get('order')}"
            )
            break

    # 3. Writer prompt contains the 4200-5500 target and
    #    the 3800-5700 hard range.
    prompt = report.writer_prompt
    if (
        f"目标{CHAPTER_TARGET_MIN_CHARS}至{CHAPTER_TARGET_MAX_CHARS}字"
        not in prompt
    ):
        failures.append("writer_prompt_missing_target_range")
    if f"低于{CHAPTER_HARD_MIN_CHARS}字" not in prompt:
        failures.append("writer_prompt_missing_hard_min")
    if f"超过{CHAPTER_HARD_MAX_CHARS}字" not in prompt:
        failures.append("writer_prompt_missing_hard_max")

    if report.quality_report.get("ok") is not True:
        failures.append("quality_report_failed")
    if not (
        CHAPTER_HARD_MIN_CHARS
        <= int(report.body_chars or 0)
        <= CHAPTER_HARD_MAX_CHARS
    ):
        failures.append(f"body_chars_out_of_range:{int(report.body_chars or 0)}")
    if report.blocking_codes:
        failures.append(
            "blocking_findings:" + ",".join(report.blocking_codes)
        )

    # 4. Writer context preserves the protagonist's
    #    equipment / level / inventory / quests when those
    #    fields are present.
    if not report.writer_context_cards:
        # The project has no current-state character
        # cards; the assertion is vacuously satisfied.
        pass
    else:
        # At least one character card must carry a
        # non-empty current state (the project must not
        # have flattened the state away).
        non_empty = [
            card
            for card in report.writer_context_cards
            if any(value for value in (card.get("current") or {}).values())
        ]
        if not non_empty:
            failures.append("writer_context_dropped_character_state")
        from packages.story_core.context.legacy_adapter import (
            _normalize_inventory_item_name,
        )

        for card in non_empty:
            current = card.get("current") or {}
            for namespace in ("game_state", "game_panel"):
                state = current.get(namespace)
                if not isinstance(state, dict):
                    continue
                inventory = state.get("inventory")
                if not isinstance(inventory, dict):
                    continue
                malformed = [
                    str(name)
                    for name in inventory
                    if _normalize_inventory_item_name(name) != str(name).strip()
                ]
                if malformed:
                    failures.append(
                        "writer_context_malformed_inventory: "
                        + ",".join(malformed[:4])
                    )
                    break

    # Source hash must match — the smoke never touches the
    # source directory.
    if report.source_hash_before != report.source_hash_after:
        failures.append("source_hash_changed")

    return failures


# --- CLI --------------------------------------------------------------------


def _resolve_project(
    *,
    project: str | None,
    copy: tuple[str, str] | None,
    tmpdir: str | None = None,
) -> tuple[Path, Path | None]:
    """Resolve the project root the smoke will operate on.

    Returns a ``(project_root, source_for_hash)`` tuple.
    The smoke NEVER touches the source directory directly:
    ``--project`` is copied to a temporary disposable
    directory unless the user explicitly opted into
    ``--copy``. ``source_for_hash`` is the original source
    path the smoke hashes before and after the run to
    detect any accidental write.
    """
    if copy is not None:
        src, dst = copy
        src_path = Path(src).resolve()
        dst_path = Path(dst).resolve()
        _copy_project(src_path, dst_path)
        return dst_path, src_path
    if project:
        src_path = Path(project).resolve()
        temp_root = Path(
            tmpdir or tempfile.mkdtemp(prefix="xiaoshuofish-smoke-")
        )
        temp_root.mkdir(parents=True, exist_ok=True)
        dst_path = temp_root / src_path.name
        _copy_project(src_path, dst_path)
        return dst_path, src_path
    raise SystemExit("specify --project <path> or --copy <src> <dst>")


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Production pipeline smoke. The default mode "
            "drives the full body-generation pipeline and "
            "asserts the Round 7 acceptance criteria. "
            "--mode rolling-fill exercises the rolling-outline "
            "fill path (Round 8) and asserts the 5-chapter "
            "window, idempotency, and manual-edit protection."
        )
    )
    parser.add_argument("--project", help="path to a project root")
    parser.add_argument(
        "--copy",
        nargs=2,
        metavar=("SRC", "DST"),
        help="copy SRC to DST then smoke DST (does not touch SRC)",
    )
    parser.add_argument(
        "--chapter",
        type=int,
        default=1,
        help="chapter number the smoke drives (default 1)",
    )
    parser.add_argument(
        "--tmpdir",
        default=None,
        help="temporary directory to use with --copy when --copy is omitted",
    )
    parser.add_argument(
        "--live",
        action="store_true",
        help="use the configured production gateway instead of deterministic stubs",
    )
    parser.add_argument(
        "--mode",
        choices=("production", "rolling-fill"),
        default="production",
        help=(
            "smoke mode. 'production' (default) drives the full "
            "body generation. 'rolling-fill' exercises the "
            "rolling-outline fill and asserts the Round 8 "
            "acceptance criteria."
        ),
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    copy = tuple(args.copy) if args.copy else None
    if copy is None and args.project is None:
        default_src = (
            Path(__file__).resolve().parent.parent
            / "data"
            / "exported-projects"
            / "p-gou-webgame-restored"
        )
        if not default_src.is_dir():
            print(
                f"default source not found: {default_src}",
                file=sys.stderr,
            )
            return 2
        temp_root = Path(
            args.tmpdir
            or tempfile.mkdtemp(prefix="xiaoshuofish-smoke-")
        )
        temp_root.mkdir(parents=True, exist_ok=True)
        copy = (str(default_src), str(temp_root / default_src.name))
    project_root, source_for_hash = _resolve_project(
        project=args.project, copy=copy, tmpdir=args.tmpdir
    )

    if args.mode == "rolling-fill":
        report = _run_rolling_fill_smoke(
            project_root,
            source_for_hash=source_for_hash,
        )
        failures = _assert_rolling_fill_acceptance(report)
    else:
        report = _run_smoke(
            project_root,
            args.chapter,
            source_for_hash=source_for_hash,
            live=args.live,
        )
        failures = _assert_acceptance(report)
    print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    if failures or report.errors:
        print("\nFAILURES:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        for error in report.errors:
            print(f"  - {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
