import urllib.error
import json
import threading
import time

import pytest

from fastapi.testclient import TestClient

from apps.api.main import app
from apps.api.routes import file_projects
from apps.api.routes.stories import _quality_context


client = TestClient(app)


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
    if json_mode:
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
    client.put(
        "/runtime-settings",
        json={
            "global": {
                "api_key": "",
                "base_url": "https://api.openai.com/v1",
                "provider": "openai",
            },
            "agents": {
                "character": {"api_key": "", "base_url": ""},
                "director": {"api_key": "", "base_url": ""},
                "writer": {"api_key": "", "base_url": ""},
                "memory": {"api_key": "", "base_url": ""},
            },
        },
    )
    monkeypatch.setattr("packages.story_core.orchestrator.StoryOrchestrator._chat", _mock_story_chat)
    yield
    client.put("/runtime-settings", json=original)


def test_runtime_settings_can_be_saved_globally():
    response = client.get("/runtime-settings")
    assert response.status_code == 200
    assert response.json()["global"]["base_url"]
    assert "api_key" in response.json()["global"]

    update_resp = client.put(
        "/runtime-settings",
        json={
            "global": {
                "api_key": "sk-test-123",
                "base_url": "https://api.example.com/v1",
            },
        },
    )
    assert update_resp.status_code == 200
    assert update_resp.json()["global"]["api_key"] == "sk-test-123"
    assert update_resp.json()["global"]["base_url"] == "https://api.example.com/v1"

    loaded = client.get("/runtime-settings")
    assert loaded.status_code == 200
    assert loaded.json()["global"]["api_key"] == "sk-test-123"
    assert loaded.json()["global"]["base_url"] == "https://api.example.com/v1"


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


def test_runtime_settings_can_store_agent_overrides():
    update_resp = client.put(
        "/runtime-settings",
        json={
            "global": {
                "api_key": "sk-global",
                "base_url": "https://api.global.example/v1",
            },
            "agents": {
                "character": {
                    "api_key": "sk-character",
                    "base_url": "https://api.character.example/v1",
                },
                "director": {
                    "api_key": "sk-director",
                    "base_url": "https://api.director.example/v1",
                },
                "writer": {
                    "api_key": "sk-writer",
                    "base_url": "https://api.writer.example/v1",
                },
                "memory": {
                    "api_key": "sk-memory",
                    "base_url": "https://api.memory.example/v1",
                },
            },
        },
    )
    assert update_resp.status_code == 200

    loaded = client.get("/runtime-settings")
    assert loaded.status_code == 200
    payload = loaded.json()
    assert payload["global"]["api_key"] == "sk-global"
    assert payload["global"]["base_url"] == "https://api.global.example/v1"
    assert payload["agents"]["character"]["api_key"] == "sk-character"
    assert payload["agents"]["director"]["base_url"] == "https://api.director.example/v1"


def test_project_writing_packet_and_manual_draft_roundtrip():
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
    generated = client.post(f"/stories/{story_id}/generate")
    assert generated.status_code == 200

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

    manual_body = "\n\n".join(
        [
            "催租单压在键盘边，苏叶把旧头盔从抽屉里拖出来。他以前做过游戏经济模型外包，最熟的是材料产出、交易流水和异常账号曲线。现在余额只剩几十块，他需要的不是奇迹，而是一条能验证的路。",
            "《天启之门》的登录界面亮起。苏叶输入游戏ID：夜烬。职业列表展开后，他没有选战士，也没有选游侠，而是点下元素法师学徒。面板很短：【角色：夜烬】【等级：Lv.1】【职业：元素法师学徒】【经验：0/100】【生命：100/100】【法力：80/80】【属性：力量5，敏捷8，体质9，智力9】【装备：新手木杖，粗布衣】【货币：0铜币】。",
            "灰烬村外的灰鼠坡有几只灰鼠在草根下乱窜。夜烬先用微光弹试距离，第一发打偏，第二发命中，法力掉了一截，肩膀也被灰鼠抓掉三点血。第三发微光弹落下后，提示跳出：【击杀灰鼠。经验+15。】【获得：灰鼠毒腺×12。】【获得：灰鼠皮×3。】他没有笑，只把背包关上，转身回村。",
            "药剂铺里，洛婶把灰鼠毒腺拿到鼻下闻了闻，说单卖一份两铜，清道夫委托要五份毒腺和三张灰鼠皮，奖励二十铜。她补了一句：单卖是材料价，委托价里算村务补贴。柜台旁的木牌写着一金币兑一百银币，一银币兑一百铜币。夜烬接下委托，却没有立刻提交。他看着背包里的材料，知道这东西能用，但不能急着暴露。",
        ]
    )
    draft_response = client.post(
        f"/projects/{project_id}/manual-draft",
        json={"chapter_number": 1, "body": manual_body, "instructions": ["Codex手写样稿"], "include_body": True},
    )
    assert draft_response.status_code == 200
    draft = draft_response.json()
    assert draft["revision"]["source"] == "manual_draft"
    assert "货币：0铜币" not in draft["chapter"]["body"]
    assert "钱袋：空" in draft["chapter"]["body"]
    assert draft["chapter"]["body_chars"] >= 1
    assert "writing_review" in draft["review"]
    refreshed = client.get(f"/stories/{story_id}").json()
    assert "货币：0铜币" not in refreshed["history"][0]["body"]
    assert "钱袋：空" in refreshed["history"][0]["body"]


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


