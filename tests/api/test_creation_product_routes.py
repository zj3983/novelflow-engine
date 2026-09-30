from copy import deepcopy
import json
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.creation_product import init_creation_product_routes
from apps.api.routes import file_projects
from apps.api.routes.longform_product import init_longform_product_routes
from apps.api.routes.novel_types import init_novel_type_routes
from packages.story_core import product_presentation as product
from tests.api.test_build_workbench_edit_route import _setup_project, _wait_orchestration
from tests.story_core.test_opening_prose import prepared_store, FakeEngine


BASE = "/file-projects/p-synthetic-build-edit/product"
INTERNAL = {"artifact", "revision", "diagnostics", "preflight", "provenance", "provider", "protocol",
            "capabilities", "schema_version", "quality_report", "task_id", "graph_revision", "context_snapshot_id"}


def test_planning_fields_keep_internal_enums_out_and_preserve_them_on_save():
    payload = {"title": "新故事", "status": "ready", "source": "custom",
               "new_internal_flag": "enabled", "unknown_list": ["core", "major"],
               "characters": [{"name": "林照", "role": "protagonist",
                               "importance": "core", "narrative_function": "other",
                               "goal": "查清旧案"}],
               "hard_constraints": ["不可改写已确认事实"],
               "must_not_write": ["不可提前揭晓幕后人"]}
    fields, paths = product.editable_fields(payload, lambda p: json.dumps(p))
    visible = json.dumps(fields, ensure_ascii=False)
    for value in ("ready", "custom", "enabled", "protagonist", "core", "major", "other"):
        assert value not in visible
    assert "不可改写已确认事实" in visible
    assert "不可提前揭晓幕后人" in visible
    title = next(f for f in fields if f["label"] == "标题")
    edited = product.apply_fields(payload, paths, {title["key"]: "修改书名"})
    assert edited == {**payload, "title": "修改书名"}


def client_for(monkeypatch):
    monkeypatch.setattr(file_projects, "router", APIRouter())
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_creation_product_routes())
    return TestClient(app)


def tree(store):
    return {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


def test_longform_planning_projection_reuses_snapshot_without_changing_actions(tmp_path, monkeypatch):
    from apps.api.routes import creation_product
    from apps.api.routes.longform_product import PlanningScreen
    from packages.story_core.persistence.project_locking import project_update_lock

    store = prepared_store(tmp_path)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    client = client_for(monkeypatch)
    request = SimpleNamespace(app=client.app)
    baseline = creation_product.Screen(request, "p-synthetic-build-edit")
    baseline.prepare_build()
    with project_update_lock(store.root):
        expected = baseline.build(all_actions=True)
    original = creation_product._handler
    calls = []

    def observed(http_request, name, **kwargs):
        calls.append(name)
        return original(http_request, name, **kwargs)

    monkeypatch.setattr(creation_product, "_handler", observed)
    screen = PlanningScreen(request, "p-synthetic-build-edit")
    screen.prepare_build()
    before = tree(store)
    with project_update_lock(store.root):
        actual = screen.build(all_actions=True)
    assert actual == expected
    assert set(screen.actions) == set(baseline.actions)
    assert calls.count("get_file_project_build_graph") == 1
    assert "get_file_project_build_graph_task" not in calls
    assert tree(store) == before


def test_next_chapter_visibility_uses_only_the_latest_confirmed_chapter(tmp_path):
    from packages.story_core.longform_presentation import _dynamic_world_view

    chapter_dir = tmp_path / "chapters"
    payloads = {
        chapter_dir / "0001.json": {
            "chapter_title": "旧安排",
            "simulation_status": {"visibility_inbox": ["上一章才适用的消息"]},
        },
        chapter_dir / "0002.json": {"chapter_title": "最新确认章"},
    }
    store = SimpleNamespace(
        chapter_numbers=lambda: [1, 2],
        story_system_dir=tmp_path,
        snapshot_store=SimpleNamespace(read_json=lambda path, default: payloads.get(path, default)),
    )

    result = _dynamic_world_view(store, {}, confirmed=2, selected_chapter=2)

    assert result["preparationInformation"] is None


def test_opening_workspace_saves_planning_edits_to_graph_artifacts(tmp_path, monkeypatch):
    from tests.story_core.test_opening_build import complete_opening, opening_store
    from packages.story_core.opening_build import runtime

    store, graph, service = opening_store(tmp_path)
    complete_opening(store, graph, service)
    runtime.publish(store, graph, service, runtime.source_revision(store))
    project_id = store.project()["project_id"]
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: project_id)
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)

    current = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    assert current["actions"]["plan"]["enabled"] is True
    assert current["planning"]["editable"] is True
    assert current["planning"]["graphManaged"] is True
    assert current["planning"]["overall"]["editable"] is True
    assert current["planning"]["upcomingChapters"][0]["editable"] is True

    chapter = current["planning"]["upcomingChapters"][0]
    saved_chapter = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": current["actions"]["plan"]["token"],
        "command": {
            "type": "plan",
            "scope": f"chapter:{chapter['number']}",
            "patch": {"upcomingChapters": [{"number": chapter["number"], "goal": "從四頁工作台修改的目標"}]},
        },
    })
    assert saved_chapter.status_code == 200, saved_chapter.text
    chapter_artifact = store.build_graph_store().read_artifact(f"chapter_outline_{chapter['number']}")
    assert chapter_artifact.payload["chapter"]["goal"] == "從四頁工作台修改的目標"
    assert service.inspect_task("outline_execution_contract").status == "stale"
    assert service.inspect_task("chapter_outline_1").status == "completed"

    refreshed = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    assert refreshed["actions"]["plan"]["enabled"] is True
    assert refreshed["planning"]["overall"]["editable"] is True
    saved_overall = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": refreshed["actions"]["plan"]["token"],
        "command": {
            "type": "plan",
            "scope": "overall",
            "patch": {"overall": {"direction": "四页工作台保存的全书方向"}},
        },
    })
    assert saved_overall.status_code == 200, saved_overall.text
    outline_artifact = store.build_graph_store().read_artifact("book_outline")
    assert outline_artifact.payload["overall"]["story"] == "四页工作台保存的全书方向"
    assert service.inspect_task("volume_plan").status == "stale"


