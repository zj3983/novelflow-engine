from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


WORKFLOW_STATUSES = {"running", "done", "error", "queued"}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_workflow_artifact(value: object) -> dict[str, object] | list[object] | str | int | float | bool | None:
    """Keep workflow trace data JSON-safe and bounded before it reaches job logs."""
    if isinstance(value, dict):
        normalized: dict[str, object] = {}
        for key, item in value.items():
            if str(key).startswith("_"):
                continue
            item = normalize_workflow_artifact(item)
            if item is not None:
                normalized[str(key)] = item
        return normalized or None
    if isinstance(value, list):
        items: list[object] = []
        for item in value[:24]:
            item = normalize_workflow_artifact(item)
            if item is not None:
                items.append(item)
        return items
    if isinstance(value, str):
        text = value.strip()
        return text[:260] + "..." if len(text) > 280 else text or None
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def build_workflow_step_event(
    step_id: str,
    label: str,
    *,
    status: str = "running",
    source: str = "orchestrator",
    used_modules: list[str] | None = None,
    reads: list[str] | None = None,
    outputs: dict[str, Any] | None = None,
) -> dict[str, object]:
    normalized_status = status if status in WORKFLOW_STATUSES else "running"
    suffix = {"queued": "等待中", "running": "进行中", "done": "完成", "error": "失败"}[normalized_status]
    workflow_step = {
        "id": str(step_id).strip(),
        "label": str(label).strip(),
        "reads": [str(item).strip() for item in (reads or []) if str(item).strip()],
    }
    artifact: dict[str, object] = {"workflow_step": workflow_step}
    if used_modules:
        artifact["used_modules"] = [str(item).strip() for item in used_modules if str(item).strip()]
    if outputs:
        artifact["outputs"] = outputs
    return {
        "message": f"{label}{suffix}",
        "status": normalized_status,
        "stage": str(step_id).strip(),
        "source": str(source).strip() or "orchestrator",
        "artifact": artifact,
    }


def normalize_workflow_step(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        return {}
    message = str(value.get("message", "")).strip()
    if not message:
        return {}
    status = str(value.get("status", "running")).strip().lower()
    normalized: dict[str, object] = {
        "message": message,
        "status": status if status in WORKFLOW_STATUSES else "running",
        "at": str(value.get("at", "")).strip() or _now_iso(),
    }
    for key in ("stage", "source"):
        text = str(value.get(key, "")).strip()
        if text:
            normalized[key] = text
    artifact = normalize_workflow_artifact(value.get("artifact"))
    if artifact is not None:
        normalized["artifact"] = artifact
    return normalized


def merge_workflow_step(steps: list[dict[str, object]], value: object) -> dict[str, object]:
    """Append a step, replacing an adjacent duplicate message with its latest state."""
    normalized = normalize_workflow_step(value)
    if not normalized:
        return {}
    message = normalized["message"]
    if steps and str(steps[-1].get("message", "")).strip() == message:
        steps[-1] = normalized
    else:
        steps.append(normalized)
    return normalized
