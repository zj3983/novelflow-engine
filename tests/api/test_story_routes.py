import json
import threading
import time
import asyncio

import pytest

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from apps.api.routes import stories as story_routes
from apps.api.routes.stories import _quality_context
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import NovelProject, StoryState


client = TestClient(app)


def _runtime_configuration(*, provider="openai"):
    planner_provider = provider
    writer_provider = provider
    return {
        "schema_version": "runtime-config/v2",
        "accounts": {
            "codexcli": {
                "api_key": "",
                "base_url": "",
                "custom_models": [],
                "codex_command": "codex-test",
            },
            "openai": {
                "api_key": "sk-test",
                "base_url": "https://api.test.example/v1",
                "custom_models": [],
                "codex_command": "",
            },
        },
        "stages": {
            "planner": {
                "provider_id": planner_provider,
                "model": "codex-planner" if planner_provider == "codexcli" else "openai-planner",
            },
            "writer": {
                "provider_id": writer_provider,
                "model": "codex-writer" if writer_provider == "codexcli" else "openai-writer",
            },
        },
        "image": {
            "enabled": False,
            "api_key": "",
            "base_url": "",
            "model": "",
        },
        "temperature": 0.7,
        "new_character_policy": "Director review",
    }


def _masked(configuration):
    """Expected wire form: non-empty api_key values are masked in API responses."""
    masked = json.loads(json.dumps(configuration))
    for provider in masked["accounts"].values():
        if provider["api_key"]:
            provider["api_key"] = "********"
    if masked["image"]["api_key"]:
        masked["image"]["api_key"] = "********"
    return masked


def _make_file_project(root, *, project_id="p-file-api", state=None):
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    project = {"project_id": project_id, "title": "File API Novel", "active_story_id": "s-file-api"}
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps({"schema_version": "story-system-master-setting/v1", "project": project}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(json.dumps(project, ensure_ascii=False), encoding="utf-8")
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(state or {"story_id": "s-file-api", "current_chapter": 0, "world_facts": []}, ensure_ascii=False),
        encoding="utf-8",
    )


def _mock_story_chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
    chapter_number = getattr(story, "current_chapter", 0) or 1
    active = [c for c in story.characters if c.lifecycle_state == "active" and not c.frozen]
    lead = active[0].name if active else "主角"
    opposition = active[-1].name if len(active) > 1 else "circumstance"
    moves = [
        {
            "name": c.name,
            "goal": c.goals[0] if c.goals else "推进主线",
            "emotion": c.current_emotion or "alert",
            "action": f"{c.name} 推进当前线索",
            "priority": 1,
            "new_character_candidates": ["Old Archivist"]
            if any("archivist" in str(secret).lower() for secret in c.secrets)
            else [],
        }
        for c in active
    ]
    runtime_stage = "planner" if agent == "director" else agent
    if runtime_stage == "memory":
        evidence = f"{lead}在压力中推进线索"
        return json.dumps(
            {
                "summary": evidence,
                "facts": [{"text": f"{lead}推进线索", "evidence": evidence}],
                "unresolved_threads": [],
                "character_updates": [],
                "ledger_updates": {},
                "ledger_evidence": {},
            },
            ensure_ascii=False,
        ), ""
    if runtime_stage == "planner" and json_mode:
        approved = ["Old Archivist"] if any(move["new_character_candidates"] for move in moves) else []
        return json.dumps(
            {
                "character_moves": moves,
                "chapter_intent": {
                    "chapter_title": f"第{chapter_number}章 测试章节",
                    "cadence": "measured",
                    "next_focus": f"继续推进{lead}与{opposition}的线索",
                    "primary_conflict": {
                        "lead": lead,
                        "opposition": opposition,
                        "collision": f"{lead}与{opposition}围绕关键线索交锋",
                    },
                    "secondary_conflict": {"pressure": "time", "detail": "局势继续加压", "participants": []},
                    "approved_new_characters": approved,
                },
                "event_plan": {
                    "chapter_title": f"第{chapter_number}章 测试章节",
                    "turn": f"{lead}发现新线索",
                    "pivot": "局势发生转折",
                    "collision": f"{lead}与{opposition}围绕关键线索交锋",
                    "ordered_actions": moves,
                    "world_reactions": ["外部势力注意到新的线索。"],
                    "stakes": "如果失败，线索会断裂。",
                    "next_focus": f"继续推进{lead}与{opposition}的线索",
                    "chapter_satisfaction": {
                        "core_event": f"{lead}发现关键线索",
                        "obstacle": f"{opposition}阻止调查继续推进",
                        "visible_payoff": f"{lead}拿到可验证的关键证据",
                        "cost": "调查行动暴露了主角的关注方向",
                        "state_change": "关键事件从无头绪变为可以继续追查",
                        "next_hook": f"继续推进{lead}与{opposition}的线索",
                    },
                    "chapter_end_hook": {
                        "type": "悬念钩",
                        "strength": "medium",
                        "content": f"新的证据迫使{lead}继续追查",
                    },
                },
                "memory_constraints": {
                    "must_keep_facts": ["主角正在推进关键事件"],
                    "unresolved_threads": ["关键线索的真相仍未揭开"],
                    "protected_characters": [],
                    "protected_foreshadowing": [],
                    "author_constraints": [],
                    "current_focus": "调查",
                    "conflict_anchor": "目标冲突",
                    "event_guardrail": "保持紧张感",
                },
                "chapter_summary": {
                    "summary": f"{lead}推进调查，发现重要线索。",
                    "facts": ["发现关键证据"],
                    "unresolved_threads": ["证据背后的真相"],
                    "next_focus": f"继续推进{lead}与{opposition}的线索",
                    "chapter_title": f"第{chapter_number}章 测试章节",
                },
            },
            ensure_ascii=False,
        ), ""
    assert runtime_stage == "writer"
    return (
        f"第{chapter_number}章\n\n{lead}在压力中推进线索，{opposition}也被卷入同一场变化。"
        "\n\n事实：主角发现了关键证据。\n真相：幕后仍未揭开。\n",
        "",
    )


@pytest.fixture(autouse=True)
def clean_db_and_restore_runtime_settings(monkeypatch, tmp_path):
    """Clean up persistent SQLite DB to ensure test isolation."""
    import os as _os
    import apps.api.storage as storage
    import apps.api.routes.stories as story_routes
    import packages.story_core.runtime_config as runtime_config
    test_db_path = tmp_path / "stories-test.db"
    monkeypatch.setattr(runtime_config, "CONFIG_FILE", tmp_path / "runtime-config.json")
    monkeypatch.setattr(storage, "_DB_PATH", str(test_db_path))
    story_routes.store._db_path = str(test_db_path)
    with story_routes._generation_jobs_lock:
        story_routes._generation_jobs.clear()
        story_routes._active_generation_jobs.clear()
    with story_routes._automation_jobs_lock:
        story_routes._automation_jobs.clear()
        story_routes._active_automation_jobs.clear()
    from apps.api.storage import _get_db_path, _local
    db_path = _get_db_path()
    # Close all cached connections before deleting DB
    if hasattr(_local, "connections"):
        for conn in _local.connections.values():
            try:
                conn.close()
            except Exception:
                pass
        _local.connections.clear()
    # Remove the DB file
    if _os.path.exists(db_path):
        try:
            _os.remove(db_path)
        except PermissionError:
            # On Windows the file may still be locked; clear contents instead
            import sqlite3
            conn = sqlite3.connect(db_path)
            conn.execute("PRAGMA foreign_keys=OFF")
            conn.execute("DELETE FROM chapter_bundles")
            conn.execute("DELETE FROM stories")
            conn.commit()
            conn.close()
    original = client.get("/runtime-settings").json()
    reset = client.put("/runtime-settings", json=_runtime_configuration())
    assert reset.status_code == 200
    monkeypatch.setattr("packages.story_core.orchestrator.StoryOrchestrator._chat", _mock_story_chat)
    yield
    client.put("/runtime-settings", json=original)


def test_runtime_settings_get_returns_only_provider_stage_contract():
    response = client.get("/runtime-settings")
    assert response.status_code == 200
    payload = response.json()
    assert set(payload) == {
        "schema_version",
        "accounts",
        "stages",
        "image",
        "temperature",
        "new_character_policy",
    }

    serialized = json.dumps(payload)
    for obsolete_key in (
        "global_model",
        "character_model",
        "director_model",
        "writer_model",
        "memory_model",
    ):
        assert obsolete_key not in serialized
    assert "global" not in payload
    assert "agents" not in payload
    assert "strategy" not in payload


def test_runtime_settings_put_saves_and_returns_strict_configuration():
    candidate = _runtime_configuration(provider="codexcli")
    candidate["temperature"] = 0.35
    candidate["new_character_policy"] = "Auto-approve named candidates"

    update_resp = client.put(
        "/runtime-settings",
        json=candidate,
    )
    assert update_resp.status_code == 200
    assert update_resp.json() == _masked(candidate)

    loaded = client.get("/runtime-settings")
    assert loaded.status_code == 200
    assert loaded.json() == _masked(candidate)


def test_runtime_settings_never_returns_plaintext_api_key():
    candidate = _runtime_configuration(provider="openai")
    assert client.put("/runtime-settings", json=candidate).status_code == 200

    for body in (client.get("/runtime-settings").json(), client.put("/runtime-settings", json=candidate).json()):
        assert body["accounts"]["openai"]["api_key"] == "********"
        assert "sk-test" not in json.dumps(body)


def test_runtime_settings_can_reveal_saved_api_key_without_cache():
    candidate = _runtime_configuration(provider="openai")
    assert client.put("/runtime-settings", json=candidate).status_code == 200

    response = client.post(
        "/runtime-settings/reveal-api-key",
        json={"provider_id": "openai"},
    )

    assert response.status_code == 200
    assert response.json() == {"api_key": "sk-test"}
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["pragma"] == "no-cache"


