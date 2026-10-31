"""Evidence-based manual completion checks, separate from story canon."""
from __future__ import annotations

from hashlib import sha256
import json

from packages.story_core.outline_rolling_store import RollingOutlineStore
from packages.story_core.persistence.project_locking import project_update_lock


def _hash(value) -> str:
    return sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def read_ending_audit(store) -> dict:
    outline = store.project_outline()
    overall = outline["overall"]
    ledger = [item.model_dump(mode="json") for item in store.foreshadowing_ledger()]
    saved = store._read_json(store.story_system_dir / "ending-audit.json", {}) or {}
    decisions = saved.get("decisions", {})
    rows = []
    evidence_hashes = {}

    def evidence_hash(number):
        if number not in evidence_hashes:
            chapter = store._read_json(store.story_system_dir / "chapters" / f"{number:04d}.json", {}) or {}
            evidence_hashes[number] = _hash(store._hydrate_chapter_body(chapter).get("body", "")) if chapter else ""
        return evidence_hashes[number]

    def add(kind, title, basis, context=""):
        key = f"{kind}:{_hash(basis)}"
        decision = decisions.get(key, {})
        stale = decision.get("chapter") and decision.get("evidence_hash") != evidence_hash(decision["chapter"])
        rows.append({"id": key, "kind": kind, "title": title, "context": context,
                     "disposition": "pending" if stale else decision.get("disposition", "pending"),
                     "chapter": decision.get("chapter"), "note": decision.get("note", "")})

    for line in overall.get("long_term_lines", []):
        if line.get("name") or line.get("final_payoff"):
            add("mainline", line.get("name") or "长期主线", line, line.get("final_payoff", ""))
    for field, title in (("protagonist_goal", "主角长期目标"), ("ending_contract", "结局契约")):
        if overall.get(field):
            add("mainline", title, {field: overall[field]}, overall[field])
    mystery = overall.get("central_mystery", {})
    if mystery.get("hidden_truth"):
        add("mainline", "核心谜团", mystery, mystery["hidden_truth"])
    for item in ledger:
        add("foreshadowing", item["text"], item,
            f"首次第{item['first_chapter']}章；最近推进第{item['last_touched_chapter']}章；账本状态：{item['status']}。{item.get('payoff_plan') or ''}")
    final_arc = next((arc for arc in outline["arcs"] if arc.get("is_final_arc") and arc["end_chapter"] == overall["core_ending_chapter"]), None)
    current = int(store.state().get("current_chapter") or 0)
    if final_arc:
        plans = RollingOutlineStore(store.root).read_rolling_outline() or {"chapters": []}
        for plan in plans["chapters"]:
            number = plan["chapter_number"]
            if final_arc["start_chapter"] <= number <= min(final_arc["end_chapter"], current):
                chapter_path = store.story_system_dir / "chapters" / f"{number:04d}.json"
                chapter = store._read_json(chapter_path, {}) or {}
                add("chapter", f"第{number}章规划与正文", {"plan": plan, "body": evidence_hash(number)},
                    f"规划《{plan['title']}》；正文《{chapter.get('chapter_title') or chapter.get('title') or '未命名'}》。请对照场景和正文后记录结论。")
    return {"items": rows, "version": _hash({"rows": rows, "current": current, "saved": saved}),
            "current_chapter": current, "pending_count": sum(row["disposition"] == "pending" for row in rows)}


def save_ending_audit(store, *, item: dict, base_version: str, assert_allowed=lambda: None) -> dict:
    with project_update_lock(store.root):
        assert_allowed()
        current = read_ending_audit(store)
        if base_version != current["version"]:
            raise ValueError("ending_audit_changed")
        if not any(row["id"] == item.get("id") for row in current["items"]):
            raise ValueError("ending_audit_unknown_item")
        disposition = item.get("disposition")
        if disposition not in {"pending", "resolved", "retained", "expired"}:
            raise ValueError("ending_audit_invalid_disposition")
        note = str(item.get("note") or "").strip()
        chapter = item.get("chapter")
        if len(note) > 2000 or (disposition != "pending" and not note):
            raise ValueError("ending_audit_note_required")
        if chapter is not None and (type(chapter) is not int or not 1 <= chapter <= current["current_chapter"]
                                    or not (store.story_system_dir / "chapters" / f"{chapter:04d}.json").is_file()):
            raise ValueError("ending_audit_invalid_evidence_chapter")
        if disposition == "resolved" and chapter is None:
            raise ValueError("ending_audit_evidence_required")
        path = store.story_system_dir / "ending-audit.json"
        saved = store._read_json(path, {}) or {}
        decisions = dict(saved.get("decisions", {}))
        raw_chapter = store._read_json(store.story_system_dir / "chapters" / f"{chapter:04d}.json", {}) if chapter else {}
        evidence = _hash(store._hydrate_chapter_body(raw_chapter).get("body", "")) if chapter else None
        decisions[item["id"]] = {"disposition": disposition, "chapter": chapter, "note": note, "evidence_hash": evidence}
        store._write_json_atomic(path, {"schema_version": "ending-audit/v1", "decisions": decisions})
        return read_ending_audit(store)
