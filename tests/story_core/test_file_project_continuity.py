from packages.story_core.file_project_store import (
    FileProjectStore,
    _promote_downstream_rewrite_status,
)


def test_store_builds_interface_from_adjacent_persisted_chapters(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path / "novel")
    chapters = {
        143: {
            "chapter_number": 143,
            "body": "开头" + "中" * 1200 + "沈墨璃踏入密道，殿门重新合拢。",
            "chapter_summary": {
                "facts": ["沈墨璃离开神殿，前往沈家与联盟传递消息。"],
                "unresolved_threads": ["天机阁六个光点正在合围。"],
            },
        },
        145: {"chapter_number": 145, "body": "第145章旧稿开头。" + "后" * 900},
    }
    monkeypatch.setattr(store, "chapter_numbers", lambda: [143, 144, 145])
    monkeypatch.setattr(store, "chapter", lambda number=None: chapters[int(number)])

    interface = store._continuity_interface_for_target(144)

    assert interface["previous_chapter_number"] == 143
    assert interface["previous_tail"].endswith("沈墨璃踏入密道，殿门重新合拢。")
    assert interface["previous_facts"] == ["沈墨璃离开神殿，前往沈家与联盟传递消息。"]
    assert interface["next_chapter_number"] == 145
    assert interface["next_opening"].startswith("第145章旧稿开头。")


def test_direction_payload_exposes_transient_continuity_interface(tmp_path, monkeypatch):
    store = FileProjectStore(tmp_path / "novel")
    monkeypatch.setattr(
        store,
        "project_outline",
        lambda: {"overall": {}, "arcs": [], "chapters": []},
    )
    monkeypatch.setattr(store, "chapter_numbers", lambda: [])
    monkeypatch.setattr(
        store,
        "_continuity_interface_for_target",
        lambda target, chapter_numbers=None: {
            "previous_chapter_number": target - 1,
            "previous_tail": "上一章真正结尾。",
            "fact_priority": ["已发生剧情", "本章计划", "静态人物设定", "后续旧稿"],
        },
    )
    state = {
        "story_id": "story-test",
        "outline": "测试大纲",
        "genre": "玄幻",
        "style": "",
        "current_chapter": 143,
        "chapter_summaries": [],
        "timeline": [],
        "characters": [],
    }
    project = {"project_id": "project-test", "title": "测试作品"}

    payload = store._story_state_payload_for_direction(state, project, 144)

    assert payload["outline_context"]["continuity_interface"]["previous_tail"] == "上一章真正结尾。"


def test_quality_report_promotes_downstream_rewrite_status():
    report = {
        "writing_review": {
            "downstream_rewrite_required": True,
            "downstream_chapter_number": 145,
        }
    }

    _promote_downstream_rewrite_status(report)

    assert report["downstream_rewrite_required"] is True
    assert report["downstream_chapter_number"] == 145