def test_author_workspace_api_projects_product_sections_from_existing_sources(tmp_path, monkeypatch):
    from packages.story_core.opening_build import runtime

    store = prepared_store(tmp_path)
    names = ["林照", "陆遥", "赵衡", "顾长老"]
    store.update_project({
        "title": "河灯录",
        "world_summary": "渡口诸城依水运商路往来。",
        "author_constraints": ["不提前揭示兄长失踪真相"],
        "relationship_graph": [{
            "source": "林照", "target": "陆遥", "relation_type": "互相试探",
            "current_state": "暂时合作", "last_changed_chapter": 0,
        }],
        "character_profiles": [
            {"name": name, "role": "protagonist" if index == 0 else "supporting",
             "identity_profile": {"current_identity": f"身份{index}"},
             "story_drive": {"motivation": f"动机{index}"}}
            for index, name in enumerate(names)
        ],
        "world_blueprint": {
            "world_rules": ["水路每旬封航一日。"],
            "locations": [{"name": "南渡口", "description": "旧商路的转运处。"}],
            "factions": [{"name": "巡河司", "description": "负责水路治安。"}],
            "writing_style": "冷峻",
        },
    })
    state = store.state()
    state["current_chapter"] = 1
    state["characters"] = [{"name": "林照", "role": "protagonist", "location": "南渡口", "memory": []}]
    state["world_snapshot"] = {"current_focus": "查找失踪的货船", "time_state": {"current_scene_time": "暮春"}, "internal_counter": 911}
    state_path = store.webnovel_dir / "state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    chapter_dir = store.story_system_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    (chapter_dir / "0001.json").write_text(json.dumps({
        "chapter_number": 1,
        "chapter_title": "夜船",
        "body": "林照登上夜船，发现货单已被改写。",
        "simulation_status": {"world_pulse": {"latest": {
            "summary": "码头出现新的收购价。",
            "public_traces": [{"text": "柜台调整了收购价。", "visible_to": ["public_price_board", "npc_counter"]}],
            "hidden_state": {"chaos_seed_anomaly_score": 3,
                             "guild_knowledge_state": "weak_pattern_only",
                             "internal_counter": 911,
                             "unknown_enum": "opaque_machine_value"},
            "market_order_book": {
                "buy_orders": [{"buyer": "village_service_counter", "quantity": 4,
                                 "price_copper": 12, "visibility": "posted_threshold"}],
                "sell_orders": [{"seller": "public_newbie_flow", "quantity_hint": 6,
                                 "price_copper": 15, "visibility": "public_price_board"}],
                "spread_copper": {"bid": 12, "ask": 15},
                "sell_pressure": "localized_batch_pressure",
            },
        }}}}, ensure_ascii=False), encoding="utf-8")
    outline_path = store.webnovel_dir / "outline.json"
    outline_path.write_text(json.dumps({
        "overall": {"story": "沿河追查旧案", "ending_direction": "兄弟重逢"},
        "arcs": [{"title": "入城", "start_chapter": 1, "end_chapter": 20,
                   "goal": "找到商路账册", "main_conflict": "巡河司封锁码头"}],
        "chapters": [{"chapter_number": 1, "title": "夜船", "chapter_goal": "发现货单被改"},
                     {"chapter_number": 2, "title": "追踪", "chapter_goal": "查明改写货单的人"}],
    }, ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: "p-synthetic-build-edit")
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    before = tree(store)

    response = TestClient(app).get("/author-workspace", params={"book_id": "p-synthetic-build-edit"})
    assert response.status_code == 200, response.text
    workspace = response.json()
    book = workspace["books"][0]
    canonical_outline = runtime.assembled_plan(store)["outline"]
    assert {person["name"] for person in book["people"]} == {*names}
    assert book["people"][0]["stableProfile"]["identity"] == "身份0"
    assert book["people"][0]["currentState"]["location"] == "南渡口"
    assert book["planning"]["overall"]["direction"] == canonical_outline["overall"]["story"]
    assert book["planning"]["volumes"][0]["mainConflict"] == canonical_outline["arcs"][0]["obstacle"]
    assert book["planning"]["upcomingChapters"][0]["number"] == 2
    assert book["planning"]["upcomingChapters"][0]["goal"] == canonical_outline["chapters"][1]["goal"]
    assert "planningParts" not in book
    assert book["worldSections"][0]["entries"][0]["text"] == "渡口诸城依水运商路往来。"
    assert {key: book["worldSections"][2]["entries"][0][key] for key in ("title", "text", "editable")} == {
        "title": "南渡口", "text": "旧商路的转运处。", "editable": True,
    }
    assert book["relationships"][0]["basisLabel"] == "作者设定"
    assert book["bookDetails"]["targetWords"] == store.project()["target_words"]
    assert book["bookDetails"]["writingStyle"] == "冷峻"
    assert "冷峻" in book["bookDetails"]["writingStyleOptions"]
    assert book["dynamicWorld"]["chapterRecord"]["chapter"] == 1
    assert book["dynamicWorld"]["chapterRecord"]["authorVisibleUnknowns"] == [
        {"label": "混沌之种异常值", "value": "3"},
        {"label": "公会掌握程度", "value": "只掌握到微弱规律"},
    ]
    assert book["dynamicWorld"]["chapterRecord"]["publicChanges"] == [
        {"text": "柜台调整了收购价。", "whoCanKnow": "公开价格牌、人物动态"}
    ]
    market_entries = book["dynamicWorld"]["chapterRecord"]["marketMovements"]
    assert market_entries == [
        {"label": "收购单", "value": "收购方：村庄服务柜台；收购数量：4；价格：12 铜币；可见范围：公布的收购标准"},
        {"label": "寄售单", "value": "出售方：新人公开交易；预计出售数量：6；价格：15 铜币；可见范围：公开价格牌"},
        {"label": "买卖价格", "value": "买入 12 铜币；卖出 15 铜币"},
        {"label": "出售压力", "value": "局部集中出售"},
    ]
    snapshot_entries = {
        (entry["label"], entry["value"])
        for entry in book["dynamicWorld"]["currentSnapshot"]["entries"]
    }
    assert {("当前焦点", "查找失踪的货船"), ("当前场景时间", "暮春")} <= snapshot_entries
    assert "internal_counter" not in json.dumps(book["dynamicWorld"], ensure_ascii=False)
    assert "opaque_machine_value" not in json.dumps(book["dynamicWorld"], ensure_ascii=False)
    assert "weak_pattern_only" not in json.dumps(book["dynamicWorld"], ensure_ascii=False)
    assert "public_price_board" not in json.dumps(book["dynamicWorld"], ensure_ascii=False)

    chapter_dissection = book["dissectionView"]["actions"]["inspectChapter"]
    assert chapter_dissection["enabled"] is True
    chapter_report = TestClient(app).post("/author-workspace/commands", json={
        "bookId": "p-synthetic-build-edit", "token": chapter_dissection["token"],
        "command": {"type": chapter_dissection["command"]},
    })
    assert chapter_report.status_code == 200, chapter_report.text
    assert chapter_report.json()["product"]["modeLabel"] == "本书章节体检"
    assert chapter_report.json()["product"]["report"]["statusLabel"] == "体检完成"
    assert "schema_version" not in json.dumps(chapter_report.json()["product"], ensure_ascii=False)
    reference_action = book["dissectionView"]["actions"]["inspectReference"]
    reference_report = TestClient(app).post("/author-workspace/commands", json={
        "bookId": "p-synthetic-build-edit", "token": reference_action["token"],
        "command": {"type": reference_action["command"], "text": "主角核对货单后发现关键记录被改，决定连夜追查经手人。"},
    })
    assert reference_report.status_code == 200, reference_report.text
    assert reference_report.json()["product"]["modeLabel"] == "参考书拆解"
    assert tree(store) == before


def test_author_workspace_structured_planning_save_and_confirmed_chapter_guard(tmp_path, monkeypatch):
    from packages.story_core.file_project_store import FileProjectStore
    from packages.story_core.models import NovelProject

    project_id = "p-synthetic-planning-edit"
    root = tmp_path / "planning-project"
    root.mkdir()
    store = FileProjectStore(root)
    project = NovelProject(project_id=project_id, title="规划边界测试", seed_outline="沿河追查旧案。")
    store.snapshot_store.replace_json_transaction({
        store.webnovel_dir / "project.json": project.model_dump(mode="json"),
        store.webnovel_dir / "state.json": {"story_id": "planning-story", "current_chapter": 1},
        store.webnovel_dir / "outline.json": {
            "overall": {"story": "沿河追查旧案。", "ending_direction": "找到旧账。"},
            "arcs": [
                {"id": "arc-1", "title": "旧渡口", "start_chapter": 1, "end_chapter": 50, "goal": "找到第一条线索。", "obstacle": "码头封锁。", "relationship_changes": [], "next_arc_entry": ""},
                {"id": "arc-2", "title": "河上暗潮", "start_chapter": 51, "end_chapter": 100, "goal": "查明旧账。", "obstacle": "证词互相矛盾。", "relationship_changes": [], "next_arc_entry": ""},
            ],
            "chapters": [
                {"chapter_number": 1, "title": "已确认章节", "goal": "保住旧信。"},
                {"chapter_number": 2, "title": "尚未确认章节", "goal": "找到目击者。"},
                {"chapter_number": 51, "title": "下一卷开篇", "goal": "重新核对旧账。"},
            ],
        },
    })
    chapter_dir = store.story_system_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    (chapter_dir / "0001.json").write_text(json.dumps({
        "chapter_number": 1, "chapter_title": "已确认章节", "body": "已经确认的正文。",
    }, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: project_id)
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)

    current = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    assert current["planning"]["editable"] is True
    assert current["planning"]["volumes"][0]["editable"] is False
    assert current["planning"]["upcomingChapters"][0]["number"] == 2
    assert current["planning"]["upcomingChapters"][0]["editable"] is True
    patch = {
        "overall": {"direction": "沿河追查被抹去的旧账。"},
        "volumes": [
            {"number": 1, "title": "旧渡口", "goal": "找到第一条线索。", "mainConflict": "码头封锁。", "characterChanges": [], "endingTurn": ""},
            {"number": 2, "title": "河上暗潮", "goal": "查明旧账。", "mainConflict": "新证据推翻旧证词。", "characterChanges": [], "endingTurn": ""},
        ],
        "upcomingChapters": [{"number": 2, "title": "尚未确认章节", "goal": "查明目击者去向。", "conflict": "证词不一致。", "progression": "前往旧档案馆。"}],
    }
    saved = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": current["actions"]["plan"]["token"],
        "command": {"type": "plan", "patch": patch},
    })
    assert saved.status_code == 200, saved.text
    outline = store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})
    assert outline["overall"]["story"] == "沿河追查被抹去的旧账。"
    assert outline["arcs"][0]["obstacle"] == "码头封锁。"
    assert outline["arcs"][1]["obstacle"] == "新证据推翻旧证词。"
    assert outline["chapters"][0]["goal"] == "保住旧信。"
    assert outline["chapters"][1]["goal"] == "查明目击者去向。"

    refreshed = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    rejected = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": refreshed["actions"]["plan"]["token"],
        "command": {"type": "plan", "patch": {"upcomingChapters": [{"number": 1, "goal": "覆盖已确认章节"}]}},
    })
    assert rejected.status_code == 409
    assert "已经用于已确认正文" in rejected.json()["detail"]["message"]
    assert store.snapshot_store.read_json(store.webnovel_dir / "outline.json", {})["chapters"][0]["goal"] == "保住旧信。"