def test_global_prompt_templates_can_be_read_and_updated(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_PROMPT_TEMPLATES_PATH", str(tmp_path / "templates.json"))
    original = client.get("/prompt-templates")
    assert original.status_code == 200
    writer = next(item for item in original.json()["templates"] if item["key"] == "writer")
    changed = writer["content"].replace("{{chapter_direction}}", "方向：{{chapter_direction}}")

    updated = client.put("/prompt-templates/writer", json={"content": changed})

    assert updated.status_code == 200
    assert updated.json()["content"] == changed
    assert updated.json()["source"] == "global_override"


def test_runtime_settings_put_with_masked_api_key_preserves_stored_key():
    saved = _runtime_configuration()
    assert client.put("/runtime-settings", json=saved).status_code == 200

    candidate = _runtime_configuration()
    candidate["accounts"]["openai"]["api_key"] = "********"
    candidate["temperature"] = 0.55

    update_resp = client.put("/runtime-settings", json=candidate)
    assert update_resp.status_code == 200
    assert update_resp.json() == _masked(candidate)

    from packages.story_core.runtime_config import get_runtime_configuration

    stored = get_runtime_configuration()
    assert stored.accounts["openai"].api_key == "sk-test"
    assert stored.temperature == 0.55


def test_runtime_settings_image_configuration_is_masked_restored_and_revealed_without_changing_text_provider():
    candidate = _runtime_configuration(provider="codexcli")
    candidate["image"] = {
        "enabled": True,
        "api_key": "image-secret",
        "base_url": "https://image.test/v1",
        "model": "cover-test-model",
    }

    saved = client.put("/runtime-settings", json=candidate)
    assert saved.status_code == 200
    assert saved.json()["stages"]["writer"]["provider_id"] == "codexcli"
    assert saved.json()["image"] == {
        "enabled": True,
        "api_key": "********",
        "base_url": "https://image.test/v1",
        "model": "cover-test-model",
    }
    assert "image-secret" not in json.dumps(saved.json())

    masked_update = json.loads(json.dumps(candidate))
    masked_update["image"]["api_key"] = "********"
    masked_update["image"]["model"] = "cover-updated-model"
    assert client.put("/runtime-settings", json=masked_update).status_code == 200

    from packages.story_core.runtime_config import get_runtime_configuration

    stored = get_runtime_configuration()
    assert stored.stages.writer.provider_id == "codexcli"
    assert stored.image.api_key == "image-secret"
    reveal = client.post("/runtime-settings/reveal-api-key", json={"provider_id": "image"})
    assert reveal.status_code == 200
    assert reveal.json() == {"api_key": "image-secret"}


@pytest.mark.parametrize("obsolete_key", ["global", "agents", "strategy", "global_model"])
def test_runtime_settings_put_rejects_obsolete_fields(obsolete_key):
    candidate = _runtime_configuration()
    candidate[obsolete_key] = {}

    response = client.put("/runtime-settings", json=candidate)

    assert response.status_code == 422


def test_runtime_settings_put_validation_does_not_replace_saved_configuration():
    saved = _runtime_configuration()
    assert client.put("/runtime-settings", json=saved).status_code == 200
    invalid = _runtime_configuration()
    invalid["stages"]["writer"]["model"] = "   "

    response = client.put("/runtime-settings", json=invalid)

    assert response.status_code == 422
    assert client.get("/runtime-settings").json() == _masked(saved)


def test_runtime_settings_validation_errors_never_echo_text_or_image_api_keys():
    candidate = _runtime_configuration()
    candidate["accounts"]["openai"]["api_key"] = "text-validation-secret"
    candidate["stages"]["writer"]["model"] = " "
    candidate["image"] = {
        "enabled": True,
        "api_key": "image-validation-secret",
        "base_url": "https://images.test/v1",
        "model": "cover-model",
    }

    response = client.put("/runtime-settings", json=candidate)

    assert response.status_code == 422
    assert "text-validation-secret" not in response.text
    assert "image-validation-secret" not in response.text


def test_runtime_settings_manual_boundary_rejects_non_json_and_oversize_without_echoing_body():
    binary = client.put("/runtime-settings", content=b"\xff\x00secret", headers={"content-type": "application/octet-stream"})
    assert binary.status_code == 422
    assert "secret" not in binary.text
    oversized = client.put(
        "/runtime-settings",
        content=b"x" * (1024 * 1024 + 1),
        headers={"content-type": "application/json"},
    )
    assert oversized.status_code == 413


def test_runtime_settings_test_validation_hides_all_nested_provider_keys():
    candidate = _runtime_configuration()
    candidate["accounts"]["codexcli"]["api_key"] = "codex-secret"
    candidate["accounts"]["openai"]["api_key"] = "text-secret"
    candidate["image"] = {"enabled": True, "api_key": "image-secret", "base_url": "https://image.test", "model": "m"}
    candidate["stages"]["writer"]["model"] = " "
    response = client.post("/runtime-settings/test", json={"stage": "writer", "runtime_settings": candidate})
    assert response.status_code == 422
    assert isinstance(response.json()["detail"], list)
    assert all(secret not in response.text for secret in ("codex-secret", "text-secret", "image-secret"))


def test_unrelated_validation_error_keeps_fastapi_default_detail_input():
    response = client.post("/file-projects/not-a-project/publishing/synopsis", json={"guidance": 3})
    assert response.status_code == 422
    assert response.json()["detail"][0]["input"] == 3


def _run_runtime_body_guard(path: str, *, method: str = "PUT", headers: list[tuple[bytes, bytes]], chunks: list[bytes]):
    received = []
    sent = []

    async def receive():
        received.append(True)
        index = len(received) - 1
        return {"type": "http.request", "body": chunks[index] if index < len(chunks) else b"", "more_body": index + 1 < len(chunks)}

    async def send(message):
        sent.append(message)

    scope = {
        "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method,
        "scheme": "http", "path": path, "raw_path": path.encode(), "query_string": b"",
        "headers": [(b"host", b"testserver"), *headers], "client": ("127.0.0.1", 1), "server": ("testserver", 80),
    }
    asyncio.run(app(scope, receive, send))
    return received, sent


@pytest.mark.parametrize("path", ["/runtime-settings", "/runtime-settings/test"])
def test_runtime_body_guard_stops_chunked_stream_at_limit(path):
    chunks = [b"x" * (128 * 1024)] * 10
    received, sent = _run_runtime_body_guard(path, method="POST" if path.endswith("/test") else "PUT", headers=[], chunks=chunks)
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert len(received) == 9
    assert len(starts) == 1
    assert starts[0]["status"] == 413


def test_runtime_body_guard_content_length_rejection_reads_zero_chunks():
    received, sent = _run_runtime_body_guard(
        "/runtime-settings", headers=[(b"content-length", str(1024 * 1024 + 1).encode())], chunks=[b"never-read"]
    )
    starts = [message for message in sent if message["type"] == "http.response.start"]
    assert received == []
    assert len(starts) == 1
    assert starts[0]["status"] == 413


def test_serialized_history_uses_saved_quality_and_adds_simplified_review(monkeypatch):
    from apps.api.routes.stories import _serialize_chapter_bundle
    from packages.story_core.engine import ChapterBundle
    from packages.story_core.models import StoryState

    story = StoryState(
        story_id="s-refresh-quality",
        outline="网游开服，主角靠千倍爆率低调发育。",
        genre="网游",
        style="升级流",
        world_facts=["低级材料交易只能形成价格、数量、时间戳等弱线索。"],
    )
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "职业选择栏弹出后，他选择元素法师学徒。"
        "【角色面板】游戏ID：夜烬；等级：1；职业：元素法师学徒；经验：0/100；主武器：新手法杖。"
        "夜烬进入灰烬村，只看见公告栏写着新手外坡怪物密度偏高，路口玩家还在排队接任务。"
        "他在低密度灰鼠坡小范围刷怪，击杀后看见掉落判定×1000，混沌之种未解析，获得灰鼠毒腺×12，任务进度一下推到清道夫前置只差一点。"
        "职业导师艾伦在木屋门口登记法师学徒，提醒元素回廊试炼需要先交十份毒腺。"
        "普通玩家还在路口排队，只当夜烬运气好。夜烬没有急着处理材料，只记下前置任务、法杖耐久和下一步再刷一轮。"
    ) * 28
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 灰烬村的登录日志",
        body=body,
        next_outline="继续低调验证规则。",
        updated_story=story,
        event_plan={"world_reactions": ["NPC只记录任务登记。"], "next_focus": "下一次验证。"},
        quality_report={"ok": False, "issues": ["stale"], "writing_review": {"issues": ["旧误判"]}},
    )

    monkeypatch.setattr(
        "apps.api.routes.stories._review_chapter_body",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("chapter reads must not rerun review")),
    )

    payload = _serialize_chapter_bundle(bundle, story.world_facts)

    assert payload["quality_report"]["writing_review"]["issues"] == ["旧误判"]
    assert payload["quality_report"]["simplified_review"]["schema_version"] == "simplified-review/v1"
    assert payload["quality_report"]["simplified_review"]["total_issues"] == 2


def test_review_recommendation_only_revises_for_hard_errors():
    from apps.api.routes.stories import _review_recommendation

    advisory = _review_recommendation(
        {"writing_review": {"pass": False, "issues": ["对话不够自然。", "章末动作不够具体。"]}}
    )
    blocking = _review_recommendation(
        {"issues": ["body_too_short"], "writing_review": {"issues": ["对话不够自然。"]}}
    )

    assert advisory["action"] == "continue"
    assert advisory["must_fix"] == []
    assert blocking["action"] == "revise"
    assert blocking["must_fix"] == ["body_too_short"]


