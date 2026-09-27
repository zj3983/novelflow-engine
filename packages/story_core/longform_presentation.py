"""Read-only author projections. Internal state is never forwarded wholesale."""
from __future__ import annotations
import re


def text(value):
    return value if isinstance(value, str) else ""


def person_role(value):
    known = {"protagonist": "主角", "antagonist": "对手", "supporting": "配角", "minor": "其他人物"}
    role = text(value)
    return known.get(role, role if re.search(r"[\u4e00-\u9fff]", role) else "人物")


def opening_content(store):
    """Do not call the legacy brief getter: it may create missing files."""
    brief = store.snapshot_store.read_json(store.webnovel_dir / "opening_brief.json", {})
    directions = store.snapshot_store.read_json(store.webnovel_dir / "opening_directions.json", {}) or {}
    return {"brief": brief, "directions": [d for d in directions.get("directions", []) if isinstance(d, dict)],
            "selected_id": directions.get("selected_id")}


def genre_id(project, state=None):
    blueprint = project.get("world_blueprint") or {}
    ids = blueprint.get("genre_plugin_ids") or (state or {}).get("genre_plugin_ids") or []
    return text(ids[0]) if ids else text(project.get("novel_type_id"))


def project_content(store):
    # Read the authoritative file without triggering the legacy Markdown sync.
    outline = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
    overall = outline.get("overall") or {}
    state = store.state()
    saved_state = store.snapshot_store.read_json(store.webnovel_dir / "state.json", {}) or {}
    confirmed = int(state.get("current_chapter") or 0)
    old_state = store.snapshot_store.read_json(store.story_system_dir / "continuity" / "stale.json", {}) or {}
    unavailable = set(n for n in old_state.get("chapters", []) if isinstance(n, int))
    existing = {n for n in store.chapter_numbers() if n <= confirmed and n not in unavailable}
    latest = store.snapshot_store.read_json(store.story_system_dir / "continuity" / "snapshots" / f"{confirmed:04d}.json", {})
    established = latest.get("state_after") or saved_state
    fact_sources = {}
    for summary in established.get("chapter_summaries") or []:
        if isinstance(summary, dict) and summary.get("chapter_number") in existing:
            for fact in summary.get("facts") or []:
                if isinstance(fact, str):
                    fact_sources.setdefault(fact, summary["chapter_number"])
    def evidence(value, chapter=None):
        item = {"text": value}
        source = chapter if isinstance(chapter, int) and chapter in existing else fact_sources.get(value)
        if source is not None:
            item["chapter"] = source
        return item
    facts_by_person = {}
    world_records = []
    for fact in established.get("continuity_facts") or []:
        if not isinstance(fact, dict):
            continue
        value = text(fact.get("value")) or text(fact.get("fact")) or text(fact.get("text"))
        number = fact.get("chapter_number", fact.get("chapter"))
        if not value or isinstance(number, int) and number > confirmed:
            continue
        item = evidence(value, number)
        if text(fact.get("subject")):
            facts_by_person.setdefault(fact["subject"], []).append(item)
        else:
            world_records.append({"title": "故事记录", **item})
    arcs = outline.get("arcs") or []
    volumes = [{"number": index + 1, "title": text(arc.get("title")) or f"第 {index + 1} 卷",
                "start": arc.get("start_chapter"), "end": arc.get("end_chapter"),
                "goal": text(arc.get("goal")), "label": "已完成" if 0 < int(arc.get("end_chapter") or 0) <= confirmed else "待创作"}
               for index, arc in enumerate(arcs) if isinstance(arc, dict)]
    people = []
    for person in state.get("characters") or []:
        if not isinstance(person, dict):
            continue
        facts = list(facts_by_person.get(text(person.get("name")), []))
        # Only a matching confirmed chapter summary gives memory a citation.
        for item in person.get("memory") or []:
            if isinstance(item, str) and item in fact_sources:
                facts.append(evidence(item))
        identity = person.get("identity_profile") or {}
        drive = person.get("story_drive") or {}
        portrayal = person.get("performance_profile") or {}
        performance = [text(portrayal.get(key)) for key in ("speech_style", "action_style", "risk_posture") if text(portrayal.get(key))]
        performance.extend(item for key in ("emotional_triggers", "decision_rules", "reveal_limits") for item in portrayal.get(key) or [] if isinstance(item, str))
        performance.extend(item for item in person.get("dialogue_examples") or [] if isinstance(item, str))
        people.append({"name": text(person.get("name")), "role": person_role(person.get("role")),
                       "description": "\n".join(v for v in (text(identity.get("current_identity")), text(identity.get("occupation")), text(drive.get("motivation")) or text(person.get("core_motivation")), text(person.get("story_function"))) if v),
                       "facts": facts, "performance": performance})
    world = list(world_records)
    if text(store.project().get("world_summary")):
        world.append({"title": "世界背景设定", "text": store.project()["world_summary"]})
    known_people = {person["name"] for person in people}
    for subject, records in facts_by_person.items():
        if subject not in known_people:
            world.extend({"title": subject, **record} for record in records)
    for key, title in (("world_facts", "世界设定"), ("world_rules", "世界规则")):
        values = saved_state.get(key) or []
        if isinstance(values, list):
            world.extend({"title": "已写入的事实" if value in fact_sources else title, **evidence(value)} for value in values if isinstance(value, str))
    foreshadow = []
    for item in store.foreshadowing_ledger():
        data = item.model_dump() if hasattr(item, "model_dump") else item
        entry = {"title": "已回收" if data.get("resolved_chapter") else "待回应", "text": text(data.get("text"))}
        number = data.get("first_chapter")
        if isinstance(number, int) and number in existing:
            entry["chapter"] = number
        foreshadow.append(entry)
        if text(data.get("payoff_plan")):
            foreshadow.append({"title": "后续回应计划", "text": data["payoff_plan"]})
    return {"plan": text(overall.get("story")) or text(overall.get("foreground_story")),
            "future": text(overall.get("expansion_route")),
            "ending": text(overall.get("ending_direction")) or text(overall.get("ending_image")),
            "volumes": volumes, "planningVolume": next((v["number"] for v in volumes if (v["end"] or 0) > confirmed), len(volumes) or 1),
            "upcoming": [{"number": item["chapter_number"], "title": text(item.get("title")), "summary": text(item.get("goal"))}
                         for item in outline.get("chapters") or [] if isinstance(item, dict) and int(item.get("chapter_number") or 0) > confirmed][:12],
            "connections": [{"text": text(arc.get("next_arc_entry"))} for arc in arcs if isinstance(arc, dict) and arc.get("next_arc_entry")],
            "people": people, "world": world, "foreshadow": foreshadow,
            "reminders": ["已确认章节只供回看；修改仅用于当前候选。", "故事事实随逐章确认保存，后续计划不会覆盖前文。"]}