def test_candidate_dissection_report_is_bound_to_current_pending_body(tmp_path, monkeypatch):
    from apps.api.routes import longform_product
    from packages.story_core.candidate_draft import CandidateDraft

    store = prepared_store(tmp_path)
    project_id = "p-synthetic-build-edit"
    candidate = CandidateDraft.create(
        project_id=store.project()["project_id"], chapter_number=1,
        chapter_title="候选章节", body="候选正文版本一。",
    )
    store.candidate_store.save(candidate)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: project_id)
    inspected = []
    queued = []
    monkeypatch.setattr(longform_product.workbench, "diagnose_project_chapter", lambda project, chapter: (
        inspected.append(chapter) or {"mode": "project", "chapter_number": chapter["chapter_number"],
                                      "chapter_title": chapter["chapter_title"],
                                      "sections": {"下一版改法": ["先核对候选正文中的人物动机。"]}}
    ))
    monkeypatch.setattr(longform_product.workbench, "start_candidate_review_job", lambda *args, **kwargs: (
        queued.append((args, kwargs)) or {"job_id": "synthetic-ai-edit"}
    ))
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)

    view = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    assert view["dissectionView"]["actions"]["inspectCandidate"]["enabled"] is True
    action = view["dissectionView"]["actions"]["inspectCandidate"]
    report_response = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": action["token"],
        "command": {"type": action["command"]},
    })
    assert report_response.status_code == 200, report_response.text
    report_payload = report_response.json()["product"]
    assert report_payload["candidateSourceToken"] == view["dissectionView"]["candidateSourceToken"]
    assert report_payload["report"]["sections"] == [{"title": "下一版改法", "items": ["先核对候选正文中的人物动机。"]}]
    assert inspected[0]["body"] == "候选正文版本一。"

    changed = store.candidate_store.get(candidate.candidate_id)
    changed.body = "候选正文版本二。"
    store.candidate_store.save(changed)
    fresh = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    rejected = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": fresh["actions"]["ai-edit"]["token"],
        "command": {"type": "ai-edit", "instruction": "使用报告建议", "dissectionSourceToken": report_payload["candidateSourceToken"]},
    })
    assert rejected.status_code == 409
    assert "旧体检报告不能用于这份稿件" in rejected.json()["detail"]["message"]
    assert queued == []