def test_existing_first_chapter_packet_uses_story_state_before_that_chapter():
    story_id = "s-first-chapter-snapshot"
    project_id = "p-first-chapter-snapshot"
    assert client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "林照看守祖祠断香炉。",
            "genre": "xianxia",
            "style": "白描",
            "characters": [{"name": "林照", "role": "protagonist"}],
        },
    ).status_code == 200
    assert client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "断香炉快照测试",
            "active_story_id": story_id,
            "world_blueprint": {"genre_plugin_ids": ["xianxia"]},
        },
    ).status_code == 200
    assert client.post(
        f"/projects/{project_id}/manual-draft",
        json={"chapter_number": 1, "body": "林照接下守炉差事。"},
    ).status_code == 200
    assert client.post(
        f"/projects/{project_id}/manual-draft",
        json={"chapter_number": 2, "body": "第二章未来污染标记。"},
    ).status_code == 200

    packet_response = client.get(f"/projects/{project_id}/writing-packet?chapter_number=1")

    assert packet_response.status_code == 200
    packet = packet_response.json()
    text = json.dumps(packet, ensure_ascii=False)
    assert packet["story"]["current_chapter"] == 0
    assert packet["continuity"]["previous_summary"] == ""
    assert packet["governance"]["runtime_context"]["previous_summary"] == ""
    assert "第二章未来污染标记" not in text


def test_project_delete_removes_owned_story_and_project():
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

    delete_response = client.delete(f"/projects/{project_id}")

    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "deleted": True,
        "project_id": project_id,
        "deleted_story_ids": [story_id],
    }
    assert client.get(f"/projects/{project_id}").status_code == 404
    assert client.get(f"/stories/{story_id}").status_code == 404


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
    writer_prompt = next(prompt for prompt in preview["prompts"] if prompt["key"] == "writer_body")
    assert all(
        heading in writer_prompt["content"]
        for heading in ("## 输出要求", "## 本章方向", "## 本章事实", "## 出场人物", "## 正文写法")
    )
    assert "五块装配" in writer_prompt["description"]


def test_project_manual_draft_can_append_next_chapter():
    story_id = "s-manual-next-chapter-api"
    project_id = "p-manual-next-chapter-api"
    client.post(
        "/stories",
        json={
            "story_id": story_id,
            "outline": "A cautious player validates a game economy anomaly.",
            "genre": "web-game",
            "style": "progression",
            "characters": [{"name": "Su Ye", "role": "protagonist", "game_id": "Night Ember"}],
        },
    )
    client.post(
        "/projects",
        json={
            "project_id": project_id,
            "title": "Manual Next Chapter",
            "active_story_id": story_id,
            "current_focus": "Chapter 2 should continue from the first task.",
        },
    )
    generated = client.post(f"/stories/{story_id}/generate")
    assert generated.status_code == 200

    packet_response = client.get(f"/projects/{project_id}/writing-packet?chapter_number=2")
    assert packet_response.status_code == 200
    assert packet_response.json()["chapter_number"] == 2

    chapter_two_body = "Chapter two starts from the task reward.\n\nThe player checks cost before fighting again."
    draft_response = client.post(
        f"/projects/{project_id}/manual-draft",
        json={"chapter_number": 2, "body": chapter_two_body, "instructions": ["Codex manual chapter 2"], "include_body": True},
    )

    assert draft_response.status_code == 200
    payload = draft_response.json()
    assert payload["revision"]["source"] == "manual_draft"
    assert payload["chapter"]["chapter_number"] == 2
    assert payload["chapter"]["body"] == chapter_two_body
    assert payload["chapter"]["quality_report"]["ok"] is True
    assert payload["chapter"]["quality_report"]["issues"] == []
    refreshed = client.get(f"/stories/{story_id}").json()
    assert refreshed["current_chapter"] == 2
    assert [chapter["chapter_number"] for chapter in refreshed["history"]][-2:] == [1, 2]
    assert refreshed["history"][-1]["body"] == chapter_two_body


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


