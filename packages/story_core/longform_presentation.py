"""Read-only author projections. Internal state is never forwarded wholesale."""
from __future__ import annotations
import re
from pathlib import Path
from packages.story_core.book_style import BOOK_STYLE_OPTIONS
from packages.story_core.novel_type_catalog import is_game_story_type


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


def _first_text(value, keys):
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, dict):
        return ""
    for key in keys:
        candidate = value.get(key)
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return ""


def _text_list(value, *, limit=60):
    values = value if isinstance(value, list) else [value]
    result = []
    for item in values:
        if isinstance(item, str) and item.strip() and item.strip() not in result:
            result.append(item.strip())
        elif isinstance(item, dict):
            candidate = _first_text(item, ("text", "summary", "description", "content", "name", "title"))
            if candidate and candidate not in result:
                result.append(candidate)
        if len(result) >= limit:
            break
    return result


def _world_entry(value):
    if isinstance(value, str):
        return {"title": "", "text": value.strip()} if value.strip() else None
    if not isinstance(value, dict):
        return None
    title = _first_text(value, ("name", "title", "label"))
    description = _first_text(value, ("description", "summary", "content", "rule", "overview", "text"))
    if not title and not description:
        return None
    return {"title": title, "text": description or title}


def _world_sections(project, saved_state, *, include_game_catalogs=False):
    blueprint = project.get("world_blueprint") or saved_state.get("world_blueprint") or {}
    if not isinstance(blueprint, dict):
        blueprint = {}
    definitions = (
        ("background", "背景", ("world_background", "background", "world_model", "world_summary")),
        ("rules", "规则", ("world_rules", "core_rules", "world_systems", "economy_rules", "faction_rules", "power_system_spec")),
        ("locations", "地点", ("locations", "location_profiles")),
        ("factions", "势力", ("factions", "faction_profiles")),
        ("equipment", "装备图鉴", ("equipment_cards", "equipment_profiles", "equipment_catalog")),
        ("monsters", "怪物图鉴", ("monster_cards", "monster_profiles", "monster_catalog")),
    )
    sections = []
    seen = set()
    world_summary = text(project.get("world_summary"))
    for key, title, fields in definitions:
        entries = []
        if key == "background" and world_summary:
            entries.append({
                "title": "世界背景", "text": world_summary,
                "sourceField": "@project.world_summary", "sourceIndex": 0,
                "sourceOwner": "project",
            })
            seen.add(world_summary)
        for field in fields:
            raw_values = blueprint.get(field)
            source_owner = "project"
            if raw_values is None:
                raw_values = saved_state.get(field)
                source_owner = "state"
            raw_values = raw_values if isinstance(raw_values, list) else [raw_values]
            for index, raw in enumerate(raw_values[:80]):
                entry = _world_entry(raw)
                if entry is None or entry["text"] in seen:
                    continue
                seen.add(entry["text"])
                entry.update({
                    "sourceField": field,
                    "sourceIndex": index,
                    "sourceOwner": source_owner,
                })
                entries.append(entry)
        if key not in {"equipment", "monsters"} or include_game_catalogs:
            sections.append({"id": key, "title": title, "entries": entries})
    return sections