def test_author_workspace_settings_and_story_edits_use_compare_and_swap(tmp_path, monkeypatch):
    from packages.story_core.models import ForeshadowingState

    store = prepared_store(tmp_path)
    names = ["林照", "陆遥"]
    store.update_project({
        "title": "河灯录",
        "character_profiles": [{"name": name, "role": "protagonist" if index == 0 else "supporting"} for index, name in enumerate(names)],
        "relationship_graph": [{
            "source": "林照", "target": "陆遥", "relation_type": "旧识",
            "origin": "幼时曾共同守船", "current_state": "暂时合作",
            "last_changed_chapter": 1,
        }],
        "world_blueprint": {"writing_style": "冷峻", "world_rules": ["河道每旬封航一日。"]},
    })
    state = store.state()
    state["current_chapter"] = 1
    state["characters"] = [{"name": name, "role": "protagonist" if index == 0 else "supporting"} for index, name in enumerate(names)]
    (store.webnovel_dir / "state.json").write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    chapter_dir = store.story_system_dir / "chapters"
    chapter_dir.mkdir(parents=True, exist_ok=True)
    (chapter_dir / "0001.json").write_text(json.dumps({"chapter_number": 1, "chapter_title": "夜船", "body": "正文"}), encoding="utf-8")
    store.update_foreshadowing_ledger([
        ForeshadowingState(text="船票背面的暗记", first_chapter=1, last_touched_chapter=1, status="open", payoff_plan="在进城后回应"),
    ])

    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: "p-synthetic-build-edit")
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)
    project_id = "p-synthetic-build-edit"

    workspace = client.get("/author-workspace", params={"book_id": project_id}).json()
    book = workspace["books"][0]
    relation = book["relationshipView"]["items"][0]
    edges = [{
        "source": relation["source"], "target": relation["target"],
        "relation_type": relation["relationship"],
        "current_state": "暂时合作，但仍互相试探",
        "shared_interest_or_conflict": relation["sharedInterestOrConflict"],
        "trust": 35, "tension": 45, "origin": "试图静默覆盖的历史",
    }]
    immutable_history = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": book["relationshipView"]["save"]["token"],
        "command": {"type": "relationships", "items": edges},
    })
    assert immutable_history.status_code == 409, immutable_history.text
    assert "只读" in immutable_history.text
    assert store.project()["relationship_graph"][0]["origin"] == "幼时曾共同守船"
    edges[0]["origin"] = relation["history"]
    saved = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": book["relationshipView"]["save"]["token"],
        "command": {"type": "relationships", "items": edges},
    })
    assert saved.status_code == 200, saved.text
    updated_edge = store.project()["relationship_graph"][0]
    assert updated_edge["current_state"] == "暂时合作，但仍互相试探"
    assert updated_edge["trust"] == 35
    assert updated_edge["origin"] == "幼时曾共同守船"
    assert updated_edge["last_changed_chapter"] == 1

    stale_write = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": book["relationshipView"]["save"]["token"],
        "command": {"type": "relationships", "items": [{**edges[0], "current_state": "旧版本覆盖"}]},
    })
    assert stale_write.status_code == 409
    assert store.project()["relationship_graph"][0]["current_state"] == "暂时合作，但仍互相试探"

    chapter_source = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    returned = chapter_source["foreshadowingView"]["items"][0]
    returned["statusLabel"] = "已强化"
    returned["lastTouchedChapter"] = 1
    returned["payoffPlan"] = "在第 2 章推进暗记来源"
    saved_foreshadowing = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": chapter_source["foreshadowingView"]["save"]["token"],
        "command": {"type": "foreshadowing", "items": [{
            "text": returned["text"], "firstChapter": returned["firstChapter"],
            "lastTouchedChapter": returned["lastTouchedChapter"],
            "statusLabel": returned["statusLabel"], "resolvedChapter": returned["resolvedChapter"],
            "payoffPlan": returned["payoffPlan"],
        }]},
    })
    assert saved_foreshadowing.status_code == 200, saved_foreshadowing.text
    assert store.foreshadowing_ledger()[0].status == "reinforced"
    assert store.foreshadowing_ledger()[0].payoff_plan == "在第 2 章推进暗记来源"

    store.update_foreshadowing_ledger([
        ForeshadowingState(text="暂未确认出处的船票暗记", first_chapter=0, status="open", payoff_plan="找到原始船票后再核对"),
    ])
    unplaced = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    unplaced_foreshadow = unplaced["foreshadowingView"]["items"][0]
    assert unplaced_foreshadow["firstChapter"] is None
    saved_unplaced = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": unplaced["foreshadowingView"]["save"]["token"],
        "command": {"type": "foreshadowing", "items": [{
            "text": unplaced_foreshadow["text"], "firstChapter": unplaced_foreshadow["firstChapter"],
            "lastTouchedChapter": unplaced_foreshadow["lastTouchedChapter"],
            "statusLabel": unplaced_foreshadow["statusLabel"], "resolvedChapter": unplaced_foreshadow["resolvedChapter"],
            "payoffPlan": unplaced_foreshadow["payoffPlan"],
        }]},
    })
    assert saved_unplaced.status_code == 200, saved_unplaced.text
    assert store.foreshadowing_ledger()[0].first_chapter == 0

    workspace = client.get("/author-workspace", params={"book_id": project_id}).json()
    details = workspace["books"][0]["bookDetails"]
    style_saved = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": details["actions"]["saveStyle"]["token"],
        "command": {"type": "book-style", "writingStyle": "细腻"},
    })
    assert style_saved.status_code == 200, style_saved.text
    assert store.project()["world_blueprint"]["writing_style"] == "细腻"
    assert store.project()["world_blueprint"]["world_rules"] == ["河道每旬封航一日。"]

    refreshed = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    type_id = refreshed["bookDetails"]["novelTypeOptions"][0]["id"]
    type_saved = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": refreshed["bookDetails"]["actions"]["saveType"]["token"],
        "command": {"type": "book-type", "novelTypeId": type_id},
    })
    assert type_saved.status_code == 200, type_saved.text
    assert store.project()["world_blueprint"]["genre_plugin_ids"] == [type_id]


