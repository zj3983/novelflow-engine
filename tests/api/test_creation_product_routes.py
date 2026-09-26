from copy import deepcopy
import json
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor

import pytest

from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient

from apps.api.routes.creation_product import init_creation_product_routes
from apps.api.routes import file_projects
from packages.story_core import product_presentation as product
from tests.api.test_build_workbench_edit_route import _setup_project, _wait_orchestration
from tests.story_core.test_opening_prose import prepared_store, FakeEngine


BASE = "/file-projects/p-synthetic-build-edit/product"
INTERNAL = {"artifact", "revision", "diagnostics", "preflight", "provenance", "provider", "protocol",
            "capabilities", "schema_version", "quality_report", "task_id", "graph_revision", "context_snapshot_id"}


def client_for(monkeypatch):
    monkeypatch.setattr(file_projects, "router", APIRouter())
    app = FastAPI()
    app.include_router(file_projects.init_file_project_routes())
    app.include_router(init_creation_product_routes())
    return TestClient(app)


def tree(store):
    return {str(p.relative_to(store.root)): p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


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
    old = client.get(BASE + "/write").json()["candidate"]["actions"][0]
    candidate = store.candidate_store.get(generated["candidate_id"])
    candidate.submission_payload["opening_authority"]["graph_revision"] -= 1
    store.candidate_store.save(candidate)
    before = tree(store)
    assert client.post(BASE + "/actions", json={"token": old["token"]}).status_code == 409
    changed = client.get(BASE + "/write").json()["candidate"]
    assert not changed["actions"][0]["enabled"]
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
    assert product.author_advice(quality) == [{"message": "人物在雨夜离开的动机不够清楚，请补一句说明。", "tone": "warning"}]


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