def _planning_projection(outline, confirmed, *, editable=True):
    overall = outline.get("overall") if isinstance(outline.get("overall"), dict) else {}
    arcs = outline.get("arcs") if isinstance(outline.get("arcs"), list) else []
    volumes = []
    for index, arc in enumerate(arcs):
        if not isinstance(arc, dict):
            continue
        end = arc.get("end_chapter")
        volumes.append({
            "number": index + 1,
            "title": text(arc.get("title")) or f"第 {index + 1} 卷",
            "startChapter": arc.get("start_chapter"),
            "endChapter": end,
            "goal": _first_text(arc, ("goal", "arc_goal", "summary")),
            "mainConflict": _first_text(arc, ("obstacle", "main_conflict", "conflict", "central_conflict")),
            "characterChanges": _text_list(arc.get("character_changes") or arc.get("relationship_changes"), limit=20),
            "endingTurn": _first_text(arc, ("ending_turn", "turning_point", "planned_hook", "next_arc_entry")),
            "statusLabel": "已完成" if isinstance(end, int) and 0 < end <= confirmed else "待创作",
            "editable": bool(editable and not (isinstance(arc.get("start_chapter"), int) and arc["start_chapter"] <= confirmed)),
        })
    chapters = []
    raw_chapters = outline.get("chapters") if isinstance(outline.get("chapters"), list) else []
    for item in raw_chapters:
        if not isinstance(item, dict):
            continue
        number = item.get("chapter_number")
        if not isinstance(number, int) or number <= confirmed:
            continue
        chapters.append({
            "number": number,
            "title": _first_text(item, ("chapter_title", "title")),
            "goal": _first_text(item, ("chapter_goal", "goal", "summary")),
            "conflict": _first_text(item, ("obstacle", "core_conflict", "conflict", "main_conflict")),
            "progression": _first_text(item, ("action", "progression", "next_focus", "outcome")),
            "foreshadowing": _text_list(item.get("foreshadowing") or item.get("foreshadowing_in"), limit=12),
            "editable": bool(editable),
        })
    chapters.sort(key=lambda item: item["number"])
    current_volume = next((
        item["number"] for item in volumes
        if isinstance(item["endChapter"], int) and item["endChapter"] > confirmed
    ), len(volumes) or 1)
    return {
        "editable": bool(editable),
        "overall": {
            "direction": _first_text(overall, ("story", "foreground_story", "direction")),
            "endingGoal": _first_text(overall, ("ending_direction", "ending_image", "ending_goal")),
            "previousConnection": _first_text(overall, ("previous_connection", "opening_context", "continuation_start")),
        },
        "currentVolume": current_volume,
        "volumes": volumes,
        "upcomingChapters": chapters[:12],
        "authorReminders": [
            "已确认章节只供回看；修改仅用于当前候选。",
            "故事事实随逐章确认保存，后续计划不会覆盖前文。",
        ],
    }


_WORLD_LABELS = {
    "current_arc": "当前阶段", "current_focus": "当前焦点", "current_location": "当前地点",
    "location": "当前地点", "time_state": "时间状态", "current_scene_time": "当前场景时间",
    "server_day": "开服天数", "server_phase": "开服阶段", "game_clock": "游戏时间",
    "real_clock": "现实时间", "elapsed_since_launch": "开服时长", "elapsed_minutes_since_launch": "开服分钟数",
    "chapter_time_spans": "章节时间记录", "chapter_number": "章节", "chapter_title": "章节标题",
    "start": "开始时间", "end": "结束时间", "duration_minutes": "持续分钟数",
    "scene_time": "场景时间", "cooldowns": "冷却事项", "scheduled_events": "预定事件",
    "time_rules": "时间规则", "guild_knowledge_state": "公会掌握程度", "chaos_seed_anomaly_score": "混沌之种异常值", "buy_orders": "收购单",
    "sell_orders": "寄售单", "spread_copper": "买卖价差", "sell_pressure": "出售压力",
    "buyer": "买方", "seller": "卖方", "quantity": "数量", "quantity_hint": "预计数量",
    "price_copper": "铜币价格", "bid": "买价", "ask": "卖价", "visibility": "可见范围",
    "visible_at_chapter": "公开章节", "actor": "行动方", "action": "行动", "visible_to": "可见对象",
    "text": "记录", "summary": "概要",
    "pressure": "后续压力", "public_traces": "公开痕迹", "pressure_points": "后续压力",
    "background_events": "幕后变化", "hidden_state": "尚未揭晓的信息",
}

_WORLD_VALUE_LABELS = {
    "localized_batch_pressure": "局部集中出售",
    "normal_newbie_flow": "普通新人交易",
    "village_service_counter": "村庄服务柜台",
    "public_newbie_flow": "新人公开交易",
    "posted_threshold": "公布的收购标准",
    "public_price_board": "公开价格牌",
    "weak_pattern_only": "只掌握到微弱规律",
    "correlated_weak_pattern": "掌握到相互印证的微弱规律",
    "weak": "较弱",
    "correlated": "有关联线索",
    "npc_counter": "人物动态",
    "price_board": "市场信息",
    "phone_notice": "通知",
    "player_chatter": "玩家消息",
}


def _display_scalar(value):
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return str(value)
    if isinstance(value, bool):
        return "是" if value else "否"
    return ""