def test_author_workspace_character_profile_edit_is_stable_and_compare_and_swap(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    store.update_project({
        "title": "雾港来信",
        "character_profiles": [
            {
                "name": "林照", "role": "protagonist",
                "identity_profile": {"current_identity": "旧身份"},
                "story_drive": {"motivation": "查清来信来源"},
            },
            {
                "name": "无状态人物", "role": "supporting",
                "identity_profile": {"current_identity": "档案中的身份"},
                "story_drive": {"motivation": "守住旧书店"},
            },
        ],
    })
    state = store.state()
    state["current_chapter"] = 1
    state["characters"] = [{
        "name": "林照", "role": "protagonist", "location": "旧码头",
        "emotion": "警惕", "memory": ["第一章确认的目击者信息"],
    }]
    state_path = store.webnovel_dir / "state.json"
    state_path.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")
    state_before = json.loads(state_path.read_text(encoding="utf-8"))

    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: "p-synthetic-build-edit")
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)
    project_id = "p-synthetic-build-edit"

    book = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    profiles = book["characterCardsView"]["items"]
    profile_only = next(item for item in profiles if item["name"] == "无状态人物")
    assert profile_only["currentState"] == {}
    assert profile_only["editableProfile"]["identityProfile"]["currentIdentity"] == "档案中的身份"
    save_action = profile_only["actions"]["save"]
    saved = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": save_action["token"],
        "command": {
            "type": save_action["command"],
            "profile": {
                "identityProfile": {"currentIdentity": "翻修旧书店的掌柜", "occupation": "书店掌柜"},
                "storyDrive": {"longTermGoal": "找回失散的家人", "motivation": "守住旧书店"},
                "performanceProfile": {"speechStyle": "说话克制，先问事实"},
                "dialogueExamples": ["先把信给我看。"],
                "futurePlans": ["查访旧码头的邮差"],
            },
        },
    })
    assert saved.status_code == 200, saved.text
    persisted = next(item for item in store.project()["character_profiles"] if item["name"] == "无状态人物")
    assert persisted["identity_profile"]["current_identity"] == "翻修旧书店的掌柜"
    assert persisted["story_drive"]["long_term_goal"] == "找回失散的家人"
    assert persisted["performance_profile"]["speech_style"] == "说话克制，先问事实"
    assert persisted["dialogue_examples"] == ["先把信给我看。"]
    assert persisted["future_plans"] == ["查访旧码头的邮差"]
    assert json.loads(state_path.read_text(encoding="utf-8")) == state_before

    stale = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": save_action["token"],
        "command": {
            "type": save_action["command"],
            "profile": {"identityProfile": {"currentIdentity": "旧版本覆盖"}},
        },
    })
    assert stale.status_code == 409
    assert next(item for item in store.project()["character_profiles"] if item["name"] == "无状态人物")["identity_profile"]["current_identity"] == "翻修旧书店的掌柜"

    refreshed = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    refreshed_profile = next(item for item in refreshed["characterCardsView"]["items"] if item["name"] == "无状态人物")
    completed = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": refreshed_profile["actions"]["completePortrait"]["token"],
        "command": {"type": refreshed_profile["actions"]["completePortrait"]["command"]},
    })
    assert completed.status_code == 200, completed.text
    assert json.loads(state_path.read_text(encoding="utf-8")) == state_before


def test_author_workspace_publishing_commands_are_explicit_and_revision_bound(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    store.update_project({"title": "潮声旧信"})

    class FakeSynopsis:
        calls = 0

        def generate(self, *_args, **_kwargs):
            from tests.api.test_publishing_asset_routes import _synopsis

            self.calls += 1
            return _synopsis()

    class FakeCoverPrompt:
        calls = 0

        def generate(self, *_args, **_kwargs):
            self.calls += 1
            return "雨夜海港，一封旧信被放在潮湿的木箱上。"

    synopsis_generator = FakeSynopsis()
    cover_generator = FakeCoverPrompt()
    monkeypatch.setattr(file_projects, "synopsis_generator", synopsis_generator)
    monkeypatch.setattr(file_projects, "cover_prompt_generator", cover_generator)
    monkeypatch.setattr(file_projects, "resolve_stage_runtime", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(file_projects, "_publishing_context_for", lambda _store: SimpleNamespace(title="潮声旧信"))
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: "p-synthetic-build-edit")
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)
    project_id = "p-synthetic-build-edit"

    first = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]["bookDetails"]
    assert synopsis_generator.calls == 0
    assert cover_generator.calls == 0
    assert first["synopsisStatusLabel"] == "尚无简介"
    invalid_synopsis = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": first["actions"]["saveSynopsis"]["token"],
        "command": {
            "type": first["actions"]["saveSynopsis"]["command"],
            "tags": ["悬疑"],
            "body": "标签不足时不保存。",
        },
    })
    assert invalid_synopsis.status_code == 422
    assert "4–8" in invalid_synopsis.json()["detail"]["message"]
    assert store.publishing_assets().get("synopsis") is None
    saved = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": first["actions"]["saveSynopsis"]["token"],
        "command": {
            "type": first["actions"]["saveSynopsis"]["command"],
            "tags": ["悬疑", "海港", "旧信", "追查"],
            "body": "掌柜收到一封旧信，决定追查寄件人。",
        },
    })
    assert saved.status_code == 200, saved.text
    assert store.publishing_assets()["synopsis"]["body"] == "掌柜收到一封旧信，决定追查寄件人。"
    stale = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": first["actions"]["saveSynopsis"]["token"],
        "command": {
            "type": first["actions"]["saveSynopsis"]["command"],
            "tags": ["悬疑", "海港", "旧信", "追查"],
            "body": "旧版本不能覆盖。",
        },
    })
    assert stale.status_code == 409
    assert store.publishing_assets()["synopsis"]["body"] == "掌柜收到一封旧信，决定追查寄件人。"

    refreshed = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]["bookDetails"]
    generated = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": refreshed["actions"]["generateSynopsis"]["token"],
        "command": {"type": refreshed["actions"]["generateSynopsis"]["command"], "guidance": "突出旧信来源"},
    })
    assert synopsis_generator.calls == 1
    assert generated.status_code == 200, generated.text
    assert synopsis_generator.calls == 1
    assert store.publishing_assets()["synopsis"]["body"].startswith("A young courier")

    cover_action = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]["bookDetails"]["actions"]["generateCover"]
    cover_result = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": cover_action["token"],
        "command": {"type": cover_action["command"]},
    })
    assert cover_result.status_code == 200, cover_result.text
    assert cover_generator.calls == 1
    assert store.publishing_assets()["cover"]["prompt"] == "雨夜海港，一封旧信被放在潮湿的木箱上。"


