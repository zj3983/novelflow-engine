"""Deterministic, candidate-safe fact and resource ledger.

This module is deliberately smaller than the legacy progression ledger.  It
only records explicit, chapter-scoped numeric or ownership assertions for
generic resources that have no existing structured historical owner.  Existing
progression, equipment, and relationship histories are read through adapters
and are never copied into a second writable history.  The file-project store
is responsible for the confirmation transaction; this module owns the schema,
replay, extraction, projection, and validation rules.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from hashlib import sha256
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, MutableMapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


FACT_RESOURCE_SCHEMA = "fact-resource-ledger/v1"
FACT_RESOURCE_EXTRACTION_SCHEMA = "fact-resource-extraction/v1"
FACT_RESOURCE_REVIEW_SCHEMA = "fact-resource-review/v1"
FACT_RESOURCE_AUTHORITY_SCHEMA = "fact-resource-authority/v1"

OPERATIONS = {
    "SET",
    "ADD",
    "SUBTRACT",
    "TRANSFER",
    "EQUIP",
    "UNEQUIP",
    "PROGRESS_SET",
    "PROGRESS_ADD",
}

SEVERITIES = {"error", "warning", "info"}

# These are *projection categories*, not an instruction to create another
# history.  A project can expose one of these authorities only when the
# corresponding structured source is present.  The generic ledger may own a
# category that is not represented by a project authority.
_AUTHORITY_CATEGORY_ALIASES = {
    "level": "progression",
    "character_level": "progression",
    "experience": "progression",
    "exp": "progression",
    "character_exp": "progression",
    "inventory": "progression",
    "item": "progression",
    "currency": "progression",
    "money": "progression",
    "quest": "progression",
    "quest_progress": "progression",
    "task": "progression",
    "progression": "progression",
    "equipment": "equipment_cards",
    "equipment_owner": "equipment_cards",
    "equipment_state": "equipment_cards",
    "equipment_equipped": "equipment_cards",
    "equipped": "equipment_cards",
    "relationship": "relationship_graph",
    "relationship_numeric": "relationship_graph",
    "relationship_value": "relationship_graph",
    "trust": "relationship_graph",
    "tension": "relationship_graph",
}


def fact_resource_authority_group(category: str) -> str | None:
    """Return the existing source group for a category, if one is known."""

    return _AUTHORITY_CATEGORY_ALIASES.get(_canonical_text(category))


def _text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _canonical_text(value: Any) -> str:
    return _text(unicodedata.normalize("NFKC", str(value or ""))).casefold()


def _number(value: Any) -> int | float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return value
    if isinstance(value, str):
        raw = value.strip().replace(",", "")
        try:
            parsed = float(raw)
        except ValueError:
            return None
        if not math.isfinite(parsed):
            return None
        return int(parsed) if parsed.is_integer() else parsed
    return None


def _same_number(left: Any, right: Any) -> bool:
    left_num, right_num = _number(left), _number(right)
    if left_num is None or right_num is None:
        return left == right
    return math.isclose(float(left_num), float(right_num), rel_tol=0, abs_tol=1e-9)


def _json_value(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return str(value)


def stable_fact_id(
    category: str,
    subject: str,
    resource_key: str,
    *,
    owner: str = "",
) -> str:
    """Return a stable id for exact normalized names.

    Normalization removes formatting noise only.  It never performs aliases,
    fuzzy matching, substring matching, or semantic merging.
    """

    seed = "|".join(
        _canonical_text(item)
        for item in (category, subject, resource_key, owner)
    )
    return "fr-" + sha256(seed.encode("utf-8")).hexdigest()[:20]


class FactResourceEntry(BaseModel):
    model_config = ConfigDict(extra="ignore")

    fact_id: str = ""
    category: str
    subject: str = ""
    resource_key: str
    value: Any = None
    unit: str = ""
    owner: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    updated_chapter: int = 0

    @model_validator(mode="after")
    def ensure_id(self) -> "FactResourceEntry":
        if not self.fact_id:
            self.fact_id = stable_fact_id(
                self.category,
                self.subject,
                self.resource_key,
            )
        return self


class FactResourceBaseline(BaseModel):
    model_config = ConfigDict(extra="ignore")

    chapter: int = 0
    entries: list[FactResourceEntry] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_shape(cls, value: Any) -> Any:
        if isinstance(value, list):
            return {"chapter": 0, "entries": value}
        if isinstance(value, Mapping):
            if "entries" in value:
                return value
            # A convenient authoring shape: {fact_id: entry-payload}.
            if value and all(isinstance(item, Mapping) for item in value.values()):
                entries = []
                for fact_id, raw in value.items():
                    item = dict(raw)
                    item.setdefault("fact_id", str(fact_id))
                    entries.append(item)
                return {"chapter": int(value.get("chapter") or 0), "entries": entries}
        return value or {"chapter": 0, "entries": []}


class FactResourceDelta(BaseModel):
    model_config = ConfigDict(extra="ignore")

    delta_id: str = ""
    chapter: int = Field(default=0, ge=0)
    chapter_number: int | None = Field(default=None, ge=0)
    sequence: int = Field(default=0, ge=0)
    fact_id: str = ""
    category: str
    subject: str = ""
    resource_key: str
    operation: str
    before: Any = None
    change: Any = None
    after: Any = None
    unit: str = ""
    owner: str = ""
    from_owner: str = ""
    to_owner: str = ""
    equipped: bool | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    source: str = "chapter_body"
    evidence: str = ""
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def normalize_delta(self) -> "FactResourceDelta":
        if self.chapter < 1 and self.chapter_number:
            self.chapter = self.chapter_number
        if self.chapter < 1:
            raise ValueError("chapter_number_must_be_positive")
        if self.chapter_number is None:
            self.chapter_number = self.chapter
        if self.operation not in OPERATIONS:
            raise ValueError("invalid_resource_delta_operation")
        if not self.fact_id:
            self.fact_id = stable_fact_id(
                self.category,
                self.subject,
                self.resource_key,
            )
        if not self.delta_id:
            seed = json.dumps(
                {
                    "chapter": self.chapter,
                    "sequence": self.sequence,
                    "fact_id": self.fact_id,
                    "operation": self.operation,
                    "before": _json_value(self.before),
                    "change": _json_value(self.change),
                    "after": _json_value(self.after),
                    "evidence": self.evidence,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            self.delta_id = "frd-" + sha256(seed.encode("utf-8")).hexdigest()[:24]
        return self

    @property
    def signed_change(self) -> Any:
        number = _number(self.change)
        if number is None:
            return self.change
        if self.operation in {"SUBTRACT"}:
            return -abs(number)
        if self.operation in {"ADD", "PROGRESS_ADD"}:
            return abs(number)
        return number


class FactResourceAssertion(BaseModel):
    model_config = ConfigDict(extra="ignore")

    category: str
    subject: str = ""
    resource_key: str
    fact_id: str = ""
    expected_value: Any = None
    expected_owner: str = ""
    expected_equipped: bool | None = None
    unit: str = ""
    evidence: str = ""
    source: str = "chapter_body"
    confidence: float = Field(default=1.0, ge=0, le=1)

    @model_validator(mode="after")
    def ensure_id(self) -> "FactResourceAssertion":
        if not self.fact_id:
            self.fact_id = stable_fact_id(self.category, self.subject, self.resource_key)
        return self


class FactResourceFinding(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str
    severity: str
    message: str
    delta_id: str = ""
    fact_id: str = ""
    category: str = ""
    resource_key: str = ""
    evidence: str = ""
    expected: Any = None
    observed: Any = None
    chapter: int = 0

    @model_validator(mode="after")
    def valid_severity(self) -> "FactResourceFinding":
        if self.severity not in SEVERITIES:
            raise ValueError("invalid_fact_resource_severity")
        return self


class FactResourceAuthority(BaseModel):
    """A read/write boundary for one already-structured fact source.

    ``FactResourceLedger`` never writes an authority described here.  The
    record is deliberately part of the read snapshot so the writer, review,
    and confirmation code can make the same ownership decision.
    """

    model_config = ConfigDict(extra="ignore")

    schema_version: str = FACT_RESOURCE_AUTHORITY_SCHEMA
    group: str
    categories: list[str] = Field(default_factory=list)
    source: str
    writable: bool = False
    active: bool = True
    reason: str = ""


class FactResourceExtraction(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = FACT_RESOURCE_EXTRACTION_SCHEMA
    chapter_number: int = Field(ge=1)
    deltas: list[FactResourceDelta] = Field(default_factory=list)
    assertions: list[FactResourceAssertion] = Field(default_factory=list)
    # ``observed_assertions`` is the public name used by the phase contract;
    # ``assertions`` remains as a short compatibility spelling for callers
    # already using the first implementation.
    observed_assertions: list[FactResourceAssertion] = Field(default_factory=list)
    findings: list[FactResourceFinding] = Field(default_factory=list)
    source_text_sha256: str = ""

    @model_validator(mode="before")
    @classmethod
    def inherit_chapter_on_unscoped_deltas(cls, value: Any) -> Any:
        if not isinstance(value, Mapping) or not value.get("chapter_number"):
            return value
        payload = dict(value)
        chapter_number = int(value["chapter_number"])
        deltas = []
        for raw in value.get("deltas") or []:
            if isinstance(raw, Mapping):
                item = dict(raw)
                if not item.get("chapter") and not item.get("chapter_number"):
                    item["chapter"] = chapter_number
                deltas.append(item)
            else:
                deltas.append(raw)
        payload["deltas"] = deltas
        return payload

    @model_validator(mode="after")
    def sync_assertion_names(self) -> "FactResourceExtraction":
        if not self.assertions and self.observed_assertions:
            self.assertions = list(self.observed_assertions)
        if not self.observed_assertions and self.assertions:
            self.observed_assertions = list(self.assertions)
        return self


class FactResourceSnapshot(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = "fact-resource-snapshot/v1"
    as_of_chapter: int = 0
    known: bool = False
    source: str = "missing"
    entries: list[FactResourceEntry] = Field(default_factory=list)
    findings: list[FactResourceFinding] = Field(default_factory=list)
    authorities: list[FactResourceAuthority] = Field(default_factory=list)

    @property
    def by_fact_id(self) -> dict[str, FactResourceEntry]:
        return {entry.fact_id: entry for entry in self.entries}

    def find(
        self,
        category: str,
        resource_key: str,
        *,
        subject: str = "",
        fact_id: str = "",
    ) -> FactResourceEntry | None:
        wanted_id = fact_id or stable_fact_id(category, subject, resource_key)
        entry = self.by_fact_id.get(wanted_id)
        if entry is not None:
            return entry
        # Exact field matching is allowed as a fallback for old entries whose
        # id was authored manually; aliases and partial matching are not.
        for candidate in self.entries:
            if (
                _canonical_text(candidate.category) == _canonical_text(category)
                and _canonical_text(candidate.subject) == _canonical_text(subject)
                and _canonical_text(candidate.resource_key) == _canonical_text(resource_key)
            ):
                return candidate
        # An adapter may expose one canonical entry while accepting a finite
        # set of explicit schema field names (for example ``currency`` and
        # ``game_currency``).  This is exact metadata lookup, not fuzzy or
        # substring matching.
        wanted_key = _canonical_text(resource_key)
        for candidate in self.entries:
            aliases = candidate.metadata.get("lookup_keys")
            if not isinstance(aliases, list):
                continue
            if (
                _canonical_text(candidate.category) == _canonical_text(category)
                and _canonical_text(candidate.subject) == _canonical_text(subject)
                and wanted_key in {_canonical_text(item) for item in aliases}
            ):
                return candidate
        return None

    def value_for(self, category: str, resource_key: str, *, subject: str = "") -> Any:
        entry = self.find(category, resource_key, subject=subject)
        return entry.value if entry else None

    def authority_for(self, category: str) -> FactResourceAuthority | None:
        group = fact_resource_authority_group(category)
        if not group:
            return None
        return next(
            (
                item
                for item in self.authorities
                if item.active and item.group == group
            ),
            None,
        )

    def has_existing_authority(self, category: str) -> bool:
        return self.authority_for(category) is not None


class FactResourceLedger(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = FACT_RESOURCE_SCHEMA
    baseline: FactResourceBaseline = Field(default_factory=FactResourceBaseline)
    history: list[FactResourceDelta] = Field(default_factory=list)
    entries: list[FactResourceEntry] = Field(default_factory=list)
    latest_confirmed_chapter: int = 0
    confirmed_candidates: list[str] = Field(default_factory=list)
    revision: int = 0
    audit: list[dict[str, Any]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_shape(cls, value: Any) -> Any:
        if not isinstance(value, Mapping):
            return value or {}
        payload = dict(value)
        if "baseline" not in payload:
            baseline_entries = payload.pop("initial_entries", None)
            if baseline_entries is None and isinstance(payload.get("entries"), list):
                # Top-level entries are materialized state in the current
                # shape, not a historical baseline. Keep them as baseline
                # only when no history exists, which is safe for hand-authored
                # seed files.
                baseline_entries = payload.get("entries") if not payload.get("history") else []
            payload["baseline"] = {"chapter": 0, "entries": baseline_entries or []}
        return payload

    @classmethod
    def empty(cls) -> "FactResourceLedger":
        return cls()

    @classmethod
    def load(cls, path: str | Path) -> "FactResourceLedger | None":
        target = Path(path)
        try:
            payload = json.loads(target.read_text(encoding="utf-8-sig"))
        except (OSError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(payload, Mapping):
            return None
        try:
            return cls.model_validate(payload)
        except Exception:
            return None

    def replay(self, *, as_of_chapter: int | None = None) -> FactResourceSnapshot:
        target = self.latest_confirmed_chapter if as_of_chapter is None else max(0, int(as_of_chapter))
        entries = {entry.fact_id: entry.model_copy(deep=True) for entry in self.baseline.entries}
        findings: list[FactResourceFinding] = []
        ordered = sorted(
            (delta for delta in self.history if delta.chapter <= target),
            key=lambda item: (item.chapter, item.sequence, item.delta_id),
        )
        for delta in ordered:
            finding = _apply_delta_to_entries(entries, delta, strict=False)
            if finding is not None:
                findings.append(finding)
        materialized = sorted(
            entries.values(),
            key=lambda item: (item.category, item.subject, item.resource_key, item.fact_id),
        )
        return FactResourceSnapshot(
            as_of_chapter=target,
            known=True,
            source="fact_resource_ledger",
            entries=materialized,
            findings=findings,
        )

    def append(
        self,
        extraction: FactResourceExtraction,
        *,
        candidate_id: str = "",
        allow_historical_rewrite: bool = False,
    ) -> FactResourceSnapshot:
        """Validate and append an extraction in deterministic order."""

        existing_ids = {delta.delta_id for delta in self.history}
        if candidate_id and candidate_id in self.confirmed_candidates:
            return self.replay(as_of_chapter=self.latest_confirmed_chapter)
        if extraction.deltas and all(delta.delta_id in existing_ids for delta in extraction.deltas):
            return self.replay(as_of_chapter=self.latest_confirmed_chapter)
        if not allow_historical_rewrite and extraction.chapter_number <= self.latest_confirmed_chapter:
            raise ValueError("fact_resource_historical_rewrite_requires_reconciliation")
        incoming = [delta for delta in extraction.deltas if delta.delta_id not in existing_ids]
        start = self.replay(as_of_chapter=extraction.chapter_number - 1)
        result = validate_fact_resource_extraction(start, extraction)
        errors = [item for item in result.findings if item.severity == "error"]
        if errors:
            raise ValueError(
                "fact_resource_validation_failed:" + ",".join(item.code for item in errors)
            )
        for delta in incoming:
            self.history.append(delta)
        if incoming:
            self.history.sort(key=lambda item: (item.chapter, item.sequence, item.delta_id))
        self.latest_confirmed_chapter = max(self.latest_confirmed_chapter, extraction.chapter_number)
        if candidate_id and candidate_id not in self.confirmed_candidates:
            self.confirmed_candidates.append(candidate_id)
        self.revision += 1 if incoming or candidate_id else 0
        self.audit.append(
            {
                "chapter": extraction.chapter_number,
                "candidate_id": candidate_id,
                "delta_ids": [delta.delta_id for delta in incoming],
                "revision": self.revision,
            }
        )
        self.entries = self.replay(as_of_chapter=self.latest_confirmed_chapter).entries
        return self.replay(as_of_chapter=self.latest_confirmed_chapter)

    def to_dict(self) -> dict[str, Any]:
        payload = self.model_dump(mode="json")
        payload["schema_version"] = FACT_RESOURCE_SCHEMA
        return payload


class FactResourceValidation(BaseModel):
    model_config = ConfigDict(extra="ignore")

    schema_version: str = FACT_RESOURCE_REVIEW_SCHEMA
    ok: bool
    start_snapshot: FactResourceSnapshot
    proposed_snapshot: FactResourceSnapshot
    findings: list[FactResourceFinding] = Field(default_factory=list)
    delta_count: int = 0
    assertion_count: int = 0

    @property
    def blocking_findings(self) -> list[FactResourceFinding]:
        return [item for item in self.findings if item.severity == "error"]

    @property
    def errors(self) -> list[FactResourceFinding]:
        return self.blocking_findings

    @property
    def warnings(self) -> list[FactResourceFinding]:
        return [item for item in self.findings if item.severity == "warning"]

    def to_review_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


def _entry_key(delta: FactResourceDelta) -> str:
    return delta.fact_id or stable_fact_id(delta.category, delta.subject, delta.resource_key)


def _category_mismatch_code(category: str) -> str:
    lowered = _canonical_text(category)
    if lowered in {"inventory", "item", "resource", "stackable"}:
        return "INVENTORY_QUANTITY_MISMATCH"
    if lowered in {"quest", "quest_progress", "task"}:
        return "QUEST_PROGRESS_MISMATCH"
    if lowered in {"level", "character_level"}:
        return "LEVEL_MISMATCH"
    if lowered in {"experience", "exp", "character_exp"}:
        return "EXPERIENCE_MISMATCH"
    if lowered in {"equipment_owner", "owner"}:
        return "EQUIPMENT_OWNER_MISMATCH"
    if lowered in {"equipment_state", "equipment_equipped", "equipment", "equipped"}:
        return "EQUIPMENT_STATE_MISMATCH"
    if lowered in {"relationship", "relationship_numeric", "trust", "tension", "relationship_value"}:
        return "RELATIONSHIP_VALUE_MISMATCH"
    return "RESOURCE_ASSERTION_MISMATCH"


def _apply_delta_to_entries(
    entries: dict[str, FactResourceEntry],
    delta: FactResourceDelta,
    *,
    strict: bool,
) -> FactResourceFinding | None:
    key = _entry_key(delta)
    entry = entries.get(key)
    operation = delta.operation
    if entry is None:
        if operation in {"ADD", "SUBTRACT", "PROGRESS_ADD"} and delta.before is None:
            return FactResourceFinding(
                code="INVALID_RESOURCE_DELTA",
                # An absent starting value is an unknown, not a proven
                # contradiction.  Keep it review-visible without inventing
                # a before value or blocking a candidate confirmation.
                severity="warning",
                message=f"{delta.resource_key} 的算术变化缺少已知起点，未推断 before。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
        entry = FactResourceEntry(
            fact_id=key,
            category=delta.category,
            subject=delta.subject,
            resource_key=delta.resource_key,
            value=delta.before,
            unit=delta.unit,
            owner=delta.owner or delta.from_owner,
            metadata=dict(delta.metadata),
            updated_chapter=max(0, delta.chapter - 1),
        )
        entries[key] = entry

    if operation == "TRANSFER":
        current_for_before = entry.owner
    elif operation in {"EQUIP", "UNEQUIP"} and "equipped" in entry.metadata:
        current_for_before = entry.metadata.get("equipped")
    else:
        current_for_before = entry.value
    if delta.before is not None and not _values_equal(current_for_before, delta.before):
        return FactResourceFinding(
            code=_category_mismatch_code(delta.category),
            severity="error" if strict else "warning",
            message=(
                f"{delta.resource_key} 的 before={delta.before!r} 与账本当前值 {current_for_before!r} 不一致。"
            ),
            delta_id=delta.delta_id,
            fact_id=key,
            category=delta.category,
            resource_key=delta.resource_key,
            evidence=delta.evidence,
        )

    if operation in {"ADD", "SUBTRACT", "PROGRESS_ADD"}:
        before = _number(entry.value)
        amount = _number(delta.change)
        if before is None or amount is None:
            return FactResourceFinding(
                code="INVALID_RESOURCE_DELTA",
                severity="warning",
                message=f"{delta.resource_key} 的算术变化不是已知数值。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
        next_value = before + (abs(amount) if operation != "SUBTRACT" else -abs(amount))
        if next_value < 0 and operation == "SUBTRACT":
            return FactResourceFinding(
                code="NEGATIVE_RESOURCE_BALANCE",
                severity="error",
                message=f"{delta.resource_key} 扣减后为 {next_value}，不能出现负库存或负余额。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
        target = _number(delta.metadata.get("target"))
        if _canonical_text(delta.category) in {"quest", "quest_progress", "task"} and target is not None and next_value > target:
            return FactResourceFinding(
                code="QUEST_PROGRESS_MISMATCH",
                severity="error",
                message=f"{delta.resource_key} 进度 {next_value} 超过已知目标 {target}。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
    elif operation in {"SET", "PROGRESS_SET"}:
        next_value = delta.after if delta.after is not None else delta.change
        if next_value is None:
            return FactResourceFinding(
                code="INVALID_RESOURCE_DELTA",
                severity="error",
                message=f"{delta.resource_key} 的 SET 变化缺少 after。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
        target = _number(delta.metadata.get("target"))
        numeric_next = _number(next_value)
        if numeric_next is not None and numeric_next < 0 and _canonical_text(delta.category) in {
            "currency",
            "resource",
            "inventory",
            "item",
            "stackable",
            "quest",
            "quest_progress",
            "task",
            "experience",
            "exp",
        }:
            return FactResourceFinding(
                code="NEGATIVE_RESOURCE_BALANCE",
                severity="error",
                message=f"{delta.resource_key} 设置为负数 {next_value}。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
        if _canonical_text(delta.category) in {"quest", "quest_progress", "task"} and target is not None and (_number(next_value) or 0) > target:
            return FactResourceFinding(
                code="QUEST_PROGRESS_MISMATCH",
                severity="error",
                message=f"{delta.resource_key} 进度 {next_value} 超过已知目标 {target}。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
    elif operation == "TRANSFER":
        next_value = entry.value
        if delta.from_owner and entry.owner and delta.from_owner != entry.owner:
            return FactResourceFinding(
                code="EQUIPMENT_OWNER_MISMATCH",
                severity="error" if strict else "warning",
                message=f"{delta.resource_key} 的原持有者不匹配。",
                delta_id=delta.delta_id,
                fact_id=key,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
            )
        entry.owner = delta.to_owner or delta.owner
    elif operation in {"EQUIP", "UNEQUIP"}:
        next_value = entry.value
        if operation == "EQUIP" and delta.owner and entry.owner:
            if _canonical_text(delta.owner) != _canonical_text(entry.owner):
                return FactResourceFinding(
                    code="EQUIPMENT_OWNER_MISMATCH",
                    severity="error" if strict else "warning",
                    message=f"{delta.resource_key} 的装备者与当前持有者不匹配。",
                    delta_id=delta.delta_id,
                    fact_id=key,
                    category=delta.category,
                    resource_key=delta.resource_key,
                    evidence=delta.evidence,
                )
        if operation == "EQUIP" and delta.owner and not entry.owner:
            entry.owner = delta.owner
        entry.metadata["equipped"] = operation == "EQUIP"
        if delta.equipped is not None:
            entry.metadata["equipped"] = delta.equipped
    else:  # pragma: no cover - Pydantic guards this
        return FactResourceFinding(
            code="INVALID_RESOURCE_DELTA",
            severity="error",
            message=f"不支持的事实变化操作：{operation}。",
            delta_id=delta.delta_id,
            fact_id=key,
            category=delta.category,
            resource_key=delta.resource_key,
            evidence=delta.evidence,
        )

    if operation != "TRANSFER" and operation not in {"EQUIP", "UNEQUIP"}:
        if delta.after is not None and operation in {"ADD", "SUBTRACT", "PROGRESS_ADD"}:
            if not _same_number(next_value, delta.after):
                return FactResourceFinding(
                    code="RESOURCE_ASSERTION_MISMATCH",
                    severity="error" if strict else "warning",
                    message=f"{delta.resource_key} 的 after 与 before/change 算式不一致。",
                    delta_id=delta.delta_id,
                    fact_id=key,
                    category=delta.category,
                    resource_key=delta.resource_key,
                    evidence=delta.evidence,
                )
        entry.value = next_value
    entry.updated_chapter = delta.chapter
    entry.unit = delta.unit or entry.unit
    if delta.owner and operation != "TRANSFER":
        entry.owner = delta.owner
    if delta.metadata:
        entry.metadata.update(deepcopy(delta.metadata))
    return None


def _values_equal(left: Any, right: Any) -> bool:
    if _number(left) is not None and _number(right) is not None:
        return _same_number(left, right)
    return left == right


def _assertion_finding(
    assertion: FactResourceAssertion,
    entry: FactResourceEntry | None,
    *,
    unknown_start: bool = False,
) -> FactResourceFinding | None:
    if entry is None:
        return FactResourceFinding(
            code=_category_mismatch_code(assertion.category),
            severity="warning" if unknown_start else "error",
            message=f"正文断言的 {assertion.resource_key} 在账本中仍未知。",
            fact_id=assertion.fact_id,
            category=assertion.category,
            resource_key=assertion.resource_key,
            evidence=assertion.evidence,
            chapter=0,
        )
    if assertion.expected_value is not None and not _values_equal(entry.value, assertion.expected_value):
        return FactResourceFinding(
            code="RESOURCE_ASSERTION_MISMATCH",
            severity="error",
            message=(
                f"正文断言 {assertion.resource_key}={assertion.expected_value!r}，"
                f"但计算结果为 {entry.value!r}。"
            ),
            fact_id=assertion.fact_id,
            category=assertion.category,
            resource_key=assertion.resource_key,
            evidence=assertion.evidence,
            expected=assertion.expected_value,
            observed=entry.value,
        )
    if assertion.expected_owner and assertion.expected_owner != entry.owner:
        return FactResourceFinding(
            code="EQUIPMENT_OWNER_MISMATCH",
            severity="error",
            message=f"正文断言 {assertion.resource_key} 的持有者不匹配。",
            fact_id=assertion.fact_id,
            category=assertion.category,
            resource_key=assertion.resource_key,
            evidence=assertion.evidence,
        )
    if assertion.expected_equipped is not None:
        actual = bool(entry.metadata.get("equipped"))
        if actual != assertion.expected_equipped:
            return FactResourceFinding(
                code="EQUIPMENT_STATE_MISMATCH",
                severity="error",
                message=f"正文断言 {assertion.resource_key} 的装备状态不匹配。",
                fact_id=assertion.fact_id,
                category=assertion.category,
                resource_key=assertion.resource_key,
                evidence=assertion.evidence,
            )
    return None


def validate_fact_resource_extraction(
    start_snapshot: FactResourceSnapshot | FactResourceLedger | Mapping[str, Any],
    extraction: FactResourceExtraction | Mapping[str, Any],
    *,
    end_snapshot: FactResourceSnapshot | None = None,
    include_authority_findings: bool = False,
) -> FactResourceValidation:
    """Replay candidate changes and return findings without mutating canon."""

    start = _coerce_snapshot(start_snapshot, as_of_chapter=None)
    parsed = (
        extraction
        if isinstance(extraction, FactResourceExtraction)
        else FactResourceExtraction.model_validate(extraction)
    )
    entries = {entry.fact_id: entry.model_copy(deep=True) for entry in start.entries}
    findings: list[FactResourceFinding] = []
    for delta in sorted(parsed.deltas, key=lambda item: (item.sequence, item.delta_id)):
        finding = _apply_delta_to_entries(entries, delta, strict=True)
        if finding is not None:
            findings.append(finding)
    for assertion in parsed.assertions:
        finding = _assertion_finding(
            assertion,
            entries.get(assertion.fact_id),
            unknown_start=not start.known,
        )
        if finding is not None:
            findings.append(finding)
            if (
                finding.code == "RESOURCE_ASSERTION_MISMATCH"
                and _category_mismatch_code(assertion.category)
                != "RESOURCE_ASSERTION_MISMATCH"
            ):
                findings.append(
                    finding.model_copy(
                        update={"code": _category_mismatch_code(assertion.category)}
                    )
                )
    for finding in parsed.findings:
        if finding.severity in {"error", "warning"}:
            findings.append(finding)
    # Authority ownership is a dispatch decision, not a validation error.
    # Callers that are auditing a generic-ledger-only write can still request
    # the old diagnostic explicitly, but a normal candidate confirmation must
    # be allowed to route a valid delta to its typed authority adapter.
    if include_authority_findings:
        findings.extend(fact_resource_authority_findings(start, parsed))
    if end_snapshot is not None:
        for entry in end_snapshot.entries:
            actual = entries.get(entry.fact_id)
            if actual is not None and not _values_equal(actual.value, entry.value):
                findings.append(
                    FactResourceFinding(
                        code=_category_mismatch_code(entry.category),
                        severity="error",
                        message=f"{entry.resource_key} 与提供的结束快照不一致。",
                        fact_id=entry.fact_id,
                        category=entry.category,
                        resource_key=entry.resource_key,
                    )
                )
    proposed = FactResourceSnapshot(
        as_of_chapter=parsed.chapter_number,
        known=True,
        source="candidate_projection",
        entries=sorted(
            entries.values(),
            key=lambda item: (item.category, item.subject, item.resource_key, item.fact_id),
        ),
        findings=findings,
        authorities=list(start.authorities),
    )
    return FactResourceValidation(
        ok=not any(item.severity == "error" for item in findings),
        start_snapshot=start,
        proposed_snapshot=proposed,
        findings=findings,
        delta_count=len(parsed.deltas),
        assertion_count=len(parsed.assertions),
    )


def _coerce_snapshot(value: Any, *, as_of_chapter: int | None) -> FactResourceSnapshot:
    if isinstance(value, FactResourceSnapshot):
        return value.model_copy(deep=True)
    if isinstance(value, FactResourceLedger):
        return value.replay(as_of_chapter=as_of_chapter)
    if isinstance(value, Mapping):
        if "entries" in value and "known" in value:
            return FactResourceSnapshot.model_validate(value)
        if any(
            key in value
            for key in (
                "characters",
                "progression_ledger",
                "equipment_cards",
                "relationship_graph",
            )
        ):
            return project_fact_resource_snapshot(value, as_of_chapter=as_of_chapter)
        ledger_payload = value.get("fact_resource_ledger") or value.get("ledger")
        if ledger_payload:
            try:
                return _coerce_ledger(ledger_payload).replay(as_of_chapter=as_of_chapter)
            except Exception:
                pass
    return FactResourceSnapshot(as_of_chapter=as_of_chapter or 0, known=False)


def _coerce_ledger(value: Any) -> FactResourceLedger:
    if isinstance(value, FactResourceLedger):
        return value
    if isinstance(value, list):
        return FactResourceLedger(baseline={"chapter": 0, "entries": value})
    return FactResourceLedger.model_validate(value)


def _chinese_number(raw: str) -> int | None:
    raw = raw.strip()
    if raw.isdigit():
        return int(raw)
    digits = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
    units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
    if not raw or any(char not in digits and char not in units for char in raw):
        return None
    total = 0
    section = 0
    number = 0
    for char in raw:
        if char in digits:
            number = digits[char]
        else:
            unit = units[char]
            if unit == 10000:
                section = (section + number) * unit
                total += section
                section = 0
                number = 0
            else:
                section += (number or 1) * unit
                number = 0
    return total + section + number


_AMOUNT = r"(?P<amount>\d+(?:\.\d+)?|[零一二两三四五六七八九十百千万]+)"
_RESOURCE = r"(?P<resource>[\u4e00-\u9fffA-Za-z][\u4e00-\u9fffA-Za-z0-9]{0,15})"
_UNIT = r"(?P<unit>枚|颗|块|件|瓶|张|份|个|点|级|层|金币|灵石|元|铜钱|银两)?"


def _resource_category(resource: str, *, default: str = "resource") -> str:
    lowered = _canonical_text(resource)
    if any(token in lowered for token in ("金币", "灵石", "铜钱", "银两", "余额", "元")):
        return "currency"
    if any(token in lowered for token in ("任务", "进度", "quest")):
        return "quest"
    if any(token in lowered for token in ("经验", "exp")):
        return "experience"
    if any(token in lowered for token in ("等级", "level")):
        return "level"
    return default


def _looks_trackable_resource(resource: str) -> bool:
    lowered = _canonical_text(resource)
    return any(
        token in lowered
        for token in (
            "水晶",
            "金币",
            "灵石",
            "铜钱",
            "银两",
            "药剂",
            "药水",
            "药",
            "丹",
            "矿",
            "材料",
            "道具",
            "卷轴",
            "装备",
            "经验",
            "等级",
            "任务",
        )
    )


def _parse_amount(raw: str) -> int | float | None:
    if "." in raw and raw.replace(".", "", 1).isdigit():
        return float(raw)
    return _chinese_number(raw)


def _match_amount_resource(text: str) -> list[tuple[int, int, int | float, str, str]]:
    matches = []
    for match in re.finditer(_AMOUNT + r"\s*" + _UNIT + r"\s*" + _RESOURCE, text):
        amount = _parse_amount(match.group("amount"))
        resource = _text(match.group("resource"))
        if amount is None or not resource:
            continue
        unit = _text(match.group("unit"))
        matches.append((match.start(), match.end(), amount, resource, unit))
    return matches


def _known_entry_for_text(snapshot: FactResourceSnapshot, resource: str) -> FactResourceEntry | None:
    exact = snapshot.find("resource", resource)
    if exact is not None:
        return exact
    for category in ("currency", "inventory", "item", "quest", "experience", "level", "equipment", "relationship"):
        exact = snapshot.find(category, resource)
        if exact is not None:
            return exact
    return None


def _make_delta(
    *,
    chapter_number: int,
    sequence: int,
    category: str,
    resource: str,
    operation: str,
    amount: Any = None,
    unit: str = "",
    snapshot: FactResourceSnapshot,
    evidence: str,
    subject: str = "",
    after: Any = None,
    owner: str = "",
    from_owner: str = "",
    to_owner: str = "",
    metadata: Mapping[str, Any] | None = None,
) -> FactResourceDelta:
    existing = snapshot.find(category, resource, subject=subject) or _known_entry_for_text(snapshot, resource)
    before = existing.value if existing is not None else None
    if after is None and before is not None and operation in {"ADD", "SUBTRACT", "PROGRESS_ADD"}:
        number = _number(amount)
        if number is not None:
            after = before + (abs(number) if operation != "SUBTRACT" else -abs(number))
    return FactResourceDelta(
        chapter=chapter_number,
        sequence=sequence,
        fact_id=existing.fact_id if existing is not None else stable_fact_id(category, subject, resource),
        category=category,
        subject=subject,
        resource_key=resource,
        operation=operation,
        before=before,
        change=amount,
        after=after,
        unit=unit,
        owner=owner,
        from_owner=from_owner,
        to_owner=to_owner,
        metadata=dict(metadata or {}),
        evidence=evidence,
        confidence=0.96,
    )


def extract_fact_resource_changes(
    body: str,
    chapter_number: int,
    start_snapshot: FactResourceSnapshot | FactResourceLedger | Mapping[str, Any] | None = None,
    *,
    candidate_claims: Sequence[Mapping[str, Any]] | None = None,
) -> FactResourceExtraction:
    """Extract only explicit, local resource statements from chapter prose.

    This is intentionally conservative.  A sentence that only implies a
    change is ignored; an explicit remaining balance becomes an assertion.
    """

    if chapter_number < 1:
        raise ValueError("chapter_number_must_be_positive")
    text = str(body or "")
    snapshot = _coerce_snapshot(start_snapshot or {}, as_of_chapter=chapter_number - 1)
    deltas: list[FactResourceDelta] = []
    assertions: list[FactResourceAssertion] = []
    findings: list[FactResourceFinding] = []
    sequence = 0

    # Explicit remaining/set assertions: “还剩15枚记录水晶”.
    for match in re.finditer(
        r"(?:还剩|剩余|余额为|数量为|库存为)\s*" + _AMOUNT + r"\s*" + _UNIT + r"\s*" + _RESOURCE,
        text,
    ):
        amount = _parse_amount(match.group("amount"))
        resource = _text(match.group("resource"))
        if amount is None or not resource:
            continue
        category = _resource_category(resource, default="inventory")
        existing = snapshot.find(category, resource) or _known_entry_for_text(snapshot, resource)
        assertions.append(
            FactResourceAssertion(
                category=existing.category if existing else category,
                subject=existing.subject if existing else "",
                resource_key=existing.resource_key if existing else resource,
                fact_id=existing.fact_id if existing else stable_fact_id(category, "", resource),
                expected_value=amount,
                unit=_text(match.group("unit")),
                evidence=match.group(0),
                confidence=0.98,
            )
        )

    # Gain/consume statements.  Require an explicit verb immediately before
    # the amount/resource pair to avoid treating unrelated scene numbers as
    # ledger events.
    for match in re.finditer(
        r"(?P<verb>获得|得到|拿到|收获|捡到|增加(?:了)?|补充(?:了)?|消耗(?:了)?|使用(?:了)?|花费(?:了)?|支付(?:了)?|失去(?:了)?|减少(?:了)?)"
        r"[^。；，,\n]{0,18}?" + _AMOUNT + r"\s*" + _UNIT + r"\s*" + _RESOURCE,
        text,
    ):
        amount = _parse_amount(match.group("amount"))
        resource = _text(match.group("resource"))
        verb = _text(match.group("verb"))
        if amount is None or not resource:
            continue
        if not _looks_trackable_resource(resource) and _known_entry_for_text(snapshot, resource) is None:
            continue
        subtract = any(token in verb for token in ("消耗", "使用", "花费", "支付", "失去", "减少"))
        category = _resource_category(resource, default="inventory")
        if category == "level":
            operation = "SET"
        elif category == "experience":
            operation = "ADD" if not subtract else "SUBTRACT"
        else:
            operation = "SUBTRACT" if subtract else "ADD"
        deltas.append(
            _make_delta(
                chapter_number=chapter_number,
                sequence=sequence,
                category=category,
                resource=resource,
                operation=operation,
                amount=amount,
                unit=_text(match.group("unit")),
                snapshot=snapshot,
                evidence=match.group(0),
            )
        )
        sequence += 1

    # Explicit current-state statements are SET claims, not arithmetic.  This
    # is the safe chapter-zero path for prose such as “现在有8个记录水晶”:
    # the previous value stays unknown, but the observed value can be adopted
    # with evidence and later chapters can replay from it.
    for match in re.finditer(
        r"(?:现在|此刻|背包里|库存中|手中)?\s*(?:有|拥有|持有)\s*"
        + _AMOUNT
        + r"\s*"
        + _UNIT
        + r"\s*"
        + _RESOURCE,
        text,
    ):
        amount = _parse_amount(match.group("amount"))
        resource = _text(match.group("resource"))
        if amount is None or not resource:
            continue
        if not _looks_trackable_resource(resource) and _known_entry_for_text(snapshot, resource) is None:
            continue
        category = _resource_category(resource, default="inventory")
        existing = snapshot.find(category, resource) or _known_entry_for_text(snapshot, resource)
        if existing is not None:
            assertions.append(
                FactResourceAssertion(
                    category=existing.category,
                    subject=existing.subject,
                    resource_key=existing.resource_key,
                    fact_id=existing.fact_id,
                    expected_value=amount,
                    unit=_text(match.group("unit")),
                    evidence=match.group(0),
                    confidence=0.94,
                )
            )
        else:
            deltas.append(
                FactResourceDelta(
                    chapter=chapter_number,
                    sequence=sequence,
                    fact_id=stable_fact_id(category, "", resource),
                    category=category,
                    resource_key=resource,
                    operation="SET",
                    before=None,
                    change=amount,
                    after=amount,
                    unit=_text(match.group("unit")),
                    evidence=match.group(0),
                    confidence=0.94,
                )
            )
        sequence += 1

    # Level and experience are explicit only; do not derive them from prose
    # such as “实力大涨”.
    for match in re.finditer(r"(?:升到|达到|提升至|晋升到|升至)\s*" + _AMOUNT + r"\s*级", text):
        amount = _parse_amount(match.group("amount"))
        if amount is None:
            continue
        deltas.append(
            _make_delta(
                chapter_number=chapter_number,
                sequence=sequence,
                category="level",
                resource="level",
                operation="SET",
                amount=amount,
                after=amount,
                snapshot=snapshot,
                evidence=match.group(0),
            )
        )
        sequence += 1
    for match in re.finditer(r"(?:经验值|经验)\s*(?:增加|增加了|为|达到|变为)?\s*" + _AMOUNT, text):
        amount = _parse_amount(match.group("amount"))
        if amount is None:
            continue
        is_set = bool(re.search(r"为|达到|变为", match.group(0)))
        existing = next(
            (item for item in snapshot.entries if _canonical_text(item.category) in {"experience", "exp", "character_exp"}),
            None,
        )
        if is_set and existing is not None:
            assertions.append(
                FactResourceAssertion(
                    category=existing.category,
                    subject=existing.subject,
                    resource_key=existing.resource_key,
                    fact_id=existing.fact_id,
                    expected_value=amount,
                    evidence=match.group(0),
                    confidence=0.95,
                )
            )
        else:
            deltas.append(
                _make_delta(
                    chapter_number=chapter_number,
                    sequence=sequence,
                    category="experience",
                    resource=existing.resource_key if existing else "experience",
                    operation="SET" if is_set else "ADD",
                    amount=amount,
                    after=amount if is_set else None,
                    snapshot=snapshot,
                    evidence=match.group(0),
                )
            )
        sequence += 1

    # Plain level statements are observed assertions.  “升到28级” above is
    # an explicit transition; “当前等级28” is only checked against the
    # projected result of any separately extracted change.
    for match in re.finditer(
        r"(?:当前|现在|本章结束时)?\s*等级\s*(?:为|是|达到)?\s*"
        + _AMOUNT
        + r"\s*级?",
        text,
    ):
        amount = _parse_amount(match.group("amount"))
        if amount is None:
            continue
        existing = next(
            (item for item in snapshot.entries if _canonical_text(item.category) in {"level", "character_level"}),
            None,
        )
        assertions.append(
            FactResourceAssertion(
                category=existing.category if existing else "level",
                subject=existing.subject if existing else "",
                resource_key=existing.resource_key if existing else "level",
                fact_id=existing.fact_id if existing else stable_fact_id("level", "", "level"),
                expected_value=amount,
                unit="级",
                evidence=match.group(0),
                confidence=0.95,
            )
        )

    # Numeric relationship observations.  We only use an existing exact
    # entry, or a single unambiguous numeric relationship entry; no aliases
    # are introduced here.
    relationship_entries = [
        item
        for item in snapshot.entries
        if _canonical_text(item.category) in {"relationship", "relationship_numeric", "trust", "tension"}
    ]
    # Explicit numeric relationship changes are deltas, not semantic
    # relationship inference.  A missing starting value remains unknown and
    # is surfaced as a warning by deterministic validation.
    for match in re.finditer(
        r"(?P<subject>[\u4e00-\u9fffA-Za-z]{2,12})?\s*"
        r"(?P<metric>好感度|信任值|favorability|trust|tension)\s*"
        r"(?:(?P<verb>增加|上升|提升|下降|降低|减少)\s*)?"
        r"(?P<sign>[+-])?\s*"
        + _AMOUNT,
        text,
    ):
        amount = _parse_amount(match.group("amount"))
        if amount is None:
            continue
        subject = _text(match.group("subject"))
        metric = _text(match.group("metric"))
        verb = _text(match.group("verb"))
        negative = match.group("sign") == "-" or verb in {"下降", "降低", "减少"}
        existing = next(
            (
                item
                for item in relationship_entries
                if _canonical_text(item.resource_key) == _canonical_text(metric)
                and (not subject or _canonical_text(item.subject) == _canonical_text(subject))
            ),
            None,
        )
        if existing is None and not subject and len(relationship_entries) == 1:
            existing = relationship_entries[0]
        deltas.append(
            _make_delta(
                chapter_number=chapter_number,
                sequence=sequence,
                category=existing.category if existing else "relationship_numeric",
                resource=existing.resource_key if existing else metric,
                operation="SUBTRACT" if negative else "ADD",
                amount=amount,
                snapshot=snapshot,
                evidence=match.group(0),
                subject=existing.subject if existing else subject,
            )
        )
        sequence += 1
    for match in re.finditer(
        r"(?P<subject>[\u4e00-\u9fffA-Za-z]{2,12})?\s*(?P<metric>好感度|信任值|favorability|trust|tension)"
        r"\s*(?:达到|为|是|变为)?\s*" + _AMOUNT,
        text,
    ):
        amount = _parse_amount(match.group("amount"))
        if amount is None:
            continue
        subject = _text(match.group("subject"))
        metric = _text(match.group("metric"))
        existing = next(
            (
                item
                for item in relationship_entries
                if (_canonical_text(item.resource_key) == _canonical_text(metric))
                and (not subject or _canonical_text(item.subject) == _canonical_text(subject))
            ),
            None,
        )
        if existing is None and not subject and len(relationship_entries) == 1:
            existing = relationship_entries[0]
        assertions.append(
            FactResourceAssertion(
                category=existing.category if existing else "relationship_numeric",
                subject=existing.subject if existing else subject,
                resource_key=existing.resource_key if existing else metric,
                fact_id=existing.fact_id if existing else stable_fact_id("relationship_numeric", subject, metric),
                expected_value=amount,
                evidence=match.group(0),
                confidence=0.94,
            )
        )

    # A final quest progress statement is an assertion.  If there is exactly
    # one active quest in the snapshot, the omitted name is still unambiguous.
    quest_entries = [
        item for item in snapshot.entries if _canonical_text(item.category) in {"quest", "quest_progress", "task"}
    ]
    for match in re.finditer(
        r"(?:完成|当前|任务)?[^。；\n]{0,8}?进度\s*"
        r"(?P<done>\d+)\s*(?:/|／|之)\s*(?P<target>\d+)",
        text,
    ):
        done = int(match.group("done"))
        existing = quest_entries[0] if len(quest_entries) == 1 else None
        assertions.append(
            FactResourceAssertion(
                category=existing.category if existing else "quest",
                subject=existing.subject if existing else "",
                resource_key=existing.resource_key if existing else "quest_progress",
                fact_id=existing.fact_id if existing else stable_fact_id("quest", "", "quest_progress"),
                expected_value=done,
                evidence=match.group(0),
                confidence=0.93,
            )
        )

    # Explicit ownership/state observations are assertions unless the prose
    # contains a transfer/equip verb handled above.
    equipment_entries = [
        item
        for item in snapshot.entries
        if _canonical_text(item.category) in {"equipment", "equipment_owner", "equipment_state", "equipped"}
    ]
    for match in re.finditer(
        r"(?P<owner>[\u4e00-\u9fffA-Za-z]{2,12})(?:一直|始终|目前|当前)?持有(?P<item>[\u4e00-\u9fffA-Za-z0-9]{1,20})",
        text,
    ):
        owner, item = _text(match.group("owner")), _text(match.group("item"))
        existing = next(
            (entry for entry in equipment_entries if _canonical_text(entry.resource_key) == _canonical_text(item)),
            None,
        )
        assertions.append(
            FactResourceAssertion(
                category="equipment_owner",
                subject=existing.subject if existing else "",
                resource_key=existing.resource_key if existing else item,
                fact_id=existing.fact_id if existing else stable_fact_id("equipment_owner", "", item),
                expected_owner=owner,
                evidence=match.group(0),
                confidence=0.96,
            )
        )
    for match in re.finditer(
        r"(?P<item>[\u4e00-\u9fffA-Za-z0-9]{1,20})(?P<state>已装备|装备中|装备着|未装备|没有装备)",
        text,
    ):
        item = _text(match.group("item"))
        equipped = not _text(match.group("state")).startswith(("未", "没有"))
        existing = next(
            (entry for entry in equipment_entries if _canonical_text(entry.resource_key) == _canonical_text(item)),
            None,
        )
        assertions.append(
            FactResourceAssertion(
                category="equipment_state",
                subject=existing.subject if existing else "",
                resource_key=existing.resource_key if existing else item,
                fact_id=existing.fact_id if existing else stable_fact_id("equipment_state", "", item),
                expected_equipped=equipped,
                evidence=match.group(0),
                confidence=0.95,
            )
        )

    # Quest progress such as “任务采集进度3/5”.
    for match in re.finditer(
        r"任务\s*(?P<quest>[\u4e00-\u9fffA-Za-z0-9]{1,20})[^。；\n]{0,8}?进度\s*"
        r"(?P<done>\d+)\s*(?:/|／|之)\s*(?P<target>\d+)",
        text,
    ):
        quest = _text(match.group("quest"))
        done, target = int(match.group("done")), int(match.group("target"))
        deltas.append(
            _make_delta(
                chapter_number=chapter_number,
                sequence=sequence,
                category="quest",
                resource=quest,
                operation="PROGRESS_SET",
                amount=done,
                after=done,
                snapshot=snapshot,
                evidence=match.group(0),
                metadata={"target": target},
            )
        )
        sequence += 1

    # Ownership and equipped-state statements are exact named transitions.
    for match in re.finditer(
        r"将(?P<item>[\u4e00-\u9fffA-Za-z0-9]{1,20})交给(?P<owner>[\u4e00-\u9fffA-Za-z0-9]{1,12})",
        text,
    ):
        item, owner = _text(match.group("item")), _text(match.group("owner"))
        existing = snapshot.find("equipment_owner", item) or _known_entry_for_text(snapshot, item)
        deltas.append(
            FactResourceDelta(
                chapter=chapter_number,
                sequence=sequence,
                fact_id=existing.fact_id if existing else stable_fact_id("equipment_owner", "", item),
                category="equipment_owner",
                resource_key=item,
                operation="TRANSFER",
                before=existing.owner if existing else None,
                owner=owner,
                from_owner=existing.owner if existing else "",
                to_owner=owner,
                evidence=match.group(0),
                confidence=0.97,
            )
        )
        sequence += 1
    for match in re.finditer(r"(?:装备上|穿上|戴上)(?P<item>[\u4e00-\u9fffA-Za-z0-9]{1,20})", text):
        item = _text(match.group("item"))
        deltas.append(
            _make_delta(
                chapter_number=chapter_number,
                sequence=sequence,
                category="equipment_state",
                resource=item,
                operation="EQUIP",
                snapshot=snapshot,
                evidence=match.group(0),
                metadata={"equipped": True},
            )
        )
        sequence += 1
    for match in re.finditer(r"(?:卸下|脱下)(?P<item>[\u4e00-\u9fffA-Za-z0-9]{1,20})", text):
        item = _text(match.group("item"))
        deltas.append(
            _make_delta(
                chapter_number=chapter_number,
                sequence=sequence,
                category="equipment_state",
                resource=item,
                operation="UNEQUIP",
                snapshot=snapshot,
                evidence=match.group(0),
                metadata={"equipped": False},
            )
        )
        sequence += 1

    # Optional structured claims are accepted only when explicitly marked and
    # sufficiently confident; the body remains the evidence boundary.
    for raw in candidate_claims or []:
        if not isinstance(raw, Mapping) or raw.get("explicit") is False:
            continue
        confidence = float(raw.get("confidence") or 0)
        if confidence < 0.8:
            findings.append(
                FactResourceFinding(
                    code="INVALID_RESOURCE_DELTA",
                    severity="warning",
                    message="低置信度结构化事实未进入候选账本。",
                    evidence=str(raw.get("evidence") or ""),
                )
            )
            continue
        try:
            delta = FactResourceDelta.model_validate(
                {**dict(raw), "chapter": chapter_number, "sequence": sequence}
            )
        except Exception:
            findings.append(
                FactResourceFinding(
                    code="INVALID_RESOURCE_DELTA",
                    severity="warning",
                    message="结构化事实字段无效，未进入候选账本。",
                    evidence=str(raw.get("evidence") or ""),
                )
            )
            continue
        deltas.append(delta)
        sequence += 1

    return FactResourceExtraction(
        chapter_number=chapter_number,
        deltas=deltas,
        assertions=assertions,
        findings=findings,
        source_text_sha256=sha256(text.encode("utf-8")).hexdigest(),
    )


# ---------------------------------------------------------------------------
# Existing-source projections


_PROGRESSION_FIELD_ALIASES = {
    "level": "level",
    "character_level": "level",
    "exp": "experience",
    "experience": "experience",
    "character_exp": "experience",
    "inventory": "inventory",
    "items": "inventory",
    "backpack": "inventory",
    "currency": "currency",
    "game_currency": "currency",
    "money": "currency",
    "quests": "quest",
    "quest": "quest",
    "tasks": "quest",
    "task": "quest",
}


def _plain_payload(value: Any) -> dict[str, Any]:
    if isinstance(value, Mapping):
        return dict(value)
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        try:
            dumped = model_dump(mode="python")
        except TypeError:
            dumped = model_dump()
        return dict(dumped) if isinstance(dumped, Mapping) else {}
    return {}


def _story_payload(value: Any) -> dict[str, Any]:
    """Make one non-mutating mapping for a StoryState or project payload."""

    payload = _plain_payload(value)
    # ``fact_resource_ledger`` is runtime-only on StoryState and is excluded
    # from model_dump.  Preserve it as an explicit opt-in source when a
    # caller passed a live model with that field populated.
    ledger = getattr(value, "fact_resource_ledger", None)
    if isinstance(ledger, Mapping) and ledger:
        payload["fact_resource_ledger"] = deepcopy(dict(ledger))
    return payload


def _target_chapter(story: Mapping[str, Any], as_of_chapter: int | None) -> int:
    if as_of_chapter is not None:
        return max(0, int(as_of_chapter))
    for key in ("current_chapter", "latest_chapter", "last_written_chapter"):
        value = _number(story.get(key))
        if value is not None:
            return max(0, int(value))
    # No unanchored latest field is allowed below.  A large read boundary is
    # safe because every projected mutable value still requires its own
    # chapter/last-update anchor.
    return 1_000_000


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, item in value.items():
            yield str(key)
            yield from _walk_keys(item)
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        for item in value:
            yield from _walk_keys(item)


def _progression_authority_categories(
    story: Mapping[str, Any],
) -> set[str]:
    raw = story.get("progression_ledger")
    categories: set[str] = set()
    if isinstance(raw, Mapping):
        for key in _walk_keys(raw):
            category = _PROGRESSION_FIELD_ALIASES.get(_canonical_text(key))
            if category:
                categories.add(category)
    characters = story.get("characters")
    if isinstance(characters, Sequence) and not isinstance(characters, (str, bytes, bytearray)):
        for character in characters:
            if not isinstance(character, Mapping):
                continue
            if not (
                _canonical_text(character.get("role")) in {"protagonist", "主角"}
                or _canonical_text(character.get("character_tier")) in {"protagonist", "主角"}
            ):
                continue
            for namespace in ("progression", "game_state"):
                container = character.get(namespace)
                if isinstance(container, Mapping):
                    for key in _walk_keys(container):
                        category = _PROGRESSION_FIELD_ALIASES.get(_canonical_text(key))
                        if category:
                            categories.add(category)
    return categories


def _adapter_chapter(value: Any, *, default: int | None = None) -> int | None:
    if isinstance(value, bool):
        return None
    try:
        chapter = int(value)
    except (TypeError, ValueError):
        return default
    return chapter if chapter >= 0 else None


def _adapter_event_list(value: Any) -> list[Mapping[str, Any]]:
    if isinstance(value, Mapping):
        if not any(key in value for key in ("chapter", "chapter_number", "as_of_chapter")):
            keyed: list[Mapping[str, Any]] = []
            for key, item in value.items():
                chapter = _adapter_chapter(key)
                if chapter is None or not isinstance(item, Mapping):
                    keyed = []
                    break
                keyed.append({"chapter": chapter, **dict(item)})
            if keyed:
                return keyed
        return [value]
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [item for item in value if isinstance(item, Mapping)]
    return []


def _adapter_event_value(event: Mapping[str, Any]) -> dict[str, Any]:
    for key in ("current", "state", "delta", "state_delta", "value"):
        value = event.get(key)
        if isinstance(value, Mapping):
            return {
                str(item_key): deepcopy(item_value)
                for item_key, item_value in value.items()
                if item_value not in (None, "")
            }
    ignored = {
        "chapter",
        "chapter_number",
        "as_of_chapter",
        "summary",
        "evidence",
        "source",
        "confidence",
        "fact",
        "line",
        "scene_line",
        "namespace",
    }
    return {
        str(key): deepcopy(value)
        for key, value in event.items()
        if str(key) not in ignored
        and str(key) not in {"current", "state", "delta", "state_delta", "value"}
        and value not in (None, "")
    }


def _adapter_events(
    container: Any,
    *,
    default_chapter: int = 0,
    keys: Sequence[str] = (
        "baseline",
        "initial",
        "initial_state",
        "history",
        "state_history",
        "state_changes",
        "progression_history",
        "level_history",
        "changes",
        "snapshots",
        "events",
    ),
) -> list[tuple[int, int, dict[str, Any], str]]:
    payload = _plain_payload(container)
    events: list[tuple[int, int, dict[str, Any], str]] = []
    sequence = 0
    for key in keys:
        if key not in payload:
            continue
        raw_items = _adapter_event_list(payload.get(key))
        if key in {"baseline", "initial", "initial_state"} and isinstance(payload.get(key), Mapping):
            raw_items = [{"chapter": default_chapter, **dict(payload[key])}]
        for item in raw_items:
            chapter = _adapter_chapter(
                item.get("chapter", item.get("chapter_number", item.get("as_of_chapter"))),
                default=default_chapter if key in {"baseline", "initial", "initial_state"} else None,
            )
            values = _adapter_event_value(item)
            if chapter is None or not values:
                continue
            events.append((chapter, sequence, values, key))
            sequence += 1
    if not payload and isinstance(container, Sequence) and not isinstance(container, (str, bytes, bytearray)):
        for item in container:
            if not isinstance(item, Mapping):
                continue
            chapter = _adapter_chapter(
                item.get("chapter", item.get("chapter_number", item.get("as_of_chapter")))
            )
            values = _adapter_event_value(item)
            if chapter is not None and values:
                events.append((chapter, sequence, values, "sequence"))
                sequence += 1
    return events


def _field_chapter(evidence: Mapping[str, Any], prefix: str) -> int:
    chapters = []
    for path, raw in evidence.items():
        if path == prefix or path.startswith(prefix + "."):
            chapter = _adapter_chapter(raw.get("chapter") if isinstance(raw, Mapping) else None)
            if chapter is not None:
                chapters.append(chapter)
    return max(chapters, default=0)


def _historical_scalar(value: Any, category: str) -> tuple[Any, dict[str, Any]]:
    metadata: dict[str, Any] = {}
    if isinstance(value, bool):
        return value, metadata
    if isinstance(value, (int, float)):
        return value, metadata
    text = _text(value)
    if not text:
        return value, metadata
    if _canonical_text(category) == "level":
        match = re.search(r"(?:lv\.?\s*)?(\d+)", text, flags=re.IGNORECASE)
        if match:
            metadata["display_value"] = text
            return int(match.group(1)), metadata
    if _canonical_text(category) == "experience":
        match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(?:/\s*\d+(?:\.\d+)?)?\s*", text)
        if match:
            parsed = _number(match.group(1))
            if parsed is not None:
                metadata["display_value"] = text
                return parsed, metadata
    if _canonical_text(category) in {"inventory", "currency"}:
        match = re.fullmatch(
            r"\s*(\d+(?:\.\d+)?)\s*(枚|颗|块|件|瓶|张|份|个|点|金币|灵石|元|铜钱|银两)?\s*",
            text,
        )
        if match:
            parsed = _number(match.group(1))
            if parsed is not None:
                metadata["display_value"] = text
                if match.group(2):
                    metadata["display_unit"] = match.group(2)
                return parsed, metadata
    numeric = _number(text)
    if numeric is not None:
        return numeric, metadata
    return value, metadata


def _quest_scalar(value: Any) -> tuple[Any, dict[str, Any]]:
    if isinstance(value, Mapping):
        value = value.get("progress", value.get("value", value))
    metadata: dict[str, Any] = {}
    text = _text(value)
    match = re.search(r"(\d+)\s*/\s*(\d+)", text)
    if match:
        metadata["target"] = int(match.group(2))
        metadata["status"] = text
        return int(match.group(1)), metadata
    return value, metadata


def _add_projected_entry(
    entries: dict[str, FactResourceEntry],
    *,
    category: str,
    resource_key: str,
    value: Any,
    owner: str = "",
    unit: str = "",
    subject: str = "",
    chapter: int = 0,
    metadata: Mapping[str, Any] | None = None,
) -> None:
    if value in (None, "", [], {}):
        return
    payload_metadata = dict(metadata or {})
    fact_id = stable_fact_id(category, subject, resource_key)
    existing = entries.get(fact_id)
    if existing is not None and existing.updated_chapter > chapter:
        return
    entries[fact_id] = FactResourceEntry(
        fact_id=fact_id,
        category=category,
        subject=subject,
        resource_key=resource_key,
        value=value,
        unit=unit,
        owner=owner,
        metadata=payload_metadata,
        updated_chapter=chapter,
    )


def _project_progression_entries(
    story: Mapping[str, Any],
    *,
    as_of_chapter: int,
    entries: dict[str, FactResourceEntry],
) -> None:
    """Project only chapter-anchored progression/game values.

    ``get_character_state_for_writer`` is the existing replay boundary.  The
    adapter intentionally does not read an unanchored latest ``current``
    value, even when the legacy field is present.
    """

    try:
        from packages.story_core.historical_state_replay import (
            get_character_state_for_writer,
        )
    except Exception:  # pragma: no cover - import is stable in production
        get_character_state_for_writer = None

    characters = story.get("characters")
    candidates = [
        _plain_payload(item)
        for item in characters
        if isinstance(item, Mapping)
        and str(item.get("name") or "").strip()
        and (
            _canonical_text(item.get("role")) in {"protagonist", "主角"}
            or _canonical_text(item.get("character_tier")) in {"protagonist", "主角"}
        )
    ] if isinstance(characters, Sequence) and not isinstance(characters, (str, bytes, bytearray)) else []

    projected: dict[str, Any] = {}
    evidence: dict[str, Any] = {}
    for character in candidates[:1]:
        if get_character_state_for_writer is None:
            break
        try:
            historical = get_character_state_for_writer(
                story,
                str(character.get("name") or ""),
                as_of_chapter,
            )
        except (KeyError, ValueError, TypeError):
            continue
        for source_name, values in (
            ("progression", historical.progression),
            ("game_state", historical.game_state),
        ):
            if not isinstance(values, Mapping):
                continue
            for key, value in values.items():
                canonical = _PROGRESSION_FIELD_ALIASES.get(_canonical_text(key))
                if canonical and canonical not in projected:
                    projected[canonical] = deepcopy(value)
                    evidence[canonical] = (
                        _field_chapter(historical.evidence, f"{source_name}.{key}"),
                        f"{source_name}.{key}",
                    )
        # Nested values can be emitted by a progression event under a
        # single ``current`` object.  Merge only fields not already selected
        # from the explicit progression source.
        for source_name, values in (
            ("progression", historical.progression),
            ("game_state", historical.game_state),
        ):
            if not isinstance(values, Mapping):
                continue
            for key, value in values.items():
                canonical = _PROGRESSION_FIELD_ALIASES.get(_canonical_text(key))
                if canonical == "inventory" and isinstance(value, Mapping):
                    inventory = projected.setdefault("inventory", {})
                    if not isinstance(inventory, dict):
                        inventory = {}
                        projected["inventory"] = inventory
                    for item_key, item_value in value.items():
                        inventory.setdefault(str(item_key), deepcopy(item_value))
                    evidence.setdefault(
                        "inventory",
                        (
                            _field_chapter(historical.evidence, f"{source_name}.{key}"),
                            f"{source_name}.{key}",
                        ),
                    )
                elif canonical == "quest" and isinstance(value, Mapping):
                    quests = projected.setdefault("quest", {})
                    if not isinstance(quests, dict):
                        quests = {}
                        projected["quest"] = quests
                    for quest_key, quest_value in value.items():
                        if str(quest_key) != "active":
                            quests.setdefault(str(quest_key), deepcopy(quest_value))
                    evidence.setdefault(
                        "quest",
                        (
                            _field_chapter(historical.evidence, f"{source_name}.{key}"),
                            f"{source_name}.{key}",
                        ),
                    )

    # Fallback for projects whose historical progression is stored directly
    # under progression_ledger rather than under a protagonist character.
    raw_ledger = story.get("progression_ledger")
    if isinstance(raw_ledger, Mapping):
        containers: list[tuple[str, Any]] = [("progression_ledger", raw_ledger)]
        for key in ("protagonist", "economy", "quests", "panel"):
            if isinstance(raw_ledger.get(key), Mapping):
                containers.append((f"progression_ledger.{key}", raw_ledger[key]))
        fallback_values: dict[str, tuple[Any, int, str]] = {}
        for path, container in containers:
            for chapter, sequence, values, event_source in _adapter_events(container):
                del sequence
                if chapter > as_of_chapter:
                    continue
                for key, value in values.items():
                    canonical = _PROGRESSION_FIELD_ALIASES.get(_canonical_text(key))
                    if canonical:
                        fallback_values[canonical] = (value, chapter, f"{path}.{event_source}.{key}")
        for canonical, (value, chapter, path) in fallback_values.items():
            if canonical == "inventory" and isinstance(value, Mapping):
                projected.setdefault("inventory", {})
                for item_key, item_value in value.items():
                    projected["inventory"].setdefault(str(item_key), deepcopy(item_value))
                evidence.setdefault("inventory", (chapter, path))
            elif canonical == "quest" and isinstance(value, Mapping):
                projected.setdefault("quest", {})
                for quest_key, quest_value in value.items():
                    if str(quest_key) != "active":
                        projected["quest"].setdefault(str(quest_key), deepcopy(quest_value))
                evidence.setdefault("quest", (chapter, path))
            else:
                projected.setdefault(canonical, deepcopy(value))
                evidence.setdefault(canonical, (chapter, path))

    for canonical, raw_value in projected.items():
        chapter, path = evidence.get(canonical, (0, "progression_ledger"))
        if canonical == "inventory" and isinstance(raw_value, Mapping):
            for resource_key, raw_item in raw_value.items():
                value, metadata = _historical_scalar(raw_item, "inventory")
                metadata.update(
                    {
                        "authority_source": "progression_ledger",
                        "authority_path": path,
                    }
                )
                _add_projected_entry(
                    entries,
                    category="inventory",
                    resource_key=str(resource_key),
                    value=value,
                    chapter=int(chapter or 0),
                    metadata=metadata,
                )
        elif canonical == "quest" and isinstance(raw_value, Mapping):
            for resource_key, raw_quest in raw_value.items():
                value, metadata = _quest_scalar(raw_quest)
                metadata.update(
                    {
                        "authority_source": "progression_ledger",
                        "authority_path": path,
                    }
                )
                _add_projected_entry(
                    entries,
                    category="quest",
                    resource_key=str(resource_key),
                    value=value,
                    chapter=int(chapter or 0),
                    metadata=metadata,
                )
        else:
            category = canonical
            value, metadata = _historical_scalar(raw_value, category)
            lookup_keys = [canonical]
            if canonical == "currency":
                lookup_keys.extend(["game_currency", "money", "金币", "灵石", "铜币", "银两"])
            elif canonical == "experience":
                lookup_keys.extend(["exp", "经验", "经验值"])
            elif canonical == "level":
                lookup_keys.extend(["等级", "character_level"])
            metadata.update(
                {
                    "authority_source": "progression_ledger",
                    "authority_path": path,
                    "lookup_keys": lookup_keys,
                }
            )
            _add_projected_entry(
                entries,
                category=category,
                resource_key=canonical,
                value=value,
                chapter=int(chapter or 0),
                metadata=metadata,
            )


def _project_equipment_entries(
    story: Mapping[str, Any],
    *,
    as_of_chapter: int,
    entries: dict[str, FactResourceEntry],
) -> None:
    cards = story.get("equipment_cards")
    if not isinstance(cards, Sequence) or isinstance(cards, (str, bytes, bytearray)):
        return
    mutable_fields = {"current_owner", "owner", "current_location", "durability", "status", "equipped"}
    for raw_card in cards:
        card = _plain_payload(raw_card)
        name = _text(card.get("name"))
        identifier = _text(card.get("id")) or name
        if not name and not identifier:
            continue
        events = _adapter_events(
            card,
            keys=(
                "baseline",
                "initial",
                "initial_state",
                "history",
                "state_history",
                "state_changes",
                "changes",
                "snapshots",
                "events",
            ),
        )
        first = _adapter_chapter(card.get("first_appearance_chapter"))
        if first is None:
            first = min((chapter for chapter, _, _, _ in events if chapter > 0), default=None)
        if first is None or first > as_of_chapter:
            continue
        bounded: dict[str, tuple[Any, int, str]] = {}
        for chapter, sequence, values, source in sorted(events, key=lambda item: (item[0], item[1])):
            del sequence
            if chapter > as_of_chapter:
                continue
            for field, value in values.items():
                if field in mutable_fields and value not in (None, ""):
                    canonical = "current_owner" if field == "owner" else field
                    bounded[canonical] = (deepcopy(value), chapter, source)
        last_update = _adapter_chapter(card.get("last_update_chapter"))
        if last_update is not None and last_update <= as_of_chapter:
            for field in mutable_fields - {"owner"}:
                if field not in bounded and card.get(field) not in (None, ""):
                    bounded[field] = (deepcopy(card[field]), last_update, "equipment_cards.current")
        owner = bounded.get("current_owner")
        if owner is not None:
            owner_value, chapter, source = owner
            metadata = {
                "authority_source": "equipment_cards",
                "authority_path": f"equipment_cards.{identifier}.{source}.current_owner",
                "lookup_keys": [name, identifier],
            }
            _add_projected_entry(
                entries,
                category="equipment_owner",
                resource_key=name or identifier,
                value=owner_value,
                owner=str(owner_value),
                chapter=chapter,
                metadata=metadata,
            )
        equipped = bounded.get("equipped")
        if equipped is None:
            status = bounded.get("status")
            if status is not None and _canonical_text(status[0]) in {
                "已装备",
                "装备中",
                "装备着",
                "equipped",
            }:
                equipped = (True, status[1], status[2])
            elif status is not None and _canonical_text(status[0]) in {
                "未装备",
                "没有装备",
                "unequipped",
            }:
                equipped = (False, status[1], status[2])
        if equipped is not None:
            value, chapter, source = equipped
            if isinstance(value, str):
                value = _canonical_text(value) in {"true", "yes", "已装备", "装备中", "装备着", "equipped"}
            _add_projected_entry(
                entries,
                category="equipment_state",
                resource_key=name or identifier,
                value=bool(value),
                owner=str(owner[0]) if owner is not None else "",
                chapter=chapter,
                metadata={
                    "equipped": bool(value),
                    "authority_source": "equipment_cards",
                    "authority_path": f"equipment_cards.{identifier}.{source}.equipped",
                    "lookup_keys": [name, identifier],
                },
            )


def _project_relationship_entries(
    story: Mapping[str, Any],
    *,
    as_of_chapter: int,
    entries: dict[str, FactResourceEntry],
) -> None:
    graph = story.get("relationship_graph")
    if not isinstance(graph, Sequence) or isinstance(graph, (str, bytes, bytearray)):
        return
    for raw_edge in graph:
        edge = _plain_payload(raw_edge)
        source = _text(edge.get("source"))
        target = _text(edge.get("target"))
        if not source or not target:
            continue
        first = _adapter_chapter(edge.get("first_chapter"), default=0) or 0
        if first > as_of_chapter:
            continue
        values: dict[str, tuple[Any, int, str]] = {}
        for index, raw_change in enumerate(_adapter_event_list(edge.get("changes"))):
            chapter = _adapter_chapter(
                raw_change.get("chapter", raw_change.get("chapter_number", raw_change.get("as_of_chapter")))
            )
            if chapter is None or chapter > as_of_chapter:
                continue
            for field in ("trust", "tension"):
                if raw_change.get(field) not in (None, ""):
                    values[field] = (
                        raw_change[field],
                        chapter,
                        f"relationship_graph.{edge.get('id') or source + ':' + target}.changes.{index}.{field}",
                    )
        if not values:
            last_changed = _adapter_chapter(edge.get("last_changed_chapter"), default=0) or 0
            if last_changed and last_changed <= as_of_chapter:
                for field in ("trust", "tension"):
                    if edge.get(field) not in (None, ""):
                        values[field] = (
                            edge[field],
                            last_changed,
                            f"relationship_graph.{edge.get('id') or source + ':' + target}.{field}",
                        )
        subject = target if source else source
        for field, (value, chapter, path) in values.items():
            category = "relationship_numeric"
            lookup_keys = [field]
            if field == "trust":
                lookup_keys.extend(["信任值", "好感度", "favorability"])
            else:
                lookup_keys.extend(["紧张度", "tension"])
            _add_projected_entry(
                entries,
                category=category,
                subject=subject,
                resource_key=field,
                value=value,
                chapter=chapter,
                metadata={
                    "authority_source": "relationship_graph.changes",
                    "authority_path": path,
                    "lookup_keys": lookup_keys,
                    "relationship_id": edge.get("id") or f"{source}:{target}",
                },
            )


def _project_fact_resource_snapshot(
    story: Mapping[str, Any],
    *,
    generic_ledger: FactResourceLedger | None,
    as_of_chapter: int | None,
) -> FactResourceSnapshot:
    target = _target_chapter(story, as_of_chapter)
    entries: dict[str, FactResourceEntry] = {}
    findings: list[FactResourceFinding] = []
    authorities: list[FactResourceAuthority] = []
    progression_categories = _progression_authority_categories(story)
    if progression_categories:
        authorities.append(
            FactResourceAuthority(
                group="progression",
                categories=sorted(progression_categories),
                source="progression_ledger",
                writable=False,
                reason="existing progression/game history is the sole authority",
            )
        )
        _project_progression_entries(story, as_of_chapter=target, entries=entries)
    cards = story.get("equipment_cards")
    if isinstance(cards, Sequence) and not isinstance(cards, (str, bytes, bytearray)) and any(
        isinstance(item, Mapping) for item in cards
    ):
        authorities.append(
            FactResourceAuthority(
                group="equipment_cards",
                categories=["equipment_owner", "equipment_state"],
                source="equipment_cards.history",
                writable=False,
                reason="equipment card history is the sole owner/state authority",
            )
        )
        _project_equipment_entries(story, as_of_chapter=target, entries=entries)
    graph = story.get("relationship_graph")
    if isinstance(graph, Sequence) and not isinstance(graph, (str, bytes, bytearray)) and any(
        isinstance(item, Mapping) for item in graph
    ):
        authorities.append(
            FactResourceAuthority(
                group="relationship_graph",
                categories=["relationship_numeric"],
                source="relationship_graph.changes",
                writable=False,
                reason="relationship graph changes are the sole numeric relationship authority",
            )
        )
        _project_relationship_entries(story, as_of_chapter=target, entries=entries)

    if generic_ledger is not None:
        generic = generic_ledger.replay(as_of_chapter=target)
        active_groups = {item.group for item in authorities if item.active}
        for entry in generic.entries:
            group = fact_resource_authority_group(entry.category)
            if group in active_groups:
                findings.append(
                    FactResourceFinding(
                        code="DUPLICATE_AUTHORITY_SHADOW",
                        severity="warning",
                        message=(
                            f"{entry.resource_key} 的通用账本历史被 {group} 投影遮蔽；"
                            "它不是项目的官方答案。"
                        ),
                        fact_id=entry.fact_id,
                        category=entry.category,
                        resource_key=entry.resource_key,
                        chapter=entry.updated_chapter,
                    )
                )
                continue
            entry.metadata = {
                **entry.metadata,
                "authority_source": "fact_resource_ledger",
                "authority_path": "story-system/fact-resource-ledger.json",
            }
            entries.setdefault(entry.fact_id, entry)
        findings.extend(generic.findings)

    materialized = sorted(
        entries.values(),
        key=lambda item: (item.category, item.subject, item.resource_key, item.fact_id),
    )
    return FactResourceSnapshot(
        as_of_chapter=target,
        known=bool(materialized or authorities or generic_ledger is not None),
        source="project_fact_resource_projection" if authorities else "fact_resource_ledger",
        entries=materialized,
        findings=findings,
        authorities=authorities,
    )


def project_fact_resource_snapshot(
    source: Any,
    *,
    as_of_chapter: int | None = None,
    generic_ledger: FactResourceLedger | None = None,
) -> FactResourceSnapshot:
    """Project existing structured authorities and the generic ledger.

    This is the single read boundary used by the writer and by candidate
    validation.  Existing authorities win deterministically; shadow entries
    in a legacy generic file are surfaced as warnings and never returned as
    official entries.
    """

    story = _story_payload(source)
    raw_ledger = story.get("fact_resource_ledger") or story.get("initial_fact_resource_ledger")
    if generic_ledger is None and raw_ledger:
        try:
            generic_ledger = _coerce_ledger(raw_ledger)
        except Exception:
            generic_ledger = None
    if generic_ledger is None and isinstance(source, (str, Path)):
        root = Path(source)
        ledger_path = root / ".story-system" / "fact-resource-ledger.json" if root.is_dir() else root
        generic_ledger = FactResourceLedger.load(ledger_path)
    return _project_fact_resource_snapshot(
        story,
        generic_ledger=generic_ledger,
        as_of_chapter=as_of_chapter,
    )


def fact_resource_authority_findings(
    snapshot: FactResourceSnapshot,
    extraction: FactResourceExtraction,
) -> list[FactResourceFinding]:
    """Return blocking writes that would create a second history."""

    findings: list[FactResourceFinding] = []
    for delta in extraction.deltas:
        authority = snapshot.authority_for(delta.category)
        if authority is None:
            continue
        findings.append(
            FactResourceFinding(
                code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
                severity="error",
                message=(
                    f"{delta.resource_key} 属于 {authority.source}；"
                    "当前确认路径没有类型化写入器，不能追加到通用事实账本。"
                ),
                delta_id=delta.delta_id,
                fact_id=delta.fact_id,
                category=delta.category,
                resource_key=delta.resource_key,
                evidence=delta.evidence,
                chapter=delta.chapter,
            )
        )
    return findings


# ---------------------------------------------------------------------------
# Explicit authoritative write adapters


_AUTHORITY_EVENT_KEYS = (
    "history",
    "state_history",
    "state_changes",
    "progression_history",
    "level_history",
    "changes",
    "snapshots",
    "events",
)
_EQUIPMENT_EVENT_KEYS = (
    "history",
    "state_history",
    "state_changes",
    "changes",
    "snapshots",
    "events",
)


@dataclass(frozen=True)
class FactResourceAuthorityWrite:
    """One planned write to an existing structured authority.

    ``storage`` and ``path`` identify the raw JSON payload that owns the
    event.  The path is resolved again against staged payloads during apply,
    so planning never mutates the project and a failed apply can be discarded
    without repairing partially changed caller objects.
    """

    group: str
    storage: str
    path: tuple[str | int, ...]
    delta: FactResourceDelta
    authority_source: str


@dataclass(frozen=True)
class FactResourceAuthorityWritePlan:
    """Validated dispatch plan for generic and authoritative fact writes."""

    chapter_number: int
    candidate_id: str
    start_snapshot: FactResourceSnapshot
    extraction: FactResourceExtraction
    validation: FactResourceValidation
    authority_writes: tuple[FactResourceAuthorityWrite, ...] = ()
    generic_deltas: tuple[FactResourceDelta, ...] = ()
    generic_assertions: tuple[FactResourceAssertion, ...] = ()
    findings: tuple[FactResourceFinding, ...] = ()

    @property
    def blocking_findings(self) -> list[FactResourceFinding]:
        return [item for item in self.findings if item.severity == "error"]


def _authority_mapping_at(
    payload: Mapping[str, Any],
    path: Sequence[str | int],
) -> Any:
    current: Any = payload
    for part in path:
        if isinstance(part, int):
            if not isinstance(current, Sequence) or isinstance(current, (str, bytes, bytearray)):
                return None
            if part < 0 or part >= len(current):
                return None
            current = current[part]
        else:
            if not isinstance(current, Mapping) or part not in current:
                return None
            current = current[part]
    return current


def _authority_projection_story(
    state: Mapping[str, Any] | None,
    project: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """Combine raw state/project mirrors for the read-side projection.

    The file project keeps runtime values in ``state.json`` and several world
    authorities in ``project.json``.  The merge is only for planning; writes
    still use the explicitly selected raw storage path and never write both
    histories as independent events.
    """

    raw_state = dict(state) if isinstance(state, Mapping) else {}
    raw_project = dict(project) if isinstance(project, Mapping) else {}
    story = deepcopy(raw_project)
    for key, value in raw_state.items():
        if key not in story or story.get(key) in (None, "", [], {}):
            story[key] = deepcopy(value)
    for key in (
        "characters",
        "progression_ledger",
        "equipment_cards",
        "relationship_graph",
        "current_chapter",
        "latest_chapter",
        "last_written_chapter",
    ):
        if raw_state.get(key) not in (None, "", [], {}):
            story[key] = deepcopy(raw_state[key])
    blueprint = raw_project.get("world_blueprint")
    if isinstance(blueprint, Mapping):
        for key in (
            "progression_ledger",
            "equipment_cards",
            "relationship_graph",
        ):
            if story.get(key) in (None, "", [], {}) and blueprint.get(key) not in (None, "", [], {}):
                story[key] = deepcopy(blueprint[key])
    if not story.get("characters") and isinstance(story.get("character_profiles"), list):
        story["characters"] = deepcopy(story["character_profiles"])
    return story


def _is_protagonist_payload(character: Mapping[str, Any]) -> bool:
    return _canonical_text(character.get("role")) in {"protagonist", "主角"} or _canonical_text(
        character.get("character_tier")
    ) in {"protagonist", "主角"}


def _progression_category(category: str) -> str:
    canonical = _canonical_text(category)
    if canonical in {"item", "resource", "stackable"}:
        return "inventory"
    return _PROGRESSION_FIELD_ALIASES.get(canonical, canonical)


def _contains_progression_category(value: Any, category: str) -> bool:
    wanted = _progression_category(category)
    if isinstance(value, Mapping):
        return any(
            _PROGRESSION_FIELD_ALIASES.get(_canonical_text(key)) == wanted
            for key in _walk_keys(value)
        )
    return False


def _progression_location(
    state: Mapping[str, Any],
    project: Mapping[str, Any],
    delta: FactResourceDelta,
) -> tuple[str, tuple[str | int, ...]] | None:
    category = _progression_category(delta.category)
    candidates: list[tuple[str, Mapping[str, Any], tuple[str | int, ...]]] = []
    for storage, payload in (("state", state), ("project", project)):
        if not isinstance(payload, Mapping):
            continue
        candidates.append((storage, payload, ("progression_ledger",)))
        blueprint = payload.get("world_blueprint")
        if isinstance(blueprint, Mapping):
            candidates.append((storage, payload, ("world_blueprint", "progression_ledger")))
    for storage, payload, path in candidates:
        value = _authority_mapping_at(payload, path)
        if isinstance(value, Mapping) and _contains_progression_category(value, category):
            return storage, path

    for storage, payload in (("state", state), ("project", project)):
        characters = payload.get("characters")
        character_key = "characters"
        if not isinstance(characters, list):
            characters = payload.get("character_profiles")
            character_key = "character_profiles"
        if not isinstance(characters, list):
            continue
        for index, character in enumerate(characters):
            if not isinstance(character, Mapping) or not _is_protagonist_payload(character):
                continue
            for namespace in ("game_state", "progression"):
                value = character.get(namespace)
                if isinstance(value, Mapping) and _contains_progression_category(value, category):
                    return storage, (character_key, index, namespace)
    return None


def _equipment_aliases(card: Mapping[str, Any]) -> set[str]:
    raw_aliases = card.get("aliases")
    if isinstance(raw_aliases, str):
        aliases: Sequence[Any] = [raw_aliases]
    elif isinstance(raw_aliases, Sequence) and not isinstance(raw_aliases, (bytes, bytearray)):
        aliases = raw_aliases
    else:
        aliases = []
    return {
        _canonical_text(item)
        for item in [card.get("id"), card.get("name"), *aliases]
        if _canonical_text(item)
    }


def _equipment_match_indices(cards: Any, delta: FactResourceDelta) -> list[int]:
    if not isinstance(cards, list):
        return []
    wanted = {_canonical_text(delta.resource_key)}
    lookup_keys = delta.metadata.get("lookup_keys") if isinstance(delta.metadata, Mapping) else None
    if isinstance(lookup_keys, list):
        wanted.update(_canonical_text(item) for item in lookup_keys if _canonical_text(item))
    return [
        index
        for index, card in enumerate(cards)
        if isinstance(card, Mapping) and _equipment_aliases(card) & wanted
    ]


def _equipment_location(
    state: Mapping[str, Any],
    project: Mapping[str, Any],
    delta: FactResourceDelta,
) -> tuple[str, tuple[str | int, ...]] | None:
    candidates: list[tuple[str, Mapping[str, Any], tuple[str | int, ...]]] = []
    for storage, payload in (("state", state), ("project", project)):
        if not isinstance(payload, Mapping):
            continue
        candidates.append((storage, payload, ("equipment_cards",)))
        blueprint = payload.get("world_blueprint")
        if isinstance(blueprint, Mapping):
            candidates.append((storage, payload, ("world_blueprint", "equipment_cards")))
    for storage, payload, path in candidates:
        cards = _authority_mapping_at(payload, path)
        matches = _equipment_match_indices(cards, delta)
        if len(matches) == 1:
            return storage, path
        if len(matches) > 1:
            return None
    return None


def _protagonist_names(*payloads: Mapping[str, Any]) -> set[str]:
    names: set[str] = set()
    for payload in payloads:
        characters = payload.get("characters")
        if not isinstance(characters, list):
            characters = payload.get("character_profiles")
        if not isinstance(characters, list):
            continue
        for character in characters:
            if isinstance(character, Mapping) and _is_protagonist_payload(character):
                name = _text(character.get("name"))
                if name:
                    names.add(name)
    return names


def _relationship_metric(delta: FactResourceDelta) -> str:
    value = _canonical_text(delta.resource_key)
    if value in {"tension", "紧张度"} or _canonical_text(delta.category) == "tension":
        return "tension"
    return "trust"


def _relationship_match_indices(
    edges: Any,
    delta: FactResourceDelta,
    protagonist_names: set[str],
) -> list[int]:
    if not isinstance(edges, list):
        return []
    relation_id = ""
    if isinstance(delta.metadata, Mapping):
        relation_id = _text(delta.metadata.get("relationship_id"))
    if relation_id:
        return [
            index
            for index, edge in enumerate(edges)
            if isinstance(edge, Mapping) and _text(edge.get("id")) == relation_id
        ]
    subject = _text(delta.subject)
    matches: list[int] = []
    for index, edge in enumerate(edges):
        if not isinstance(edge, Mapping):
            continue
        source, target = _text(edge.get("source")), _text(edge.get("target"))
        if subject and subject not in {source, target}:
            continue
        if not subject and protagonist_names and not ({source, target} & protagonist_names):
            continue
        matches.append(index)
    return matches


def _relationship_location(
    state: Mapping[str, Any],
    project: Mapping[str, Any],
    delta: FactResourceDelta,
) -> tuple[str, tuple[str | int, ...]] | None:
    protagonist_names = _protagonist_names(state, project)
    candidates: list[tuple[str, Mapping[str, Any], tuple[str | int, ...]]] = []
    # The project graph is the normal world-level authority.  A state graph is
    # supported for imported/legacy projects that have not split the mirrors.
    for storage, payload in (("project", project), ("state", state)):
        if not isinstance(payload, Mapping):
            continue
        candidates.append((storage, payload, ("relationship_graph",)))
        blueprint = payload.get("world_blueprint")
        if isinstance(blueprint, Mapping):
            candidates.append((storage, payload, ("world_blueprint", "relationship_graph")))
    for storage, payload, path in candidates:
        edges = _authority_mapping_at(payload, path)
        matches = _relationship_match_indices(edges, delta, protagonist_names)
        if len(matches) == 1:
            return storage, path
        if len(matches) > 1:
            return None
    return None


def _authority_location(
    state: Mapping[str, Any],
    project: Mapping[str, Any],
    delta: FactResourceDelta,
    group: str,
) -> tuple[str, tuple[str | int, ...]] | None:
    if group == "progression":
        return _progression_location(state, project, delta)
    if group == "equipment_cards":
        return _equipment_location(state, project, delta)
    if group == "relationship_graph":
        return _relationship_location(state, project, delta)
    return None


def _authority_next_value(delta: FactResourceDelta) -> Any:
    if delta.operation in {"TRANSFER", "EQUIP", "UNEQUIP"}:
        return None
    if delta.after is not None:
        return deepcopy(delta.after)
    if delta.operation in {"SET", "PROGRESS_SET"}:
        return deepcopy(delta.change)
    before = _number(delta.before)
    change = _number(delta.change)
    if before is None or change is None:
        return None
    return before + (abs(change) if delta.operation in {"ADD", "PROGRESS_ADD"} else -abs(change))


def _authority_numeric_error(delta: FactResourceDelta, message: str) -> FactResourceFinding:
    return FactResourceFinding(
        code="INVALID_RESOURCE_DELTA",
        severity="error",
        message=message,
        delta_id=delta.delta_id,
        fact_id=delta.fact_id,
        category=delta.category,
        resource_key=delta.resource_key,
        evidence=delta.evidence,
        chapter=delta.chapter,
    )


def _authority_event_shape_finding(
    state: Mapping[str, Any],
    project: Mapping[str, Any],
    write: FactResourceAuthorityWrite,
) -> FactResourceFinding | None:
    """Reject an authority path whose existing history is not append-safe.

    A missing history key is intentionally allowed: the adapter can create the
    first event in an otherwise structured authority.  An existing key with a
    scalar/list-of-scalars shape is different; silently replacing it would
    destroy legacy history, so it remains an explicit reconciliation case.
    """

    payload = state if write.storage == "state" else project
    raw = _authority_mapping_at(payload, write.path)
    if write.group == "progression" and not isinstance(raw, Mapping):
        return FactResourceFinding(
            code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
            severity="error",
            message=f"{write.authority_source} 的结构化目标不存在或不是对象。",
            delta_id=write.delta.delta_id,
            fact_id=write.delta.fact_id,
            category=write.delta.category,
            resource_key=write.delta.resource_key,
            evidence=write.delta.evidence,
            chapter=write.delta.chapter,
        )

    target: Mapping[str, Any]
    if write.group == "progression":
        target = raw
    else:
        target = {}
    if write.group == "progression" and not (write.path and write.path[-1] == "game_state"):
        candidate = raw.get("protagonist")
        if isinstance(candidate, Mapping) and (
            any(key in candidate for key in _AUTHORITY_EVENT_KEYS)
            or not any(key in raw for key in _AUTHORITY_EVENT_KEYS)
        ):
            target = candidate
    elif write.group == "equipment_cards":
        cards = raw if isinstance(raw, list) else None
        if cards is None:
            return FactResourceFinding(
                code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
                severity="error",
                message="equipment_cards 不是可追加的列表。",
                delta_id=write.delta.delta_id,
                fact_id=write.delta.fact_id,
                category=write.delta.category,
                resource_key=write.delta.resource_key,
                evidence=write.delta.evidence,
                chapter=write.delta.chapter,
            )
        matches = _equipment_match_indices(cards, write.delta)
        if len(matches) != 1 or not isinstance(cards[matches[0]], Mapping):
            return FactResourceFinding(
                code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
                severity="error",
                message=f"{write.delta.resource_key} 的装备卡没有唯一的结构化目标。",
                delta_id=write.delta.delta_id,
                fact_id=write.delta.fact_id,
                category=write.delta.category,
                resource_key=write.delta.resource_key,
                evidence=write.delta.evidence,
                chapter=write.delta.chapter,
            )
        target = cards[matches[0]]
    elif write.group == "relationship_graph":
        edges = raw if isinstance(raw, list) else None
        if edges is None:
            return FactResourceFinding(
                code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
                severity="error",
                message="relationship_graph 不是可追加的列表。",
                delta_id=write.delta.delta_id,
                fact_id=write.delta.fact_id,
                category=write.delta.category,
                resource_key=write.delta.resource_key,
                evidence=write.delta.evidence,
                chapter=write.delta.chapter,
            )
        names = _protagonist_names(state, project)
        matches = _relationship_match_indices(edges, write.delta, names)
        if len(matches) != 1 or not isinstance(edges[matches[0]], Mapping):
            return FactResourceFinding(
                code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
                severity="error",
                message=f"{write.delta.resource_key} 的关系边没有唯一的结构化目标。",
                delta_id=write.delta.delta_id,
                fact_id=write.delta.fact_id,
                category=write.delta.category,
                resource_key=write.delta.resource_key,
                evidence=write.delta.evidence,
                chapter=write.delta.chapter,
            )
        target = edges[matches[0]]

    event_keys = _EQUIPMENT_EVENT_KEYS if write.group == "equipment_cards" else _AUTHORITY_EVENT_KEYS
    selected = next((key for key in event_keys if key in target), None)
    if selected is None:
        return None
    raw_events = target.get(selected)
    if not isinstance(raw_events, list):
        return FactResourceFinding(
            code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
            severity="error",
            message=f"{write.authority_source}.{selected} 不是可安全追加的列表。",
            delta_id=write.delta.delta_id,
            fact_id=write.delta.fact_id,
            category=write.delta.category,
            resource_key=write.delta.resource_key,
            evidence=write.delta.evidence,
            chapter=write.delta.chapter,
        )
    if any(not isinstance(item, Mapping) for item in raw_events):
        return FactResourceFinding(
            code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
            severity="error",
            message=f"{write.authority_source}.{selected} 含有非对象历史事件。",
            delta_id=write.delta.delta_id,
            fact_id=write.delta.fact_id,
            category=write.delta.category,
            resource_key=write.delta.resource_key,
            evidence=write.delta.evidence,
            chapter=write.delta.chapter,
        )
    return None


def plan_fact_resource_authority_writes(
    state: Mapping[str, Any] | None,
    project: Mapping[str, Any] | None,
    extraction: FactResourceExtraction | Mapping[str, Any],
    *,
    start_snapshot: FactResourceSnapshot | None = None,
    candidate_id: str = "",
) -> FactResourceAuthorityWritePlan:
    """Validate and dispatch deltas without mutating either payload.

    Existing authorities are writable only through the explicit dispatch
    result.  A missing or malformed historical container is surfaced as a
    targeted ``EXISTING_AUTHORITY_CONFIRMATION_REQUIRED`` finding; a valid
    delta is never rejected merely because its category has an authority.
    """

    parsed = (
        extraction
        if isinstance(extraction, FactResourceExtraction)
        else FactResourceExtraction.model_validate(extraction)
    )
    raw_state = state if isinstance(state, Mapping) else {}
    raw_project = project if isinstance(project, Mapping) else {}
    story = _authority_projection_story(raw_state, raw_project)
    start = start_snapshot or project_fact_resource_snapshot(
        story,
        as_of_chapter=parsed.chapter_number - 1,
    )
    validation = validate_fact_resource_extraction(start, parsed)
    authority_writes: list[FactResourceAuthorityWrite] = []
    generic_deltas: list[FactResourceDelta] = []
    generic_assertions: list[FactResourceAssertion] = []
    findings: list[FactResourceFinding] = list(validation.findings)
    for delta in sorted(parsed.deltas, key=lambda item: (item.sequence, item.delta_id)):
        authority = start.authority_for(delta.category)
        if authority is None:
            generic_deltas.append(delta)
            continue
        location = _authority_location(raw_state, raw_project, delta, authority.group)
        if location is None:
            findings.append(
                FactResourceFinding(
                    code="EXISTING_AUTHORITY_CONFIRMATION_REQUIRED",
                    severity="error",
                    message=(
                        f"{delta.resource_key} 的 {authority.source} 没有可安全追加的结构化历史容器或唯一目标。"
                    ),
                    delta_id=delta.delta_id,
                    fact_id=delta.fact_id,
                    category=delta.category,
                    resource_key=delta.resource_key,
                    evidence=delta.evidence,
                    chapter=delta.chapter,
                )
            )
            continue
        if delta.operation in {"ADD", "SUBTRACT", "PROGRESS_ADD"} and _authority_next_value(delta) is None:
            findings.append(
                _authority_numeric_error(
                    delta,
                    f"{delta.resource_key} 属于 {authority.source}，算术变化缺少可验证的 before/after。",
                )
            )
            continue
        if authority.group == "relationship_graph":
            next_value = _number(_authority_next_value(delta))
            if next_value is None or next_value < 0 or next_value > 100:
                findings.append(
                    FactResourceFinding(
                        code="RELATIONSHIP_VALUE_MISMATCH",
                        severity="error",
                        message=f"{delta.resource_key} 的关系数值必须在 0 到 100 之间。",
                        delta_id=delta.delta_id,
                        fact_id=delta.fact_id,
                        category=delta.category,
                        resource_key=delta.resource_key,
                        evidence=delta.evidence,
                        chapter=delta.chapter,
                    )
                )
                continue
        write = FactResourceAuthorityWrite(
            group=authority.group,
            storage=location[0],
            path=location[1],
            delta=delta,
            authority_source=authority.source,
        )
        shape_finding = _authority_event_shape_finding(raw_state, raw_project, write)
        if shape_finding is not None:
            findings.append(shape_finding)
            continue
        authority_writes.append(write)
    for assertion in parsed.assertions:
        if start.authority_for(assertion.category) is None:
            generic_assertions.append(assertion)
    return FactResourceAuthorityWritePlan(
        chapter_number=parsed.chapter_number,
        candidate_id=str(candidate_id or ""),
        start_snapshot=start,
        extraction=parsed,
        validation=validation,
        authority_writes=tuple(authority_writes),
        generic_deltas=tuple(generic_deltas),
        generic_assertions=tuple(generic_assertions),
        findings=tuple(findings),
    )


def _display_number(value: Any) -> str:
    number = _number(value)
    if number is None:
        return str(value)
    return str(int(number)) if float(number).is_integer() else str(number)


def _format_authoritative_scalar(
    value: Any,
    existing: Any,
    delta: FactResourceDelta,
    category: str,
) -> Any:
    if not isinstance(existing, str):
        return value
    text = existing.strip()
    number = _display_number(value)
    lowered = _canonical_text(category)
    if lowered == "level":
        if re.match(r"lv\.?", text, flags=re.IGNORECASE):
            return f"Lv.{number}"
        if "级" in text:
            return f"{number}级"
        return number
    if lowered == "experience" and "/" in text:
        denominator = text.split("/", 1)[1].strip()
        denominator = re.sub(r"[^0-9.].*$", "", denominator)
        if denominator:
            return f"{number}/{denominator}"
    match = re.match(r"\s*[-+]?\d+(?:\.\d+)?\s*(.*)$", text)
    suffix = match.group(1).strip() if match else ""
    unit = suffix or _text(delta.unit)
    return f"{number}{unit}" if unit else number


def _mapping_candidates_for_progression(
    container: MutableMapping[str, Any],
    category: str,
    *,
    game_state: bool = False,
) -> list[MutableMapping[str, Any]]:
    result: list[MutableMapping[str, Any]] = []

    def add(value: Any) -> None:
        if isinstance(value, MutableMapping) and not any(value is item for item in result):
            result.append(value)

    if not game_state and isinstance(container.get("protagonist"), MutableMapping):
        add(container.get("protagonist"))
    if category in {"inventory", "currency"} and isinstance(container.get("economy"), MutableMapping):
        add(container.get("economy"))
    if category == "quest" and isinstance(container.get("quests"), MutableMapping):
        add(container.get("quests"))
    if game_state and isinstance(container.get("current"), MutableMapping):
        add(container.get("current"))
    add(container)
    if isinstance(container.get("current"), MutableMapping):
        add(container.get("current"))
    if isinstance(container.get("panel"), MutableMapping):
        add(container.get("panel"))
    return result


def _choose_field(mapping: Mapping[str, Any], names: Sequence[str], default: str) -> str:
    for name in names:
        if name in mapping and mapping.get(name) not in (None, "", [], {}):
            return name
    return next((name for name in names if name in mapping), default)


def _find_exact_key(mapping: Mapping[str, Any], wanted: str) -> str | None:
    needle = _canonical_text(wanted)
    for key in mapping:
        if _canonical_text(key) == needle:
            return str(key)
    return None


def _format_quest_value(value: Any, existing: Any, delta: FactResourceDelta) -> Any:
    if isinstance(existing, Mapping):
        result = deepcopy(dict(existing))
        field = "progress" if "progress" in result else "value" if "value" in result else "progress"
        result[field] = value
        target = _number(result.get("target")) or _number(delta.metadata.get("target"))
        if target is not None:
            result.setdefault("target", target)
            if isinstance(result.get("status"), str) and "/" in result["status"]:
                result["status"] = f"{_display_number(value)}/{_display_number(target)}"
        return result
    if isinstance(existing, str):
        match = re.search(r"/\s*(\d+)", existing)
        target = match.group(1) if match else _display_number(delta.metadata.get("target")) if delta.metadata.get("target") is not None else ""
        return f"{_display_number(value)}/{target}" if target else _display_number(value)
    return value


def _update_progression_value(
    container: MutableMapping[str, Any],
    delta: FactResourceDelta,
    *,
    game_state: bool = False,
) -> dict[str, Any]:
    category = _progression_category(delta.category)
    candidates = _mapping_candidates_for_progression(container, category, game_state=game_state)
    next_value = _authority_next_value(delta)
    if category in {"level", "experience", "currency"} and next_value is None:
        raise ValueError("existing_authority_confirmation_required:authoritative_scalar_unavailable")
    if category in {"level", "experience"}:
        names = ("level", "character_level") if category == "level" else ("experience", "exp", "character_exp")
        target = candidates[0] if candidates else container
        field = _choose_field(target, names, names[0])
        formatted = _format_authoritative_scalar(next_value, target.get(field), delta, category)
        target[field] = deepcopy(formatted)
        # Existing panels/current mirrors are presentation surfaces, not a
        # second history.  Update them only when they already exist.
        for mirror in candidates[1:]:
            if any(name in mirror for name in names):
                mirror[_choose_field(mirror, names, names[0])] = deepcopy(
                    _format_authoritative_scalar(next_value, mirror.get(_choose_field(mirror, names, names[0])), delta, category)
                )
        return {category: deepcopy(formatted)}
    if category == "currency":
        target = next(
            (item for item in candidates if any(name in item for name in ("game_currency", "currency", "money"))),
            candidates[0] if candidates else container,
        )
        field = _choose_field(target, ("game_currency", "currency", "money"), "game_currency")
        formatted = _format_authoritative_scalar(next_value, target.get(field), delta, category)
        target[field] = deepcopy(formatted)
        return {"currency": deepcopy(formatted)}
    if category == "inventory":
        target = next(
            (item for item in candidates if any(isinstance(item.get(name), MutableMapping) for name in ("inventory", "items", "backpack"))),
            candidates[0] if candidates else container,
        )
        field = _choose_field(target, ("inventory", "items", "backpack"), "inventory")
        inventory = target.get(field)
        if not isinstance(inventory, MutableMapping):
            inventory = {}
            target[field] = inventory
        key = _find_exact_key(inventory, delta.resource_key) or _text(delta.resource_key)
        if not key:
            raise ValueError("existing_authority_confirmation_required:inventory_key_unavailable")
        existing = inventory.get(key)
        inventory[key] = deepcopy(_format_authoritative_scalar(next_value, existing, delta, category))
        return {"inventory": deepcopy(dict(inventory))}
    if category == "quest":
        target = next(
            (item for item in candidates if isinstance(item.get("quests"), MutableMapping)),
            candidates[0] if candidates else container,
        )
        field = "quests" if isinstance(target.get("quests"), MutableMapping) else "quests"
        quests = target.get(field)
        if not isinstance(quests, MutableMapping):
            quests = {}
            target[field] = quests
        key = _find_exact_key(quests, delta.resource_key) or _text(delta.resource_key)
        if not key:
            raise ValueError("existing_authority_confirmation_required:quest_key_unavailable")
        quests[key] = _format_quest_value(next_value, quests.get(key), delta)
        return {"quests": deepcopy(dict(quests))}
    raise ValueError(f"existing_authority_confirmation_required:unsupported_progression_category:{delta.category}")


def _progression_event_container(
    container: MutableMapping[str, Any],
) -> MutableMapping[str, Any]:
    protagonist = container.get("protagonist")
    if isinstance(protagonist, MutableMapping):
        if any(key in protagonist for key in _AUTHORITY_EVENT_KEYS) or not any(
            key in container for key in _AUTHORITY_EVENT_KEYS
        ):
            return protagonist
    return container


def _event_list_for_write(
    container: MutableMapping[str, Any],
    keys: Sequence[str],
) -> list[MutableMapping[str, Any]]:
    selected = next((key for key in keys if key in container), None)
    if selected is None:
        selected = keys[0]
        container[selected] = []
    raw = container.get(selected)
    if not isinstance(raw, list):
        raise ValueError("existing_authority_confirmation_required:historical_container_not_list")
    if any(not isinstance(item, MutableMapping) for item in raw):
        raise ValueError("existing_authority_confirmation_required:historical_event_not_mapping")
    return raw


def _event_has_delta(events: Sequence[Mapping[str, Any]], delta: FactResourceDelta) -> bool:
    for event in events:
        if _text(event.get("fact_resource_delta_id")) == delta.delta_id:
            return True
        metadata = event.get("metadata")
        if isinstance(metadata, Mapping) and _text(metadata.get("fact_resource_delta_id")) == delta.delta_id:
            return True
    return False


def _sort_authority_events(events: list[MutableMapping[str, Any]]) -> None:
    """Keep appended authority history deterministic by chapter and id."""

    events.sort(
        key=lambda item: (
            _adapter_chapter(
                item.get("chapter", item.get("chapter_number", item.get("as_of_chapter"))),
                default=0,
            )
            or 0,
            _text(item.get("fact_resource_delta_id") or item.get("summary")),
        )
    )


def _apply_progression_write(
    payload: MutableMapping[str, Any],
    write: FactResourceAuthorityWrite,
    *,
    candidate_id: str,
) -> bool:
    raw_container = _authority_mapping_at(payload, write.path)
    if not isinstance(raw_container, MutableMapping):
        raise ValueError("existing_authority_confirmation_required:progression_container_unavailable")
    is_game_state = bool(write.path and write.path[-1] == "game_state")
    values = _update_progression_value(raw_container, write.delta, game_state=is_game_state)
    event_container = raw_container if is_game_state else _progression_event_container(raw_container)
    events = _event_list_for_write(event_container, _AUTHORITY_EVENT_KEYS)
    already = _event_has_delta(events, write.delta)
    if not already:
        events.append(
            {
                "chapter": write.delta.chapter,
                "current": values,
                "fact_resource_delta_id": write.delta.delta_id,
                "candidate_id": candidate_id,
                "operation": write.delta.operation,
                "evidence": write.delta.evidence,
            }
        )
        _sort_authority_events(events)
    return not already


def _update_progression_mirror(
    mapping: MutableMapping[str, Any],
    delta: FactResourceDelta,
) -> None:
    try:
        _update_progression_value(mapping, delta, game_state=True)
    except ValueError:
        # A presentation mirror may omit the field that is authoritative in
        # the ledger.  It must not make an otherwise valid authority commit
        # fail; the historical source was already updated above.
        return


def _sync_progression_mirrors(
    state: MutableMapping[str, Any],
    project: MutableMapping[str, Any],
    delta: FactResourceDelta,
) -> None:
    for payload in (state, project):
        for key in ("characters", "character_profiles"):
            characters = payload.get(key)
            if not isinstance(characters, list):
                continue
            for character in characters:
                if not isinstance(character, MutableMapping) or not _is_protagonist_payload(character):
                    continue
                game_state = character.get("game_state")
                if isinstance(game_state, MutableMapping):
                    _update_progression_mirror(game_state, delta)
                panel = character.get("game_panel")
                if isinstance(panel, MutableMapping) and _progression_category(delta.category) in {"level", "experience"}:
                    _update_progression_mirror(panel, delta)


def _equipment_event_payload(
    card: MutableMapping[str, Any],
    delta: FactResourceDelta,
    *,
    candidate_id: str,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "chapter": delta.chapter,
        "fact_resource_delta_id": delta.delta_id,
        "candidate_id": candidate_id,
        "operation": delta.operation,
        "evidence": delta.evidence,
    }
    if delta.operation == "TRANSFER":
        owner = delta.to_owner or delta.owner
        if not owner:
            raise ValueError("existing_authority_confirmation_required:equipment_owner_unavailable")
        payload["current_owner"] = owner
    elif delta.operation in {"EQUIP", "UNEQUIP"}:
        equipped = delta.equipped if delta.equipped is not None else delta.operation == "EQUIP"
        payload["equipped"] = bool(equipped)
        payload["status"] = "已装备" if equipped else "未装备"
        owner = delta.owner or _text(card.get("current_owner"))
        if owner:
            payload["current_owner"] = owner
    else:
        raise ValueError(f"existing_authority_confirmation_required:unsupported_equipment_operation:{delta.operation}")
    return payload


def _apply_equipment_write(
    payload: MutableMapping[str, Any],
    write: FactResourceAuthorityWrite,
    *,
    candidate_id: str,
) -> bool:
    cards = _authority_mapping_at(payload, write.path)
    if not isinstance(cards, list):
        raise ValueError("existing_authority_confirmation_required:equipment_cards_not_list")
    matches = _equipment_match_indices(cards, write.delta)
    if len(matches) != 1:
        raise ValueError("existing_authority_confirmation_required:equipment_target_not_unique")
    card = cards[matches[0]]
    if not isinstance(card, MutableMapping):
        raise ValueError("existing_authority_confirmation_required:equipment_card_not_mapping")
    event = _equipment_event_payload(card, write.delta, candidate_id=candidate_id)
    events = _event_list_for_write(card, _EQUIPMENT_EVENT_KEYS)
    already = _event_has_delta(events, write.delta)
    if not already:
        events.append(event)
        _sort_authority_events(events)
    if write.delta.operation == "TRANSFER":
        card["current_owner"] = event["current_owner"]
    else:
        card["equipped"] = event["equipped"]
        card["status"] = event["status"]
        if event.get("current_owner"):
            card["current_owner"] = event["current_owner"]
    current_last = _adapter_chapter(card.get("last_update_chapter"), default=0) or 0
    card["last_update_chapter"] = max(current_last, write.delta.chapter)
    return not already


def _relationship_event_summary(delta: FactResourceDelta) -> str:
    evidence = _text(delta.evidence).replace("\n", " ")
    suffix = f" {evidence}" if evidence else ""
    return f"事实资源[{delta.delta_id}]{suffix}"[:500]


def _apply_relationship_write(
    payload: MutableMapping[str, Any],
    write: FactResourceAuthorityWrite,
) -> bool:
    edges = _authority_mapping_at(payload, write.path)
    if not isinstance(edges, list):
        raise ValueError("existing_authority_confirmation_required:relationship_graph_not_list")
    protagonist_names = _protagonist_names(payload)
    matches = _relationship_match_indices(edges, write.delta, protagonist_names)
    if len(matches) != 1:
        raise ValueError("existing_authority_confirmation_required:relationship_target_not_unique")
    edge = edges[matches[0]]
    if not isinstance(edge, MutableMapping):
        raise ValueError("existing_authority_confirmation_required:relationship_edge_not_mapping")
    changes = edge.get("changes")
    if changes is None:
        changes = []
        edge["changes"] = changes
    if not isinstance(changes, list) or any(not isinstance(item, MutableMapping) for item in changes):
        raise ValueError("existing_authority_confirmation_required:relationship_changes_not_list")
    summary = _relationship_event_summary(write.delta)
    already = any(
        summary == _text(item.get("summary")) or write.delta.delta_id in _text(item.get("summary"))
        for item in changes
    )
    metric = _relationship_metric(write.delta)
    next_value = _number(_authority_next_value(write.delta))
    if next_value is None or next_value < 0 or next_value > 100:
        raise ValueError("fact_resource_validation_failed:RELATIONSHIP_VALUE_MISMATCH")
    event = {
        "chapter_number": write.delta.chapter,
        "summary": summary,
        metric: next_value,
    }
    if not already:
        changes.append(event)
        _sort_authority_events(changes)
    edge[metric] = next_value
    current_last = _adapter_chapter(edge.get("last_changed_chapter"), default=0) or 0
    edge["last_changed_chapter"] = max(current_last, write.delta.chapter)
    return not already


def apply_fact_resource_authority_writes(
    state: MutableMapping[str, Any],
    project: MutableMapping[str, Any],
    plan: FactResourceAuthorityWritePlan,
) -> dict[str, Any]:
    """Apply one validated plan to staged raw payloads.

    The caller owns persistence and transaction rollback.  This function also
    stages both mappings locally and commits them to the caller only after all
    adapter operations succeed, so an unsupported legacy shape cannot leave a
    partially changed in-memory payload behind.
    """

    blocking = plan.blocking_findings
    if blocking:
        unsupported = [
            item
            for item in blocking
            if item.code == "EXISTING_AUTHORITY_CONFIRMATION_REQUIRED"
        ]
        if unsupported:
            raise ValueError(
                "existing_authority_confirmation_required:"
                + ",".join(item.category or item.resource_key for item in unsupported)
            )
        raise ValueError(
            "fact_resource_validation_failed:" + ",".join(item.code for item in blocking)
        )
    if not isinstance(state, MutableMapping) or not isinstance(project, MutableMapping):
        raise ValueError("existing_authority_confirmation_required:mutable_authority_payload_required")
    staged_state = deepcopy(dict(state))
    staged_project = deepcopy(dict(project))
    new_delta_ids: list[str] = []
    skipped_delta_ids: list[str] = []
    for write in plan.authority_writes:
        payload = staged_state if write.storage == "state" else staged_project
        if write.group == "progression":
            was_new = _apply_progression_write(
                payload,
                write,
                candidate_id=plan.candidate_id,
            )
            _sync_progression_mirrors(staged_state, staged_project, write.delta)
        elif write.group == "equipment_cards":
            was_new = _apply_equipment_write(
                payload,
                write,
                candidate_id=plan.candidate_id,
            )
        elif write.group == "relationship_graph":
            was_new = _apply_relationship_write(payload, write)
        else:  # pragma: no cover - dispatch is constrained by the authority map
            raise ValueError(f"existing_authority_confirmation_required:unsupported_authority:{write.group}")
        if was_new:
            new_delta_ids.append(write.delta.delta_id)
        else:
            skipped_delta_ids.append(write.delta.delta_id)
    state.clear()
    state.update(staged_state)
    project.clear()
    project.update(staged_project)
    return {
        "committed": bool(new_delta_ids),
        "authority_write_count": len(plan.authority_writes),
        "new_delta_ids": new_delta_ids,
        "skipped_delta_ids": skipped_delta_ids,
        "sources": sorted({write.authority_source for write in plan.authority_writes}),
        "writes": [
            {
                "group": write.group,
                "storage": write.storage,
                "path": [str(part) for part in write.path],
                "authority_source": write.authority_source,
                "delta_id": write.delta.delta_id,
            }
            for write in plan.authority_writes
        ],
    }


def get_fact_resource_snapshot(
    source: Any,
    *,
    as_of_chapter: int | None = None,
) -> FactResourceSnapshot:
    """Read one official snapshot from authorities plus generic resources."""

    target = max(0, int(as_of_chapter or 0)) if as_of_chapter is not None else None
    if isinstance(source, FactResourceSnapshot):
        return source.model_copy(deep=True)
    if isinstance(source, FactResourceLedger):
        return source.replay(as_of_chapter=target)
    getter = getattr(source, "get_fact_resource_snapshot", None)
    if callable(getter):
        try:
            return getter(as_of_chapter=target)
        except Exception:
            pass
    model_story = _story_payload(source)
    if any(
        key in model_story
        for key in (
            "characters",
            "progression_ledger",
            "equipment_cards",
            "relationship_graph",
            "current_chapter",
        )
    ):
        return project_fact_resource_snapshot(model_story, as_of_chapter=target)
    if isinstance(source, Mapping):
        if "entries" in source and "known" in source:
            try:
                return FactResourceSnapshot.model_validate(source)
            except Exception:
                return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="invalid")
        if any(
            key in source
            for key in (
                "characters",
                "progression_ledger",
                "equipment_cards",
                "relationship_graph",
                "current_chapter",
            )
        ):
            return project_fact_resource_snapshot(source, as_of_chapter=target)
    getter = getattr(source, "fact_resource_ledger", None)
    if callable(getter):
        try:
            ledger = getter()
            if isinstance(ledger, FactResourceLedger):
                return ledger.replay(as_of_chapter=target)
        except Exception:
            pass
    explicit = getattr(source, "fact_resource_ledger", None)
    if isinstance(explicit, Mapping) and explicit:
        try:
            return _coerce_ledger(explicit).replay(as_of_chapter=target)
        except Exception:
            return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="invalid")
    if isinstance(source, Mapping):
        raw = source.get("fact_resource_ledger") or source.get("initial_fact_resource_ledger")
        if raw:
            try:
                return project_fact_resource_snapshot(
                    source,
                    as_of_chapter=target,
                    generic_ledger=_coerce_ledger(raw),
                )
            except Exception:
                return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="invalid")
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_dir():
            ledger_path = path / ".story-system" / "fact-resource-ledger.json"
            story: dict[str, Any] = {}
            for candidate in (
                path / ".webnovel" / "project.json",
                path / ".webnovel" / "state.json",
                path / ".story-system" / "MASTER_SETTING.json",
            ):
                try:
                    payload = json.loads(candidate.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError, json.JSONDecodeError):
                    continue
                if not isinstance(payload, Mapping):
                    continue
                nested_project = payload.get("project")
                if isinstance(nested_project, Mapping):
                    payload = {**dict(payload), **dict(nested_project)}
                # state.json is loaded after project.json and therefore wins
                # for runtime fields.  Project-only sources fill gaps.
                for key, value in payload.items():
                    if key not in story or story[key] in (None, "", [], {}):
                        story[key] = deepcopy(value)
                    elif key in {"characters", "equipment_cards", "relationship_graph"} and isinstance(value, list) and value:
                        story[key] = deepcopy(value)
            if not story.get("characters") and isinstance(story.get("character_profiles"), list):
                story["characters"] = deepcopy(story["character_profiles"])
            ledger = FactResourceLedger.load(ledger_path)
            raw = story.get("fact_resource_ledger") or story.get("initial_fact_resource_ledger")
            if ledger is None and raw:
                try:
                    ledger = _coerce_ledger(raw)
                except Exception:
                    return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="invalid")
            if story or ledger is not None:
                return project_fact_resource_snapshot(
                    story,
                    as_of_chapter=target,
                    generic_ledger=ledger,
                )
            return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="missing")
        else:
            ledger_path = path
        ledger = FactResourceLedger.load(ledger_path)
        if ledger is not None:
            return ledger.replay(as_of_chapter=target)
        return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="missing")
    return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="missing")


def render_fact_resource_context(
    snapshot: FactResourceSnapshot,
    relevant_names: Iterable[str] | None = None,
    relevant_keys: Iterable[str] | None = None,
) -> str:
    """Render a compact, writer-facing chapter-start resource view."""

    if not snapshot.known:
        return "## 可计算事实资源（章节起点）\n- 未建立显式事实资源账本；不要从旧正文或最新状态猜测数值。"
    names = {_canonical_text(item) for item in (relevant_names or []) if _text(item)}
    keys = {_canonical_text(item) for item in (relevant_keys or []) if _text(item)}
    entries = [
        entry
        for entry in snapshot.entries
        if not names
        or _canonical_text(entry.subject) in names
        or _canonical_text(entry.resource_key) in keys
        or _canonical_text(entry.resource_key) in names
    ]
    if not entries:
        entries = list(snapshot.entries)
    lines = [f"## 可计算事实资源（截至第{snapshot.as_of_chapter}章）"]
    if snapshot.authorities:
        lines.append(
            "- 已有权威源："
            + "；".join(
                f"{item.source}（{','.join(item.categories)}）"
                for item in snapshot.authorities
                if item.active
            )
            + "。已有类别不从通用账本另行推断。"
        )
    if not entries:
        lines.append("- 账本/权威源已建立，但当前没有已知条目；未知值不能自行补齐。")
        return "\n".join(lines)
    for entry in entries[:32]:
        details = [f"值={entry.value!r}"]
        if entry.unit:
            details.append(f"单位={entry.unit}")
        if entry.owner:
            details.append(f"持有者={entry.owner}")
        if "equipped" in entry.metadata:
            details.append(f"已装备={bool(entry.metadata.get('equipped'))}")
        if entry.subject:
            prefix = f"{entry.subject}/{entry.category}"
        else:
            prefix = entry.category
        lines.append(f"- {prefix} · {entry.resource_key}：" + "；".join(details))
    lines.append("- 只把正文明确写出的获得、消耗、设置、转移或装备状态作为候选变化；不从含糊描写推导数值。")
    return "\n".join(lines)


__all__ = [
    "FACT_RESOURCE_SCHEMA",
    "FACT_RESOURCE_AUTHORITY_SCHEMA",
    "FactResourceAssertion",
    "FactResourceBaseline",
    "FactResourceDelta",
    "FactResourceEntry",
    "FactResourceExtraction",
    "FactResourceFinding",
    "FactResourceAuthority",
    "FactResourceAuthorityWrite",
    "FactResourceAuthorityWritePlan",
    "FactResourceLedger",
    "FactResourceSnapshot",
    "FactResourceValidation",
    "extract_fact_resource_changes",
    "apply_fact_resource_authority_writes",
    "fact_resource_authority_findings",
    "fact_resource_authority_group",
    "get_fact_resource_snapshot",
    "project_fact_resource_snapshot",
    "plan_fact_resource_authority_writes",
    "render_fact_resource_context",
    "stable_fact_id",
    "validate_fact_resource_extraction",
]