def _author_value(value):
    scalar = _display_scalar(value)
    if not scalar:
        return ""
    if scalar in _WORLD_VALUE_LABELS:
        return _WORLD_VALUE_LABELS[scalar]
    # A bare machine identifier is not useful author-facing state. Known
    # identifiers are translated above; prose and numeric values pass through.
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*(?:_[A-Za-z0-9]+)+", scalar):
        return ""
    return scalar


def _state_entries(value):
    entries = []
    if not isinstance(value, dict):
        return entries
    for key, raw in value.items():
        label = _WORLD_LABELS.get(key)
        if not label:
            continue
        if key == "market_order_book":
            entries.extend(_market_view(raw))
            continue
        scalar = _author_value(raw)
        if scalar:
            entries.append({"label": label, "value": scalar})
        elif isinstance(raw, dict):
            entries.extend(_state_entries(raw))
        elif isinstance(raw, list):
            values = []
            for item in raw:
                if isinstance(item, dict):
                    line = _first_text(item, ("text", "summary", "action", "description", "name"))
                else:
                    line = _author_value(item)
                if line:
                    values.append(line)
            if values:
                entries.append({"label": label, "value": "、".join(values)})
    return entries


def _market_orders(value, *, side):
    if not isinstance(value, list):
        return []
    role_key = "buyer" if side == "buy" else "seller"
    role_label = "收购方" if side == "buy" else "出售方"
    amount_key = "quantity" if side == "buy" else "quantity_hint"
    amount_label = "收购数量" if side == "buy" else "预计出售数量"
    result = []
    for order in value:
        if not isinstance(order, dict):
            continue
        parts = []
        role = _author_value(order.get(role_key))
        if role:
            parts.append(f"{role_label}：{role}")
        amount = order.get(amount_key)
        if isinstance(amount, (int, float)) and not isinstance(amount, bool):
            parts.append(f"{amount_label}：{amount}")
        price = order.get("price_copper")
        if isinstance(price, (int, float)) and not isinstance(price, bool):
            parts.append(f"价格：{price} 铜币")
        visibility = _author_value(order.get("visibility"))
        if visibility:
            parts.append(f"可见范围：{visibility}")
        if parts:
            result.append("；".join(parts))
    return result


def _market_view(value):
    if not isinstance(value, dict):
        return []
    entries = []
    buy_orders = _market_orders(value.get("buy_orders"), side="buy")
    sell_orders = _market_orders(value.get("sell_orders"), side="sell")
    if buy_orders:
        entries.append({"label": "收购单", "value": "；".join(buy_orders)})
    if sell_orders:
        entries.append({"label": "寄售单", "value": "；".join(sell_orders)})
    spread = value.get("spread_copper")
    if isinstance(spread, dict):
        bid, ask = spread.get("bid"), spread.get("ask")
        if all(isinstance(item, (int, float)) and not isinstance(item, bool) for item in (bid, ask)):
            entries.append({"label": "买卖价格", "value": f"买入 {bid} 铜币；卖出 {ask} 铜币"})
    pressure = _author_value(value.get("sell_pressure"))
    if pressure:
        entries.append({"label": "出售压力", "value": pressure})
    return entries


def _event_entries(value):
    result = []
    for item in value if isinstance(value, list) else []:
        if isinstance(item, str):
            line = item.strip()
            visibility = ""
        elif isinstance(item, dict):
            line = _first_text(item, ("text", "summary", "description", "action", "content"))
            visibility = "、".join(_author_value(value) for value in _text_list(
                item.get("visible_to") or item.get("audience") or item.get("who"), limit=12
            ) if _author_value(value))
            channel = item.get("channel")
            if not visibility and isinstance(channel, str):
                visibility = _author_value(channel)
        else:
            continue
        if line:
            entry = {"text": line}
            if visibility:
                entry["whoCanKnow"] = visibility
            result.append(entry)
    return result