def test_author_workspace_world_section_edit_only_merges_selected_field(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    store.update_project({
        "title": "潮汐城记",
        "world_summary": "一座靠潮汐运转的港口城。",
        "world_blueprint": {
            "world_rules": ["涨潮后旧桥封闭。"],
            "locations": [{"name": "北堤", "description": "渔船集中停靠。", "secret_note": "保留"}],
            "factions": [{"name": "巡潮会", "description": "负责港区秩序。"}],
        },
    })
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: "p-synthetic-build-edit")
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)
    project_id = "p-synthetic-build-edit"
    book = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    rules = next(section for section in book["worldSections"] if section["id"] == "rules")
    target = next(item for item in rules["entries"] if item["text"] == "涨潮后旧桥封闭。")
    edit = [
        {**item, "text": "台风预警期间旧桥封闭。" if item["id"] == target["id"] else item["text"]}
        for item in rules["entries"]
    ]
    saved = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": rules["save"]["token"],
        "command": {"type": rules["save"]["command"], "entries": edit},
    })
    assert saved.status_code == 200, saved.text
    updated = store.project()["world_blueprint"]
    assert updated["world_rules"] == ["台风预警期间旧桥封闭。"]
    assert updated["locations"] == [{"name": "北堤", "description": "渔船集中停靠。", "secret_note": "保留"}]
    assert updated["factions"] == [{"name": "巡潮会", "description": "负责港区秩序。"}]
    stale = client.post("/author-workspace/commands", json={
        "bookId": project_id,
        "token": rules["save"]["token"],
        "command": {"type": rules["save"]["command"], "entries": rules["entries"]},
    })
    assert stale.status_code == 409
    assert store.project()["world_blueprint"]["world_rules"] == ["台风预警期间旧桥封闭。"]


def test_game_catalog_projection_keeps_structured_cards_out_of_generic_stories(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    equipment = {
        "id": "equipment-silver-tide-sword",
        "name": "银潮短剑",
        "equipment_type": "武器",
        "rarity": "精良",
        "description": "刃面留有潮汐纹路。",
    }
    monster = {
        "id": "monster-sand-crab",
        "name": "沙甲蟹",
        "category": "海岸生物",
        "rank": "普通",
        "skills": ["夹击"],
        "habitats": ["北堤"],
    }
    store.update_project({"world_blueprint": {
        "genre_plugin_ids": ["game_webnovel"],
        "equipment_cards": [equipment],
        "monster_profiles": [monster],
    }})
    blueprint = store.project()["world_blueprint"]
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: "p-synthetic-build-edit")
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)

    game_book = client.get("/author-workspace", params={"book_id": "p-synthetic-build-edit"}).json()["books"][0]
    assert game_book["worldCatalogs"] == {
        "equipment_cards": blueprint["equipment_cards"],
        "monster_profiles": blueprint["monster_profiles"],
    }
    assert {section["id"] for section in game_book["worldSections"]} >= {"equipment", "monsters"}

    store.update_project({"world_blueprint": {"genre_plugin_ids": ["generic_webnovel"]}})
    generic_book = client.get("/author-workspace", params={"book_id": "p-synthetic-build-edit"}).json()["books"][0]
    assert "worldCatalogs" not in generic_book
    assert {section["id"] for section in generic_book["worldSections"]}.isdisjoint({"equipment", "monsters"})


def test_author_workspace_projects_and_saves_templates_and_skill_selection(tmp_path, monkeypatch):
    from apps.api.routes import prompt_audit as prompt_audit_routes
    from apps.api.routes.prompt_audit import init_prompt_audit_routes
    from packages.story_core.prompt_audit_deep import DeepPromptAuditResult
    from packages.story_core.prompt_templates import get_global_prompt_template
    from packages.story_core.skill_packs import skill_module_key

    store = prepared_store(tmp_path)
    store.update_project({"title": "河灯录", "world_blueprint": {"writing_style": "冷峻"},
                          "enabled_skill_ids": ["demo-pack"]})
    skill_root = tmp_path / "skill-packs" / "demo-pack"
    (skill_root / "skills" / "scene-craft").mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: demo-pack\ndescription: 合成根能力\n---\n# 根能力\n## 要求\n生成时保留已经确认的事件结果。\n", encoding="utf-8"
    )
    (skill_root / "skills" / "scene-craft" / "SKILL.md").write_text(
        "---\nname: scene-craft\ndescription: 场景动作拆解\npurposes: writer\n---\n# 场景能力\n## 要求\n每场写出人物动作和可见变化。\n", encoding="utf-8"
    )
    global_template_path = tmp_path / "global-templates.json"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_SKILL_PACKS_DIR", str(tmp_path / "skill-packs"))
    monkeypatch.setenv("NOVEL_PROMPT_TEMPLATES_PATH", str(global_template_path))
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "_stores", lambda *, lifecycle=None: [store] if lifecycle == "active" else [])
    monkeypatch.setattr(file_projects, "_public_project_id", lambda _: "p-synthetic-build-edit")

    deep_calls = []

    class FakeDeepAuditor:
        def analyze(self, *, content, local_result):
            deep_calls.append(content)
            return DeepPromptAuditResult.model_validate({
                **local_result.model_dump(),
                "runtime": {"provider": "private-provider", "model": "private-model",
                            "elapsed_seconds": 0.01, "prompt_characters": 20},
            })

    monkeypatch.setattr(prompt_audit_routes, "deep_auditor", FakeDeepAuditor())
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_novel_type_routes())
    app.include_router(init_prompt_audit_routes())
    app.include_router(init_longform_product_routes())
    client = TestClient(app)
    project_id = "p-synthetic-build-edit"

    response = client.get("/author-workspace", params={"book_id": project_id})
    assert response.status_code == 200, response.text
    book = response.json()["books"][0]
    writer_pack = next(item for item in book["writingAbilitiesView"]["packs"] if item["id"] == "demo-pack")
    assert writer_pack["modules"][0]["id"] == "root"
    assert all(module["selected"] for module in writer_pack["modules"])
    abilities = book["writingAbilitiesView"]
    disabled_module_ids = [skill_module_key("demo-pack", "root")]
    ability_saved = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": abilities["save"]["token"],
        "command": {"type": "writing-abilities", "packIds": ["demo-pack"], "moduleIds": disabled_module_ids},
    })
    assert ability_saved.status_code == 200, ability_saved.text
    assert store.project()["enabled_skill_module_ids"] == disabled_module_ids
    packet = store.writing_packet(1)
    writer_context = json.dumps(packet.get("skill_context", {}).get("writer", []), ensure_ascii=False)
    assert "保留已经确认的事件结果" not in writer_context
    assert "人物动作和可见变化" not in writer_context

    book = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    template = next(item for item in book["writingTemplatesView"]["templates"] if item["title"] == "整章正文写作")
    assert "上下文快照" not in json.dumps(book["writingTemplatesView"], ensure_ascii=False)
    assert "prompt_context" not in json.dumps(book["writingTemplatesView"], ensure_ascii=False)
    edited_content = template["content"] + "\n写作时保留作者已确认的事实。"
    project_save = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": template["actions"]["saveProject"]["token"],
        "command": {"type": template["actions"]["saveProject"]["command"], "content": edited_content},
    })
    assert project_save.status_code == 200, project_save.text
    assert store.prompt_template_object("writer").content == edited_content
    stale_project_save = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": template["actions"]["saveProject"]["token"],
        "command": {"type": template["actions"]["saveProject"]["command"], "content": edited_content + "\n旧稿"},
    })
    assert stale_project_save.status_code == 409
    assert store.prompt_template_object("writer").content == edited_content

    overridden = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    template = next(item for item in overridden["writingTemplatesView"]["templates"] if item["title"] == "整章正文写作")
    restore_action = template["actions"]["restoreGlobal"]
    denied_restore = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": restore_action["token"],
        "command": {"type": restore_action["command"]},
    })
    assert denied_restore.status_code == 409
    assert store.prompt_template_object("writer").content == edited_content
    restored = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": restore_action["token"],
        "command": {"type": restore_action["command"], "confirm": True},
    })
    assert restored.status_code == 200, restored.text
    assert store.prompt_template_object("writer").content == get_global_prompt_template("writer").content

    refreshed = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]
    template = next(item for item in refreshed["writingTemplatesView"]["templates"] if item["title"] == "整章正文写作")
    content_for_check = template["content"] + "\n请检查这一版模板。"
    checked = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": template["actions"]["check"]["token"],
        "command": {"type": template["actions"]["check"]["command"], "content": content_for_check},
    })
    assert checked.status_code == 200, checked.text
    assert checked.json()["product"]["bindingToken"]
    assert "content_sha256" not in json.dumps(checked.json()["product"])
    assert "passed_checks" not in json.dumps(checked.json()["product"])
    deep_checked = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": template["actions"]["deepCheck"]["token"],
        "command": {"type": template["actions"]["deepCheck"]["command"], "content": content_for_check},
    })
    assert deep_checked.status_code == 200, deep_checked.text
    assert deep_calls == [content_for_check]
    assert "private-provider" not in json.dumps(deep_checked.json()["product"])
    assert "private-model" not in json.dumps(deep_checked.json()["product"])
    assert "runtime" not in deep_checked.json()["product"]

    template_before_global = get_global_prompt_template("writer").version
    global_action = template["actions"]["saveGlobal"]
    global_content = get_global_prompt_template("writer").content + "\n全局更新需要用户确认。"
    denied_global = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": global_action["token"],
        "command": {"type": global_action["command"], "content": global_content},
    })
    assert denied_global.status_code == 409
    assert get_global_prompt_template("writer").version == template_before_global
    updated_global = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": global_action["token"],
        "command": {"type": global_action["command"], "content": global_content, "confirm": True},
    })
    assert updated_global.status_code == 200, updated_global.text
    assert get_global_prompt_template("writer").content == global_content

    abilities_workspace = client.get("/author-workspace", params={"book_id": project_id}).json()["books"][0]["writingAbilitiesView"]
    inconsistent_selection = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": abilities_workspace["save"]["token"],
        "command": {"type": "writing-abilities", "packIds": ["demo-pack"], "moduleIds": []},
    })
    assert inconsistent_selection.status_code == 409, inconsistent_selection.text
    assert "模块" in inconsistent_selection.text
    next_selection = client.post("/author-workspace/commands", json={
        "bookId": project_id, "token": abilities_workspace["save"]["token"],
        "command": {"type": "writing-abilities", "packIds": ["demo-pack"],
                    "moduleIds": [skill_module_key("demo-pack", "scene-craft")]},
    })
    assert next_selection.status_code == 200, next_selection.text
    next_packet = store.writing_packet(1)
    next_writer_context = json.dumps(next_packet["skill_context"]["writer"], ensure_ascii=False)
    assert "人物动作和可见变化" in next_writer_context