def test_project_writing_packet_returns_packet():
    story_id = "s-writing-packet-api"
    project_id = "p-writing-packet-api"
    create_story = client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "网游开服，苏叶以夜烬身份低调验证千倍爆率。",
            "genre": "网游",
            "style": "升级流",
            "characters": [{"name": "苏叶", "role": "主角", "game_id": "夜烬", "goals": ["安全升到10级"]}],
        },
    )
    assert create_story.status_code == 200
    create_project = client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "荷在网游里成神",
            "seed_outline": "网游开服，主角靠千倍爆率低调发育。",
            "active_story_id": story_id,
            "author_constraints": ["现实姓名和游戏ID必须分层。"],
        },
    )
    assert create_project.status_code == 200

    packet_response = client.get(f"/projects/{project_id}/writing-packet?chapter_number=1")
    assert packet_response.status_code == 200
    packet = packet_response.json()
    assert packet["schema_version"] == "codex-writing-packet/v1"
    assert packet["governance_gate"]["reviewer"] == "chapter_governance_gate/v1"
    assert packet["governance_gate"]["next_action"] == "write_or_revise_chapter"
    assert packet["protagonist"]["real_name"] == "苏叶"
    assert any("游戏ID：夜烬" in item or "现实姓名：苏叶" in item for item in packet["hard_locks"])
    assert packet["scene_cards"]
    assert any("灰鼠" in " ".join(card.get("must_show", []) + card.get("fact_locks", [])) for card in packet["scene_cards"]) or any(
        "首杀" in str(card) or "验证" in str(card) for card in packet["scene_cards"]
    )


def test_project_writing_packet_ignores_previous_bundle_attribute_decision(monkeypatch):
    story_id = "s-attribute-packet-scope"
    project_id = "p-attribute-packet-scope"
    allocation_rule = {
        "mode": "free",
        "points_per_level": 5,
        "starting_level": 1,
        "base_attributes": {"智力": 5},
        "allow_carry": True,
        "respec_rule": "主城洗点",
    }
    story = StoryState(
        story_id=story_id,
        outline="夜烬继续探索。",
        genre="网游",
        style="白描",
        current_chapter=1,
        progression_ledger={"protagonist": {"level": "Lv.2", "unallocated_attribute_points": 5}},
    )
    story_routes.store.create(story)
    story_routes.store.create_project(NovelProject(project_id=project_id, title="属性点范围", active_story_id=story_id))
    story_routes.store.append_chapter_bundle(
        story_id,
        ChapterBundle(
            chapter_number=1,
            body="",
            next_outline="继续探索",
            updated_story=story,
            event_plan={"attribute_allocation_decision": {"mode": "carry", "remaining": 5, "reason": "留给转职"}},
        ),
    )

    def inject_attribute_rule(project, packet_story, *, has_history):
        packet_story.world_context = {"power_system_spec": {"attribute_allocation": allocation_rule}}

    monkeypatch.setattr(story_routes, "_sync_project_context_for_story", inject_attribute_rule)

    response = client.get(f"/projects/{project_id}/writing-packet?chapter_number=2")

    assert response.status_code == 200
    allocation = response.json()["attribute_allocation"]
    assert allocation["available_points"] == 5
    assert "chapter_decision" not in allocation


def test_project_writing_packet_uses_explicit_non_game_project_type():
    story_id = "s-xianxia-packet-api"
    project_id = "p-xianxia-packet-api"
    create_story = client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "林照被分去祖祠看守断香炉。",
            "genre": "修仙",
            "style": "白描",
            "characters": [{"name": "林照", "role": "protagonist"}],
        },
    )
    assert create_story.status_code == 200
    create_project = client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "我替宗门看守断香炉",
            "seed_outline": "外门弟子看守断香炉。",
            "active_story_id": story_id,
            "author_constraints": ["不要写网游面板、背包、铜币、掉落、任务牌或玩家生态。"],
            "world_blueprint": {
                "genre_plugin_ids": ["xianxia"],
                "premise": "断香炉里有未了因果。",
                "constraints": ["第一章只打开断香炉异常，不直接变强。"],
            },
        },
    )
    assert create_project.status_code == 200

    packet_response = client.get(f"/projects/{project_id}/writing-packet?chapter_number=1")

    assert packet_response.status_code == 200
    packet = packet_response.json()
    text = json.dumps(packet, ensure_ascii=False)
    assert "小说类型：xianxia" in packet["world_facts"]
    assert packet["whole_chapter_contract"] == {}
    assert "现实压力 -> 登录建号" not in text
    assert "见习冒险者（未转职）" not in text
    assert "清道夫委托" not in text


def test_regular_project_world_blueprint_patch_merges_fields_and_preserves_explicit_clears():
    project_id = "p-world-blueprint-patch"
    created = client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "普通项目世界观更新",
            "world_blueprint": {
                "genre_plugin_ids": ["xuanhuan"],
                "world_rules": ["旧规则"],
                "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
            },
        },
    )
    assert created.status_code == 200

    merged = client.patch(
        f"/projects/{project_id}",
        json={"world_blueprint": {"locations": [{"name": "新港"}]}},
    )

    assert merged.status_code == 200
    assert merged.json()["world_blueprint"] == {
        "genre_plugin_ids": ["xuanhuan"],
        "world_rules": ["旧规则"],
        "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
        "locations": [{"name": "新港"}],
    }

    normalized_and_cleared = client.patch(
        f"/projects/{project_id}",
        json={"world_blueprint": {"genre_plugin_ids": [" XIANXIA "], "world_rules": []}},
    )
    assert normalized_and_cleared.status_code == 200
    assert normalized_and_cleared.json()["world_blueprint"] == {
        "genre_plugin_ids": ["xianxia"],
        "world_rules": [],
        "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
        "locations": [{"name": "新港"}],
    }

    cleared_type = client.patch(
        f"/projects/{project_id}",
        json={"world_blueprint": {"genre_plugin_ids": []}},
    )
    assert cleared_type.status_code == 200
    assert cleared_type.json()["world_blueprint"]["genre_plugin_ids"] == []
    assert cleared_type.json()["world_blueprint"]["monster_profiles"] == [{"id": "wolf", "name": "灰狼"}]


def test_regular_project_saves_and_clears_optional_writing_style():
    story_id = "s-optional-writing-style"
    project_id = "p-optional-writing-style"
    assert client.post(
        "/stories",
        json={"story_id": story_id, "outline": "开篇。", "genre": "都市", "style": "白描、现代中文"},
    ).status_code == 200
    assert client.post(
        "/projects",
        json={"project_id": project_id, "title": "可选文风", "active_story_id": story_id},
    ).status_code == 200

    selected = client.patch(
        f"/projects/{project_id}",
        json={"world_blueprint": {"writing_style": "幽默"}},
    )

    assert selected.status_code == 200
    assert selected.json()["world_blueprint"]["writing_style"] == "幽默"
    assert client.get(f"/stories/{story_id}").json()["style"] == "幽默"

    cleared = client.patch(
        f"/projects/{project_id}",
        json={"world_blueprint": {"writing_style": ""}},
    )

    assert cleared.status_code == 200
    assert cleared.json()["world_blueprint"]["writing_style"] == ""
    assert client.get(f"/stories/{story_id}").json()["style"] == ""


def test_regular_project_rejects_unknown_writing_style():
    project_id = "p-invalid-writing-style"
    assert client.post("/projects", json={"project_id": project_id, "title": "Invalid Style"}).status_code == 200

    response = client.patch(
        f"/projects/{project_id}",
        json={"world_blueprint": {"writing_style": "通用白描"}},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "invalid_writing_style"


def test_regular_project_updates_are_serialized_per_project(monkeypatch):
    import apps.api.routes.stories as story_routes

    project_id = "p-concurrent-world-blueprint"
    created = client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "普通项目并发更新",
            "world_blueprint": {"monster_profiles": [{"id": "wolf", "name": "灰狼"}]},
        },
    )
    assert created.status_code == 200

    original_get_project = story_routes.store.get_project
    read_barrier = threading.Barrier(2)
    start_barrier = threading.Barrier(3)
    responses = []
    errors: list[BaseException] = []

    def synchronized_get_project(requested_project_id):
        project = original_get_project(requested_project_id)
        if requested_project_id == project_id:
            try:
                read_barrier.wait(timeout=0.25)
            except threading.BrokenBarrierError:
                pass
        return project

    monkeypatch.setattr(story_routes.store, "get_project", synchronized_get_project)

    def update(payload):
        try:
            start_barrier.wait()
            responses.append(client.patch(f"/projects/{project_id}", json={"world_blueprint": payload}))
        except BaseException as exc:  # Capture worker failures for the main assertion thread.
            errors.append(exc)

    threads = [
        threading.Thread(target=update, args=({"world_rules": ["并发规则"]},)),
        threading.Thread(target=update, args=({"locations": [{"name": "并发新港"}]},)),
    ]
    for thread in threads:
        thread.start()
    start_barrier.wait()
    for thread in threads:
        thread.join()

    assert errors == []
    assert [response.status_code for response in responses] == [200, 200]
    final_project = original_get_project(project_id)
    assert final_project.world_blueprint == {
        "world_rules": ["并发规则"],
        "locations": [{"name": "并发新港"}],
        "monster_profiles": [{"id": "wolf", "name": "灰狼"}],
    }


def test_project_lifecycle_archive_trash_restore_and_permanent_delete():
    project_id = "p-delete-project"
    story_id = "s-delete-project"
    story_response = client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "林照看守祖祠断香炉。",
            "genre": "xianxia",
            "style": "白描、现代中文",
        },
    )
    assert story_response.status_code == 200
    project_response = client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "待删除修仙项目",
            "seed_outline": "林照看守祖祠断香炉。",
            "active_story_id": story_id,
            "world_blueprint": {"genre_plugin_ids": ["xianxia"]},
        },
    )
    assert project_response.status_code == 200

    archive_response = client.post(f"/projects/{project_id}/archive")
    assert archive_response.status_code == 200
    assert archive_response.json()["project_lifecycle"] == "archived"
    assert client.get("/projects").json() == []
    assert [item["project_id"] for item in client.get("/projects?lifecycle=archived").json()] == [project_id]

    restore_response = client.post(f"/projects/{project_id}/restore")
    assert restore_response.status_code == 200
    assert restore_response.json()["project_lifecycle"] == "active"

    trash_response = client.post(f"/projects/{project_id}/trash")
    assert trash_response.status_code == 200
    assert trash_response.json()["project_lifecycle"] == "trashed"
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert [item["project_id"] for item in client.get("/projects?lifecycle=trashed").json()] == [project_id]

    wrong_title = client.delete(f"/projects/{project_id}?confirm_title=wrong")
    assert wrong_title.status_code == 422

    delete_response = client.delete(
        f"/projects/{project_id}",
        params={"confirm_title": "待删除修仙项目"},
    )

    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "deleted": True,
        "project_id": project_id,
        "deleted_story_ids": [story_id],
    }
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert client.get(f"/stories/{story_id}").status_code == 404