def _dynamic_world_view(store, snapshot, confirmed, selected_chapter):
    snapshot_entries = _state_entries(snapshot)
    chapters = []
    selected_payload = None
    latest_payload = None
    for number in store.chapter_numbers():
        if number > confirmed:
            continue
        path = store.story_system_dir / "chapters" / f"{number:04d}.json"
        payload = store.snapshot_store.read_json(path, {})
        if not isinstance(payload, dict):
            continue
        simulation = payload.get("simulation_status")
        has_record = isinstance(simulation, dict) and bool(simulation)
        if has_record:
            chapters.append({
                "number": number,
                "title": text(payload.get("chapter_title")) or f"第 {number} 章",
            })
            latest_payload = (number, payload)
        if number == selected_chapter:
            selected_payload = (number, payload)

    def product_record(number, payload):
        simulation = payload.get("simulation_status") if isinstance(payload.get("simulation_status"), dict) else {}
        pulse_store = simulation.get("world_pulse") if isinstance(simulation.get("world_pulse"), dict) else {}
        pulse = pulse_store.get("latest") if isinstance(pulse_store.get("latest"), dict) else {}
        inbox = simulation.get("visibility_inbox") or pulse.get("visibility_inbox")
        chapter_summary = payload.get("chapter_summary") if isinstance(payload.get("chapter_summary"), dict) else {}
        market = pulse.get("market_order_book") if isinstance(pulse.get("market_order_book"), dict) else {}
        result = {
            "chapter": number,
            "summary": text(pulse.get("summary")) or text(chapter_summary.get("summary")),
            "publicChanges": _event_entries(pulse.get("public_traces")),
            "nextPressures": _event_entries(pulse.get("pressure_points")),
            "nextChapterInformation": _event_entries(inbox),
            "backgroundEvents": _event_entries(pulse.get("background_events")),
            "authorVisibleUnknowns": _state_entries(pulse.get("hidden_state")),
            "marketMovements": _market_view(market),
        }
        if not any(result[key] for key in (
            "summary", "publicChanges", "nextPressures", "nextChapterInformation",
            "backgroundEvents", "authorVisibleUnknowns", "marketMovements",
        )):
            return None
        return result

    record = product_record(*selected_payload) if selected_payload else None
    preparation = None
    if latest_payload:
        latest_number, latest = latest_payload
        latest_record = product_record(latest_number, latest)
        if latest_record and latest_record["nextChapterInformation"]:
            preparation = {
                "sourceChapter": latest_number,
                "entries": latest_record["nextChapterInformation"],
            }
    return {
        "currentSnapshot": {"chapter": confirmed or None, "entries": snapshot_entries},
        "availableChapters": chapters,
        "selectedChapter": selected_chapter,
        "chapterRecord": record,
        "preparationInformation": preparation,
        "emptyMessage": "暂无记录" if record is None else "",
    }