def assert_product(value):
    if isinstance(value, dict):
        assert not INTERNAL.intersection(value)
        for item in value.values():
            assert_product(item)
    elif isinstance(value, list):
        for item in value:
            assert_product(item)


def test_build_read_is_product_only_and_form_reuses_validation(tmp_path, monkeypatch):
    store, graph, service, *_ = _setup_project(tmp_path, monkeypatch)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", SimpleNamespace(complete_stage=lambda *_: (_ for _ in ()).throw(AssertionError("probe"))))
    client = client_for(monkeypatch)
    before = tree(store)
    response = client.get(BASE + "/build")
    assert response.status_code == 200, response.text
    view = response.json()
    assert_product(view)
    assert tree(store) == before
    form = view["selected"]["form"]
    assert form["fields"][0]["label"] == "名称"
    values = {form["fields"][0]["key"]: ""}
    old_artifact = store.build_artifact("world_model")
    denied = client.post(BASE + "/actions", json={"token": form["actions"][0]["token"], "values": values})
    assert denied.status_code == 422, denied.text
    assert_product(denied.json())
    assert store.build_artifact("world_model") == old_artifact
    values[form["fields"][0]["key"]] = "作者修改的世界规则"
    saved = client.post(BASE + "/actions", json={"token": form["actions"][0]["token"], "values": values})
    assert saved.status_code == 200, saved.text
    assert store.build_artifact("world_model")["payload"]["label"] == "作者修改的世界规则"
    again = client.post(BASE + "/actions", json={"token": form["actions"][0]["token"], "values": values})
    assert again.status_code == 409
    assert "revision" not in again.text


