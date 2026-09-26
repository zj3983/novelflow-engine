"""Model capability identity, provenance, resolution, and safe preflight helpers.

The capability layer deliberately sits beside ``runtime-config/v2``.  Runtime
configuration answers "how do we connect?" while this module answers "what has
this exact provider/model endpoint been shown to support?".  The distinction is
important for OpenAI-compatible endpoints where the same model name can expose
different behavior behind different base URLs.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import tempfile
from threading import RLock
from typing import Any, Callable, Literal, Mapping
from urllib.parse import urlsplit, urlunsplit


CapabilityState = Literal["supported", "unsupported", "unknown"]
CapabilitySource = Literal[
    "runtime_observation",
    "provider_metadata",
    "official_catalog",
    "user_declared",
    "unknown",
]
VerificationStatus = Literal["verified", "declared", "inferred", "unknown"]
ContextPreflightStatus = Literal["READY", "COMPACT", "SPLIT", "BLOCKED"]

TRANSPORT_CAPABILITIES = ("streaming", "json_mode", "tool_calling")
SAMPLING_CAPABILITIES = ("temperature", "top_p", "emotion_intensity")
REASONING_CAPABILITIES = ("reasoning_effort", "thinking", "thinking_budget")
LIMIT_CAPABILITIES = (
    "input_token_limit",
    "context_window",
    "max_output_tokens",
)
KNOWN_CAPABILITIES = (
    *TRANSPORT_CAPABILITIES,
    *SAMPLING_CAPABILITIES,
    *REASONING_CAPABILITIES,
)
KNOWN_LIMITS = LIMIT_CAPABILITIES

_SOURCE_PRIORITY: dict[str, int] = {
    "runtime_observation": 50,
    "provider_metadata": 40,
    "official_catalog": 30,
    "user_declared": 20,
    "unknown": 0,
}

DEFAULT_CAPABILITY_CACHE_FILE = (
    Path.home() / ".novel-autogrowth-engine" / "model_capability_cache.json"
)
CAPABILITY_CACHE_FILE = Path(
    os.getenv(
        "NOVEL_AUTOGROWTH_CAPABILITY_CACHE_PATH",
        str(DEFAULT_CAPABILITY_CACHE_FILE),
    )
)
CACHE_SCHEMA_VERSION = "model-capability-cache/v1"
PROFILE_SCHEMA_VERSION = "model-profile/v1"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _timestamp_value(value: datetime | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        current = value
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current.astimezone(timezone.utc).isoformat()
    text = str(value).strip()
    return text or None


def _timestamp_is_expired(value: str | None) -> bool:
    if not value:
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed <= datetime.now(timezone.utc)
    except ValueError:
        # An unreadable expiry is not permission to treat a capability as
        # permanent.  Keep it conservative and ignore the record.
        return True


def normalize_base_url(base_url: str | None) -> str:
    """Normalize an endpoint without persisting credentials or URL queries."""

    raw = str(base_url or "").strip()
    if not raw:
        return ""

    def invalid_identity() -> str:
        digest = hashlib.sha256(raw.encode("utf-8", errors="replace")).hexdigest()[:24]
        return f"invalid://sha256/{digest}"

    try:
        parsed = urlsplit(raw if "://" in raw else f"//{raw}")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if not hostname:
            return invalid_identity()
        host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
        # Accessing .port validates syntax and the 0..65535 range.  Never
        # return the raw authority when validation fails: it may contain URL
        # userinfo that must not reach capability cache files or diagnostics.
        port = parsed.port
        scheme = parsed.scheme.lower()
        if port is not None and not (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        ):
            host = f"{host}:{port}"
        path = parsed.path.rstrip("/")
        return urlunsplit((scheme, host, path, "", "")).rstrip("/")
    except ValueError:
        return invalid_identity()


def safe_base_url_for_diagnostics(base_url: str | None) -> str:
    """Serialize endpoint identity without ever exposing userinfo or query data.

    This is intentionally independent from the capability cache normalizer so
    reports remain safe even when handed an old or malformed cached identity.
    """

    raw = str(base_url or "").strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw if "://" in raw else f"//{raw}")
        hostname = (parsed.hostname or "").lower().rstrip(".")
        if not hostname:
            return "invalid endpoint (redacted)"
        port = parsed.port
        host = f"[{hostname}]" if ":" in hostname and not hostname.startswith("[") else hostname
        scheme = parsed.scheme.lower()
        if port is not None and not (
            (scheme == "http" and port == 80)
            or (scheme == "https" and port == 443)
        ):
            host = f"{host}:{port}"
        path = parsed.path.rstrip("/")
        return urlunsplit((scheme, host, path, "", "")).rstrip("/")
    except ValueError:
        return "invalid endpoint (redacted)"


@dataclass(frozen=True)
class ModelIdentity:
    """The complete identity used for capability cache isolation."""

    provider_id: str
    protocol: str
    normalized_base_url: str
    requested_model: str
    resolved_model: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "provider_id", str(self.provider_id or "").strip().lower())
        object.__setattr__(self, "protocol", str(self.protocol or "").strip().lower())
        object.__setattr__(
            self,
            "normalized_base_url",
            normalize_base_url(self.normalized_base_url),
        )
        object.__setattr__(
            self,
            "requested_model",
            str(self.requested_model or "").strip(),
        )
        resolved = str(self.resolved_model or "").strip()
        object.__setattr__(self, "resolved_model", resolved or None)

    @property
    def identity_key(self) -> str:
        return json.dumps(
            {
                "provider_id": self.provider_id,
                "protocol": self.protocol,
                "normalized_base_url": self.normalized_base_url,
                "requested_model": self.requested_model,
                "resolved_model": self.resolved_model,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    @property
    def cache_key(self) -> str:
        return hashlib.sha256(self.identity_key.encode("utf-8")).hexdigest()

    def with_resolved_model(self, resolved_model: str | None) -> "ModelIdentity":
        return replace(self, resolved_model=resolved_model)

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider_id": self.provider_id,
            "protocol": self.protocol,
            "normalized_base_url": self.normalized_base_url,
            "requested_model": self.requested_model,
            "resolved_model": self.resolved_model,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelIdentity":
        return cls(
            provider_id=str(value.get("provider_id") or ""),
            protocol=str(value.get("protocol") or ""),
            normalized_base_url=str(value.get("normalized_base_url") or value.get("base_url") or ""),
            requested_model=str(value.get("requested_model") or value.get("model") or ""),
            resolved_model=value.get("resolved_model"),
        )


@dataclass(frozen=True)
class CapabilityProvenance:
    source: str = "unknown"
    verified_at: str | None = None
    expires_at: str | None = None
    confidence: float | None = None
    verification_status: str = "unknown"
    note: str = ""

    def __post_init__(self) -> None:
        confidence = self.confidence
        if confidence is not None:
            confidence = float(confidence)
            if not math.isfinite(confidence) or not 0 <= confidence <= 1:
                raise ValueError("capability confidence must be between 0 and 1")
            object.__setattr__(self, "confidence", confidence)
        object.__setattr__(self, "verified_at", _timestamp_value(self.verified_at))
        object.__setattr__(self, "expires_at", _timestamp_value(self.expires_at))
        object.__setattr__(self, "source", str(self.source or "unknown"))
        object.__setattr__(
            self,
            "verification_status",
            str(self.verification_status or "unknown"),
        )
        object.__setattr__(self, "note", str(self.note or ""))

    @classmethod
    def for_source(
        cls,
        source: CapabilitySource,
        *,
        now: str | None = None,
        confidence: float | None = None,
        expires_at: str | None = None,
        note: str = "",
    ) -> "CapabilityProvenance":
        status = {
            "runtime_observation": "verified",
            "provider_metadata": "verified",
            "official_catalog": "declared",
            "user_declared": "declared",
            "unknown": "unknown",
        }.get(source, "unknown")
        return cls(
            source=source,
            verified_at=None if source == "unknown" else (now or _utc_now_iso()),
            expires_at=expires_at,
            confidence=confidence,
            verification_status=status,
            note=note,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "source": self.source,
            "verified_at": self.verified_at,
            "expires_at": self.expires_at,
            "confidence": self.confidence,
            "verification_status": self.verification_status,
            "note": self.note,
        }

    @classmethod
    def from_dict(
        cls,
        value: Mapping[str, Any] | None,
        *,
        default_source: CapabilitySource = "unknown",
        now: str | None = None,
    ) -> "CapabilityProvenance":
        data = dict(value or {})
        source = str(data.get("source") or default_source)
        return cls(
            source=source,
            verified_at=data.get("verified_at") or data.get("updated_at") or (
                None if source == "unknown" else now
            ),
            expires_at=data.get("expires_at"),
            confidence=data.get("confidence"),
            verification_status=str(
                data.get("verification_status")
                or ("verified" if source in {"runtime_observation", "provider_metadata"} else "declared" if source in {"official_catalog", "user_declared"} else "unknown")
            ),
            note=str(data.get("note") or ""),
        )


@dataclass(frozen=True)
class CapabilityRecord:
    """A tri-state capability or a known numeric limit with provenance."""

    state: CapabilityState = "unknown"
    value: Any = None
    provenance: CapabilityProvenance = field(default_factory=CapabilityProvenance)

    def __post_init__(self) -> None:
        state = str(self.state or "unknown")
        if state not in {"supported", "unsupported", "unknown"}:
            raise ValueError(f"unsupported capability state: {state}")
        object.__setattr__(self, "state", state)
        if not isinstance(self.provenance, CapabilityProvenance):
            object.__setattr__(
                self,
                "provenance",
                CapabilityProvenance.from_dict(self.provenance),
            )

    @classmethod
    def unknown(cls, *, source: CapabilitySource = "unknown") -> "CapabilityRecord":
        return cls(
            state="unknown",
            provenance=CapabilityProvenance.for_source(source),
        )

    @classmethod
    def from_raw(
        cls,
        value: Any,
        *,
        source: CapabilitySource,
        now: str | None = None,
    ) -> "CapabilityRecord":
        if isinstance(value, cls):
            if value.provenance.source == source:
                return value
            return replace(
                value,
                provenance=replace(value.provenance, source=source),
            )

        state: CapabilityState = "unknown"
        record_value: Any = None
        provenance_data: Mapping[str, Any] | None = None
        if isinstance(value, Mapping):
            state_value = value.get("state") or value.get("status")
            if state_value is not None:
                state_text = str(state_value).strip().lower()
                if state_text in {"supported", "unsupported", "unknown"}:
                    state = state_text  # type: ignore[assignment]
            if "value" in value:
                record_value = value.get("value")
            elif "limit" in value:
                record_value = value.get("limit")
            provenance_value = value.get("provenance")
            if isinstance(provenance_value, Mapping):
                provenance_data = provenance_value
            elif any(
                key in value
                for key in ("source", "verified_at", "updated_at", "expires_at", "confidence")
            ):
                provenance_data = value
        elif isinstance(value, bool):
            state = "supported" if value else "unsupported"
        elif isinstance(value, (int, float)) and not isinstance(value, bool):
            state = "supported"
            record_value = value
        elif isinstance(value, str):
            state_text = value.strip().lower()
            if state_text in {"supported", "unsupported", "unknown"}:
                state = state_text  # type: ignore[assignment]
            elif value.strip():
                state = "supported"
                record_value = value
        elif value is not None:
            state = "supported"
            record_value = value

        provenance = CapabilityProvenance.from_dict(
            provenance_data,
            default_source=source,
            now=now,
        )
        if provenance.source != source:
            provenance = replace(provenance, source=source)
        if provenance.confidence is None and source != "unknown":
            provenance = replace(
                provenance,
                confidence={
                    "runtime_observation": 1.0,
                    "provider_metadata": 0.9,
                    "official_catalog": 0.7,
                    "user_declared": 0.5,
                }.get(source, None),
            )
        return cls(state=state, value=record_value, provenance=provenance)

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state,
            "value": self.value,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "CapabilityRecord":
        return cls.from_raw(
            value,
            source=str(
                (value.get("provenance") or {}).get("source", "unknown")
                if isinstance(value.get("provenance"), Mapping)
                else "unknown"
            ),
        )


@dataclass(frozen=True)
class CapabilityObservation:
    """A provider event that can be safely persisted as runtime evidence."""

    identity: ModelIdentity
    capability: str
    state: CapabilityState = "unknown"
    value: Any = None
    observed_at: str | None = None
    confidence: float = 1.0
    note: str = ""

    def to_record(self) -> CapabilityRecord:
        return CapabilityRecord(
            state=self.state,
            value=self.value,
            provenance=CapabilityProvenance.for_source(
                "runtime_observation",
                now=self.observed_at or _utc_now_iso(),
                confidence=self.confidence,
                note=self.note,
            ),
        )


@dataclass(frozen=True)
class ModelProfile:
    """Resolved capabilities for one exact model execution environment."""

    identity: ModelIdentity
    declared_capabilities: Mapping[str, CapabilityRecord] = field(default_factory=dict)
    verified_capabilities: Mapping[str, CapabilityRecord] = field(default_factory=dict)
    effective_capabilities: Mapping[str, CapabilityRecord] = field(default_factory=dict)
    limits: Mapping[str, CapabilityRecord] = field(default_factory=dict)
    provenance: Mapping[str, CapabilityProvenance] = field(default_factory=dict)
    schema_version: str = PROFILE_SCHEMA_VERSION

    @classmethod
    def unknown(cls, identity: ModelIdentity) -> "ModelProfile":
        unknown_capabilities = {
            name: CapabilityRecord.unknown() for name in KNOWN_CAPABILITIES
        }
        unknown_limits = {name: CapabilityRecord.unknown() for name in KNOWN_LIMITS}
        return cls(
            identity=identity,
            declared_capabilities=unknown_capabilities,
            verified_capabilities=dict(unknown_capabilities),
            effective_capabilities=dict(unknown_capabilities),
            limits=unknown_limits,
            provenance={
                **{name: record.provenance for name, record in unknown_capabilities.items()},
                **{name: record.provenance for name, record in unknown_limits.items()},
            },
        )

    def effective_capability(self, name: str) -> CapabilityRecord:
        if name in self.effective_capabilities:
            return self.effective_capabilities[name]
        if name in self.limits:
            return self.limits[name]
        return CapabilityRecord.unknown()

    def effective_limit(self, name: str = "context_window") -> int | None:
        record = self.limits.get(name) or CapabilityRecord.unknown()
        if record.state != "supported" or record.value is None:
            return None
        try:
            value = int(record.value)
        except (TypeError, ValueError):
            return None
        return value if value > 0 else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "identity": self.identity.to_dict(),
            "declared_capabilities": {
                name: record.to_dict() for name, record in self.declared_capabilities.items()
            },
            "verified_capabilities": {
                name: record.to_dict() for name, record in self.verified_capabilities.items()
            },
            "effective_capabilities": {
                name: record.to_dict() for name, record in self.effective_capabilities.items()
            },
            "limits": {name: record.to_dict() for name, record in self.limits.items()},
            "provenance": {
                name: provenance.to_dict() for name, provenance in self.provenance.items()
            },
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ModelProfile":
        identity_data = value.get("identity")
        if not isinstance(identity_data, Mapping):
            raise ValueError("model profile identity is required")

        def records(key: str) -> dict[str, CapabilityRecord]:
            raw = value.get(key)
            if not isinstance(raw, Mapping):
                return {}
            return {
                str(name): CapabilityRecord.from_dict(item)
                for name, item in raw.items()
                if isinstance(item, Mapping)
            }

        provenance: dict[str, CapabilityProvenance] = {}
        raw_provenance = value.get("provenance")
        if isinstance(raw_provenance, Mapping):
            provenance = {
                str(name): CapabilityProvenance.from_dict(item)
                for name, item in raw_provenance.items()
                if isinstance(item, Mapping)
            }
        return cls(
            identity=ModelIdentity.from_dict(identity_data),
            declared_capabilities=records("declared_capabilities"),
            verified_capabilities=records("verified_capabilities"),
            effective_capabilities=records("effective_capabilities"),
            limits=records("limits"),
            provenance=provenance,
            schema_version=str(value.get("schema_version") or PROFILE_SCHEMA_VERSION),
        )


class ModelCapabilityStore:
    """Small JSON cache containing runtime evidence only, never credentials."""

    _shared_lock = RLock()

    def __init__(self, path: str | os.PathLike[str] | None = None) -> None:
        self.path = Path(path) if path is not None else CAPABILITY_CACHE_FILE
        self._lock = self._shared_lock

    def invalidate_identity(self, identity: ModelIdentity) -> None:
        """Discard evidence for a removed binding, including resolved snapshots."""
        with self._lock:
            payload = self._read()
            profiles = payload["profiles"]
            removed = []
            for key, entry in profiles.items():
                try:
                    cached = ModelIdentity.from_dict(entry["identity"])
                except (KeyError, TypeError, ValueError):
                    continue
                if cached.with_resolved_model(None) == identity.with_resolved_model(None):
                    removed.append(key)
            for key in removed:
                del profiles[key]
            if removed:
                self._write(payload)

    @staticmethod
    def _empty_payload() -> dict[str, Any]:
        return {"schema_version": CACHE_SCHEMA_VERSION, "profiles": {}}

    def _read(self) -> dict[str, Any]:
        if not self.path.exists():
            return self._empty_payload()
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            return self._empty_payload()
        if not isinstance(data, dict) or data.get("schema_version") != CACHE_SCHEMA_VERSION:
            return self._empty_payload()
        profiles = data.get("profiles")
        if not isinstance(profiles, dict):
            data["profiles"] = {}
        return data

    def _write(self, payload: Mapping[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary_path = tempfile.mkstemp(
            dir=str(self.path.parent), prefix="model_capability_", suffix=".json"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            os.replace(temporary_path, self.path)
            try:
                os.chmod(self.path, 0o600)
            except OSError:
                pass
        finally:
            if os.path.exists(temporary_path):
                os.remove(temporary_path)

    def get_profile(self, identity: ModelIdentity) -> ModelProfile | None:
        with self._lock:
            entry = self._read().get("profiles", {}).get(identity.cache_key)
        if not isinstance(entry, Mapping):
            return None
        try:
            profile = ModelProfile.from_dict(entry)
        except (TypeError, ValueError, KeyError):
            return None
        if profile.identity != identity:
            return None
        return profile

    def put_profile(self, profile: ModelProfile) -> None:
        """Persist only the verified runtime evidence from a profile."""

        entry = {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "identity": profile.identity.to_dict(),
            "verified_capabilities": {
                name: record.to_dict()
                for name, record in profile.verified_capabilities.items()
                if record.provenance.source == "runtime_observation"
            },
        }
        with self._lock:
            payload = self._read()
            payload.setdefault("profiles", {})[profile.identity.cache_key] = entry
            self._write(payload)

    @staticmethod
    def _new_profile_entry(identity: ModelIdentity) -> dict[str, Any]:
        return {
            "schema_version": PROFILE_SCHEMA_VERSION,
            "identity": identity.to_dict(),
            "verified_capabilities": {},
        }

    @classmethod
    def _record_resolved_model_in_payload(
        cls,
        payload: dict[str, Any],
        identity: ModelIdentity,
    ) -> None:
        """Update an alias snapshot and discard stale alias evidence on change."""

        if identity.resolved_model is None:
            return
        profiles = payload.setdefault("profiles", {})
        alias = identity.with_resolved_model(None)
        raw_entry = profiles.get(alias.cache_key)
        if not isinstance(raw_entry, dict):
            raw_entry = cls._new_profile_entry(alias)
            profiles[alias.cache_key] = raw_entry
        previous = str(raw_entry.get("last_resolved_model") or "").strip() or None
        if previous is not None and previous != identity.resolved_model:
            # The alias now points at another backend snapshot. Keep the exact
            # backend profile, but make the alias unknown until it is observed
            # again for the new snapshot.
            raw_entry["verified_capabilities"] = {}
        if not isinstance(raw_entry.get("verified_capabilities"), dict):
            raw_entry["verified_capabilities"] = {}
        raw_entry["last_resolved_model"] = identity.resolved_model
        raw_entry["last_resolved_at"] = _utc_now_iso()

    def record_resolved_model(self, identity: ModelIdentity) -> None:
        """Remember the latest resolved backend for a requested-model alias."""

        if identity.resolved_model is None:
            return
        with self._lock:
            payload = self._read()
            self._record_resolved_model_in_payload(payload, identity)
            self._write(payload)

    def record_runtime_observation(
        self,
        identity: ModelIdentity,
        capability: str,
        record: CapabilityRecord,
    ) -> None:
        if record.provenance.source != "runtime_observation":
            record = replace(
                record,
                provenance=replace(record.provenance, source="runtime_observation"),
            )
        identities = [identity]
        if identity.resolved_model is not None:
            identities.append(identity.with_resolved_model(None))
        with self._lock:
            payload = self._read()
            self._record_resolved_model_in_payload(payload, identity)
            profiles = payload.setdefault("profiles", {})
            for candidate in identities:
                entry = profiles.get(candidate.cache_key)
                if not isinstance(entry, dict):
                    entry = self._new_profile_entry(candidate)
                    profiles[candidate.cache_key] = entry
                verified = entry.setdefault("verified_capabilities", {})
                if isinstance(verified, dict):
                    verified[capability] = record.to_dict()
            self._write(payload)


# The maintained catalog intentionally starts conservative.  Entries can be
# added with explicit ``provenance.updated_at``/``expires_at`` metadata without
# turning a model name into a permanent truth.  Unknown models remain unknown.
DEFAULT_MODEL_CAPABILITY_CATALOG: Mapping[tuple[str, str, str], Mapping[str, Any]] = {}


def provider_capability_catalog(
    provider_id: str,
    protocol: str,
    requested_model: str,
) -> Mapping[str, Any]:
    return dict(
        DEFAULT_MODEL_CAPABILITY_CATALOG.get(
            (str(provider_id), str(protocol), str(requested_model)),
            {},
        )
    )


CatalogResolver = Callable[[str, str, str], Mapping[str, Any]]


def _source_maps(
    raw: Mapping[str, Any] | None,
    *,
    source: CapabilitySource,
    now: str,
) -> tuple[dict[str, CapabilityRecord], dict[str, CapabilityRecord]]:
    if not isinstance(raw, Mapping):
        return {}, {}
    if isinstance(raw.get("capabilities"), Mapping):
        capability_raw = dict(raw["capabilities"])
    else:
        capability_raw = {
            name: value for name, value in raw.items() if name not in KNOWN_LIMITS
        }
    if isinstance(raw.get("limits"), Mapping):
        limit_raw = dict(raw["limits"])
    else:
        limit_raw = {name: raw[name] for name in KNOWN_LIMITS if name in raw}
    return (
        {
            str(name): CapabilityRecord.from_raw(value, source=source, now=now)
            for name, value in capability_raw.items()
        },
        {
            str(name): CapabilityRecord.from_raw(value, source=source, now=now)
            for name, value in limit_raw.items()
        },
    )


def _select_records(
    sources: list[Mapping[str, CapabilityRecord]],
    *,
    known_names: tuple[str, ...],
) -> dict[str, CapabilityRecord]:
    names = set(known_names)
    for source in sources:
        names.update(source)
    selected: dict[str, CapabilityRecord] = {}
    for name in sorted(names):
        candidates = [source[name] for source in sources if name in source]
        active = [
            record
            for record in candidates
            if not _timestamp_is_expired(record.provenance.expires_at)
        ]
        if not active:
            expired = [
                record
                for record in candidates
                if _timestamp_is_expired(record.provenance.expires_at)
            ]
            if expired:
                previous = max(
                    enumerate(expired),
                    key=lambda item: (
                        _SOURCE_PRIORITY.get(item[1].provenance.source, 0),
                        item[1].provenance.verified_at or "",
                        -item[0],
                    ),
                )[1]
                # Keep the old source and expiry visible for diagnostics, but
                # never let expired evidence continue to authorize a request.
                selected[name] = replace(previous, state="unknown")
            else:
                selected[name] = CapabilityRecord.unknown()
            continue
        selected[name] = max(
            enumerate(active),
            key=lambda item: (
                _SOURCE_PRIORITY.get(item[1].provenance.source, 0),
                item[1].provenance.verified_at or "",
                -item[0],
            ),
        )[1]
    return selected


class ModelCapabilityResolver:
    """Resolve runtime, provider, catalog, and user evidence by precedence."""

    def __init__(
        self,
        *,
        store: ModelCapabilityStore | None = None,
        catalog: Mapping[Any, Mapping[str, Any]] | CatalogResolver | None = None,
        clock: Callable[[], str] | None = None,
    ) -> None:
        self.store = store or ModelCapabilityStore()
        self.catalog = catalog
        self.clock = clock or _utc_now_iso

    def identity(
        self,
        provider_id: str,
        base_url: str,
        requested_model: str,
        protocol: str,
        *,
        resolved_model: str | None = None,
    ) -> ModelIdentity:
        return ModelIdentity(
            provider_id=provider_id,
            protocol=protocol,
            normalized_base_url=base_url,
            requested_model=requested_model,
            resolved_model=resolved_model,
        )

    def _catalog_data(
        self,
        provider_id: str,
        protocol: str,
        requested_model: str,
    ) -> Mapping[str, Any]:
        if self.catalog is None:
            return provider_capability_catalog(provider_id, protocol, requested_model)
        if callable(self.catalog):
            return self.catalog(provider_id, protocol, requested_model)
        for key in (
            (provider_id, protocol, requested_model),
            (provider_id, requested_model),
            requested_model,
        ):
            value = self.catalog.get(key)  # type: ignore[arg-type]
            if isinstance(value, Mapping):
                return value
        return {}

    def resolve_model_profile(
        self,
        provider_id: str,
        base_url: str,
        requested_model: str,
        protocol: str,
        *,
        resolved_model: str | None = None,
        provider_metadata: Mapping[str, Any] | None = None,
        user_declared: Mapping[str, Any] | None = None,
    ) -> ModelProfile:
        identity = self.identity(
            provider_id,
            base_url,
            requested_model,
            protocol,
            resolved_model=resolved_model,
        )
        now = self.clock()
        cached = self.store.get_profile(identity)
        cached_verified = (
            dict(cached.verified_capabilities) if cached is not None else {}
        )
        runtime_capabilities = {
            name: record
            for name, record in cached_verified.items()
            if name not in KNOWN_LIMITS
        }
        runtime_limits = {
            name: record
            for name, record in cached_verified.items()
            if name in KNOWN_LIMITS
        }
        provider_capabilities, provider_limits = _source_maps(
            provider_metadata,
            source="provider_metadata",
            now=now,
        )
        catalog_capabilities, catalog_limits = _source_maps(
            self._catalog_data(provider_id, protocol, requested_model),
            source="official_catalog",
            now=now,
        )
        user_capabilities, user_limits = _source_maps(
            user_declared,
            source="user_declared",
            now=now,
        )

        declared = _select_records(
            [provider_capabilities, catalog_capabilities, user_capabilities],
            known_names=KNOWN_CAPABILITIES,
        )
        verified = _select_records(
            [runtime_capabilities],
            known_names=KNOWN_CAPABILITIES,
        )
        effective = _select_records(
            [
                runtime_capabilities,
                provider_capabilities,
                catalog_capabilities,
                user_capabilities,
            ],
            known_names=KNOWN_CAPABILITIES,
        )
        limits = _select_records(
            [runtime_limits, provider_limits, catalog_limits, user_limits],
            known_names=KNOWN_LIMITS,
        )
        return ModelProfile(
            identity=identity,
            declared_capabilities=declared,
            verified_capabilities=verified,
            effective_capabilities=effective,
            limits=limits,
            provenance={
                **{name: record.provenance for name, record in effective.items()},
                **{name: record.provenance for name, record in limits.items()},
            },
        )

    def record_runtime_observation(self, observation: CapabilityObservation) -> None:
        self.store.record_runtime_observation(
            observation.identity,
            observation.capability,
            observation.to_record(),
        )

    def record_resolved_model(self, identity: ModelIdentity) -> None:
        self.store.record_resolved_model(identity)

    observe_runtime = record_runtime_observation


def resolve_model_profile(
    provider: str,
    base_url: str,
    model: str,
    protocol: str,
    *,
    resolved_model: str | None = None,
    provider_metadata: Mapping[str, Any] | None = None,
    user_declared: Mapping[str, Any] | None = None,
    store: ModelCapabilityStore | None = None,
) -> ModelProfile:
    """Convenience boundary used by callers that do not need a resolver object."""

    return ModelCapabilityResolver(store=store).resolve_model_profile(
        provider,
        base_url,
        model,
        protocol,
        resolved_model=resolved_model,
        provider_metadata=provider_metadata,
        user_declared=user_declared,
    )


@dataclass(frozen=True)
class StreamingDecision:
    requested_streaming: bool
    effective_streaming: bool
    capability_state: CapabilityState
    reason: str


def _capability_state(value: ModelProfile | CapabilityRecord | CapabilityState | None) -> CapabilityState:
    if isinstance(value, ModelProfile):
        return value.effective_capability("streaming").state
    if isinstance(value, CapabilityRecord):
        return value.state
    state = str(value or "unknown")
    return state if state in {"supported", "unsupported", "unknown"} else "unknown"  # type: ignore[return-value]


def decide_streaming(
    requested_streaming: bool,
    capability: ModelProfile | CapabilityRecord | CapabilityState | None,
) -> StreamingDecision:
    state = _capability_state(capability)
    if not requested_streaming:
        return StreamingDecision(False, False, state, "stream_not_requested")
    if state == "supported":
        return StreamingDecision(True, True, state, "capability_supported")
    if state == "unsupported":
        return StreamingDecision(True, False, state, "capability_unsupported")
    return StreamingDecision(True, False, "unknown", "capability_unknown_conservative")


def effective_streaming(
    requested_streaming: bool,
    capability: ModelProfile | CapabilityRecord | CapabilityState | None,
) -> bool:
    return decide_streaming(requested_streaming, capability).effective_streaming


resolve_effective_streaming = effective_streaming


@dataclass(frozen=True)
class ContextPreflightResult:
    status: ContextPreflightStatus
    estimated_required_input: int
    estimated_optional_input: int
    reserved_output: int
    safety_margin: int
    context_limit: int | None
    reason: str
    input_limit: int | None = None
    max_output_limit: int | None = None
    estimated_input: int = 0

    @property
    def safe(self) -> bool:
        return self.status == "READY"

    @property
    def estimated_total(self) -> int:
        return (
            self.estimated_required_input
            + self.estimated_optional_input
            + self.reserved_output
            + self.safety_margin
        )


def _coerce_context_limit(value: Any) -> int | None:
    if isinstance(value, ModelProfile):
        return value.effective_limit()
    if isinstance(value, CapabilityRecord):
        if value.state == "unsupported":
            return None
        value = value.value
    if value is None:
        return None
    try:
        limit = int(value)
    except (TypeError, ValueError):
        return None
    return limit if limit > 0 else None


def preflight_context(
    *,
    estimated_required_input: int,
    estimated_optional_input: int = 0,
    reserved_output: int = 0,
    safety_margin: int = 0,
    model_effective_limit: int | CapabilityRecord | ModelProfile | None = None,
    context_limit: int | CapabilityRecord | ModelProfile | None = None,
    input_limit: int | CapabilityRecord | ModelProfile | None = None,
    max_output_limit: int | CapabilityRecord | ModelProfile | None = None,
    allow_split: bool = True,
) -> ContextPreflightResult:
    """Classify a request without treating an unknown context as safe."""

    required = int(estimated_required_input)
    optional = int(estimated_optional_input)
    output = int(reserved_output)
    margin = int(safety_margin)
    limit = _coerce_context_limit(
        model_effective_limit if model_effective_limit is not None else context_limit
    )
    resolved_input_limit = _coerce_context_limit(input_limit)
    resolved_output_limit = _coerce_context_limit(max_output_limit)
    estimated_input = required + optional
    result_args = dict(
        estimated_required_input=required,
        estimated_optional_input=optional,
        reserved_output=output,
        safety_margin=margin,
        context_limit=limit,
        input_limit=resolved_input_limit,
        max_output_limit=resolved_output_limit,
        estimated_input=estimated_input,
    )
    if min(required, optional, output, margin) < 0:
        return ContextPreflightResult(status="BLOCKED", reason="negative_budget", **result_args)
    if resolved_output_limit is not None and output > resolved_output_limit:
        return ContextPreflightResult(
            status="BLOCKED", reason="max_output_limit_exceeded", **result_args
        )
    if resolved_input_limit is not None:
        required_input = required + margin
        total_input = required + optional + margin
        if required_input > resolved_input_limit:
            if allow_split and required <= resolved_input_limit:
                return ContextPreflightResult(
                    status="SPLIT", reason="required_input_exceeds_safety_budget", **result_args
                )
            return ContextPreflightResult(
                status="BLOCKED", reason="required_input_over_limit", **result_args
            )
        if total_input > resolved_input_limit:
            if optional > 0:
                return ContextPreflightResult(
                    status="COMPACT", reason="optional_input_over_input_limit", **result_args
                )
            if allow_split and required <= resolved_input_limit:
                return ContextPreflightResult(
                    status="SPLIT", reason="input_exceeds_safety_budget", **result_args
                )
            return ContextPreflightResult(
                status="BLOCKED", reason="input_over_limit", **result_args
            )
    if limit is None:
        return ContextPreflightResult(
            status="COMPACT",
            reason="context_limit_unknown_conservative",
            **result_args,
        )
    total = required + optional + output + margin
    if total <= limit:
        return ContextPreflightResult(status="READY", reason="within_context_limit", **result_args)
    required_budget = required + output + margin
    if required_budget <= limit:
        return ContextPreflightResult(
            status="COMPACT",
            reason="optional_context_must_be_compacted",
            **result_args,
        )
    if allow_split and required + output <= limit:
        return ContextPreflightResult(
            status="SPLIT",
            reason="required_context_exceeds_safety_budget",
            **result_args,
        )
    return ContextPreflightResult(status="BLOCKED", reason="required_context_over_limit", **result_args)


__all__ = [
    "CACHE_SCHEMA_VERSION",
    "CAPABILITY_CACHE_FILE",
    "CapabilityObservation",
    "CapabilityProvenance",
    "CapabilityRecord",
    "CapabilitySource",
    "CapabilityState",
    "ContextPreflightResult",
    "ContextPreflightStatus",
    "DEFAULT_MODEL_CAPABILITY_CATALOG",
    "KNOWN_CAPABILITIES",
    "KNOWN_LIMITS",
    "LIMIT_CAPABILITIES",
    "ModelCapabilityResolver",
    "ModelCapabilityStore",
    "ModelIdentity",
    "ModelProfile",
    "SAMPLING_CAPABILITIES",
    "StreamingDecision",
    "TRANSPORT_CAPABILITIES",
    "decide_streaming",
    "effective_streaming",
    "normalize_base_url",
    "preflight_context",
    "provider_capability_catalog",
    "resolve_effective_streaming",
    "resolve_model_profile",
    "safe_base_url_for_diagnostics",
]