def _person_views(project, state, facts_by_person, fact_sources):
    profiles = project.get("character_profiles") if isinstance(project.get("character_profiles"), list) else []
    current = state.get("characters") if isinstance(state.get("characters"), list) else []
    profile_by_name = {text(item.get("name")): item for item in profiles if isinstance(item, dict) and text(item.get("name"))}
    current_by_name = {text(item.get("name")): item for item in current if isinstance(item, dict) and text(item.get("name"))}
    names = list(profile_by_name)
    names.extend(name for name in current_by_name if name not in profile_by_name)
    result = []
    for name in names:
        profile = profile_by_name.get(name, {})
        live = current_by_name.get(name, {})
        identity = profile.get("identity_profile") if isinstance(profile.get("identity_profile"), dict) else {}
        drive = profile.get("story_drive") if isinstance(profile.get("story_drive"), dict) else {}
        portrayal = profile.get("performance_profile") if isinstance(profile.get("performance_profile"), dict) else {}
        facts = list(facts_by_person.get(name, []))
        for memory in live.get("memory") or []:
            if isinstance(memory, str) and memory in fact_sources:
                evidence = {"text": memory, "chapter": fact_sources[memory]}
                if evidence not in facts:
                    facts.append(evidence)
        stable = {
            "identity": text(identity.get("current_identity")) or text(profile.get("identity")),
            "occupation": text(identity.get("occupation")) or text(profile.get("occupation")),
            "motivation": text(drive.get("motivation")) or text(profile.get("core_motivation")),
            "goal": text(drive.get("long_term_goal")) or text(profile.get("goal")),
            "personality": text(profile.get("personality")),
            "appearance": text(profile.get("appearance")),
            "background": text(profile.get("background")),
        }
        stable = {key: value for key, value in stable.items() if value}
        current_state = {
            key: text(live.get(source))
            for key, source in (("location", "location"), ("condition", "condition"), ("emotion", "emotion"), ("currentGoal", "current_goal"))
            if text(live.get(source))
        }
        future = []
        for key in ("future_plan", "future_plans", "future_intent", "development_arc", "next_goal"):
            future.extend(_text_list(profile.get(key), limit=10))
        performance = [text(portrayal.get(key)) for key in ("speech_style", "action_style", "risk_posture") if text(portrayal.get(key))]
        performance.extend(item for key in ("emotional_triggers", "decision_rules", "reveal_limits") for item in _text_list(portrayal.get(key), limit=12))
        performance.extend(_text_list(profile.get("dialogue_examples"), limit=8))
        identity_profile = profile.get("identity_profile") if isinstance(profile.get("identity_profile"), dict) else {}
        background_profile = profile.get("background_profile") if isinstance(profile.get("background_profile"), dict) else {}
        drive_profile = profile.get("story_drive") if isinstance(profile.get("story_drive"), dict) else {}
        editable_profile = {
            "identityProfile": {
                "age": identity_profile.get("age") if isinstance(identity_profile.get("age"), int) else None,
                "gender": text(identity_profile.get("gender")),
                "aliases": _text_list(identity_profile.get("aliases"), limit=20),
                "birthplace": text(identity_profile.get("birthplace")),
                "origin": text(identity_profile.get("origin")),
                "currentIdentity": text(identity_profile.get("current_identity")),
                "occupation": text(identity_profile.get("occupation")),
                "affiliation": text(identity_profile.get("affiliation")),
            },
            "backgroundProfile": {
                "family": text(background_profile.get("family")),
                "upbringing": text(background_profile.get("upbringing")),
                "educationOrTraining": text(background_profile.get("education_or_training")),
                "formativeEvents": _text_list(background_profile.get("formative_events"), limit=30),
                "arrivalReason": text(background_profile.get("arrival_reason")),
            },
            "storyDrive": {
                "longTermGoal": text(drive_profile.get("long_term_goal")),
                "immediateGoal": text(drive_profile.get("immediate_goal")),
                "motivation": text(drive_profile.get("motivation") or profile.get("core_motivation")),
                "failureStakes": text(drive_profile.get("failure_stakes")),
                "hiddenMatters": _text_list(drive_profile.get("hidden_matters"), limit=30),
                "mainConflictReason": text(drive_profile.get("main_conflict_reason")),
            },
            "performanceProfile": {
                "speechStyle": text(portrayal.get("speech_style") or profile.get("speech_style")),
                "actionStyle": text(portrayal.get("action_style")),
                "riskPosture": text(portrayal.get("risk_posture")),
                "emotionalTriggers": _text_list(portrayal.get("emotional_triggers"), limit=30),
                "decisionRules": _text_list(portrayal.get("decision_rules"), limit=30),
                "revealLimits": _text_list(portrayal.get("reveal_limits"), limit=30),
            },
            "dialogueExamples": _text_list(profile.get("dialogue_examples"), limit=20),
            "futurePlans": list(dict.fromkeys(future)),
        }
        identity_text = "\n".join(stable.values())
        description = identity_text or text(profile.get("description")) or text(profile.get("summary"))
        result.append({
            "name": name,
            "role": person_role(profile.get("role") or live.get("role")),
            "description": description,
            "stableProfile": stable,
            "currentState": current_state,
            "facts": facts,
            "performance": performance,
            "futurePlans": list(dict.fromkeys(future)),
            "editableProfile": editable_profile,
        })
    return result