def test_write_read_and_confirmation_use_existing_authority(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    client = client_for(monkeypatch)
    generated = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    before = tree(store)
    response = client.get(BASE + "/write")
    assert response.status_code == 200, response.text
    assert_product(response.json())
    assert tree(store) == before
    candidate = response.json()["candidate"]
    assert candidate["body"] == generated["body"]
    confirm = next(a for a in candidate["actions"] if a["label"] == "确认提交")
    assert confirm["enabled"]
    result = client.post(BASE + "/actions", json={"token": confirm["token"]})
    assert result.status_code == 200, result.text
    assert result.json()["redirect"].endswith("write?chapter=1")
    assert store.state()["current_chapter"] == 1
    again = client.post(BASE + "/actions", json={"token": confirm["token"]})
    assert again.status_code == 409
    assert store.state()["current_chapter"] == 1
    following = client.get(BASE + "/write").json()
    assert any(a["label"] == "生成下一章" for a in following["actions"])


def test_candidate_hard_block_is_not_an_enabled_product_action(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    generated = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    candidate = store.candidate_store.get(generated["candidate_id"])
    candidate.quality_report["writing_review"] = {"blocking": [{"code": "canon.hard_blocker", "message": "SECRET Authorization TEST_KEY"}]}
    store.candidate_store.save(candidate)
    client = client_for(monkeypatch)
    response = client.get(BASE + "/write")
    assert response.status_code == 200, response.text
    assert "SECRET" not in response.text and "canon.hard_blocker" not in response.text
    view = response.json()["candidate"]
    assert view["review"]["tone"] == "danger"
    denied_action = next(a for a in view["actions"] if a["label"] == "确认提交")
    assert not denied_action["enabled"]
    before = tree(store)
    result = client.post(BASE + "/actions", json={"token": denied_action["token"]})
    assert result.status_code == 409
    assert tree(store) == before
    assert store.candidate_store.get(candidate.candidate_id).status == "pending"


def test_malformed_product_request_does_not_echo_credentials(tmp_path, monkeypatch):
    store, *_ = _setup_project(tmp_path, monkeypatch)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    response = client_for(monkeypatch).post(BASE + "/actions", json={"token": "Authorization TEST_SECRET", "values": {"key": ["PRIVATE"]}})
    assert response.status_code == 422
    assert "TEST_SECRET" not in response.text and "PRIVATE" not in response.text


def test_product_problem_mapping_and_no_raw_fallback():
    assert product.problem("stages.missing_change")["message"] == "修炼阶段缺少升级条件。"
    assert "SECRET" not in json.dumps(product.problem("SECRET raw_message"))
    assert product.status("validation_failed")["label"] == "设定还不完整"


@pytest.mark.parametrize("succeeds", [True, False])
def test_repair_uses_existing_model_path_outside_lock_and_keeps_failed_result(tmp_path, monkeypatch, succeeds):
    from packages.story_core.persistence.project_locking import project_update_lock
    store, graph, service, marker_path, marker_bytes = _setup_project(tmp_path, monkeypatch)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    calls = []

    def complete(*args):
        def acquire():
            lock = project_update_lock(store.root)
            got = lock.acquire(timeout=2)
            if got:
                lock.release()
            return got
        with ThreadPoolExecutor(max_workers=1) as pool:
            assert pool.submit(acquire).result(timeout=3)
        calls.append(1)
        return SimpleNamespace(ok=succeeds, text=json.dumps({"label": "修复后的世界规则"}), provider="synthetic", model="injected", resolved_model="injected")

    monkeypatch.setattr(file_projects, "shuangwen_model_gateway", SimpleNamespace(complete_stage=complete))
    client = client_for(monkeypatch)
    before = store.build_artifact("world_model")
    action = next(a for a in client.get(BASE + "/build").json()["selected"]["actions"] if a["label"] == "让 AI 修复")
    response = client.post(BASE + "/actions", json={"token": action["token"]})
    assert response.status_code == (200 if succeeds else 422), response.text
    assert calls == [1]
    assert not service.inspect_task("world_model").active_run_id
    if succeeds:
        assert store.build_artifact("world_model")["revision"] == before["revision"] + 1
    else:
        assert store.build_artifact("world_model") == before
        assert marker_path.read_bytes() == marker_bytes
        assert service.inspect_task("world_model").status == "completed"


def test_changed_candidate_authority_disables_confirmation(tmp_path, monkeypatch):
    store = prepared_store(tmp_path)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    generated = store.generate_next_chapter(engine=FakeEngine(), persist=False)["candidate"]
    client = client_for(monkeypatch)
    old = next(a for a in client.get(BASE + "/write").json()["candidate"]["actions"] if a["label"] == "确认提交")
    candidate = store.candidate_store.get(generated["candidate_id"])
    candidate.submission_payload["opening_authority"]["graph_revision"] -= 1
    store.candidate_store.save(candidate)
    before = tree(store)
    assert client.post(BASE + "/actions", json={"token": old["token"]}).status_code == 409
    changed = client.get(BASE + "/write").json()["candidate"]
    assert not next(a for a in changed["actions"] if a["label"] == "确认提交")["enabled"]
    assert changed["review"]["tone"] == "danger"
    assert tree(store) == before


def test_product_form_preserves_hidden_fields_and_exposes_missing_upgrade_condition():
    payload = {"schema_version": "internal/v1", "stages": [{"name": "筑基"}], "mode": "internal_enum"}
    prepared = product.editable_payload(payload, [{"code": "stages.missing_change"}])
    fields, paths = product.editable_fields(prepared, lambda path: str(len(str(path))) + str(path).encode().hex())
    assert all("internal" not in f["value"] for f in fields)
    field = next(f for f in fields if "升级条件" in f["label"])
    edited = product.apply_fields(prepared, paths, {field["key"]: "掌握基础功法"})
    assert edited["stages"][0]["change"] == "掌握基础功法"
    assert edited["schema_version"] == payload["schema_version"]
    assert edited["mode"] == payload["mode"]


def test_real_author_review_advice_survives_without_engineering_details():
    quality = {"writing_review": {"warnings": [
        {"message": "人物在雨夜离开的动机不够清楚，请补一句说明。"},
        {"message": "内部诊断 canon.failed Authorization TEST_SECRET"}]}}
    assert product.author_advice(quality) == [{"message": "人物在雨夜离开的动机不够清楚，请补一句说明。",
        "suggestion": "结合正文与相关章节核对，再修改并重新检查。", "tone": "warning"}]


def test_job_reads_happen_before_project_lock(tmp_path, monkeypatch):
    from apps.api.routes import creation_product
    from packages.story_core.persistence.project_locking import project_update_lock
    store, *_ = _setup_project(tmp_path, monkeypatch)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    original = creation_product._handler
    observed = []

    def checking(http_request, name, **kwargs):
        if name in {"get_current_file_project_build_orchestration", "get_current_file_generation_job"}:
            assert not project_update_lock(store.root)._is_owned()
            observed.append(name)
        return original(http_request, name, **kwargs)

    monkeypatch.setattr(creation_product, "_handler", checking)
    client = client_for(monkeypatch)
    assert client.get(BASE + "/build").status_code == 200
    assert client.get(BASE + "/write").status_code == 200
    assert len(observed) == 2


def test_creation_action_skips_unrelated_details_and_redirects_to_new_candidate(tmp_path, monkeypatch):
    from apps.api.routes import creation_product
    store = prepared_store(tmp_path)
    monkeypatch.setattr(file_projects, "_store_for", lambda _: store)
    client = client_for(monkeypatch)
    screen = client.get(BASE + "/write").json()
    action = next(a for a in screen["actions"] if a["label"] == "生成第一章")
    calls = []
    monkeypatch.setattr(file_projects, "start_file_generation_job", lambda *args: calls.append(args) or {})
    result = client.post(BASE + "/actions", json={"token": action["token"]})
    assert result.status_code == 200
    assert result.json()["redirect"].endswith("/write?chapter=1")
    assert len(calls) == 1

    view = client.get(BASE + "/build").json()
    start = next(a for a in view["actions"] if a["label"] == "生成规划")
    original = creation_product._handler
    def checking(http_request, name, **kwargs):
        assert name != "get_file_project_build_graph_task", "global action must not load every task"
        if name == "start_file_project_build_orchestration":
            return {}
        return original(http_request, name, **kwargs)
    monkeypatch.setattr(creation_product, "_handler", checking)
    assert client.post(BASE + "/actions", json={"token": start["token"]}).status_code == 200
