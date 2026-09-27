"""Read-only author projections. Internal state is never forwarded wholesale."""
from __future__ import annotations


def text(value):
    return value if isinstance(value, str) else ""


def project_content(store):
    # Read the authoritative file without triggering the legacy Markdown sync.
    outline = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
    overall = outline.get("overall") or {}
    state = store.state()
    confirmed = int(state.get("current_chapter") or 0)
    arcs = outline.get("arcs") or []
    volumes = [{"number": index + 1, "title": text(arc.get("title")) or f"第 {index + 1} 卷",
                "start": arc.get("start_chapter"), "end": arc.get("end_chapter"),
                "goal": text(arc.get("goal")), "label": "已完成" if int(arc.get("end_chapter") or 0) <= confirmed else "待创作"}
               for index, arc in enumerate(arcs) if isinstance(arc, dict)]
    people = []
    for person in state.get("characters") or []:
        if not isinstance(person, dict):
            continue
        facts = []
        # Memory has no dependable chapter provenance: do not invent citations.
        for item in person.get("memory") or []:
            if isinstance(item, str):
                facts.append({"text": item})
        people.append({"name": text(person.get("name")), "role": text(person.get("role")),
                       "description": text(person.get("core_motivation")) or text(person.get("story_function")),
                       "facts": facts, "performance": [item for item in person.get("dialogue_examples") or [] if isinstance(item, str)]})
    world = []
    for key, title in (("world_facts", "已写入的世界事实"), ("world_rules", "世界规则"), ("canon_facts", "已写入的事实")):
        values = state.get(key) or []
        if isinstance(values, list):
            world.extend({"title": title, "text": value} for value in values if isinstance(value, str))
    foreshadow = []
    for item in store.foreshadowing_ledger():
        data = item.model_dump() if hasattr(item, "model_dump") else item
        entry = {"title": "已回收" if data.get("resolved_chapter") else "待回应", "text": text(data.get("text"))}
        number = data.get("first_chapter")
        if isinstance(number, int) and 0 < number <= confirmed:
            entry["chapter"] = number
        foreshadow.append(entry)
    return {"plan": text(overall.get("story")) or text(overall.get("foreground_story")),
            "future": text(overall.get("expansion_route")),
            "ending": text(overall.get("ending_direction")) or text(overall.get("ending_image")),
            "volumes": volumes, "planningVolume": next((v["number"] for v in volumes if (v["end"] or 0) > confirmed), len(volumes) or 1),
            "upcoming": [{"number": item["chapter_number"], "title": text(item.get("title")), "summary": text(item.get("goal"))}
                         for item in outline.get("chapters") or [] if isinstance(item, dict) and int(item.get("chapter_number") or 0) > confirmed][:12],
            "connections": [{"text": text(arc.get("next_arc_entry"))} for arc in arcs if isinstance(arc, dict) and arc.get("next_arc_entry")],
            "people": people, "world": world, "foreshadow": foreshadow,
            "reminders": ["已确认章节只供回看；修改仅用于当前候选。", "故事事实随逐章确认保存，后续计划不会覆盖前文。"]}