def test_project_lifecycle_change_is_blocked_while_generation_is_active():
    project_id = "p-busy-project"
    story_id = "s-busy-project"
    assert client.post(
        "/stories",
        json={"story_id": story_id, "outline": "主角处理一桩现实麻烦。", "genre": "urban", "style": "现代中文"},
    ).status_code == 200
    assert client.post("/projects", json={"project_id": project_id, "title": "生成中的项目", "active_story_id": story_id}).status_code == 200
    with story_routes._generation_jobs_lock:
        story_routes._generation_jobs["job-busy"] = {"job_id": "job-busy", "story_id": story_id, "status": "running"}
        story_routes._active_generation_jobs[story_id] = "job-busy"

    response = client.post(f"/projects/{project_id}/archive")

    assert response.status_code == 409
    assert response.json()["detail"] == "project_generation_in_progress"


def test_database_project_prompt_preview_exposes_modular_prompts():
    project_id = "p-prompt-preview"
    story_id = "s-prompt-preview"
    assert client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "林照看守祖祠断香炉。",
            "genre": "xianxia",
            "style": "白描、现代中文",
            "characters": [{"name": "林照", "role": "protagonist"}],
        },
    ).status_code == 200
    assert client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "断香炉",
            "seed_outline": "林照看守祖祠断香炉。",
            "active_story_id": story_id,
            "world_blueprint": {"genre_plugin_ids": ["xianxia"]},
        },
    ).status_code == 200

    response = client.get(f"/projects/{project_id}/prompt-preview?chapter_number=1")

    assert response.status_code == 200
    preview = response.json()
    assert preview["schema_version"] == "project-prompt-preview/v1"
    assert preview["project_id"] == project_id
    assert preview["chapter_number"] == 1
    assert {module["key"] for module in preview["modules"]} >= {"core_context", "character_context", "genre_context"}
    assert {prompt["key"] for prompt in preview["prompts"]} >= {"director_plan", "writer_body", "review_agents"}
    assert "style_adapt" not in {prompt["key"] for prompt in preview["prompts"]}
    writer_prompt = next(prompt for prompt in preview["prompts"] if prompt["key"] == "writer_body")
    assert all(
        heading in writer_prompt["content"]
        for heading in ("## 输出要求", "## 本章方向", "## 本章事实", "## 出场人物", "## 正文写法")
    )
    assert "五块装配" in writer_prompt["description"]


