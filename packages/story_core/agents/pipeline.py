"""High-level pipeline that drives the new modular agents.

The orchestrator's main flow still calls the legacy
``resolve_chapter_plan`` / ``generate_chapter_body`` helpers. This
module is the single bridge that lets the orchestrator delegate to
the new Director / Writer agents *and* the CanonService entity
preflight — without forcing every real project to migrate to the
new ``.story-system/`` layout first.

The bridge handles two real-world gaps the modular agents alone do
not cover:

* **Legacy project layout.** Real projects keep their state under
  ``.webnovel/`` (``outline.json``, ``state.json``,
  ``project.json``). The bridge reads through
  ``context.legacy_adapter`` and synthesises the canonical view
  the agents expect (``outline.json``, ``volume.json``,
  ``characters/*.json``).
* **Outline shortcut.** The director agent's
  ``_outline_artifact`` shortcut looks for a target chapter
  keyed ``number`` in ``context.nearby_outline``. The bridge
  performs the same lookup against the legacy ``chapter_number``
  key so projects with no canonical outline still get the
  short-circuit.

The pipeline exposes three high-level entry points the orchestrator
calls:

* :func:`plan_director_artifact` — runs the director context
  builder and the director agent and returns a
  ``DirectorArtifact``.
* :func:`run_writer` — runs the writer context builder, the
  canon entity preflight, the writer agent, and the focused
  consistency check. Returns a ``WriterPipelineResult`` with the
  prose and the per-stage traces.
* :func:`run_fact_extractor` — extracts a ``ContinuityDelta``
  from the body so the candidate can carry the user's proposed
  facts into confirmation.

These three entry points are exercised end-to-end by
``tests/story_core/test_modular_pipeline_e2e.py``.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import hashlib
import re
from typing import Any

from packages.story_core.agents.contracts import (
    DirectorArtifact,
    EntityRequirement,
    WriterRequest,
    WriterResult,
)
from packages.story_core.agents.director.agent import DirectorAgent
from packages.story_core.agents.director.runtime import (
    DirectorRuntime,
    GatewayDirectorRuntime,
)
from packages.story_core.agents.fact_extractor import (
    FactExtractor,
    FactExtractorContext,
)
from packages.story_core.agents.writer.agent import WriterAgent
from packages.story_core.agents.writer.runtime import (
    GatewayWriterRuntime,
    WriterRuntime,
)
from packages.story_core.agents.consistency import (
    ConsistencyFinding,
    ConsistencyRuntime,
    GatewayConsistencyRuntime,
    focused_consistency_review,
)
# Canon classes are imported lazily inside the two callers that
# actually construct them (``_ensure_canon_service`` and
# ``_RequirementEntityDesigner.design``).  Importing them at module
# scope creates a circular import with
# ``packages.story_core.canon`` — the canon package itself loads
# ``agents.contracts`` (via ``entity_designer``), and
# ``agents/__init__.py`` eagerly re-exports this pipeline module.
from packages.story_core.chapter_length_policy import (
    CHAPTER_HARD_MAX_CHARS,
    CHAPTER_HARD_MIN_CHARS,
    acceptance_chars,
    target_chars,
)
from packages.story_core.generation_progress import report_generation_progress
from packages.story_core.context.director_context import (
    DirectorContext,
    build_director_context,
)
from packages.story_core.context.legacy_adapter import (
    legacy_active_characters,
    legacy_enabled_skill_ids,
    legacy_outline_view,
    legacy_project_view,
    legacy_previous_chapter,
    legacy_state_view,
    legacy_volume_view,
)
from packages.story_core.context.writer_context import (
    WriterContext,
    build_writer_context,
)
from packages.story_core.writer_character_context import (
    historical_writer_character_cards,
    writer_historical_chapter,
)
from packages.story_core.continuity.delta import ContinuityDelta
from packages.story_core.generation_consistency_gate import (
    ConsistencyGateRequired,
    GenerationConsistencyGate,
    require_generation_consistency,
)
from packages.story_core.consistency_replanning import (
    ConsistencyReplanRequest,
    build_director_replan_guidance,
)
from packages.story_core.skill_packs import resolve_enabled_skill_module_ids


# --- Result envelopes ---------------------------------------------------------


@dataclass
class DirectorPipelineResult:
    """Output of :func:`plan_director_artifact`."""

    artifact: DirectorArtifact
    context: DirectorContext
    trace_id: str = ""


@dataclass
class WriterPipelineResult:
    """Output of :func:`run_writer`."""

    body: str
    context: WriterContext
    director_artifact: DirectorArtifact
    canon_preflight: dict[str, Any] = field(default_factory=dict)
    consistency_findings: list[dict[str, Any]] = field(default_factory=list)
    trace_id: str = ""


@dataclass
class ModularChapterBundle:
    """The full output of :func:`run_modular_pipeline`.

    Bundles the director's :class:`DirectorArtifact`, the writer's
    body, and the :class:`ContinuityDelta` produced by the
    fact-extractor into a single envelope. The orchestrator exposes
    this envelope as the workbench's "what each agent did" record;
    tests use it to assert the three modules were each called
    exactly once.
    """

    chapter_number: int
    director_artifact: DirectorArtifact
    director_trace_id: str
    body: str
    writer_context: WriterContext
    canon_preflight: dict[str, Any] = field(default_factory=dict)
    writer_trace_id: str = ""
    consistency_findings: list[dict[str, Any]] = field(default_factory=list)
    consistency_gate: GenerationConsistencyGate | None = None
    continuity_delta: ContinuityDelta | None = None
    fact_extractor_trace_id: str = ""


# --- Helpers ------------------------------------------------------------------


def _ensure_director_context(
    *,
    project_root: Any,
    chapter_number: int,
) -> DirectorContext:
    """Build a director context, falling back to the legacy adapter
    when the canonical ``.story-system/`` artifacts are missing.
    """
    canonical: DirectorContext | None = None
    try:
        canonical = build_director_context(
            project=project_root, chapter_number=chapter_number
        )
    except (FileNotFoundError, ValueError):
        pass
    system_root = _system_root(project_root)
    legacy = _legacy_director_context(
        system_root=system_root, project_root=project_root, chapter_number=chapter_number
    )
    if canonical is None:
        return legacy
    return canonical.model_copy(
        update={
            "volume": canonical.volume or legacy.volume,
            "book_outline_summary": (
                canonical.book_outline_summary or legacy.book_outline_summary
            ),
            "nearby_outline": canonical.nearby_outline or legacy.nearby_outline,
            "previous_chapter_summary": (
                canonical.previous_chapter_summary
                or legacy.previous_chapter_summary
            ),
            "previous_chapter_tail": (
                canonical.previous_chapter_tail or legacy.previous_chapter_tail
            ),
            "continuity_ledger": (
                canonical.continuity_ledger or legacy.continuity_ledger
            ),
            "foreshadowing": canonical.foreshadowing or legacy.foreshadowing,
            "character_cards": canonical.character_cards or legacy.character_cards,
            "inventory": canonical.inventory or legacy.inventory,
            "active_entity_names": (
                canonical.active_entity_names or legacy.active_entity_names
            ),
        }
    )


def _ensure_writer_context(
    *,
    project_root: Any,
    chapter_number: int,
    director_artifact: DirectorArtifact,
) -> WriterContext:
    """Build a writer context, falling back to the legacy adapter
    when the canonical ``.story-system/`` artifacts are missing.
    """
    canonical: WriterContext | None = None
    try:
        canonical = build_writer_context(
            project=project_root,
            chapter_number=chapter_number,
            director_artifact=director_artifact,
        )
    except (FileNotFoundError, ValueError):
        pass
    system_root = _system_root(project_root)
    legacy = _legacy_writer_context(
        system_root=system_root,
        project_root=project_root,
        chapter_number=chapter_number,
        director_artifact=director_artifact,
    )
    if canonical is None:
        return legacy
    return canonical.model_copy(
        update={
            "project_title": canonical.project_title or legacy.project_title,
            "genre": canonical.genre or legacy.genre,
            "previous_tail": canonical.previous_tail or legacy.previous_tail,
            "continuity_facts": (
                canonical.continuity_facts or legacy.continuity_facts
            ),
            "character_cards": canonical.character_cards or legacy.character_cards,
            "entity_cards": canonical.entity_cards or legacy.entity_cards,
            "world_rules": canonical.world_rules or legacy.world_rules,
            "craft_modules": canonical.craft_modules or legacy.craft_modules,
            "enabled_skill_ids": (
                canonical.enabled_skill_ids or legacy.enabled_skill_ids
            ),
            "enabled_skill_module_ids": (
                canonical.enabled_skill_module_ids
                if canonical.enabled_skill_module_ids is not None
                else legacy.enabled_skill_module_ids
            ),
            "book_outline": canonical.book_outline or legacy.book_outline,
        }
    )


def _system_root(project_root: Any):
    from pathlib import Path

    return Path(project_root) / ".story-system"


def _normalize_legacy_facts(items: Any) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for item in items or []:
        if isinstance(item, dict):
            normalized.append(dict(item))
            continue
        text = str(item or "").strip()
        if text:
            normalized.append({"subject": "", "field": "fact", "value": text})
    return normalized


def _legacy_director_context(
    *,
    system_root: Any,
    project_root: Any,
    chapter_number: int,
) -> DirectorContext:
    """Synthesise a director context from the legacy ``.webnovel/`` shape."""
    from pathlib import Path

    system_root_path = Path(system_root)
    outline = legacy_outline_view(system_root_path) or {}
    volume = legacy_volume_view(system_root_path, chapter_number) or {}
    # The director context reads ``number`` per chapter; the
    # adapter already translates this for us.
    nearby = list(outline.get("chapters") or [])
    previous_summary = ""
    previous_tail = ""
    continuity_ledger: list[dict[str, Any]] = []
    foreshadowing: list[dict[str, Any]] = []
    state = legacy_state_view(system_root_path) or {}
    if state:
        # Pull the most recent chapter summary so the director sees
        # the story so far.
        for entry in reversed(list(state.get("chapter_summaries") or [])):
            if isinstance(entry, dict) and entry.get("chapter_number") == chapter_number - 1:
                previous_summary = str(entry.get("summary") or "")
                previous_tail = str(entry.get("next_focus") or previous_summary)
                continuity_ledger = _normalize_legacy_facts(entry.get("facts"))
                break
        foreshadowing = list(state.get("foreshadowing") or [])
    character_cards = legacy_active_characters(system_root_path)
    return DirectorContext(
        chapter_number=chapter_number,
        volume=volume or {"chapter_range": [max(chapter_number - 2, 1), chapter_number + 2]},
        book_outline_summary=str((outline.get("overall") or {}).get("story") or ""),
        nearby_outline=nearby,
        previous_chapter_summary=previous_summary,
        previous_chapter_tail=previous_tail,
        continuity_ledger=continuity_ledger,
        foreshadowing=foreshadowing,
        character_cards=character_cards,
        active_entity_names=[str(card.get("name") or "") for card in character_cards if card.get("name")],
    )


def _legacy_writer_context(
    *,
    system_root: Any,
    project_root: Any,
    chapter_number: int,
    director_artifact: DirectorArtifact,
) -> WriterContext:
    """Synthesise a writer context from the legacy ``.webnovel/`` shape."""
    from pathlib import Path

    system_root_path = Path(system_root)
    previous = legacy_previous_chapter(system_root_path, chapter_number) or {}
    character_cards = legacy_active_characters(system_root_path)
    state = legacy_state_view(system_root_path) or {}
    replay_state = dict(state)
    if not isinstance(replay_state.get("characters"), list) or not replay_state.get("characters"):
        replay_state["characters"] = [dict(card) for card in character_cards]
    else:
        state_characters = replay_state["characters"]
        known_state_names = {
            str(item.get("name") or "").strip()
            for item in state_characters
            if isinstance(item, dict)
        }
        replay_state["characters"] = [
            *state_characters,
            *[
                dict(card)
                for card in character_cards
                if str(card.get("name") or "").strip() not in known_state_names
            ],
        ]
    historical_cards = historical_writer_character_cards(
        replay_state,
        as_of_chapter=writer_historical_chapter(chapter_number),
    )
    historical_by_name = {
        str(card.get("name") or "").strip(): card
        for card in historical_cards
        if str(card.get("name") or "").strip()
    }
    character_cards = [
        historical_by_name[str(card.get("name") or "").strip()]
        for card in character_cards
        if str(card.get("name") or "").strip() in historical_by_name
    ]
    world_facts = list(state.get("world_facts") or [])
    progression_ledger = state.get("progression_ledger")
    continuity_facts = (
        _normalize_legacy_facts(progression_ledger.get("continuity_ledger"))
        if isinstance(progression_ledger, dict)
        else []
    )
    if not continuity_facts:
        # Fall back to the previous chapter's ``facts`` so the
        # writer sees what just happened.
        continuity_facts = _normalize_legacy_facts(previous.get("facts"))
    enabled_skill_ids = legacy_enabled_skill_ids(system_root_path)
    project_payload = legacy_project_view(system_root_path) or {}
    enabled_skill_module_ids = resolve_enabled_skill_module_ids(
        project_payload,
        state,
    )
    project_title = ""
    genre = ""
    if isinstance(project_payload, dict):
        project_title = str(project_payload.get("title") or "").strip()
        genre_id = project_payload.get("genre_plugin_id") or project_payload.get("genre")
        if isinstance(genre_id, str) and genre_id.strip():
            genre = genre_id.strip()
    return WriterContext(
        chapter_number=chapter_number,
        director_artifact=director_artifact,
        project_title=project_title,
        genre=genre,
        previous_tail=str(previous.get("tail") or ""),
        continuity_facts=continuity_facts,
        character_cards=character_cards,
        entity_cards=character_cards,  # characters double as entity cards in legacy shape
        world_rules=world_facts,
        craft_modules=[{"id": skill_id, "enabled": True} for skill_id in enabled_skill_ids],
        enabled_skill_ids=enabled_skill_ids,
        enabled_skill_module_ids=enabled_skill_module_ids,
    )


# --- Director pipeline --------------------------------------------------------


def plan_director_artifact(
    *,
    project_root: Any,
    chapter_number: int,
    runtime: DirectorRuntime | None = None,
    rewrite_guidance: str = "",
    replan_request: ConsistencyReplanRequest | None = None,
    persist: bool = True,
) -> DirectorPipelineResult:
    """Run the new director pipeline for ``chapter_number``.

    The pipeline builds a ``DirectorContext`` (legacy-aware),
    delegates to ``DirectorAgent.plan``, and persists the
    resulting artifact under ``.story-system/director/NNNN.json``.
    The returned :class:`DirectorPipelineResult` carries the
    context so the writer pipeline can reuse it without a second
    read pass.

    The agent is told the *real* provider / model from the
    stage settings so the persisted
    ``.story-system/director/NNNN.json`` envelope no longer
    reports the placeholder ``"gateway"`` / ``"runtime/director"``
    pair. The workbench's stage evidence column reads this
    field directly, so the operator sees which runtime
    answered the director call.
    """
    context = _ensure_director_context(
        project_root=project_root, chapter_number=chapter_number
    )
    guidance_parts = [rewrite_guidance.strip()] if rewrite_guidance.strip() else []
    if replan_request is not None:
        guidance_parts.append(build_director_replan_guidance(replan_request))
    combined_guidance = "\n\n".join(guidance_parts)
    if combined_guidance:
        context = context.model_copy(
            update={"rewrite_guidance": combined_guidance}
        )
    runtime = runtime or _default_director_runtime(project_root)
    provider, model = _resolved_stage_provider_model("director")
    agent = DirectorAgent(
        runtime=runtime,
        project_root=project_root,
        provider=provider,
        model=model,
    )
    artifact = agent.plan(context, persist=persist)
    return DirectorPipelineResult(
        artifact=artifact,
        context=context,
        trace_id=f"director:{chapter_number}",
    )


# --- Writer pipeline ----------------------------------------------------------


_SIMILE_MARKERS = ("仿佛", "如同", "犹如", "宛如", "就像", "像是")
_REALM_PATTERN = re.compile(
    r"(炼气|筑基|结丹|金丹|元婴|化神|洞天|登天)(?:期)?"
    r"([一二三四五六七八九十百两\d]+)层"
)


def _plain_card(card: Any) -> dict[str, Any]:
    if isinstance(card, dict):
        return card
    model_dump = getattr(card, "model_dump", None)
    if callable(model_dump):
        dumped = model_dump(mode="json")
        return dumped if isinstance(dumped, dict) else {}
    return {}


def _protagonist_card(cards: list[Any]) -> dict[str, Any] | None:
    for raw_card in cards:
        card = _plain_card(raw_card)
        role_text = " ".join(
            str(card.get(key) or "")
            for key in ("role", "character_tier", "story_role")
        )
        if "主角" in role_text or "protagonist" in role_text.lower():
            return card
    return None


def _realm_mentions(text: str) -> list[tuple[str, str]]:
    return [(match.group(1), match.group(2)) for match in _REALM_PATTERN.finditer(text)]


def _deterministic_prose_findings(
    body: str,
    character_cards: list[Any],
    *,
    rewrite_guidance: str = "",
) -> list[ConsistencyFinding]:
    """Catch a few objective draft defects without another model call."""
    findings: list[ConsistencyFinding] = []
    simile_count = sum(body.count(marker) for marker in _SIMILE_MARKERS)
    if simile_count >= 8:
        findings.append(
            ConsistencyFinding(
                code="style.simile_stacking",
                message=f"正文使用了{simile_count}处显式比喻，密度过高，需要改成直接叙述。",
                source="deterministic",
                blocking=True,
            )
        )

    limited_relief_required = "只缓解" in rewrite_guidance or "仅缓解" in rewrite_guidance
    full_recovery_claimed = bool(
        re.search(r"(?:完全|彻底)(?:化解|治愈|恢复)", body)
    )
    if limited_relief_required and full_recovery_claimed:
        findings.append(
            ConsistencyFinding(
                code="canon.limited_effect_overstated",
                message="本章要求效果仅为缓解，正文却写成完全恢复。",
                source="deterministic",
                blocking=True,
            )
        )

    protagonist = _protagonist_card(character_cards)
    if protagonist is None:
        return findings
    profile = protagonist.get("current_life_profile") or {}
    current_state = protagonist.get("current_state") or {}
    expected_text = " ".join(
        str(value or "")
        for value in (
            profile.get("resources_and_ability") if isinstance(profile, dict) else "",
            current_state.get("summary") if isinstance(current_state, dict) else current_state,
        )
    )
    expected = _realm_mentions(expected_text)
    if not expected:
        return findings
    expected_realm, expected_layer = expected[-1]
    for actual_realm, actual_layer in _realm_mentions(body):
        if actual_realm == expected_realm and actual_layer != expected_layer:
            findings.append(
                ConsistencyFinding(
                    code="canon.protagonist_realm_drift",
                    message=(
                        f"主角角色卡为{expected_realm}{expected_layer}层，"
                        f"正文却写成{actual_realm}{actual_layer}层。"
                    ),
                    source="deterministic",
                    blocking=True,
                )
            )
            break
    return findings


def run_writer(
    *,
    project_root: Any,
    chapter_number: int,
    director_artifact: DirectorArtifact,
    canon_registry: Any | None = None,
    runtime: WriterRuntime | None = None,
    consistency_runtime: ConsistencyRuntime | None = None,
    rewrite_guidance: str = "",
) -> WriterPipelineResult:
    """Run the new writer pipeline for ``chapter_number``.

    The pipeline:
      1. Builds a ``WriterContext`` (legacy-aware);
      2. Calls :func:`canon_service.ensure_requirements` to
         preflight or promote the entities the director requires;
      3. Calls :func:`WriterAgent.run` to render the prose;
      4. Calls the focused consistency agent to surface any
         contradiction the deterministic hard gate should review.

    The orchestrator still runs its own review / revision flow
    after this pipeline returns, so the pipeline never
    overwrites the bounded review contract.
    """
    context = _ensure_writer_context(
        project_root=project_root,
        chapter_number=chapter_number,
        director_artifact=director_artifact,
    )
    if rewrite_guidance.strip():
        context = context.model_copy(
            update={"rewrite_guidance": rewrite_guidance.strip()}
        )
    canon = _ensure_canon_service(canon_registry, project_root)
    preflight, prepared_entities = _preflight_entities(canon, director_artifact)
    context = _add_prepared_entities_to_context(context, prepared_entities)
    runtime = runtime or _default_writer_runtime(project_root)
    request = _build_writer_request(
        context=context, director_artifact=director_artifact
    )
    agent = WriterAgent(runtime=runtime)
    result = agent.run(request)
    # Deterministic pre-candidate length gate. The bounded flow
    # used to surface a 3800-character failure only at the
    # confirmation step, by which time the workbench had already
    # shown "通过" on the candidate. We add a blocking finding
    # here so the candidate quality report shows the same
    # failure the confirmation will reject.
    consistency_findings: list[ConsistencyFinding] = []
    consistency_findings.extend(
        _deterministic_prose_findings(
            result.body,
            list(context.character_cards or []),
            rewrite_guidance=rewrite_guidance,
        )
    )
    if result.notes.startswith("rewrite_guidance_violation:"):
        detail = result.notes.partition(":")[2].replace(",", "、")
        consistency_findings.append(
            ConsistencyFinding(
                code="guidance.explicit_prohibition_violated",
                message=f"正文仍包含本次写作指导明确禁止的细节：{detail}",
                source="rewrite_guidance",
                blocking=True,
            )
        )
    elif result.notes.startswith("document_transcription:"):
        detail = result.notes.partition(":")[2].replace(",", "、")
        consistency_findings.append(
            ConsistencyFinding(
                code="style.document_transcription",
                message=f"文书或面板字段照抄过多：{detail}",
                source="writer",
                blocking=False,
            )
        )
    body_chars = len("".join(result.body.split()))
    if body_chars < int(
        request.acceptance_chars.get("min", CHAPTER_HARD_MIN_CHARS)
    ):
        consistency_findings.append(
            ConsistencyFinding(
                code="chapter.length_too_short",
                message=(
                    f"正文约{body_chars}字，低于"
                    f"{request.acceptance_chars.get('min', CHAPTER_HARD_MIN_CHARS)}字。"
                ),
                source="deterministic",
                blocking=True,
            )
        )
    elif body_chars > int(
        request.acceptance_chars.get("max", CHAPTER_HARD_MAX_CHARS)
    ):
        consistency_findings.append(
            ConsistencyFinding(
                code="chapter.length_too_long",
                message=(
                    f"正文约{body_chars}字，超过"
                    f"{request.acceptance_chars.get('max', CHAPTER_HARD_MAX_CHARS)}字。"
                ),
                source="deterministic",
                blocking=True,
            )
        )
    # The focused consistency review surfaces deterministic
    # contradictions (e.g. world facts the writer violated, the
    # director's plan the writer diverged from). A failure here
    # must propagate through the bundle so the orchestrator's
    # ``writing_review.pass`` reflects the actual finding set,
    # not a hard-coded True. The agent itself is best-effort:
    # if the runtime is missing or the model call raises we
    # still return the writer's body and just record no
    # findings — the user's confirmation gate is the final
    # safety net for the legacy editor surface.
    if consistency_runtime is None:
        try:
            consistency_runtime = _default_consistency_runtime(project_root)
        except Exception:
            consistency_runtime = None
    if consistency_runtime is not None:
        try:
            model_findings = focused_consistency_review(
                result.body,
                director_artifact=director_artifact,
                active_facts=list(context.continuity_facts or []),
                runtime=consistency_runtime,
                character_states=list(context.character_cards or []),
            )
            consistency_findings.extend(model_findings)
        except Exception:
            # Defensive double-belt: the agent itself now fails
            # closed inside ``focused_consistency_review`` so a
            # runtime error surfaces as a blocking
            # ``consistency.unavailable`` finding. If anything
            # escapes that layer we still fall back to a blocking
            # finding rather than silently dropping the review.
            consistency_findings.append(
                ConsistencyFinding(
                    code="consistency.unavailable",
                    message="事实审稿 pipeline 异常；视为失败。",
                    source="consistency",
                    blocking=True,
                )
            )
    return WriterPipelineResult(
        body=result.body,
        context=context,
        director_artifact=director_artifact,
        canon_preflight=preflight,
        consistency_findings=[
            {
                "code": finding.code,
                "message": finding.message,
                "source": finding.source,
                "blocking": finding.blocking,
            }
            for finding in consistency_findings
        ],
        trace_id=f"writer:{chapter_number}",
    )


# --- Fact extraction ----------------------------------------------------------


def run_fact_extractor(
    *,
    project_root: Any,
    chapter_number: int,
    body: str,
    canon_registry: Any | None = None,
) -> ContinuityDelta:
    """Run the fact extractor over a confirmed body.

    The orchestrator wires this in *after* the writer pipeline so
    the candidate carries a ``ContinuityDelta`` shaped per the
    candidate draft v2 contract.
    """
    canon = _ensure_canon_service(canon_registry, project_root)
    canon_view = _canon_view_for(canon)
    context = FactExtractorContext(
        body=body,
        chapter_number=chapter_number,
        canon_view=canon_view,
    )
    extractor = FactExtractor()
    return extractor.extract(context)


# --- Internal helpers ---------------------------------------------------------


def _default_director_runtime(project_root: Any) -> DirectorRuntime:
    """Return a director runtime backed by the model gateway.

    The gateway reuses the ``planner`` provider binding (which is
    what ``resolve_stage_runtime("director")`` returns).
    """
    from packages.story_core.model_gateway import RuntimeModelGateway

    gateway = RuntimeModelGateway()
    return GatewayDirectorRuntime(gateway)


def _default_writer_runtime(project_root: Any) -> WriterRuntime:
    """Return a writer runtime backed by the model gateway."""
    from packages.story_core.model_gateway import RuntimeModelGateway

    gateway = RuntimeModelGateway()
    return GatewayWriterRuntime(gateway)


def _default_consistency_runtime(project_root: Any) -> ConsistencyRuntime:
    """Return a consistency runtime backed by the model gateway.

    The focus-consistency agent uses the same model gateway as
    the writer so the user does not have to configure a second
    provider binding just to enable a deterministic
    contradiction check. The dedicated
    :class:`GatewayConsistencyRuntime` routes the call through
    ``complete_stage("consistency", ...)`` — the previous
    round reused ``GatewayDirectorRuntime`` and the
    workbench's stage evidence column ended up listing two
    ``director`` rows per chapter run.
    """
    from packages.story_core.model_gateway import RuntimeModelGateway

    gateway = RuntimeModelGateway()
    return GatewayConsistencyRuntime(gateway)


def _resolved_stage_provider_model(stage: str) -> tuple[str, str]:
    """Return the ``(provider, model)`` the gateway will see
    for ``stage``.

    The pipeline passes these to
    :class:`DirectorAgent` (so the persisted
    ``.story-system/director/NNNN.json`` envelope reports
    the real provider / model) and to the workflow artifact
    record writers (so the workbench's stage evidence column
    shows the same model the user would see in the prompt
    call log). When the runtime configuration is missing or
    unparseable the function falls back to empty strings —
    the agent and the record writer both treat an empty
    provider as "unknown" rather than crashing.
    """
    try:
        from packages.story_core.runtime_config import resolve_stage_runtime
    except Exception:
        return "", ""
    try:
        settings = resolve_stage_runtime(stage)
    except Exception:
        return "", ""
    if settings is None:
        return "", ""
    provider = str(
        getattr(settings, "provider_id", "") or getattr(settings, "provider", "")
    )
    model = str(getattr(settings, "model", "") or "")
    return provider, model


def _ensure_canon_service(
    canon_registry: Any | None,
    project_root: Any,
) -> CanonService:
    """Return a CanonService that owns the given registry.

    A real project can pass a live ``CanonRegistry``. Tests pass
    ``None`` to opt into a fresh, in-process registry. The
    preflight path calls the non-mutating
    :meth:`CanonService.prepare_requirements` variant. Missing entities
    become transient proposed cards for the writer, while the registry
    stays unchanged until chapter confirmation.
    """
    if canon_registry is not None:
        registry = canon_registry
    else:
        from packages.story_core.canon.registry import CanonRegistry

        registry = CanonRegistry()
    # Lazy import to break the canon ↔ agents circular import: this
    # module is loaded as part of ``agents/__init__.py`` and a top-level
    # import of ``canon.service`` would re-enter ``canon`` while it is
    # still being initialised.  See the test
    # ``test_canon_service_imports_in_a_fresh_process_without_agent_cycle``
    # for the regression this comment guards.
    from packages.story_core.canon.service import CanonService

    return CanonService(registry=registry, designer=_RequirementEntityDesigner())


class _RequirementEntityDesigner:
    """Build a small, genre-neutral proposed card from director output."""

    def design(self, requirement: EntityRequirement, registry: Any) -> CanonEntity:
        # Lazy import to break the canon ↔ agents circular import
        # (see ``_ensure_canon_service`` above for the full reason).
        from packages.story_core.canon.registry import CanonEntity

        digest = hashlib.sha1(
            f"{requirement.kind}:{requirement.name}".encode("utf-8")
        ).hexdigest()[:10]
        notes = requirement.notes.strip()
        if requirement.kind == "character":
            extensions: dict[str, Any] = {
                "identity": notes,
                "origin": "",
                "age_or_age_range": "",
                "occupation_or_role": "",
                "present_goal": notes,
                "fear_or_weakness": "",
                "behavioral_habits": "",
                "speech_tendency": "",
                "relationships": [],
                "knowledge_boundary": [],
                "current_state": notes,
                "change_arc": "",
            }
        elif requirement.kind in {"equipment", "technique"}:
            extensions = {
                "effect": notes,
                "limitation": "",
                "cost": "",
                "owner": "",
                "provenance": "",
                "plot_function": notes,
            }
        else:
            extensions = {"summary": notes}
        return CanonEntity(
            entity_id=f"{requirement.kind}-{digest}",
            kind=requirement.kind,
            display_name=requirement.name,
            lifecycle="proposed",
            extensions=extensions,
        )


def _canon_view_for(canon: CanonService) -> dict[str, Any]:
    """Project a CanonService into the ``canon_view`` dict the
    FactExtractor expects.
    """
    registry = canon.registry
    by_id = {
        entity.entity_id: _entity_to_dict(entity) for entity in registry.list_all()
    }
    by_kind: dict[str, list[str]] = {}
    by_alias: dict[str, list[str]] = {}
    for entity_id, record in by_id.items():
        kind = str(record.get("kind") or "")
        by_kind.setdefault(kind, []).append(entity_id)
        canonical = str(record.get("canonical_name") or "")
        if canonical:
            by_alias.setdefault(canonical, []).append(entity_id)
        for alias in record.get("aliases") or []:
            by_alias.setdefault(str(alias), []).append(entity_id)
    return {"by_id": by_id, "by_kind": by_kind, "by_alias": by_alias}


def _entity_to_dict(entity: CanonEntity) -> dict[str, Any]:
    return {
        "kind": entity.kind,
        "canonical_name": entity.display_name,
        "aliases": list(entity.aliases),
        "lifecycle": entity.lifecycle,
        "attributes": dict(entity.extensions),
    }


def _preflight_entities(
    canon: CanonService,
    director_artifact: DirectorArtifact,
) -> tuple[dict[str, Any], list[CanonEntity]]:
    """Prepare transient cards and return a workbench summary.

    Designed cards are passed to the writer but are not persisted.
    Confirmation remains the only path that can change canon.
    """
    requirements = list(director_artifact.entity_requirements or [])
    if not requirements:
        return (
            {
                "requested": 0,
                "existing": 0,
                "prepared": 0,
                "missing": 0,
                "skipped": 0,
            },
            [],
        )
    existing = 0
    skipped = 0
    for req in requirements:
        if req.inline_minor:
            skipped += 1
            continue
        if canon.registry.resolve(req.name, req.kind) is not None:
            existing += 1
    contextual_requirements = [
        _requirement_with_scene_context(req, director_artifact)
        for req in requirements
    ]
    prepared_entities = canon.prepare_requirements(contextual_requirements)
    prepared = len(prepared_entities) - existing
    return (
        {
            "requested": len(requirements),
            "existing": existing,
            "prepared": prepared,
            "missing": 0,
            "skipped": skipped,
        },
        prepared_entities,
    )


def _requirement_with_scene_context(
    requirement: EntityRequirement,
    artifact: DirectorArtifact,
) -> EntityRequirement:
    """Fill an omitted entity note from the beats that mention it."""
    if requirement.notes.strip() or requirement.inline_minor:
        return requirement
    snippets: list[str] = []
    for beat in artifact.scene_beats:
        fields = (beat.location, beat.action, beat.result)
        if requirement.name not in " ".join(fields):
            continue
        for value in (beat.action, beat.result):
            text = str(value).strip()
            if text and text not in snippets:
                snippets.append(text)
    if not snippets:
        kind_label = {
            "character": "角色",
            "item": "物品",
            "equipment": "装备",
            "technique": "技能或功法",
            "location": "地点",
            "organization": "组织",
            "quest": "任务",
            "monster": "怪物",
            "rule": "规则",
        }.get(requirement.kind, "实体")
        snippets.append(f"本章场景中出现的{kind_label}。")
    notes = "；".join(snippets)[:220]
    return requirement.model_copy(update={"notes": notes})


def _add_prepared_entities_to_context(
    context: WriterContext,
    entities: list[CanonEntity],
) -> WriterContext:
    """Merge transient entity cards into the writer-only context."""
    characters = list(context.character_cards)
    entity_cards = list(context.entity_cards)
    known_characters = {
        str(card.get("name") or "").strip() for card in characters
    }
    known_entities = {
        (str(card.get("kind") or ""), str(card.get("name") or "").strip())
        for card in entity_cards
    }
    for entity in entities:
        extensions = dict(entity.extensions or {})
        name = entity.display_name
        if entity.kind == "character":
            if name in known_characters:
                continue
            characters.append(
                {
                    "id": entity.entity_id,
                    "name": name,
                    "role": extensions.get("occupation_or_role") or "本章角色",
                    "lifecycle": entity.lifecycle,
                    "identity_profile": {
                        "current_identity": extensions.get("identity") or "",
                        "occupation": extensions.get("occupation_or_role") or "",
                    },
                    "performance_profile": {
                        "speech_style": extensions.get("speech_tendency") or "",
                    },
                    "knowledge_boundary": list(
                        extensions.get("knowledge_boundary") or []
                    ),
                    "current_state": extensions.get("current_state") or "",
                }
            )
            known_characters.add(name)
            continue
        key = (entity.kind, name)
        if key in known_entities:
            continue
        summary = str(
            extensions.get("summary")
            or extensions.get("plot_function")
            or extensions.get("effect")
            or ""
        )
        entity_cards.append(
            {
                "id": entity.entity_id,
                "kind": entity.kind,
                "name": name,
                "summary": summary,
                "lifecycle": entity.lifecycle,
            }
        )
        known_entities.add(key)
    return context.model_copy(
        update={"character_cards": characters, "entity_cards": entity_cards}
    )


def _build_writer_request(
    *,
    context: WriterContext,
    director_artifact: DirectorArtifact,
) -> WriterRequest:
    """Project a ``WriterContext`` into the canonical ``WriterRequest``."""
    return WriterRequest(
        chapter_number=context.chapter_number,
        director_artifact=director_artifact,
        project_title=context.project_title,
        genre=context.genre,
        rewrite_guidance=context.rewrite_guidance,
        # Production length policy is guidance plus review metadata.
        # Preserve the first draft for human judgment instead of
        # asking the writer model to resize it automatically.
        target_chars=target_chars(),
        acceptance_chars=acceptance_chars(),
        repair_length=False,
        previous_tail=context.previous_tail,
        continuity_facts=list(context.continuity_facts),
        character_cards=list(context.character_cards),
        entity_cards=list(context.entity_cards),
        world_rules=list(context.world_rules),
        craft_modules=list(context.craft_modules),
        enabled_skill_ids=list(context.enabled_skill_ids),
        enabled_skill_module_ids=(
            list(context.enabled_skill_module_ids)
            if context.enabled_skill_module_ids is not None
            else None
        ),
    )


# --- High-level entry point ---------------------------------------------------


def run_modular_pipeline(
    *,
    project_root: Any,
    chapter_number: int,
    director_runtime: DirectorRuntime | None = None,
    writer_runtime: WriterRuntime | None = None,
    fact_extractor: FactExtractor | None = None,
    consistency_runtime: ConsistencyRuntime | None = None,
    canon_registry: Any | None = None,
    workflow_store: Any | None = None,
    job_id: str | None = None,
    rewrite_guidance: str = "",
    consistency_source: Any | None = None,
    consistency_override: bool = False,
    director_plan_override: Any | None = None,
) -> ModularChapterBundle:
    """Run Director -> CanonService -> Writer -> FactExtractor end-to-end.

    This is the single entry point the orchestrator exposes for the
    modular pipeline. The legacy ``generate_next_chapter_bundle``
    still calls ``resolve_chapter_plan`` / ``generate_chapter_body``
    for backward compatibility, but production callers can opt in
    to this path by setting ``StoryOrchestrator(use_modular_agents=True)``.

    The pipeline:

    1. Builds a :class:`DirectorContext` (canonical-first, legacy
       fallback) and runs the new :class:`DirectorAgent`.
    2. Builds a :class:`WriterContext`, prepares transient canon cards
       without mutating the registry, then runs the new
       :class:`WriterAgent` to render the prose.
    3. Runs the deterministic :class:`FactExtractor` over the body
       so the candidate can carry a :class:`ContinuityDelta` into
       confirmation.

    When ``workflow_store`` is supplied, each stage records an
    on-disk artifact under
    ``.story-system/workflow/{job_id}/{stage_id}.json`` so the
    workbench can re-render what the agent saw and produced.
    ``job_id`` defaults to ``chapter-{N}`` when the caller does
    not pass one; the orchestrator typically passes a timestamped
    id so parallel runs of the same chapter do not collide.

    Returns a :class:`ModularChapterBundle` so the workbench can
    display each agent's output and the e2e test can assert each
    stage was called exactly once.
    """
    import time as _time

    from .pipeline_artifacts import (
        record_director_stage,
        record_fact_extractor_stage,
        record_writer_stage,
    )

    report_generation_progress(
        {
            "message": "导演正在读取大纲、连续性和角色卡",
            "stage": "director",
            "source": "modular-pipeline",
            "artifact": {
                "reason": "stage_started",
                "inputs": {"chapter_number": chapter_number},
                "used_modules": ["outline", "continuity", "character_cards"],
            },
        }
    )
    director_started = _time.monotonic()
    if director_plan_override is not None:
        try:
            reused_artifact = (
                director_plan_override
                if isinstance(director_plan_override, DirectorArtifact)
                else DirectorArtifact.model_validate(director_plan_override)
            )
        except Exception as exc:
            raise ValueError(f"director_plan_override_invalid:{exc}") from exc
        director_result = DirectorPipelineResult(
            artifact=reused_artifact,
            context=_ensure_director_context(
                project_root=project_root, chapter_number=chapter_number
            ),
            trace_id=f"director:{chapter_number}:replanned",
        )
    else:
        director_result = plan_director_artifact(
            project_root=project_root,
            chapter_number=chapter_number,
            runtime=director_runtime,
            rewrite_guidance=rewrite_guidance,
        )
    report_generation_progress(
        {
            "message": "导演已产出章节节拍和实体要求",
            "status": "done",
            "stage": "director",
            "source": "modular-pipeline",
            "artifact": {
                "reason": "stage_completed",
                "outputs": {
                    "scene_beats": len(director_result.artifact.scene_beats),
                    "entity_requirements": len(
                        director_result.artifact.entity_requirements
                    ),
                },
            },
        }
    )
    report_generation_progress(
        {
            "message": "正在检查生成前人物一致性",
            "stage": "consistency_check",
            "source": "generation-consistency-gate",
            "artifact": {
                "reason": "pre_writer_check_started",
                "inputs": {
                    "chapter_number": chapter_number,
                    "historical_boundary": chapter_number - 1,
                },
            },
        }
    )
    try:
        consistency_gate = require_generation_consistency(
            consistency_source or project_root,
            director_result.artifact,
            target_chapter=chapter_number,
            fallback_root=project_root if consistency_source is not None else None,
            override=consistency_override,
        )
    except ConsistencyGateRequired as exc:
        report_generation_progress(
            {
                "message": "生成前一致性检查发现问题，等待作者决定",
                "status": "error",
                "stage": "consistency_check",
                "source": "generation-consistency-gate",
                "artifact": {
                    "reason": "author_decision_required",
                    "gate": exc.gate.model_dump(mode="json"),
                },
            }
        )
        raise
    report_generation_progress(
        {
            "message": (
                "生成前一致性检查通过"
                if consistency_gate.status == "clear"
                else "已记录一致性提示，按作者决定继续生成"
            ),
            "status": "done",
            "stage": "consistency_check",
            "source": "generation-consistency-gate",
            "artifact": {
                "reason": "pre_writer_check_completed",
                "gate": consistency_gate.model_dump(mode="json"),
            },
        }
    )
    report_generation_progress(
        {
            "message": "写手正在准备实体卡并组装写作上下文",
            "stage": "writer",
            "source": "modular-pipeline",
            "artifact": {
                "reason": "stage_started",
                "used_modules": [
                    "director_artifact",
                    "character_cards",
                    "entity_preflight",
                    "world_rules",
                ],
            },
        }
    )
    writer_started = _time.monotonic()
    writer_result = run_writer(
        project_root=project_root,
        chapter_number=chapter_number,
        director_artifact=director_result.artifact,
        canon_registry=canon_registry,
        runtime=writer_runtime,
        consistency_runtime=consistency_runtime,
        rewrite_guidance=rewrite_guidance,
    )
    report_generation_progress(
        {
            "message": "写手已产出正文",
            "status": "done",
            "stage": "writer",
            "source": "modular-pipeline",
            "artifact": {
                "reason": "stage_completed",
                "outputs": {
                    "body_chars": len("".join(writer_result.body.split())),
                    "canon_preflight": dict(writer_result.canon_preflight or {}),
                },
            },
        }
    )
    report_generation_progress(
        {
            "message": "事实审稿正在提取正文中的状态变化",
            "stage": "fact_extractor",
            "source": "modular-pipeline",
            "artifact": {
                "reason": "stage_started",
                "used_modules": ["chapter_body", "canon_view"],
            },
        }
    )
    extractor_started = _time.monotonic()
    if fact_extractor is None:
        fact_extractor = FactExtractor()
    delta = fact_extractor.extract(
        FactExtractorContext(
            body=writer_result.body,
            chapter_number=chapter_number,
            director_artifact=director_result.artifact,
            canon_view=_canon_view_for(
                _ensure_canon_service(canon_registry, project_root)
            ),
            continuity_facts=list(writer_result.context.continuity_facts or []),
            candidate_entities=[
                {**dict(card), "kind": "character"}
                for card in (writer_result.context.character_cards or [])
                if isinstance(card, dict)
            ]
            + [
                dict(card)
                for card in (writer_result.context.entity_cards or [])
                if isinstance(card, dict)
            ],
        )
    )
    report_generation_progress(
        {
            "message": "事实审稿已产出连续性变更",
            "status": "done",
            "stage": "fact_extractor",
            "source": "modular-pipeline",
            "artifact": {
                "reason": "stage_completed",
                "outputs": {
                    "chapter_number": delta.chapter_number,
                    "entity_additions": len(delta.entity_additions),
                    "entity_updates": len(delta.entity_updates),
                },
            },
        }
    )

    if workflow_store is not None:
        effective_job_id = job_id or f"chapter-{chapter_number}"
        from pathlib import Path

        director_path = (
            Path(project_root) / ".story-system" / "director" / f"{chapter_number:04d}.json"
        )
        try:
            director_content = (
                director_path.read_bytes() if director_path.is_file() else None
            )
        except OSError:
            director_content = None
        artifact_meta: dict[str, str] = {}
        if director_content is not None:
            import hashlib as _hashlib

            artifact_meta = {
                "path": str(director_path),
                "sha256": _hashlib.sha256(director_content).hexdigest(),
            }
        # Resolve the actual provider / model for each stage
        # so the workbench's stage evidence column shows the
        # same metadata the user would see in the prompt call
        # log. The placeholder ``"gateway"`` / ``"runtime/director"``
        # pair is gone — the resolved values come from
        # :func:`resolve_stage_runtime` exactly the way the
        # gateway itself reads them internally.
        director_provider, director_model = _resolved_stage_provider_model("director")
        writer_provider, writer_model = _resolved_stage_provider_model("writer")
        record_director_stage(
            store=workflow_store,
            job_id=effective_job_id,
            artifact=director_result.artifact,
            context=director_result.context,
            started_monotonic=director_started,
            artifact_paths=(director_path,),
            artifact_reader=lambda p, _content=director_content: _content
            if _content is not None
            else (p.read_bytes() if p.is_file() else None),
            provider=director_provider,
            model=director_model,
        )
        record_writer_stage(
            store=workflow_store,
            job_id=effective_job_id,
            result=writer_result,
            context=writer_result.context,
            started_monotonic=writer_started,
            provider=writer_provider,
            model=writer_model,
            # The blocking findings surface on the workbench's
            # stage evidence column so the operator sees the
            # same contradiction / length failure the candidate
            # card shows before the user clicks confirm.
            consistency_findings=list(writer_result.consistency_findings or []),
        )
        record_fact_extractor_stage(
            store=workflow_store,
            job_id=effective_job_id,
            delta=delta,
            started_monotonic=extractor_started,
            # The fact-extractor stage is a deterministic
            # algorithm, not a model call, so it carries no
            # provider / model. The prompt_call_log records the
            # consistency model call separately under the
            # ``consistency`` stage.
        )

    return ModularChapterBundle(
        chapter_number=chapter_number,
        director_artifact=director_result.artifact,
        director_trace_id=director_result.trace_id,
        body=writer_result.body,
        writer_context=writer_result.context,
        canon_preflight=dict(writer_result.canon_preflight or {}),
        writer_trace_id=writer_result.trace_id,
        consistency_findings=list(writer_result.consistency_findings or []),
        consistency_gate=consistency_gate,
        continuity_delta=delta,
        fact_extractor_trace_id=f"fact-extractor:{chapter_number}",
    )


__all__ = [
    "DirectorPipelineResult",
    "ModularChapterBundle",
    "WriterPipelineResult",
    "plan_director_artifact",
    "run_fact_extractor",
    "run_modular_pipeline",
    "run_writer",
]