def test_runtime_settings_connection_can_be_tested_for_one_agent(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["method"] = request.get_method()
        captured["url"] = request.full_url
        captured["authorization"] = request.headers["Authorization"]
        captured["content_type"] = request.headers.get("Content-type")
        captured["body"] = request.data

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr("apps.api.routes.stories.urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "character",
            "runtime_settings": {
                "global": {
                    "api_key": "sk-global",
                    "base_url": "https://api.global.example/v1",
                },
                "agents": {
                    "character": {
                        "api_key": "sk-character",
                        "base_url": "https://api.character.example/v1",
                    }
                },
            },
            "model_name": "gpt-4.1-mini",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert response.json()["agent_name"] == "character"
    assert captured["method"] == "POST"
    assert captured["url"] == "https://api.character.example/v1/chat/completions"
    assert captured["authorization"] == "Bearer sk-character"
    assert captured["content_type"] == "application/json"
    assert b'"model": "gpt-4.1-mini"' in captured["body"]


def test_runtime_settings_connection_uses_strategy_model_when_model_name_missing(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url
        captured["body"] = request.data

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr("apps.api.routes.stories.urllib.request.urlopen", fake_urlopen)
    client.put(
        "/runtime-strategy",
        json={
            "mode": "LLM-assisted",
            "global_model": "global-model",
            "character_model": "character-model",
            "director_model": "director-model",
            "writer_model": "writer-model",
            "memory_model": "memory-model",
            "temperature": 0.7,
            "new_character_policy": "Director review",
        },
    )

    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "writer",
            "runtime_settings": {
                "global": {
                    "api_key": "sk-global",
                    "base_url": "https://api.global.example/v1",
                },
            },
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["url"] == "https://api.global.example/v1/chat/completions"
    assert b'"model": "writer-model"' in captured["body"]


def test_runtime_settings_connection_treats_null_global_as_empty_config():
    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "character",
            "runtime_settings": {
                "global": None,
                "agents": {},
            },
            "model_name": "gpt-4.1-mini",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is False
    assert response.json()["agent_name"] == "character"


def test_runtime_settings_connection_falls_back_to_models_when_chat_endpoint_missing(monkeypatch):
    captured_urls = []

    def fake_urlopen(request, timeout=30):
        captured_urls.append(request.full_url)
        if request.full_url.endswith("/chat/completions"):
            raise urllib.error.HTTPError(
                request.full_url,
                404,
                "Not Found",
                hdrs=None,
                fp=None,
            )

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr("apps.api.routes.stories.urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "global",
            "runtime_settings": {
                "global": {
                    "api_key": "sk-global",
                    "base_url": "https://api.global.example/v1",
                },
            },
            "model_name": "gpt-4.1",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured_urls == [
        "https://api.global.example/v1/chat/completions",
        "https://api.global.example/v1/models",
    ]


def test_runtime_settings_connection_uses_custom_global_base_url(monkeypatch):
    captured = {}

    def fake_urlopen(request, timeout=30):
        captured["url"] = request.full_url

        class _Response:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def read(self):
                return b"{}"

        return _Response()

    monkeypatch.setattr("apps.api.routes.stories.urllib.request.urlopen", fake_urlopen)

    response = client.post(
        "/runtime-settings/test",
        json={
            "agent_name": "global",
            "runtime_settings": {
                "global": {
                    "api_key": "sk-global",
                    "base_url": "https://api.global.example/v1",
                },
            },
            "model_name": "gpt-4.1",
        },
    )

    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert captured["url"] == "https://api.global.example/v1/chat/completions"


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

    monkeypatch.setattr("packages.story_core.orchestrator.StoryOrchestrator._chat", fake_revision_chat)

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


def test_file_project_character_routes_return_404_for_unknown_character(monkeypatch):
    class FakeStore:
        def update_character(self, name, patch):
            raise KeyError(f"character_not_found:{name}")

        def complete_character_portrait(self, name):
            raise KeyError(f"character_not_found:{name}")

    monkeypatch.setattr(file_projects, "_store_for", lambda project_id: FakeStore())

    response = client.put("/file-projects/file:p-test/characters/不存在", json={})

    assert response.status_code == 404