def test_file_project_regenerate_rejects_frozen_chapter(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "frozen-file-project"
    _make_file_project(
        project_root,
        project_id="p-frozen-file",
        state={
            "story_id": "s-file-api",
            "outline": "A grounded game story.",
            "current_chapter": 1,
            "world_facts": [],
            "progression_ledger": {"continuity_lock": {"chapters_frozen": [1]}},
        },
    )

    response = client.post(
        "/file-projects/p-frozen-file/regenerate-chapter",
        json={"chapter_number": 1},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "chapter_frozen:1:regenerate"


def test_file_project_regenerate_accepts_temporary_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "guided-file-project"
    _make_file_project(
        project_root,
        project_id="p-guided-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    captured: dict[str, object] = {}

    def fake_regenerate(self, chapter_number, engine=None, *, variant=None, guidance=None, commit_message=None):
        captured["chapter_number"] = chapter_number
        captured["variant"] = variant
        captured["guidance"] = guidance
        return {"schema_version": "file-project-regenerate/v1", "chapter_number": chapter_number, "chapter_title": "Guided"}

    monkeypatch.setattr("packages.story_core.file_project_store.FileProjectStore.regenerate_chapter", fake_regenerate)

    response = client.post(
        "/file-projects/p-guided-file/regenerate-chapter",
        json={"chapter_number": 1, "variant": "progression-lead", "guidance": "keep the dissection ledger"},
    )

    assert response.status_code == 200
    assert captured == {
        "chapter_number": 1,
        "variant": "progression-lead",
        "guidance": "keep the dissection ledger",
    }


def test_file_project_generate_next_accepts_chapter_direction_id(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "direction-file-project"
    _make_file_project(
        project_root,
        project_id="p-direction-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    captured: dict[str, object] = {}

    def fake_generate_next(self, engine=None, *, chapter_direction_id=None, commit_message=None):
        captured["chapter_direction_id"] = chapter_direction_id
        return {"schema_version": "file-project-generate-next/v1", "chapter_number": 2, "chapter_title": "Direction"}

    monkeypatch.setattr("packages.story_core.file_project_store.FileProjectStore.generate_next_chapter", fake_generate_next)

    response = client.post(
        "/file-projects/p-direction-file/generate-next",
        json={"chapter_direction_id": "chaos-seed-trace"},
    )

    assert response.status_code == 200
    assert captured["chapter_direction_id"] == "chaos-seed-trace"
    assert response.json()["generated"]["chapter_title"] == "Direction"


def test_file_project_candidate_routes_list_and_discard_pending_draft(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "candidate-file-project"
    _make_file_project(
        project_root,
        project_id="p-candidate-file",
        state={"story_id": "s-file-api", "outline": "A story.", "current_chapter": 0, "world_facts": []},
    )
    from packages.story_core.candidate_draft import CandidateDraft
    from packages.story_core.file_project_store import FileProjectStore

    draft = CandidateDraft.create(project_id="p-candidate-file", chapter_number=1, body="候选正文")
    FileProjectStore(project_root).candidate_store.save(draft)

    listed = client.get("/file-projects/p-candidate-file/candidates")
    assert listed.status_code == 200
    assert listed.json()["items"][0]["candidate_id"] == draft.candidate_id

    discarded = client.post(f"/file-projects/p-candidate-file/candidates/{draft.candidate_id}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["candidate"]["status"] == "discarded"


def test_file_project_candidate_routes_accept_file_prefixed_candidate_id(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "prefixed-candidate-project"
    _make_file_project(
        project_root,
        project_id="",
        state={
            "story_id": "file:prefixed-candidate-project",
            "outline": "A story.",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    from packages.story_core.candidate_draft import CandidateDraft
    from packages.story_core.file_project_store import FileProjectStore

    draft = CandidateDraft.create(
        project_id="file:prefixed-candidate-project",
        chapter_number=1,
        body="带前缀的候选正文",
    )
    FileProjectStore(project_root).candidate_store.save(draft)

    base = "/file-projects/file%3Aprefixed-candidate-project/candidates"
    listed = client.get(f"{base}?chapter_number=1")
    assert listed.status_code == 200
    assert [item["candidate_id"] for item in listed.json()["items"]] == [draft.candidate_id]

    loaded = client.get(f"{base}/{draft.candidate_id}")
    assert loaded.status_code == 200
    assert loaded.json()["candidate"]["body"] == "带前缀的候选正文"

    discarded = client.post(f"{base}/{draft.candidate_id}/discard")
    assert discarded.status_code == 200
    assert discarded.json()["candidate"]["status"] == "discarded"


def test_file_project_generation_job_accepts_temporary_guidance(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "guided-job-file-project"
    _make_file_project(
        project_root,
        project_id="p-guided-job-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    submitted: dict[str, object] = {}

    def fake_submit(fn, job_id, project_id, **kwargs):
        submitted["fn"] = fn
        submitted["job_id"] = job_id
        submitted["project_id"] = project_id
        submitted["kwargs"] = kwargs

    monkeypatch.setattr(file_projects._file_generation_executor, "submit", fake_submit)

    response = client.post(
        "/file-projects/p-guided-job-file/generation-jobs",
        json={"chapter_number": 1, "guidance": "use dissection guidance"},
    )

    assert response.status_code == 200
    assert submitted["project_id"] == "p-guided-job-file"
    assert submitted["kwargs"] == {
        "chapter_number": 1,
        "variant": None,
        "guidance": "use dissection guidance",
    }


def test_file_project_generation_job_accepts_chapter_direction_id(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "direction-job-file-project"
    _make_file_project(
        project_root,
        project_id="p-direction-job-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    submitted: dict[str, object] = {}

    def fake_submit(fn, job_id, project_id, **kwargs):
        submitted["fn"] = fn
        submitted["job_id"] = job_id
        submitted["project_id"] = project_id
        submitted["kwargs"] = kwargs

    monkeypatch.setattr(file_projects._file_generation_executor, "submit", fake_submit)

    response = client.post(
        "/file-projects/p-direction-job-file/generation-jobs",
        json={"chapter_direction_id": "guild-ecology"},
    )

    assert response.status_code == 200
    assert submitted["project_id"] == "p-direction-job-file"
    assert submitted["kwargs"]["chapter_direction_id"] == "guild-ecology"


def test_file_project_generation_job_response_has_steps(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "queued-step-file-project"
    _make_file_project(
        project_root,
        project_id="p-queued-step-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    monkeypatch.setattr(file_projects._file_generation_executor, "submit", lambda *args, **kwargs: None)

    response = client.post(
        "/file-projects/p-queued-step-file/generation-jobs",
        json={"chapter_direction_id": "guild-queued"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["steps"][0]["message"] == "生成已排队"
    assert payload["steps"][0]["status"] == "queued"
    assert payload["steps"][0]["stage"] == "orchestrator"
    assert payload["steps"][0]["source"] == "file-project-route"
    assert isinstance(payload["steps"][0]["at"], str)
    job_id = payload["job_id"]

    get_response = client.get(f"/file-projects/p-queued-step-file/generation-jobs/{job_id}")
    assert get_response.status_code == 200
    polled = get_response.json()
    assert len(polled["steps"]) >= 1
    assert polled["steps"][0]["status"] == "queued"


def test_file_project_current_generation_job_returns_active_job(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "current-job-file-project"
    _make_file_project(
        project_root,
        project_id="p-current-job-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    monkeypatch.setattr(file_projects._file_generation_executor, "submit", lambda *args, **kwargs: None)

    missing = client.get("/file-projects/p-current-job-file/generation-jobs/current")
    assert missing.status_code == 404

    started = client.post("/file-projects/p-current-job-file/generation-jobs", json={})
    assert started.status_code == 200

    current = client.get("/file-projects/p-current-job-file/generation-jobs/current")
    assert current.status_code == 200
    payload = current.json()
    assert payload["job_id"] == started.json()["job_id"]
    assert payload["status"] == "queued"
    assert isinstance(payload["steps"], list) and payload["steps"]


def test_file_project_generation_job_history_is_sorted_and_skips_invalid_logs(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "history-job-file-project"
    _make_file_project(
        project_root,
        project_id="p-history-job-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 2, "world_facts": []},
    )
    log_dir = project_root / ".story-system" / "generation-jobs"
    log_dir.mkdir(parents=True)
    older = {
        "job_id": "fgj-older",
        "story_id": "file:p-history-job-file",
        "chapter_number": 1,
        "status": "completed",
        "progress": "已完成",
        "error": None,
        "created_at": "2026-07-29T01:00:00+00:00",
        "updated_at": "2026-07-29T01:10:00+00:00",
        "steps": [{"message": "旧任务", "status": "done"}],
    }
    newer = {
        **older,
        "job_id": "fgj-newer",
        "chapter_number": 2,
        "status": "failed",
        "progress": "审稿改稿失败",
        "error": "candidate_above_chapter_maximum",
        "created_at": "2026-07-29T02:00:00+00:00",
        "updated_at": "2026-07-29T02:10:00+00:00",
    }
    (log_dir / "fgj-older.json").write_text(json.dumps(older, ensure_ascii=False), encoding="utf-8")
    (log_dir / "fgj-newer.json").write_text(json.dumps(newer, ensure_ascii=False), encoding="utf-8")
    (log_dir / "latest.json").write_text(json.dumps(newer, ensure_ascii=False), encoding="utf-8")
    (log_dir / "fgj-broken.json").write_text("{not-json", encoding="utf-8")

    response = client.get("/file-projects/p-history-job-file/generation-jobs?limit=30")

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "file-generation-job-history/v1"
    assert [item["job_id"] for item in payload["items"]] == ["fgj-newer", "fgj-older"]
    assert payload["items"][0] == {
        "job_id": "fgj-newer",
        "story_id": "file:p-history-job-file",
        "chapter_number": 2,
        "status": "failed",
        "progress": "审稿改稿失败",
        "error": "candidate_above_chapter_maximum",
        "created_at": "2026-07-29T02:00:00+00:00",
        "updated_at": "2026-07-29T02:10:00+00:00",
    }


def test_file_project_generation_job_history_returns_empty_list(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "empty-history-file-project"
    _make_file_project(project_root, project_id="p-empty-history-file")

    response = client.get("/file-projects/p-empty-history-file/generation-jobs")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_file_project_generation_log_survives_in_memory_job_reset(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "persistent-log-file-project"
    _make_file_project(
        project_root,
        project_id="p-persistent-log-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    monkeypatch.setattr(file_projects._file_generation_executor, "submit", lambda *args, **kwargs: None)

    started = client.post("/file-projects/p-persistent-log-file/generation-jobs", json={})
    assert started.status_code == 200
    started_payload = started.json()

    with file_projects._file_generation_jobs_lock:
        file_projects._file_generation_jobs.clear()
        file_projects._active_file_generation_jobs.clear()

    restored = client.get("/file-projects/p-persistent-log-file/generation-jobs/current")

    assert restored.status_code == 200
    payload = restored.json()
    assert payload["job_id"] == started_payload["job_id"]
    assert payload["steps"] == started_payload["steps"]


def test_reserved_generation_job_reuses_completed_persisted_job(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "reserved-job-file-project"
    _make_file_project(
        project_root,
        project_id="p-reserved-job-file",
        state={"story_id": "s-reserved-job", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )
    submitted: list[tuple[object, ...]] = []
    monkeypatch.setattr(
        file_projects._file_generation_executor,
        "submit",
        lambda *args, **_kwargs: submitted.append(args),
    )

    first = file_projects.start_file_generation_job(
        "p-reserved-job-file", reserved_job_id="fgj-reserved"
    )
    with file_projects._file_generation_jobs_lock:
        job = file_projects._file_generation_jobs["fgj-reserved"]
        job["status"] = "completed"
        file_projects._persist_file_generation_job(job)
        file_projects._file_generation_jobs.clear()
        file_projects._active_file_generation_jobs.clear()

    recovered = file_projects.start_file_generation_job(
        "p-reserved-job-file", reserved_job_id="fgj-reserved"
    )

    assert first["job_id"] == recovered["job_id"] == "fgj-reserved"
    assert recovered["status"] == "completed"
    assert len(submitted) == 1


def test_story_current_generation_job_returns_active_job(monkeypatch):
    import apps.api.routes.stories as story_routes

    client.post(
        "/stories",
        json={
            "story_id": "s-current-job",
            "outline": "A cautious player tests a strange login token.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    monkeypatch.setattr(story_routes._generation_executor, "submit", lambda *args, **kwargs: None)

    missing = client.get("/stories/s-current-job/generation-jobs/current")
    assert missing.status_code == 404

    started = client.post("/stories/s-current-job/generation-jobs")
    assert started.status_code == 200

    current = client.get("/stories/s-current-job/generation-jobs/current")
    assert current.status_code == 200
    payload = current.json()
    assert payload["job_id"] == started.json()["job_id"]
    assert payload["status"] == "queued"
    assert isinstance(payload["steps"], list) and payload["steps"]


def test_user_facing_generation_error_maps_quality_failure():
    from packages.story_core.file_project_store import ChapterQualityError

    exc = ChapterQualityError(
        "generate_quality_failed:writing_review; 推演事件未被正文场景化：npc_counter dump; AI高频套话进入正文：轻松。",
        quality_report={
            "ok": False,
            "issues": ["推演事件未被正文场景化：npc_counter dump"],
            "writing_review": {
                "pass": False,
                "issues": ["推演事件未被正文场景化：npc_counter dump", "AI高频套话进入正文：轻松。"],
            },
        },
        operation="generate",
    )

    message = file_projects._user_facing_generation_error(exc)

    assert message.startswith("章节质量检查未通过")
    assert "npc_counter" not in message
    assert "generate_quality_failed" not in message
    assert "重试" in message


def test_user_facing_generation_error_maps_common_failures():
    assert "模型请求失败" in file_projects._user_facing_generation_error(
        ValueError("generate_failed:planner model_request_failed:模型 HTTP 400")
    )
    assert "字数不达标" in file_projects._user_facing_generation_error(
        ValueError("generate_length_failed:body_chars 1200 < 3800")
    )
    assert "正文为空" in file_projects._user_facing_generation_error(ValueError("generate_failed:body"))
    assert "超时" in file_projects._user_facing_generation_error(ValueError("generate_failed:plan_timeout"))
    assert file_projects._user_facing_generation_error(ValueError("unexpected")) == "生成失败，请重试。"


def test_user_facing_generation_error_maps_missing_api_key():
    message = file_projects._user_facing_generation_error(ValueError("generate_failed:Missing OPENAI_API_KEY"))

    assert "API Key" in message
    assert "重试" in message


def test_file_project_generation_job_polling_does_not_reload_project_store(tmp_path, monkeypatch):
    monkeypatch.setenv("NOVEL_AUTOGROWTH_FILE_PROJECTS_DIR", str(tmp_path))
    project_root = tmp_path / "poll-cache-file-project"
    _make_file_project(
        project_root,
        project_id="p-poll-cache-file",
        state={"story_id": "s-file-api", "outline": "A grounded game story.", "current_chapter": 1, "world_facts": []},
    )

    project_id = "file:p-poll-cache-file"
    job_id = "fgj-poll-cache"
    with file_projects._file_generation_jobs_lock:
        file_projects._file_generation_jobs.clear()
        file_projects._active_file_generation_jobs.clear()
        file_projects._file_generation_jobs[job_id] = {
            "job_id": job_id,
            "story_id": project_id,
            "status": "queued",
            "progress": "queued",
            "starting_chapter": 1,
            "error": "",
            "created_at": file_projects._now_iso(),
            "updated_at": file_projects._now_iso(),
            "chapter_number": None,
        }
        file_projects._active_file_generation_jobs[project_id] = job_id

    def fail_if_called(project_id: str):
        raise AssertionError(f"Unexpected _store_for call for {project_id}")

    try:
        monkeypatch.setattr(file_projects, "_store_for", fail_if_called)

        response = client.get(f"/file-projects/{project_id}/generation-jobs/{job_id}")

        assert response.status_code == 200
        payload = response.json()
        assert payload["job_id"] == job_id
        assert payload["status"] == "queued"
    finally:
        with file_projects._file_generation_jobs_lock:
            file_projects._file_generation_jobs.clear()
            file_projects._active_file_generation_jobs.clear()




@pytest.mark.parametrize("stage", ["character", "director", "global", "unknown"])
def test_runtime_connection_rejects_non_runtime_stages(stage):
    response = client.post(
        "/runtime-settings/test",
        json={
            "stage": stage,
            "runtime_settings": _runtime_configuration(),
        },
    )

    assert response.status_code == 422


def test_runtime_connection_rejects_old_agent_name_contract():
    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "writer",
            "runtime_settings": _runtime_configuration(),
        },
    )

    assert response.status_code == 422




def test_runtime_cli_info_reports_detected_version(monkeypatch):
    candidate = _runtime_configuration(provider="codexcli")
    candidate["accounts"]["codexcli"]["codex_command"] = "candidate-codex"
    assert client.put("/runtime-settings", json=candidate).status_code == 200
    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.read_codex_cli_version",
        lambda command: f"version-from-{command}",
    )
    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.read_codex_cli_models",
        lambda: ["gpt-5.6-sol", "gpt-5.5"],
    )
    monkeypatch.setattr(
        "apps.api.routes.runtime_settings.read_latest_codex_cli_version",
        lambda: "0.145.0",
    )

    response = client.get("/runtime-settings/cli-info")

    assert response.status_code == 200
    assert response.json() == {
        "available": True,
        "command": "candidate-codex",
        "version": "version-from-candidate-codex",
        "models": ["gpt-5.6-sol", "gpt-5.5"],
        "latest_version": "0.145.0",
        "update_status": "unknown",
    }




def test_runtime_strategy_keeps_only_non_model_compatibility_fields():
    response = client.put(
        "/runtime-strategy",
        json={
            "mode": "LLM-assisted",
            "temperature": 0.45,
            "new_character_policy": "Auto-approve named candidates",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "mode": "LLM-assisted",
        "temperature": 0.45,
        "new_character_policy": "Auto-approve named candidates",
    }
    settings = client.get("/runtime-settings").json()
    assert settings["temperature"] == 0.45
    assert settings["new_character_policy"] == "Auto-approve named candidates"


@pytest.mark.parametrize(
    "model_field",
    ["global_model", "character_model", "director_model", "writer_model", "memory_model"],
)
def test_runtime_strategy_rejects_model_fields(model_field):
    payload = {
        "mode": "LLM-assisted",
        "temperature": 0.7,
        "new_character_policy": "Director review",
        model_field: "obsolete-model",
    }

    response = client.put("/runtime-strategy", json=payload)

    assert response.status_code == 422


def test_story_can_be_created_and_rolled_back():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-001",
            "outline": "A detective prince uncovers palace crimes.",
            "genre": "fantasy",
            "style": "noir",
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["current_chapter"] == 0
    assert create_resp.json()["history"] == []

    gen_resp = client.post("/stories/s-001/generate")
    assert gen_resp.status_code == 200
    assert gen_resp.json()["chapter_number"] == 1

    rollback_resp = client.post("/stories/s-001/rollback")
    assert rollback_resp.status_code == 200
    assert rollback_resp.json()["current_chapter"] == 0


def test_story_can_store_characters_and_freeze_them():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-characters",
            "outline": "A palace clerk learns the truth about the treasury.",
            "genre": "fantasy",
            "style": "court intrigue",
            "characters": [
                {
                    "name": "Pei An",
                    "role": "clerk",
                    "goals": ["protect the evidence"],
                    "frozen": False,
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["characters"][0]["name"] == "Pei An"

    freeze_resp = client.post("/stories/s-characters/characters/Pei%20An/freeze")
    assert freeze_resp.status_code == 200
    assert freeze_resp.json()["characters"][0]["frozen"] is True


def test_story_can_store_global_default_model_in_agent_settings():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-global-model",
            "outline": "A court witness shifts the balance of power.",
            "genre": "mystery",
            "style": "tense",
            "agent_settings": {
                "global_model": "gpt-global",
                "character_model": "",
                "director_model": "",
                "writer_model": "",
            },
        },
    )

    assert create_resp.status_code == 200
    assert create_resp.json()["agent_settings"]["global_model"] == "gpt-global"


def test_story_serializes_character_lifecycle_fields():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-lifecycle",
            "outline": "A witness keeper enters the archive under a false name.",
            "genre": "mystery",
            "style": "tense",
            "characters": [
                {
                    "name": "Old Archivist",
                    "role": "supporting",
                    "goals": ["hide the witness"],
                    "frozen": False,
                    "lifecycle_state": "proposed",
                    "last_proposed_chapter": 2,
                    "last_approved_chapter": 0,
                    "introduced_by": "Su Wan",
                }
            ],
        },
    )

    assert create_resp.status_code == 200
    character = create_resp.json()["characters"][0]
    assert character["lifecycle_state"] == "proposed"
    assert character["last_proposed_chapter"] == 2
    assert character["last_approved_chapter"] == 0
    assert character["introduced_by"] == "Su Wan"


def test_agent_settings_influence_story_approval_flow():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-agent-settings",
            "outline": "A court witness arrives under a false name.",
            "genre": "mystery",
            "style": "tense",
            "agent_settings": {
                "mode": "LLM-assisted",
                "character_model": "qwen3.6-plus",
                "director_model": "qwen3.6-plus",
                "writer_model": "qwen3.6-plus",
                "temperature": "0.85",
                "new_character_policy": "Auto-approve named candidates",
            },
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "protagonist",
                    "goals": ["find the witness"],
                    "secrets": ["Old archivist knows the false name."],
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    assert create_resp.json()["agent_settings"]["mode"] == "LLM-assisted"

    generated = client.post("/stories/s-agent-settings/generate")
    assert generated.status_code == 200

    story = generated.json()["updated_story"]
    assert story["agent_settings"]["new_character_policy"] == "Auto-approve named candidates"
    assert "Old Archivist" in generated.json()["conflict_summary"]["approved_new_characters"]


def test_lifecycle_fields_remain_present_across_generate_freeze_and_rollback():
    create_resp = client.post(
        "/stories",
        json={
            "story_id": "s-lifecycle-flow",
            "outline": "A clerk follows witness rumors through sealed archives.",
            "genre": "mystery",
            "style": "tense",
            "characters": [
                {
                    "name": "Pei An",
                    "role": "supporting",
                    "goals": ["hide the witness"],
                    "frozen": False,
                    "lifecycle_state": "active",
                    "last_proposed_chapter": 0,
                    "last_approved_chapter": 0,
                    "introduced_by": "",
                }
            ],
        },
    )
    assert create_resp.status_code == 200

    generated = client.post("/stories/s-lifecycle-flow/generate")
    assert generated.status_code == 200
    generated_character = generated.json()["updated_story"]["characters"][0]
    assert "lifecycle_state" in generated_character
    assert "last_proposed_chapter" in generated_character
    assert "last_approved_chapter" in generated_character
    assert "introduced_by" in generated_character

    frozen = client.post("/stories/s-lifecycle-flow/characters/Pei%20An/freeze")
    assert frozen.status_code == 200
    frozen_character = frozen.json()["characters"][0]
    assert frozen_character["frozen"] is True
    assert frozen_character["lifecycle_state"] == "frozen"

    rolled_back = client.post("/stories/s-lifecycle-flow/rollback")
    assert rolled_back.status_code == 200
    rolled_character = rolled_back.json()["characters"][0]
    assert "lifecycle_state" in rolled_character
    assert "last_proposed_chapter" in rolled_character
    assert "last_approved_chapter" in rolled_character
    assert "introduced_by" in rolled_character


def test_rollback_restores_previous_story_state():
    client.post(
        "/stories",
        json={
            "story_id": "s-rollback-state",
            "outline": "A magistrate hunts the source of forged decrees.",
            "genre": "mystery",
            "style": "tense",
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "investigator",
                    "goals": ["find the forger"],
                    "frozen": False,
                    "relationships": {
                        "Su Wan": {
                            "target": "Su Wan",
                            "trust": 0.4,
                            "tension": 0.9,
                            "bond": "uneasy alliance",
                        }
                    },
                }
            ],
        },
    )

    client.post("/stories/s-rollback-state/generate")
    client.post("/stories/s-rollback-state/generate")

    rollback_resp = client.post("/stories/s-rollback-state/rollback")
    assert rollback_resp.status_code == 200

    story = rollback_resp.json()
    assert story["current_chapter"] == 1
    assert len(story["history"]) == 1
    assert story["history"][0]["chapter_number"] == 1
    relation = story["characters"][0]["relationships"]["Su Wan"]
    assert relation["trust"] == 0.4
    assert relation["tension"] == 0.9


def test_story_can_branch_from_a_previous_chapter():
    client.post(
        "/stories",
        json={
            "story_id": "s-branch-root",
            "outline": "Two rivals hunt a ledger buried under the imperial archives.",
            "genre": "fantasy",
            "style": "court intrigue",
            "characters": [
                {
                    "name": "Lin Yue",
                    "role": "investigator",
                    "goals": ["find the ledger"],
                    "frozen": False,
                }
            ],
        },
    )
    client.post("/stories/s-branch-root/generate")
    client.post("/stories/s-branch-root/generate")

    branch_resp = client.post(
        "/stories/s-branch-root/branch",
        json={"new_story_id": "s-branch-alt", "from_chapter": 1},
    )
    assert branch_resp.status_code == 200

    branch_story = branch_resp.json()
    assert branch_story["story_id"] == "s-branch-alt"
    assert branch_story["current_chapter"] == 1
    assert len(branch_story["history"]) == 1
    assert branch_story["history"][0]["chapter_number"] == 1
    assert branch_story["parent_story_id"] == "s-branch-root"
    assert branch_story["branched_from_chapter"] == 1

    original_story = client.get("/stories/s-branch-root")
    assert original_story.status_code == 200
    assert original_story.json()["current_chapter"] == 2

    list_resp = client.get("/stories")
    assert list_resp.status_code == 200
    assert {story["story_id"] for story in list_resp.json()} >= {"s-branch-root", "s-branch-alt"}


def test_generation_job_completes_and_updates_story():
    client.post(
        "/stories",
        json={
            "story_id": "s-generation-job",
            "outline": "A cautious player tests a strange login token.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )

    start_resp = client.post("/stories/s-generation-job/generation-jobs")
    assert start_resp.status_code == 200
    job = start_resp.json()
    assert job["story_id"] == "s-generation-job"
    assert job["status"] in {"queued", "running", "completed"}
    assert job["job_id"]

    finished = job
    for _ in range(50):
        poll_resp = client.get(f"/stories/s-generation-job/generation-jobs/{job['job_id']}")
        assert poll_resp.status_code == 200
        finished = poll_resp.json()
        if finished["status"] in {"completed", "failed"}:
            break
        time.sleep(0.02)

    assert finished["status"] == "completed"
    assert finished["chapter_number"] == 1
    assert finished["error"] == ""

    story_resp = client.get("/stories/s-generation-job")
    assert story_resp.status_code == 200
    story = story_resp.json()
    assert story["current_chapter"] == 1
    assert len(story["history"]) == 1


def test_generation_job_reports_missing_story():
    start_resp = client.post("/stories/s-missing/generation-jobs")

    assert start_resp.status_code == 404
    assert start_resp.json()["detail"] == "story_not_found"


def test_generation_job_reconciles_when_story_already_advanced():
    import apps.api.routes.stories as story_routes

    client.post(
        "/stories",
        json={
            "story_id": "s-generation-reconcile",
            "outline": "A cautious player tests a strange login token.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post("/stories/s-generation-reconcile/generate")

    with story_routes._generation_jobs_lock:
        story_routes._generation_jobs["gj-stale"] = {
            "job_id": "gj-stale",
            "story_id": "s-generation-reconcile",
            "status": "running",
            "progress": "章节扩写中...",
            "chapter_number": None,
            "error": "",
            "starting_chapter": 0,
            "created_at": story_routes._now_iso(),
            "updated_at": story_routes._now_iso(),
        }
        story_routes._active_generation_jobs["s-generation-reconcile"] = "gj-stale"

    response = client.get("/stories/s-generation-reconcile/generation-jobs/gj-stale")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["chapter_number"] == 1
    with story_routes._generation_jobs_lock:
        assert "s-generation-reconcile" not in story_routes._active_generation_jobs


def test_generation_job_exposes_pipeline_progress(monkeypatch):
    from types import SimpleNamespace

    import apps.api.routes.stories as story_routes
    from packages.story_core.generation_progress import report_generation_progress

    client.post(
        "/stories",
        json={
            "story_id": "s-progress-job",
            "outline": "A cautious player tests a strange login token.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    progress_seen = threading.Event()
    finish_generation = threading.Event()

    def fake_generate_story_chapter(story_id: str):
        report_generation_progress("剧情计划生成中...")
        progress_seen.set()
        assert finish_generation.wait(2)
        report_generation_progress("正文生成中...")
        return SimpleNamespace(chapter_number=1)

    monkeypatch.setattr(story_routes, "_generate_story_chapter", fake_generate_story_chapter)

    start_resp = client.post("/stories/s-progress-job/generation-jobs")
    assert start_resp.status_code == 200
    job = start_resp.json()
    assert isinstance(job.get("steps"), list)

    assert progress_seen.wait(2)
    progress_resp = client.get(f"/stories/s-progress-job/generation-jobs/{job['job_id']}")
    assert progress_resp.status_code == 200
    assert progress_resp.json()["status"] == "running"
    assert progress_resp.json()["progress"] == "剧情计划生成中..."

    finish_generation.set()
    finished = progress_resp.json()
    for _ in range(50):
        poll_resp = client.get(f"/stories/s-progress-job/generation-jobs/{job['job_id']}")
        assert poll_resp.status_code == 200
        finished = poll_resp.json()
        if finished["status"] == "completed":
            break
        time.sleep(0.02)

    assert finished["status"] == "completed"
    assert finished["chapter_number"] == 1
    assert len(finished.get("steps", [])) >= 2


def test_project_agent_context_pack_exposes_current_workbench_state():
    client.post(
        "/stories",
        json={
            "story_id": "s-agent-context",
            "outline": "网游开服，主角靠千倍爆率低调发育。",
            "genre": "网游",
            "style": "升级流",
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "goals": ["低调验证千倍爆率"],
                    "game_id": "夜烬",
                }
            ],
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-agent-context",
            "title": "苟在网游里成神",
            "seed_outline": "交易行变现会留下弱线索。",
            "world_summary": "《天启之门》开服初期。",
            "current_focus": "第2章继续验证收益。",
            "author_constraints": ["网游币制默认使用 1金币=100银币=10000铜币。"],
            "world_blueprint": {
                "living_world": {
                    "economy": {"resource_flow": ["低级材料由散人和商人消化"]},
                    "information_visibility_rules": ["交易行只显示价格、数量、时间戳。"],
                }
            },
            "active_story_id": "s-agent-context",
        },
    )
    client.post("/stories/s-agent-context/generate")

    response = client.get("/projects/p-agent-context/agent-context?recent_chapters=1")

    assert response.status_code == 200
    context = response.json()
    assert context["schema_version"] == "agent-context/v1"
    assert context["project"]["project_id"] == "p-agent-context"
    assert context["project"]["active_story_id"] == "s-agent-context"
    assert context["active_story"]["story_id"] == "s-agent-context"
    assert context["active_story"]["current_chapter"] == 1
    assert context["active_story"]["characters"][0]["game_id"] == "夜烬"
    assert context["recent_chapters"][0]["chapter_number"] == 1
    assert context["recent_chapters"][0]["body_chars"] > 0
    assert "body" not in context["recent_chapters"][0]
    assert any(gap["area"] == "npc_system" for gap in context["world"]["gaps"])
    assert "review_chapter" in context["controls"]["suggested_tools"]


def test_project_agent_context_pack_can_include_recent_chapter_body():
    client.post(
        "/stories",
        json={
            "story_id": "s-agent-context-body",
            "outline": "A player tests a strange market clue.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-agent-context-body",
            "title": "Body Context",
            "active_story_id": "s-agent-context-body",
        },
    )
    client.post("/stories/s-agent-context-body/generate")

    response = client.get("/projects/p-agent-context-body/agent-context?recent_chapters=1&include_body=true")

    assert response.status_code == 200
    chapter = response.json()["recent_chapters"][0]
    assert chapter["body_chars"] == len(chapter["body"])
    assert chapter["body"]


def test_project_agent_review_returns_structured_chapter_review():
    client.post(
        "/stories",
        json={
            "story_id": "s-agent-review",
            "outline": "网游开服，主角靠千倍爆率低调发育。",
            "genre": "网游",
            "style": "升级流",
            "characters": [
                {
                    "name": "苏叶",
                    "role": "protagonist",
                    "goals": ["低调验证千倍爆率"],
                    "game_id": "夜烬",
                }
            ],
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-agent-review",
            "title": "苟在网游里成神",
            "world_summary": "《天启之门》开服初期。",
            "author_constraints": ["网游币制默认使用 1金币=100银币=10000铜币。"],
            "active_story_id": "s-agent-review",
        },
    )
    client.post("/stories/s-agent-review/generate")

    response = client.get("/projects/p-agent-review/agent-review?chapter_number=1")

    assert response.status_code == 200
    review = response.json()
    assert review["schema_version"] == "agent-review/v1"
    assert review["project"]["project_id"] == "p-agent-review"
    assert review["story"]["story_id"] == "s-agent-review"
    assert review["chapter"]["chapter_number"] == 1
    assert review["chapter"]["body_chars"] > 0
    assert "body" not in review["chapter"]
    assert "writing_review" in review["review"]
    assert "scores" in review["review"]["writing_review"]
    assert "prose_quality_review" in review["review"]["writing_review"]
    assert "adversarial_cut_review" in review["review"]["writing_review"]
    assert review["controls"]["governance_gate"]["reviewer"] == "chapter_governance_gate/v1"
    assert review["recommendation"]["action"] in {"continue", "revise"}
    assert "revise_chapter" in review["controls"]["suggested_tools"]


def test_quality_context_exposes_revision_safety_reports():
    quality = {
        "ok": False,
        "issues": ["writing_review"],
        "writing_review": {"pass": False, "scores": {}, "issues": [], "revision_plan": []},
        "revision_safety": {
            "reviewer": "revision_safety/v1",
            "accepted": False,
            "selected": "original",
            "reason": "candidate_worse_than_original",
        },
    }

    context = _quality_context(quality)

    assert context["revision_safety"]["selected"] == "original"


def test_project_agent_review_can_include_chapter_body():
    client.post(
        "/stories",
        json={
            "story_id": "s-agent-review-body",
            "outline": "A player tests a strange market clue.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-agent-review-body",
            "title": "Review Body",
            "active_story_id": "s-agent-review-body",
        },
    )
    client.post("/stories/s-agent-review-body/generate")

    response = client.get("/projects/p-agent-review-body/agent-review?include_body=true")

    assert response.status_code == 200
    chapter = response.json()["chapter"]
    assert chapter["body"]
    assert chapter["body_chars"] == len(chapter["body"])


def test_project_agent_review_reports_missing_chapter():
    client.post(
        "/stories",
        json={
            "story_id": "s-agent-review-missing",
            "outline": "A player tests a strange market clue.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-agent-review-missing",
            "title": "Review Missing",
            "active_story_id": "s-agent-review-missing",
        },
    )

    response = client.get("/projects/p-agent-review-missing/agent-review?chapter_number=9")

    assert response.status_code == 404
    assert response.json()["detail"] == "chapter_not_found"


def test_project_agent_revise_updates_latest_chapter(monkeypatch):
    from packages.story_core import orchestrator as orchestrator_module
    from packages.story_core.simplified_review import build_simplified_review

    safety_inputs = {}
    real_choose_best_revision = orchestrator_module.choose_best_revision

    def capture_safety(**kwargs):
        safety_inputs.update(kwargs)
        return real_choose_best_revision(**kwargs)

    monkeypatch.setattr(orchestrator_module, "choose_best_revision", capture_safety)
    client.post(
        "/stories",
        json={
            "story_id": "s-agent-revise",
            "outline": "A player tests a strange market clue.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-agent-revise",
            "title": "Revise Latest",
            "active_story_id": "s-agent-revise",
        },
    )
    client.post("/stories/s-agent-revise/generate")
    original = client.get("/stories/s-agent-revise").json()["history"][0]["body"]
    revised_body = "REVISED CHAPTER BODY. " + ("market detail and character pressure. " * 130)

    def fake_revision_chat(self, story, prompt: str, *, max_tokens: int, json_mode: bool, agent: str = "director"):
        if agent == "writer":
            assert "strengthen market detail" in prompt
            assert original in prompt
            return revised_body, ""
        assert agent == "memory"
        return "", "memory unavailable"

    def soft_candidate_review(*_args, **_kwargs):
        issues = [f"候选软问题{i}" for i in range(9)]
        return {
            "pass": False,
            "scores": {"genre_rules": 6},
            "issues": issues,
            "revision_plan": ["局部润色，不改变剧情。"] * len(issues),
        }

    monkeypatch.setattr("packages.story_core.orchestrator.StoryOrchestrator._chat", fake_revision_chat)
    monkeypatch.setattr(orchestrator_module, "_review_chapter_body", soft_candidate_review)

    response = client.post(
        "/projects/p-agent-revise/agent-revise",
        json={
            "chapter_number": 1,
            "instructions": ["strengthen market detail"],
            "include_body": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == "agent-revision/v1"
    original_gate = build_simplified_review(safety_inputs["original_quality"])
    candidate_gate = build_simplified_review(safety_inputs["candidate_quality"])
    assert safety_inputs["original_quality"]["has_hard_errors"] is True, original_gate
    assert safety_inputs["candidate_quality"]["has_hard_errors"] is False, json.dumps(
        candidate_gate,
        ensure_ascii=False,
        sort_keys=True,
    )
    safety = payload["review"]["quality"]["revision_safety"]
    assert safety["accepted"] is True, json.dumps(safety, ensure_ascii=False, sort_keys=True)
    assert safety["selected"] == "candidate"
    assert safety["reason"] == "structural_length_error_resolved"
    assert safety["candidate_score"] >= safety["original_score"] - 100
    assert safety["original_chars"] == 46
    assert safety["candidate_chars"] == 4309
    assert safety["candidate_issue_count"] == 9
    assert safety["candidate_issue_count"] <= safety["original_issue_count"] + 3
    assert payload["revision"]["changed"] is True
    assert payload["revision"]["previous_body_chars"] == len(original)
    assert payload["chapter"]["body"] == revised_body
    assert payload["chapter"]["body_chars"] == len(revised_body)
    assert payload["review"]["writing_review"]["scores"]

    persisted = client.get("/stories/s-agent-revise").json()
    assert persisted["history"][0]["body"] == revised_body


def test_project_agent_revise_rejects_non_latest_chapter():
    client.post(
        "/stories",
        json={
            "story_id": "s-agent-revise-old",
            "outline": "A player tests a strange market clue.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-agent-revise-old",
            "title": "Revise Old",
            "active_story_id": "s-agent-revise-old",
        },
    )
    client.post("/stories/s-agent-revise-old/generate")
    client.post("/stories/s-agent-revise-old/generate")

    response = client.post(
        "/projects/p-agent-revise-old/agent-revise",
        json={"chapter_number": 1, "instructions": ["do not rewrite downstream chapters"]},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "chapter_not_latest"


def test_project_automation_job_generates_a_chapter_and_exposes_status():
    client.post(
        "/stories",
        json={
            "story_id": "s-automation-status",
            "outline": "A player enters a game village and tests a market clue.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-automation-status",
            "title": "Automation Status",
            "active_story_id": "s-automation-status",
        },
    )

    response = client.post(
        "/projects/p-automation-status/automation-jobs",
        json={"max_revisions": 0, "review_provider": "local"},
    )

    assert response.status_code == 200
    job = response.json()
    assert job["status"] in {"queued", "running"}
    assert job["phase"] in {"queued", "environment", "generating"}

    finished = job
    for _ in range(80):
        poll = client.get(f"/projects/p-automation-status/automation-jobs/{job['job_id']}")
        assert poll.status_code == 200
        finished = poll.json()
        if finished["status"] in {"completed", "paused", "failed"}:
            break
        time.sleep(0.02)

    assert finished["status"] in {"completed", "paused"}
    assert finished["project_id"] == "p-automation-status"
    assert finished["story_id"] == "s-automation-status"
    assert finished["chapter_number"] == 1
    assert finished["revision_attempts"] == 0
    assert finished["final_action"] in {"approve", "revise", "pause"}
    assert finished["progress"]

    story = client.get("/stories/s-automation-status").json()
    assert story["current_chapter"] == 1
    assert story["history"][0]["body"]


def test_project_automation_job_revises_until_review_approves(monkeypatch):
    import apps.api.routes.stories as story_routes

    client.post(
        "/stories",
        json={
            "story_id": "s-automation-revise",
            "outline": "A player enters a game village and tests a market clue.",
            "genre": "game fantasy",
            "style": "webnovel",
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": "p-automation-revise",
            "title": "Automation Revise",
            "active_story_id": "s-automation-revise",
        },
    )

    review_actions = ["revise", "approve"]

    def fake_review_result(project, record, bundle, *, provider: str, include_body: bool):
        action = review_actions.pop(0)
        return {
            "schema_version": "automation-review-result/v1",
            "action": action,
            "summary": f"{action} summary",
            "must_fix": ["expand market scene"] if action == "revise" else [],
            "revision_instructions": ["add one grounded NPC exchange"] if action == "revise" else [],
            "risk_flags": [],
        }

    monkeypatch.setattr(story_routes, "_automation_review_result", fake_review_result, raising=False)

    response = client.post(
        "/projects/p-automation-revise/automation-jobs",
        json={"max_revisions": 2, "review_provider": "local"},
    )

    assert response.status_code == 200
    job = response.json()
    finished = job
    for _ in range(120):
        poll = client.get(f"/projects/p-automation-revise/automation-jobs/{job['job_id']}")
        assert poll.status_code == 200
        finished = poll.json()
        if finished["status"] in {"completed", "paused", "failed"}:
            break
        time.sleep(0.02)

    assert finished["status"] == "completed"
    assert finished["phase"] == "completed"
    assert finished["revision_attempts"] == 1
    assert finished["final_action"] == "approve"
    assert finished["review_provider"] == "local"
    assert finished["progress"] == "automation completed"


def test_project_automation_job_normalizes_openclaw_provider_to_local():
    from apps.api.routes.stories import ProjectAutomationJobRequest

    request = ProjectAutomationJobRequest(max_revisions=1, review_provider="openclaw")

    assert request.review_provider == "local"


def test_branch_can_be_renamed_and_deleted():
    client.post(
        "/stories",
        json={
            "story_id": "s-branch-admin-root",
            "outline": "A censor builds three versions of the same testimony.",
            "genre": "fantasy",
            "style": "political",
        },
    )
    client.post("/stories/s-branch-admin-root/generate")
    client.post(
        "/stories/s-branch-admin-root/branch",
        json={"new_story_id": "s-branch-admin-alt", "from_chapter": 1},
    )

    rename_resp = client.post(
        "/stories/s-branch-admin-alt/rename",
        json={"new_story_id": "s-branch-admin-shadow"},
    )
    assert rename_resp.status_code == 200
    assert rename_resp.json()["story_id"] == "s-branch-admin-shadow"
    assert rename_resp.json()["parent_story_id"] == "s-branch-admin-root"

    list_resp = client.get("/stories")
    assert list_resp.status_code == 200
    assert {story["story_id"] for story in list_resp.json()} >= {"s-branch-admin-root", "s-branch-admin-shadow"}
    assert "s-branch-admin-alt" not in {story["story_id"] for story in list_resp.json()}

    delete_resp = client.delete("/stories/s-branch-admin-shadow")
    assert delete_resp.status_code == 200
    assert delete_resp.json()["deleted"] is True

    fetch_deleted = client.get("/stories/s-branch-admin-shadow")
    assert fetch_deleted.status_code == 404


def test_rename_preserves_chapter_history():
    client.post(
        "/stories",
        json={
            "story_id": "s-rename-history-root",
            "outline": "An archivist rewrites the same case file.",
            "genre": "fantasy",
            "style": "mystery",
        },
    )
    client.post("/stories/s-rename-history-root/generate")
    client.post("/stories/s-rename-history-root/generate")
    before = client.get("/stories/s-rename-history-root").json()
    assert len(before["history"]) == 2

    rename_resp = client.post(
        "/stories/s-rename-history-root/rename",
        json={"new_story_id": "s-rename-history-new"},
    )
    assert rename_resp.status_code == 200

    after = client.get("/stories/s-rename-history-new").json()
    assert [entry["chapter_number"] for entry in after["history"]] == [1, 2]
    assert after["current_chapter"] == before["current_chapter"]


def test_file_project_character_routes_read_update_and_complete(monkeypatch):
    class FakeStore:
        def __init__(self):
            self.card = {"name": "林月", "personality_portrait": {"growth": {"invariants": ["守住药铺"]}}}

        def state(self):
            return {"characters": [self.card]}

        def update_character(self, name, patch):
            self.card = {**self.card, **patch}
            return self.card

        def complete_character_portrait(self, name):
            self.card["personality_portrait"]["behavior"] = {"pressure_mode": "先护住药铺，再谈别的。"}
            return self.card

    store = FakeStore()
    monkeypatch.setattr(file_projects, "_store_for", lambda project_id: store)

    read = client.get("/file-projects/file:p-test/characters")
    update = client.put(
        "/file-projects/file:p-test/characters/林月",
        json={"personality_portrait": {"temperament": {"core_traits": ["嘴硬"]}}},
    )
    complete = client.post("/file-projects/file:p-test/characters/林月/complete-portrait")

    assert read.status_code == 200
    assert update.status_code == 200
    assert update.json()["personality_portrait"]["temperament"]["core_traits"] == ["嘴硬"]
    assert complete.status_code == 200
    assert complete.json()["personality_portrait"]["behavior"]["pressure_mode"]


def test_update_file_project_route_preserves_game_title_in_patch(monkeypatch, tmp_path):
    class FakeStore:
        def __init__(self):
            self.root = tmp_path / "p-test"
            self.saved_project = {
                "project_id": "p-test",
                "title": "作品标题",
                "active_story_id": "s-test",
            }
            self.received_patch = None

        def update_project(self, patch):
            self.received_patch = patch
            self.saved_project.update(patch)
            return self.saved_project

        def project(self):
            return self.saved_project

        def state(self):
            return {"story_id": "s-test", "current_chapter": 0}

        def summary(self):
            return {"current_chapter": 0, "title": "作品标题"}

        def publishing_assets(self):
            return {"schema_version": "publishing-assets/v1", "synopsis": None, "cover": None}

    store = FakeStore()
    monkeypatch.setattr(file_projects, "_store_for", lambda project_id: store)

    response = client.put(
        "/file-projects/file:p-test",
        json={"game_title": "神域"},
    )

    assert response.status_code == 200
    assert store.received_patch == {"game_title": "神域"}


def test_file_project_character_routes_return_404_for_unknown_character(monkeypatch):
    class FakeStore:
        def update_character(self, name, patch):
            raise KeyError(f"character_not_found:{name}")

        def complete_character_portrait(self, name):
            raise KeyError(f"character_not_found:{name}")

    monkeypatch.setattr(file_projects, "_store_for", lambda project_id: FakeStore())

    response = client.put("/file-projects/file:p-test/characters/不存在", json={})

    assert response.status_code == 404
