from __future__ import annotations

import json
from pathlib import Path

from packages.story_core.engine import ChapterBundle
from packages.story_core.file_project_store import FileProjectStore
from packages.story_core.models import StoryState


def _write_project(root: Path, *, genre_plugin_id: str, character: dict) -> None:
    for directory in (root / ".story-system" / "chapters", root / ".story-system" / "reviews", root / ".webnovel", root / "chapters"):
        directory.mkdir(parents=True, exist_ok=True)

    project = {
        "project_id": "p-dual-state-compat",
        "title": "双状态兼容测试",
        "active_story_id": "s-dual-state-compat",
        "world_blueprint": {"genre_plugin_ids": [genre_plugin_id]},
        "character_profiles": [character],
    }
    state = {
        "story_id": "s-dual-state-compat",
        "current_chapter": 0,
        "genre": "网游" if genre_plugin_id == "game_webnovel" else "玄幻",
        "style": "白描",
        "outline": "兼容测试",
        "characters": [character],
        "world_facts": [],
    }
    outline = {
        "overall": {"story": "兼容测试"},
        "arcs": [],
        "chapters": [
            {
                "chapter_number": 1,
                "title": "进入场景",
                "goal": "推进当前场景",
                "action": "进入副本领取任务" if genre_plugin_id == "game_webnovel" else "完成一次明确行动",
            }
        ],
    }
    for path, value in (
        (root / ".story-system" / "MASTER_SETTING.json", {"project": project}),
        (root / ".webnovel" / "project.json", project),
        (root / ".webnovel" / "state.json", state),
        (root / ".webnovel" / "outline.json", outline),
    ):
        path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def _persist_public_chapter(store: FileProjectStore, *, chapter_number: int, event: dict) -> None:
    body = "正文推进。" * 900
    story = StoryState.model_validate(store.state())
    bundle = ChapterBundle(
        chapter_number=chapter_number,
        chapter_title="进入场景" if chapter_number == 1 else "现实结算",
        body=body,
        next_outline="继续推进。",
        updated_story=story,
        chapter_summary={"state_changes": [event]},
        quality_report={"ok": True},
    )
    store.persist_bundle(bundle, operation="manual")


def test_old_game_project_is_read_compatibly_and_migrates_lazily_after_sync(tmp_path: Path):
    old_card = {
        "name": "苏叶",
        "role": "主角",
        "game_id": "夜烬",
        "identity_profile": {
            "age": 24,
            "current_identity": "待业青年",
            "occupation": "临时工",
            "origin": "小城出身",
        },
        "current_life_profile": {
            "residence": "城中村出租屋",
            "livelihood": "靠零工维持生活",
        },
        "game_panel": {
            "game_id": "夜烬",
            "level": 1,
            "currency": "0铜币",
            "inventory": {"灰狼毒腺": 2},
        },
    }
    _write_project(tmp_path, genre_plugin_id="game_webnovel", character=old_card)
    store = FileProjectStore(tmp_path)

    packet = store.writing_packet(1)
    packet_card = packet["character_cards"][0]
    assert packet["scene_kind"] == "game"
    assert packet_card["state_context"]["game_state"]["current"]["currency"] == "0铜币"
    assert "real_state" not in packet_card["state_context"]

    before_sync = json.loads((tmp_path / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert "game_state" not in before_sync["character_profiles"][0]

    _persist_public_chapter(
        store,
        chapter_number=1,
        event={
            "line": "game",
            "character": "苏叶",
            "fact": "游戏内获得奖励",
            "game_state": {"current": {"level": 2, "currency": "30铜币"}},
        },
    )

    persisted_state = json.loads((tmp_path / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    persisted_card = persisted_state["characters"][0]
    assert persisted_card["game_state"]["current"]["currency"] == "30铜币"
    assert persisted_card["real_state"]["current"]["identity_profile"]["occupation"] == "临时工"
    assert persisted_card["real_state"]["current"]["current_life_profile"]["residence"] == "城中村出租屋"

    persisted_project = json.loads((tmp_path / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    project_card = persisted_project["character_profiles"][0]
    assert project_card["game_state"]["current"]["currency"] == "30铜币"
    assert project_card["real_state"]["current"]["identity_profile"]["current_identity"] == "待业青年"

    _persist_public_chapter(
        store,
        chapter_number=2,
        event={
            "line": "reality",
            "character": "苏叶",
            "fact": "现实收入到账后支付房租",
            "real_state": {"current": {"balance": "25.60元", "payment": "2.00元房租"}},
        },
    )
    after_reality_event = json.loads((tmp_path / ".webnovel" / "state.json").read_text(encoding="utf-8"))["characters"][0]
    assert after_reality_event["real_state"]["current"]["balance"] == "25.60元"
    assert after_reality_event["game_state"]["current"] == persisted_card["game_state"]["current"]


def test_non_game_legacy_game_panel_never_materializes_game_state(tmp_path: Path):
    old_card = {
        "name": "沈砚",
        "role": "主角",
        "real_state": {"current": {"balance": "27.60元"}, "recent_changes": []},
        "game_panel": {"game_id": "旧数据", "level": 9, "currency": "99铜币"},
    }
    _write_project(tmp_path, genre_plugin_id="xuanhuan", character=old_card)
    store = FileProjectStore(tmp_path)

    packet = store.writing_packet(1)
    assert packet["scene_kind"] == "reality"
    assert "game_state" not in packet["character_cards"][0]["state_context"]

    _persist_public_chapter(
        store,
        chapter_number=1,
        event={
            "line": "game",
            "character": "沈砚",
            "game_state": {"current": {"level": 10, "currency": "100铜币"}},
        },
    )

    persisted_state = json.loads((tmp_path / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    persisted_project = json.loads((tmp_path / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert "game_state" not in persisted_state["characters"][0]
    assert "game_state" not in persisted_project["character_profiles"][0]
    assert persisted_state["characters"][0]["current_state"]["current"]["balance"] == "27.60元"
    assert "real_state" not in persisted_state["characters"][0]