def project_content(store, *, future_intent=None, selected_chapter=None, planning_editable=True):
    # Read the authoritative file without triggering the legacy Markdown sync.
    outline = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
    project = store.project()
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
    planning = _planning_projection(outline, confirmed, editable=planning_editable)
    volumes = [{"number": item["number"], "title": item["title"], "start": item["startChapter"],
                "end": item["endChapter"], "goal": item["goal"], "label": item["statusLabel"],
                "conflict": item["mainConflict"], "characterChanges": item["characterChanges"],
                "endingTurn": item["endingTurn"]} for item in planning["volumes"]]
    people = _person_views(project, state, facts_by_person, fact_sources)
    known_people = {person["name"] for person in people}
    for subject, records in facts_by_person.items():
        if subject not in known_people:
            world_records.extend({"title": subject, **record} for record in records)
    selected_type = genre_id(project, state)
    world_sections = _world_sections(
        project,
        saved_state,
        include_game_catalogs=is_game_story_type({"genre_plugin_ids": [selected_type]}),
    )
    world = [{"title": section["title"], "text": item["text"]}
             for section in world_sections for item in section["entries"]]
    for key, title in (("world_facts", "世界事实"), ("world_rules", "世界规则")):
        values = saved_state.get(key) or []
        if isinstance(values, list):
            for value in values:
                if isinstance(value, str) and value.strip() and value not in {item["text"] for item in world}:
                    world.append({"title": title, "text": value.strip()})
    world.extend(world_records)
    foreshadow = []
    foreshadow_view = []
    for item in store.foreshadowing_ledger():
        data = item.model_dump() if hasattr(item, "model_dump") else item
        status_label = {
            "open": "待回应", "reinforced": "已强化", "resolved": "已回收", "expired": "已过期",
        }.get(data.get("status"), "待检查")
        first_chapter = data.get("first_chapter")
        last_touched = data.get("last_touched_chapter")
        resolved_chapter = data.get("resolved_chapter")
        entry = {"title": status_label, "text": text(data.get("text"))}
        if isinstance(first_chapter, int) and first_chapter in existing:
            entry["chapter"] = first_chapter
        foreshadow.append(entry)
        foreshadow_view.append({
            "text": text(data.get("text")),
            "statusLabel": status_label,
            "firstChapter": first_chapter if isinstance(first_chapter, int) and first_chapter in existing else None,
            "lastTouchedChapter": last_touched if isinstance(last_touched, int) and last_touched in existing else None,
            "resolvedChapter": resolved_chapter if isinstance(resolved_chapter, int) and resolved_chapter in existing else None,
            "payoffPlan": text(data.get("payoff_plan")),
            "editable": True,
        })
        if text(data.get("payoff_plan")):
            foreshadow.append({"title": "后续回应计划", "text": data["payoff_plan"]})
    confirmed_world_facts = [
        {"text": item["text"], "chapter": item.get("chapter")}
        for item in world_records if item.get("text")
    ]
    for key, title in (("world_facts", "世界事实"), ("world_rules", "世界规则")):
        for value in saved_state.get(key) or []:
            if isinstance(value, str) and value in fact_sources:
                confirmed_world_facts.append({"text": value, "chapter": fact_sources[value]})
    selected = confirmed if selected_chapter is None or selected_chapter > confirmed else max(0, int(selected_chapter))
    snapshot = state.get("world_snapshot") if isinstance(state.get("world_snapshot"), dict) else {}
    arcs = outline.get("arcs") if isinstance(outline.get("arcs"), list) else []
    relationships = []
    for edge in project.get("relationship_graph") or []:
        if not isinstance(edge, dict):
            continue
        source, target = text(edge.get("source")), text(edge.get("target"))
        if not source or not target or source == target:
            continue
        changed_at = edge.get("last_changed_chapter")
        relationships.append({
            "id": text(edge.get("id")), "source": source, "target": target,
            "relationship": text(edge.get("relation_type")) or text(edge.get("bond")),
            "history": text(edge.get("origin")), "currentState": text(edge.get("current_state")),
            "sharedInterestOrConflict": text(edge.get("shared_interest_or_conflict")),
            "trust": edge.get("trust") if isinstance(edge.get("trust"), (int, float)) else None,
            "tension": edge.get("tension") if isinstance(edge.get("tension"), (int, float)) else None,
            "basisLabel": (
                "已确认章节" if isinstance(changed_at, int) and changed_at in existing
                else "来源章节已不可用" if isinstance(changed_at, int) and changed_at > 0
                else "作者设定"
            ),
            "evidenceChapter": changed_at if isinstance(changed_at, int) and changed_at in existing else None,
        })
    requirements = project.get("author_constraints") or saved_state.get("author_constraints") or []
    future = text(future_intent) if future_intent is not None else text(overall.get("expansion_route"))
    return {"plan": text(overall.get("story")) or text(overall.get("foreground_story")),
            "future": future,
            "ending": text(overall.get("ending_direction")) or text(overall.get("ending_image")),
            "volumes": volumes, "planningVolume": next((v["number"] for v in volumes if (v["end"] or 0) > confirmed), len(volumes) or 1),
            "upcoming": [{"number": item["chapter_number"], "title": text(item.get("title")), "summary": text(item.get("goal"))}
                         for item in outline.get("chapters") or [] if isinstance(item, dict) and int(item.get("chapter_number") or 0) > confirmed][:12],
            "connections": [{"text": text(arc.get("next_arc_entry"))} for arc in arcs if isinstance(arc, dict) and arc.get("next_arc_entry")],
            "planning": planning,
            "people": people, "world": world, "worldSections": world_sections,
            "relationships": relationships, "dynamicWorld": _dynamic_world_view(store, snapshot, confirmed, selected),
            "confirmedWorldFacts": confirmed_world_facts,
            "foreshadow": foreshadow, "foreshadowing": foreshadow_view,
            "authorRequirements": {"constraints": _text_list(requirements, limit=100), "futureIntent": future},
            "reminders": ["已确认章节只供回看；修改仅用于当前候选。", "故事事实随逐章确认保存，后续计划不会覆盖前文。"]}


