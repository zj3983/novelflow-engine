"""Deterministic, candidate-safe fact and resource ledger.

This module is deliberately smaller than the legacy progression ledger.  It
only records explicit, chapter-scoped numeric or ownership assertions that
can be replayed without looking at the latest prose or at a mutable mirror.
The file-project store is responsible for the confirmation transaction; this
module owns the schema, replay, extraction, and validation rules.
"""

from __future__ import annotations

from copy import deepcopy
from hashlib import sha256
import json
import math
import re
import unicodedata
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from pydantic import BaseModel, ConfigDict, Field, model_validator


FACT_RESOURCE_SCHEMA = "fact-resource-ledger/v1"
FACT_RESOURCE_EXTRACTION_SCHEMA = "fact-resource-extraction/v1"
FACT_RESOURCE_REVIEW_SCHEMA = "fact-resource-review/v1"

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
        return None

    def value_for(self, category: str, resource_key: str, *, subject: str = "") -> Any:
        entry = self.find(category, resource_key, subject=subject)
        return entry.value if entry else None


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


def get_fact_resource_snapshot(
    source: Any,
    *,
    as_of_chapter: int | None = None,
) -> FactResourceSnapshot:
    """Read an explicit ledger/baseline without deriving from latest prose."""

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
                return _coerce_ledger(raw).replay(as_of_chapter=target)
            except Exception:
                return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="invalid")
    if isinstance(source, (str, Path)):
        path = Path(source)
        if path.is_dir():
            ledger_path = path / ".story-system" / "fact-resource-ledger.json"
            if not ledger_path.is_file():
                master = path / ".story-system" / "MASTER_SETTING.json"
                try:
                    payload = json.loads(master.read_text(encoding="utf-8-sig"))
                except (OSError, ValueError, json.JSONDecodeError):
                    payload = {}
                raw = payload.get("fact_resource_ledger") or payload.get("initial_fact_resource_ledger") if isinstance(payload, Mapping) else None
                if raw:
                    try:
                        return _coerce_ledger(raw).replay(as_of_chapter=target)
                    except Exception:
                        return FactResourceSnapshot(as_of_chapter=target or 0, known=False, source="invalid")
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
    if not entries:
        lines.append("- 账本已建立，但当前没有已知条目；未知值不能自行补齐。")
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
    "FactResourceAssertion",
    "FactResourceBaseline",
    "FactResourceDelta",
    "FactResourceEntry",
    "FactResourceExtraction",
    "FactResourceFinding",
    "FactResourceLedger",
    "FactResourceSnapshot",
    "FactResourceValidation",
    "extract_fact_resource_changes",
    "get_fact_resource_snapshot",
    "render_fact_resource_context",
    "stable_fact_id",
    "validate_fact_resource_extraction",
]
