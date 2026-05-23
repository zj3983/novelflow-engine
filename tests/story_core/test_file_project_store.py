import json
from types import SimpleNamespace

from packages.story_core.file_project_store import FileProjectStore, _regeneration_quality_blocking


def _make_minimal_file_project(root, *, state=None, project=None):
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps(project or {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(state or {"story_id": "s-file", "current_chapter": 0, "world_facts": []}, ensure_ascii=False),
        encoding="utf-8",
    )
    return FileProjectStore(root)


def test_regeneration_quality_allows_soft_scene_coverage_warnings():
    writing_review = {
        "issues": [
            "场景卡必写内容缺失：s3-c2-reaction-1 缺少 路人玩家抱怨爆率低。",
            "Scene contract not consumed: s1-c2-inherit-ledger missing visibility_boundary_surface.",
        ],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is False


def test_regeneration_quality_still_blocks_progression_overreach():
    writing_review = {
        "issues": ["第二章推进过快：从第一章账本直接完成元素回廊前置或升级。"],
        "critical_review": {"hard_issues": [], "severity_summary": {"has_hard_violation": False}},
    }
    quality_report = {"ok": False, "issues": ["writing_review"], "writing_review": writing_review}

    assert _regeneration_quality_blocking(quality_report, writing_review) is True


def test_file_project_store_writes_rewrites_and_commits(tmp_path, monkeypatch):
    root = tmp_path / "novel"
    workflow_log = tmp_path / "chapter_exports" / "workflow_log.jsonl"
    monkeypatch.setenv("NOVEL_AUTOGROWTH_WORKFLOW_LOG_PATH", str(workflow_log))
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps({"story_id": "s-file", "current_chapter": 0, "world_facts": []}, ensure_ascii=False),
        encoding="utf-8",
    )

    store = FileProjectStore(root)
    written = store.write_chapter(
        chapter_number=1,
        title="Chapter One",
        body="Night Ember checked the village counter and kept walking.",
        next_outline="Check the wolf slope.",
        summary="Night Ember enters the village.",
        instructions=["keep it grounded"],
    )

    assert written["schema_version"] == "file-project-write/v1"
    assert written["review"]["writing_review"]["pass"] is True
    assert (root / ".story-system" / "chapters" / "0001.json").exists()
    assert (root / "chapters" / "0001-Chapter One.md").read_text(encoding="utf-8").startswith("Night Ember")
    assert store.summary()["current_chapter"] == 1
    assert (root / ".story-system" / "commits" / "latest_commit.json").exists()
    project_after_write = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project_after_write["world_blueprint"]["continuity_state"]["latest_chapter"] == 1
    assert project_after_write["world_blueprint"]["continuity_state"]["latest_summary"] == "Night Ember enters the village."

    rewritten = store.rewrite_chapter(
        chapter_number=1,
        title="Chapter One Revised",
        body="Night Ember bought nothing. He only counted the cost and left.",
        next_outline="Return after two more glands.",
        instructions=["remove explanatory narrator voice"],
    )

    assert rewritten["schema_version"] == "file-project-rewrite/v1"
    assert rewritten["review"]["writing_review"]["pass"] is True
    assert not (root / "chapters" / "0001-Chapter One.md").exists()
    assert (root / "chapters" / "0001-Chapter One Revised.md").read_text(encoding="utf-8").startswith("Night Ember")
    latest_commit = json.loads((root / ".story-system" / "commits" / "latest_commit.json").read_text(encoding="utf-8"))
    assert latest_commit["operation"] == "rewrite"
    assert any(item["path"] == "chapters/0001-Chapter One Revised.md" for item in latest_commit["manifest"])
    project_after_rewrite = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project_after_rewrite["world_blueprint"]["continuity_state"]["latest_title"] == "Chapter One Revised"
    state_after_rewrite = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    world_facts_after_rewrite = "\n".join(state_after_rewrite["world_facts"])
    assert "remove explanatory narrator voice" in world_facts_after_rewrite
    assert "keep it grounded" not in world_facts_after_rewrite
    workflow_records = [json.loads(line) for line in workflow_log.read_text(encoding="utf-8").splitlines()]
    assert [record["operation"] for record in workflow_records] == ["write", "rewrite"]
    assert workflow_records[0]["chapter"] == 1
    assert workflow_records[1]["chapter_title"] == "Chapter One Revised"


def test_file_project_store_generates_next_chapter_without_api(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-file", "title": "File Novel", "active_story_id": "s-file"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-file",
                "outline": "A grounded game story.",
                "genre": "webgame",
                "style": "plain",
                "current_chapter": 0,
                "world_facts": [],
                "characters": [
                    {
                        "name": "Night Ember",
                        "role": "protagonist",
                        "game_id": "Night Ember",
                        "goals": ["stay quiet"],
                        "memory": ["Entered the village."],
                        "current_emotion": "neutral",
                        "location": "village gate",
                        "game_panel": {"level": 1, "class_path": "apprentice", "currency": "0 gold"},
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    class FakeEngine:
        def generate_next_chapter(self, story):
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Generated One",
                body="Night Ember checked the quest counter and left quietly.",
                cadence="manual",
                next_outline="Check costs.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Generated One",
                    "cadence": "manual",
                    "summary": "Night Ember checks the counter.",
                    "facts": ["No sale happened."],
                    "next_focus": "Check costs.",
                    "primary_conflict": "Low resources.",
                    "secondary_conflict": "Limited information.",
                    "event_beat": "Counter check.",
                },
            )

    generated = FileProjectStore(root).generate_next_chapter(engine=FakeEngine())

    assert generated["schema_version"] == "file-project-generate-next/v1"
    assert generated["chapter_number"] == 1
    assert (root / ".story-system" / "chapters" / "0001.json").exists()
    assert (root / "chapters" / "0001-Generated One.md").read_text(encoding="utf-8").startswith("Night Ember")
    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["current_chapter"] == 1
    assert any(item["chapter_number"] == 1 for item in state["chapter_summaries"])
    assert any("Night Ember checks the counter." in item for item in state["world_facts"])
    assert state["time_state"]["server_day"] == 1
    assert state["time_state"]["chapter_time_spans"][0]["chapter_number"] == 1
    project = json.loads((root / ".webnovel" / "project.json").read_text(encoding="utf-8"))
    assert project["current_focus"] == "Check costs."
    assert project["world_blueprint"]["continuity_state"]["latest_title"] == "Generated One"
    assert project["world_blueprint"]["time_state"]["current_scene_time"] == "第1章章末"
    assert project["character_profiles"][0]["name"] == "Night Ember"
    assert project["character_profiles"][0]["game_panel"]["updated_chapter"] == 1
    packet = FileProjectStore(root).writing_packet(2)
    assert packet["state"]["time_state"]["current_scene_time"] == "第1章章末"
    latest_commit = json.loads((root / ".story-system" / "commits" / "latest_commit.json").read_text(encoding="utf-8"))
    assert latest_commit["operation"] == "generate"


def test_persist_bundle_ignores_stale_bundle_updated_story(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 0, "world_facts": ["source:canonical"]},
    )

    bundle = SimpleNamespace(
        chapter_number=1,
        chapter_title="Fresh Chapter",
        body="Night Ember keeps the current ledger clean.",
        cadence="manual",
        next_outline="Continue from fresh facts.",
        updated_story={
            "story_id": "s-file",
            "current_chapter": 99,
            "world_facts": ["stale fact should not return"],
        },
        chapter_summary={
            "chapter_title": "Fresh Chapter",
            "cadence": "manual",
            "summary": "Fresh summary wins.",
            "facts": ["fresh fact from summary"],
            "next_focus": "Continue from fresh facts.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    store.persist_bundle(bundle)

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    facts = "\n".join(state["world_facts"])
    assert "fresh fact from summary" in facts
    assert "Fresh summary wins." in facts
    assert "stale fact should not return" not in facts
    assert state["current_chapter"] == 1


def test_persist_bundle_uses_runtime_updated_story(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "current_chapter": 1,
            "progression_ledger": {"economy": {"game_currency": "0铜"}},
            "world_facts": ["source:canonical"],
        },
    )

    bundle = SimpleNamespace(
        chapter_number=2,
        chapter_title="Ledger Chapter",
        body="Night Ember turns the completed quest into a clean ledger.",
        cadence="manual",
        next_outline="Continue from the updated ledger.",
        updated_story={
            "story_id": "s-file",
            "current_chapter": 2,
            "progression_ledger": {"economy": {"game_currency": "5铜"}},
            "world_facts": ["source:canonical"],
        },
        chapter_summary={
            "chapter_title": "Ledger Chapter",
            "cadence": "manual",
            "summary": "The quest reward and costs settle into the ledger.",
            "facts": ["ledger fact"],
            "next_focus": "Continue from the updated ledger.",
            "primary_conflict": "Clean state.",
            "secondary_conflict": "Old snapshot.",
            "event_beat": "Persist.",
        },
    )

    store.persist_bundle(bundle)

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert state["progression_ledger"]["economy"]["game_currency"] == "5铜"
    assert state["current_chapter"] == 2


def test_rewrite_chapter_uses_canonical_state_not_embedded_snapshot(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={"story_id": "s-file", "current_chapter": 1, "world_facts": ["source:canonical"]},
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "Old Chapter",
        "body": "Old body.",
        "next_outline": "Old next.",
        "updated_story": {
            "story_id": "s-file",
            "current_chapter": 1,
            "world_facts": ["stale embedded snapshot"],
        },
        "chapter_summary": {
            "chapter_title": "Old Chapter",
            "cadence": "manual",
            "summary": "Old summary.",
            "facts": ["old fact"],
            "next_focus": "Old next.",
            "primary_conflict": "Old.",
            "secondary_conflict": "Old.",
            "event_beat": "Old.",
        },
    }
    (root / ".story-system" / "chapters" / "0001.json").write_text(json.dumps(chapter, ensure_ascii=False), encoding="utf-8")
    (root / ".story-system" / "reviews" / "0001.json").write_text(
        json.dumps({"writing_review": {"pass": True, "issues": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "chapters" / "0001-Old Chapter.md").write_text("Old body.", encoding="utf-8")

    store.rewrite_chapter(
        chapter_number=1,
        title="Rewritten Chapter",
        body="Night Ember rewrites only the live facts.",
        instructions=["fresh rewrite fact"],
    )

    state = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    facts = "\n".join(state["world_facts"])
    assert "fresh rewrite fact" in facts
    assert "stale embedded snapshot" not in facts


def test_regenerate_blocks_frozen_chapter(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "current_chapter": 1,
            "world_facts": [],
            "progression_ledger": {"continuity_lock": {"chapters_frozen": [1]}},
        },
    )

    try:
        store.regenerate_chapter(1, engine=SimpleNamespace(generate_next_chapter=lambda story: None))
    except ValueError as exc:
        assert str(exc) == "chapter_frozen:1:regenerate"
    else:
        raise AssertionError("expected frozen chapter regeneration to fail")


def test_file_project_store_dedupes_npc_aliases_and_filters_surface_entities(tmp_path):
    store = FileProjectStore(tmp_path / "novel")
    chapter = {
        "chapter_number": 1,
        "chapter_title": "药剂铺窗口",
        "body": "夜烬走进药剂铺。灰头巾老妇人抬头。公共频道还在滚动。清道夫委托写在木牌上。",
        "chapter_summary": {"summary": "夜烬问药剂师。"},
    }

    cards = store._merge_character_cards([], store._chapter_entity_cards(chapter))

    assert [card["name"] for card in cards] == ["药剂师洛婶"]
    assert cards[0]["role"] == "服务NPC"
    assert "药剂师NPC" not in {card["name"] for card in cards}
    assert "药剂铺老妇人" not in {card["name"] for card in cards}
    assert "公共频道" not in {card["name"] for card in cards}
    assert "清道夫委托" not in {card["name"] for card in cards}


def test_file_project_store_filters_stale_non_character_profiles(tmp_path):
    store = FileProjectStore(tmp_path / "novel")
    project = {
        "project_id": "p-file",
        "character_profiles": [
            {"name": "公共频道", "role": "玩家群体", "memory": ["旧噪音。"]},
            {"name": "药剂铺老妇人", "role": "服务NPC", "memory": ["旧药剂铺卡。"]},
        ],
    }
    state = {
        "characters": [
            {"name": "药剂师NPC", "role": "服务NPC", "memory": ["第1章：委托十份一批。"]},
            {"name": "清道夫委托", "role": "任务线", "memory": ["不是人物。"]},
        ]
    }
    chapter = {
        "chapter_number": 1,
        "chapter_title": "药剂铺窗口",
        "body": "夜烬问药剂师。",
        "chapter_summary": {
            "chapter_title": "药剂铺窗口",
            "cadence": "urgent",
            "summary": "夜烬问药剂师。",
            "facts": ["药剂铺十份一批。"],
            "next_focus": "回灰狼坡。",
            "primary_conflict": "材料不足。",
            "secondary_conflict": "0铜。",
            "event_beat": "窗口规则。",
        },
    }

    synced = store._sync_project_after_chapter(project, state, chapter)

    names = [profile["name"] for profile in synced["character_profiles"]]
    assert names == ["药剂师洛婶"]
    assert synced["character_profiles"][0]["memory"][-1] == "第1章：委托十份一批。"


def test_file_project_store_regenerates_target_chapter_with_rotating_variant(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)
    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {"schema_version": "story-system-master-setting/v1", "project": {"project_id": "p-file", "title": "File Novel"}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-file", "title": "File Novel"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-file",
                "outline": "网游开服，主角先确认边界。",
                "genre": "网游",
                "style": "番茄升级流",
                "current_chapter": 1,
                "world_facts": ["世界摘要：保留。", "第1章事实：灰鼠毒腺x18。"],
                "progression_ledger": {
                    "inventory": ["灰鼠毒腺18份"],
                    "simulation_variant": {"id": "old"},
                },
                "characters": [
                    {
                        "name": "苏叶",
                        "role": "主角",
                        "game_id": "夜烬",
                        "game_panel": {"game_id": "夜烬", "inventory": {"灰鼠毒腺": "18份"}},
                        "memory": ["第1章灰鼠毒腺。", "现实压力。"],
                    },
                    {"name": "公共频道", "role": "玩家群体", "memory": ["旧噪音。"]},
                ],
                "chapter_summaries": [{"chapter_number": 1, "chapter_title": "旧第一章", "summary": "旧版。"}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    store = FileProjectStore(root)
    store.write_chapter(chapter_number=1, title="旧第一章", body="旧正文。", summary="旧版。")

    seen_variants: list[str] = []

    class FakeEngine:
        def generate_next_chapter(self, story):
            simulation_variant = story.progression_ledger["simulation_variant"]
            variant = simulation_variant["id"]
            seen_variants.append(variant)
            assert simulation_variant["skip_style_adapt"] is True
            assert simulation_variant["skip_expansion"] is False
            assert "灰鼠" not in json.dumps(story.model_dump(mode="json"), ensure_ascii=False)
            assert story.chapter_summaries == []
            assert [character.name for character in story.characters] == ["苏叶"]
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title=f"新版-{variant}",
                body=f"正文使用变体 {variant}。",
                cadence="manual",
                next_outline="继续确认边界。",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": f"新版-{variant}",
                    "cadence": "manual",
                    "summary": f"使用 {variant} 重推。",
                    "facts": [f"variant:{variant}"],
                    "next_focus": "继续确认边界。",
                    "primary_conflict": "边界",
                    "secondary_conflict": "代价",
                    "event_beat": "重推",
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine())

    assert regenerated["schema_version"] == "file-project-regenerate/v1"
    assert regenerated["chapter_number"] == 1
    assert regenerated["chapter_title"] == "背包快满了"
    assert seen_variants == ["boundary-inventory-route"]
    assert regenerated["simulation_variant"]["id"] == "boundary-inventory-route"
    assert regenerated["simulation_variant"]["skip_style_adapt"] is True
    assert regenerated["simulation_variant"]["skip_expansion"] is False
    assert (root / "chapters" / "0001-背包快满了.md").exists()


def test_file_project_store_passes_temporary_guidance_to_regeneration(tmp_path):
    root = tmp_path / "novel"
    store = _make_minimal_file_project(
        root,
        state={
            "story_id": "s-file",
            "outline": "A grounded game story.",
            "genre": "webgame",
            "style": "plain",
            "current_chapter": 1,
            "world_facts": [],
        },
    )
    store.write_chapter(chapter_number=1, title="Old One", body="Old body kept costs visible.", summary="Old summary.")
    guidance = "Use the dissection report: keep exp 30/100 and do not jump to class change."
    seen_guidance: list[dict] = []

    class FakeEngine:
        def generate_next_chapter(self, story):
            temporary = story.progression_ledger["simulation_variant"]["rewrite_guidance"]
            seen_guidance.append(temporary)
            assert temporary["source"] == "book_dissection"
            assert temporary["text"] == guidance
            updated_story = story.model_copy(update={"current_chapter": 1})
            return SimpleNamespace(
                chapter_number=1,
                chapter_title="Guided One",
                body="Night Ember keeps exp 30/100 visible and stays away from class change.",
                cadence="manual",
                next_outline="Continue the guided path.",
                updated_story=updated_story,
                chapter_summary={
                    "chapter_title": "Guided One",
                    "cadence": "manual",
                    "summary": "Guidance shaped the rewrite.",
                    "facts": ["guided rewrite"],
                    "next_focus": "Continue the guided path.",
                    "primary_conflict": "cost",
                    "secondary_conflict": "visibility",
                    "event_beat": "guided",
                },
            )

    regenerated = store.regenerate_chapter(1, engine=FakeEngine(), guidance=guidance)

    assert seen_guidance == [{"source": "book_dissection", "text": guidance}]
    assert regenerated["simulation_variant"]["rewrite_guidance"]["text"] == guidance
    state_after = json.loads((root / ".webnovel" / "state.json").read_text(encoding="utf-8"))
    assert "rewrite_guidance" not in state_after.get("progression_ledger", {}).get("simulation_variant", {})


def test_file_project_store_reads_exported_layout(tmp_path):
    root = tmp_path / "novel"
    (root / ".story-system" / "chapters").mkdir(parents=True)
    (root / ".story-system" / "reviews").mkdir(parents=True)
    (root / ".webnovel").mkdir(parents=True)
    (root / "chapters").mkdir(parents=True)

    (root / ".story-system" / "MASTER_SETTING.json").write_text(
        json.dumps(
            {
                "schema_version": "story-system-master-setting/v1",
                "project": {"project_id": "p-test", "title": "测试书", "active_story_id": "s-test"},
                "active_story_id": "s-test",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / ".webnovel" / "project.json").write_text(
        json.dumps({"project_id": "p-test", "title": "测试书", "active_story_id": "s-test"}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".webnovel" / "state.json").write_text(
        json.dumps(
            {
                "story_id": "s-test",
                "genre": "网游",
                "style": "升级流",
                "current_chapter": 1,
                "author_constraints": ["不要写后台判断"],
                "world_facts": ["洛婶在药剂铺"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    chapter = {
        "chapter_number": 1,
        "chapter_title": "第一章 灰烬村",
        "body": "夜烬走进药剂铺，洛婶抬头看了他一眼。",
        "chapter_summary": {"summary": "夜烬见到洛婶。"},
        "event_plan": {"next_focus": "补齐毒腺"},
        "quality_report": {"writing_review": {"pass": True, "issues": []}},
    }
    (root / ".story-system" / "chapters" / "0001.json").write_text(
        json.dumps(chapter, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / ".story-system" / "reviews" / "0001.json").write_text(
        json.dumps({"writing_review": {"pass": True, "issues": []}}, ensure_ascii=False),
        encoding="utf-8",
    )
    (root / "chapters" / "0001-第一章.md").write_text(chapter["body"], encoding="utf-8")

    store = FileProjectStore(root)

    assert store.exists()
    assert store.summary()["chapter_count"] == 1
    assert store.review(1)["writing_review"]["pass"] is True
    assert store.query("洛婶")["result_count"] > 0
    packet = store.writing_packet(2)
    assert packet["target_chapter"] == 2
    assert packet["latest_chapter_number"] == 1
    assert packet["prose_renderer"]["skill"] == "chinese-novelist"
    assert packet["prose_renderer"]["role"] == "prose_renderer_only"
    assert packet["title_contract"]["style"] == "tomato_concrete_short_title"
    assert any("番茄爆款网文" in rule for rule in packet["style_rules"])
    assert packet["recent_chapters"][0]["next_focus"] == "补齐毒腺"