def book_details(store):
    project = store.project()
    state = store.state()
    assets = store.publishing_assets()
    synopsis = assets.get("synopsis") if isinstance(assets.get("synopsis"), dict) else {}
    cover = assets.get("cover") if isinstance(assets.get("cover"), dict) else {}
    confirmed = max(0, int(state.get("current_chapter") or 0))
    confirmed_numbers = [number for number in store.chapter_numbers() if number <= confirmed]
    total_chars = 0
    complete_count = 0
    for number in confirmed_numbers:
        payload = store.snapshot_store.read_json(store.story_system_dir / "chapters" / f"{number:04d}.json", {})
        if not isinstance(payload, dict):
            continue
        cached = payload.get("body_chars")
        if isinstance(cached, int) and not isinstance(cached, bool) and cached >= 0:
            total_chars += cached
            complete_count += 1
            continue
        body = payload.get("body")
        if isinstance(body, str):
            total_chars += len("".join(body.split()))
            complete_count += 1
            continue
        relative = payload.get("body_path")
        if isinstance(relative, str) and relative.strip():
            candidate = (store.root / Path(relative)).resolve()
            root = store.root.resolve()
            if candidate.is_relative_to(root) and candidate.is_file():
                try:
                    total_chars += len("".join(candidate.read_text(encoding="utf-8").split()))
                    complete_count += 1
                except OSError:
                    pass
    lifecycle = project.get("project_lifecycle") or "active"
    lifecycle_label = {"active": "创作中", "archived": "已归档", "trashed": "回收站"}.get(lifecycle, "可查看")
    blueprint = project.get("world_blueprint") if isinstance(project.get("world_blueprint"), dict) else {}
    synopsis_body = text(synopsis.get("body"))
    cover_file = store.root / "assets" / "cover.png"
    return {
        "title": text(project.get("title")),
        "synopsis": synopsis_body,
        "synopsisTags": _text_list(synopsis.get("tags"), limit=30),
        "coverAvailable": bool(cover.get("rendered_path") == "assets/cover.png" and cover_file.is_file()),
        "targetWords": project.get("target_words") if isinstance(project.get("target_words"), int) else None,
        "targetChapterWords": project.get("target_chapter_words") if isinstance(project.get("target_chapter_words"), int) else None,
        "confirmedChapterCount": len(confirmed_numbers),
        "confirmedWordCount": total_chars if complete_count == len(confirmed_numbers) else None,
        "chapterCountComplete": complete_count == len(confirmed_numbers),
        "currentChapter": confirmed,
        "lifecycleLabel": lifecycle_label,
        "authorRequirements": _text_list(project.get("author_constraints") or state.get("author_constraints"), limit=100),
        "novelTypeId": genre_id(project, state),
        "writingStyle": text(blueprint.get("writing_style") or blueprint.get("style")),
        "writingStyleOptions": list(BOOK_STYLE_OPTIONS),
    }
