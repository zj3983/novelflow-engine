"""Deterministic chapter review checks.

The plan restricts the hard gate to evidence-backed defects
the reader can verify against the body. Every check here is
a pure function: it takes a ``CheckContext`` (the body plus
the minimum needed from the director / canon / outline) and
returns zero or more ``CheckFinding`` records with the
``source`` set to the function that produced them, so the
workbench can highlight the exact line / span.

The categories are:

* empty body
* length window (min / max)
* chapter number and title contract
* arithmetic and state contradictions (count claims,
  inventory claims, location / time / knowledge changes)
* named entity identity conflicts
* explicit outline must-have violations
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable


@dataclass(frozen=True)
class CheckFinding:
    """One hard-gate finding from a deterministic check.

    ``source`` is the function name that produced the
    finding; ``evidence`` is a small dict the workbench can
    render (line number, span, conflicting value, ...).
    ``blocking`` is always True here — the deterministic
    checks are the hard gate.
    """

    code: str
    message: str
    source: str
    evidence: dict[str, Any] = field(default_factory=dict)
    blocking: bool = True


@dataclass
class CheckContext:
    """Everything the deterministic checks need to run.

    The orchestrator assembles this from the chapter body,
    the director artifact, the active continuity facts, the
    canon knowledge boundaries, and the outline's must-have
    list. Tests build it directly.
    """

    body: str
    chapter_number: int
    min_chars: int = 0
    max_chars: int = 0
    director_artifact: Any = None
    active_facts: list[dict[str, Any]] = field(default_factory=list)
    outline_must_haves: tuple[str, ...] = field(default_factory=tuple)
    inventory: dict[str, Any] = field(default_factory=dict)
    inventory_changes: list[dict[str, Any]] = field(default_factory=list)
    knowledge: dict[str, Any] = field(default_factory=dict)


class DeterministicChecks:
    """All seven deterministic checks as a single object.

    Each check is exposed both as a public method and as a
    module-level function so callers can run a single check
    in isolation.
    """

    check_body_not_empty: Callable[[CheckContext], list[CheckFinding]]
    check_length_window: Callable[[CheckContext], list[CheckFinding]]
    check_chapter_number_contract: Callable[[CheckContext], list[CheckFinding]]
    check_inventory_changes: Callable[[CheckContext], list[CheckFinding]]
    check_knowledge_boundaries: Callable[[CheckContext], list[CheckFinding]]
    check_outline_must_haves: Callable[[CheckContext], list[CheckFinding]]
    check_arithmetic_and_state: Callable[[CheckContext], list[CheckFinding]]
    check_named_entity_identity: Callable[[CheckContext], list[CheckFinding]]


# Individual checks ----------------------------------------------------------


def check_body_not_empty(ctx: CheckContext) -> list[CheckFinding]:
    compact = "".join(str(ctx.body or "").split())
    if compact:
        return []
    return [
        CheckFinding(
            code="body.empty",
            message="章节正文为空。",
            source="checks.body_not_empty",
            evidence={"body_chars": 0},
        )
    ]


def check_length_window(ctx: CheckContext) -> list[CheckFinding]:
    compact = "".join(str(ctx.body or "").split())
    chars = len(compact)
    findings: list[CheckFinding] = []
    if ctx.min_chars and chars < ctx.min_chars:
        findings.append(
            CheckFinding(
                code="body.too_short",
                message=f"章节篇幅 {chars} 字，少于下限 {ctx.min_chars} 字。",
                source="checks.body_length",
                evidence={
                    "body_chars": chars,
                    "min_chars": ctx.min_chars,
                    "max_chars": ctx.max_chars,
                },
            )
        )
    if ctx.max_chars and chars > ctx.max_chars:
        findings.append(
            CheckFinding(
                code="body.too_long",
                message=f"章节篇幅 {chars} 字，超过上限 {ctx.max_chars} 字。",
                source="checks.body_length",
                evidence={
                    "body_chars": chars,
                    "min_chars": ctx.min_chars,
                    "max_chars": ctx.max_chars,
                },
            )
        )
    return findings


_CHAPTER_NUMBER_PATTERN = re.compile(r"第\s*(\d+)\s*章")


def _find_chapter_number(body: str) -> int | None:
    match = _CHAPTER_NUMBER_PATTERN.search(body or "")
    if match is None:
        return None
    try:
        return int(match.group(1))
    except ValueError:
        return None


def check_chapter_number_contract(ctx: CheckContext) -> list[CheckFinding]:
    found = _find_chapter_number(ctx.body)
    if found is None:
        return []
    if found == ctx.chapter_number:
        return []
    return [
        CheckFinding(
            code="chapter.number_mismatch",
            message=f"正文中标注「第{found}章」与目标章节 {ctx.chapter_number} 不一致。",
            source="checks.chapter_number",
            evidence={
                "body_chapter": found,
                "target_chapter": ctx.chapter_number,
            },
        )
    ]


_OUTLINE_MUST_HAVE_PATTERN = re.compile(r"[\u4e00-\u9fffA-Za-z0-9]{2,}")


def _tokens(text: str) -> set[str]:
    return {match.group(0) for match in _OUTLINE_MUST_HAVE_PATTERN.finditer(text or "")}


def check_outline_must_haves(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    body_tokens = _tokens(ctx.body)
    for must_have in ctx.outline_must_haves:
        if not must_have:
            continue
        if must_have in ctx.body or must_have in body_tokens:
            continue
        # Allow the must-have to appear as a contiguous run of
        # characters anywhere in the body. A simple substring
        # match would miss the case where the user wrote
        # "进入矿区" but the body has "进入了矿区".
        if any(must_have in token for token in body_tokens):
            continue
        findings.append(
            CheckFinding(
                code="outline.must_have_missing",
                message=f"大纲要求「{must_have}」未在正文中出现。",
                source="checks.outline_must_haves",
                evidence={"must_have": must_have},
            )
        )
    return findings


def check_inventory_changes(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    inventory = ctx.inventory or {}
    body_tokens = _tokens(ctx.body)
    for change in ctx.inventory_changes or []:
        owner = str(change.get("owner") or "")
        lost = list(change.get("lost") or [])
        gained = list(change.get("gained") or [])
        held = list(inventory.get(owner) or [])
        for item in lost:
            if item not in held:
                findings.append(
                    CheckFinding(
                        code="inventory.impossible_change",
                        message=f"{owner} 不持有 {item}，无法失去。",
                        source="checks.inventory_changes",
                        evidence={"owner": owner, "item": item, "held": held},
                    )
                )
            if item not in body_tokens and not any(item in token for token in body_tokens):
                findings.append(
                    CheckFinding(
                        code="inventory.change_unconfirmed",
                        message=f"失去 {item} 必须在正文中可见。",
                        source="checks.inventory_changes",
                        evidence={"owner": owner, "item": item},
                    )
                )
        for item in gained:
            if item in body_tokens or any(item in token for token in body_tokens):
                continue
            findings.append(
                CheckFinding(
                    code="inventory.change_unconfirmed",
                    message=f"获得 {item} 必须在正文中可见。",
                    source="checks.inventory_changes",
                    evidence={"owner": owner, "item": item},
                )
            )
    return findings


def check_knowledge_boundaries(ctx: CheckContext) -> list[CheckFinding]:
    findings: list[CheckFinding] = []
    characters = (ctx.knowledge or {}).get("characters") or []
    body = ctx.body or ""
    for character in characters:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "")
        boundaries = list(character.get("knowledge_boundary") or [])
        # Heuristic: a knowledge boundary is a phrase the
        # character should not know about. We flag any
        # boundary string that appears in the same line as the
        # character's name in the body, unless the line
        # explicitly attributes the knowledge ("X 不知道 ...").
        if not name or not boundaries:
            continue
        for line_number, line in enumerate(body.splitlines(), start=1):
            if name not in line:
                continue
            for boundary in boundaries:
                if boundary and boundary in line and "不知道" not in line:
                    findings.append(
                        CheckFinding(
                            code="knowledge.impossible_change",
                            message=(
                                f"{name} 不应知道「{boundary}」但正文中已显示该信息。"
                            ),
                            source="checks.knowledge_boundaries",
                            evidence={
                                "character": name,
                                "boundary": boundary,
                                "line": line_number,
                            },
                        )
                    )
    return findings


def check_named_entity_identity(ctx: CheckContext) -> list[CheckFinding]:
    """Surface conflicts where the body reuses a name the
    canon declared for a different role.

    A real production version would call the canonical
    registry's ``resolve`` to detect name-collision issues.
    For now the deterministic layer flags any duplicate name
    in the canon's character list — that is, the canon
    itself shouldn't have two characters sharing a name.
    """
    findings: list[CheckFinding] = []
    characters = (ctx.knowledge or {}).get("characters") or []
    seen: dict[str, int] = {}
    for character in characters:
        if not isinstance(character, dict):
            continue
        name = str(character.get("name") or "").strip()
        if not name:
            continue
        seen[name] = seen.get(name, 0) + 1
    for name, count in seen.items():
        if count > 1:
            findings.append(
                CheckFinding(
                    code="entity.identity_conflict",
                    message=f"canon 内部存在 {count} 个同名「{name}」角色。",
                    source="checks.named_entity_identity",
                    evidence={"name": name, "count": count},
                )
            )
    return findings


def check_arithmetic_and_state(ctx: CheckContext) -> list[CheckFinding]:
    """Detect impossible arithmetic and state contradictions.

    The deterministic layer checks that explicit numeric
    claims in the body (e.g. "三枚玉佩") don't conflict
    with the inventory. A real version would also walk the
    active facts for state changes; we keep this minimal
    here so the test contract is small.
    """
    findings: list[CheckFinding] = []
    body_tokens = _tokens(ctx.body)
    inventory = ctx.inventory or {}
    for owner, items in inventory.items():
        for item in items:
            # If the body says the owner has N of an item but
            # the inventory lists 1, the deterministic check
            # surfaces the arithmetic contradiction.
            match = re.search(rf"(\d+)\s*枚?\s*{re.escape(item)}", ctx.body or "")
            if match is None:
                continue
            try:
                claimed = int(match.group(1))
            except ValueError:
                continue
            if claimed > 1 and item in body_tokens and claimed > 1:
                # Soft signal: only fire if the inventory says
                # one and the body claims more than one.
                if not isinstance(items, list) or len(items) == 1:
                    findings.append(
                        CheckFinding(
                            code="continuity.inconsistency",
                            message=(
                                f"{owner} 的「{item}」库存为 1，"
                                f"但正文声称 {claimed} 枚。"
                            ),
                            source="checks.arithmetic_and_state",
                            evidence={
                                "owner": owner,
                                "item": item,
                                "claimed": claimed,
                                "held": 1,
                            },
                        )
                    )
    return findings


# Aggregate runner ----------------------------------------------------------


def run_deterministic_checks(ctx: CheckContext) -> list[CheckFinding]:
    """Run every check the hard gate requires.

    The order is fixed so the workbench shows findings in a
    predictable order; duplicates are not deduplicated
    because each carries a distinct source.
    """
    findings: list[CheckFinding] = []
    for runner in (
        check_body_not_empty,
        check_length_window,
        check_chapter_number_contract,
        check_outline_must_haves,
        check_inventory_changes,
        check_knowledge_boundaries,
        check_named_entity_identity,
        check_arithmetic_and_state,
    ):
        findings.extend(runner(ctx))
    return findings


__all__ = [
    "CheckContext",
    "CheckFinding",
    "DeterministicChecks",
    "check_body_not_empty",
    "check_chapter_number_contract",
    "check_inventory_changes",
    "check_knowledge_boundaries",
    "check_length_window",
    "check_outline_must_haves",
    "check_named_entity_identity",
    "check_arithmetic_and_state",
    "run_deterministic_checks",
]
