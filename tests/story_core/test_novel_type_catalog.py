from types import SimpleNamespace

import pytest

from apps.api.storage import _project_world_facts
from packages.story_core.chapter_governance import build_chapter_governance
from packages.story_core.chapter_seed import _is_game_story as chapter_seed_is_game_story, build_chapter_seed
from packages.story_core.genre_plugins import (
    is_game_genre,
    plugin_prompt_guide,
    plugin_simulation_blueprint,
    select_genre_plugins,
)
from packages.story_core.models import ChapterSummary, CharacterState, NovelProject, StoryState
from packages.story_core.orchestrator import StoryOrchestrator, _genre_context_for_prompt, _review_chapter_body, _story_snapshot
from packages.story_core.web_game_review import _has_game_context
from packages.story_core import novel_type_catalog
from packages.story_core.novel_type_catalog import (
    DEFAULT_NOVEL_TYPE_ID,
    NOVEL_TYPE_CATALOG,
    novel_type_options,
)


def test_xuanhuan_prompt_uses_non_game_phase_and_subtype_method():
    story = StoryState(
        story_id="s-xuanhuan-prompt",
        outline="林照守着断香炉，第三块青砖下藏着旧事。",
        genre="xuanhuan",
        style="白描、现代中文",
        world_facts=["小说类型：xuanhuan"],
        characters=[
            CharacterState(name="林照", role="主角"),
            CharacterState(name="陆青禾", role="相关配角", goals=["查清断香炉的旧事"]),
        ],
        chapter_summaries=[
            ChapterSummary(
                chapter_number=1,
                summary="上一章陆青禾在炉灰里发现了半枚旧印。",
                unresolved_threads=["陆青禾仍未说明旧印来自何处。"],
                next_focus="林照与陆青禾核对旧印。",
            )
        ],
    )

    plan_prompt = StoryOrchestrator()._plan_prompt(story, 2)
    genre_context = _genre_context_for_prompt(story, 2)
    method_text = "\n".join(genre_context["genre_method"])

    assert "本章连续性材料" in plan_prompt
    assert "上一章陆青禾在炉灰里发现了半枚旧印" in plan_prompt
    assert "陆青禾" in plan_prompt
    assert "千倍爆率" not in plan_prompt
    assert "铜币" not in plan_prompt
    assert "推进当前核心矛盾" in plan_prompt
    assert genre_context["genre_family"] == "xuanhuan"
    assert "自创力量" in method_text
    assert "渡劫" not in method_text
    assert "飞升" not in method_text


def test_director_snapshot_prioritizes_chapter_relevant_characters_and_caps_detailed_cards():
    story = StoryState(
        story_id="s-director-relevant-characters",
        outline="林照追查断香炉，陆青禾掌握关键旧事。",
        genre="xuanhuan",
        style="白描",
        characters=[
            CharacterState(name="闲人甲", role="旧配角"),
            CharacterState(name="闲人乙", role="旧配角"),
            CharacterState(name="林照", role="主角", goals=["查清断香炉"]),
            CharacterState(
                name="陆青禾",
                role="相关配角",
                goals=["隐瞒旧印来历"],
                current_emotion="戒备",
                memory=["见过同样的旧印"],
            ),
            CharacterState(name="执事周衡", role="本章施压者", chapter_role="阻止查炉"),
        ],
        chapter_summaries=[
            ChapterSummary(
                chapter_number=4,
                summary="陆青禾带林照避开闲人甲，执事周衡随后封了炉房。",
                unresolved_threads=["陆青禾为何认得旧印"],
                next_focus="林照找陆青禾追问，设法绕过执事周衡。",
            )
        ],
    )

    cards = _story_snapshot(story)["characters"]

    assert len(cards) <= 4
    assert {"林照", "陆青禾", "执事周衡"}.issubset({card["name"] for card in cards})
    lu_card = next(card for card in cards if card["name"] == "陆青禾")
    assert lu_card["emotion"] == "戒备"
    assert "见过同样的旧印" in lu_card["memory"]

    prompt = StoryOrchestrator()._plan_prompt(story, 5)
    assert "戒备" in prompt
    assert "见过同样的旧印" in prompt


def test_novel_type_catalog_exposes_selectable_genres():
    options = novel_type_options()

    ids = {item["id"] for item in options}
    assert DEFAULT_NOVEL_TYPE_ID == "generic_webnovel"
    assert {
        "generic_webnovel",
        "game_webnovel",
        "urban",
        "xuanhuan",
        "xianxia",
        "suspense",
        "romance",
        "rules_mystery",
    }.issubset(ids)
    assert all(item["label"] and item["description"] for item in options)
    assert NOVEL_TYPE_CATALOG["game_webnovel"].plugin_id == "game_webnovel"


def test_runtime_catalog_bulk_views_use_one_stable_library_snapshot(monkeypatch):
    from packages.story_core import novel_type_library

    records = [
        SimpleNamespace(id="first", name="First", description="First description", keywords=()),
        SimpleNamespace(id="second", name="Second", description="Second description", keywords=()),
    ]
    calls = 0

    def list_once():
        nonlocal calls
        calls += 1
        if calls > 1:
            raise AssertionError("bulk catalog view reread the changing library")
        return records

    monkeypatch.setattr(novel_type_library, "list_novel_types", list_once)

    assert list(NOVEL_TYPE_CATALOG.items()) == [
        ("first", novel_type_catalog.NovelType("first", "First", "First description", ())),
        ("second", novel_type_catalog.NovelType("second", "Second", "Second description", ())),
    ]
    assert calls == 1


def test_runtime_catalog_values_and_copy_each_read_one_snapshot(monkeypatch):
    from packages.story_core import novel_type_library

    records = [
        SimpleNamespace(id="only", name="Only", description="Only description", keywords=())
    ]
    calls = 0

    def current_records():
        nonlocal calls
        calls += 1
        return records

    monkeypatch.setattr(novel_type_library, "list_novel_types", current_records)

    assert [item.plugin_id for item in NOVEL_TYPE_CATALOG.values()] == ["only"]
    assert calls == 1
    copied = NOVEL_TYPE_CATALOG.copy()
    assert copied == {
        "only": novel_type_catalog.NovelType("only", "Only", "Only description", ())
    }
    assert calls == 1
    copied.clear()
    assert [item.plugin_id for item in NOVEL_TYPE_CATALOG.values()] == ["only"]
    assert calls == 1


def test_dict_runtime_catalog_uses_one_library_snapshot(monkeypatch):
    from packages.story_core import novel_type_library

    original = novel_type_library.list_novel_types
    calls = 0

    def counted_records():
        nonlocal calls
        calls += 1
        return original()

    monkeypatch.setattr(novel_type_library, "list_novel_types", counted_records)

    converted = dict(NOVEL_TYPE_CATALOG)

    assert calls == 1
    assert converted
    assert set(converted) == {item.id for item in original()}
    assert all(type(key) is str for key in converted)
    assert all(key == item.plugin_id for key, item in converted.items())
    assert novel_type_catalog._CONVERSION_KEYS.pin is None


def test_runtime_catalog_bulk_operations_explicitly_clear_previous_pin():
    operations = (
        lambda: NOVEL_TYPE_CATALOG.keys(),
        lambda: NOVEL_TYPE_CATALOG.items(),
        lambda: NOVEL_TYPE_CATALOG.values(),
        lambda: NOVEL_TYPE_CATALOG.copy(),
    )

    for operation in operations:
        saved_keys = list(NOVEL_TYPE_CATALOG.keys())
        pin = novel_type_catalog._CONVERSION_KEYS.pin
        assert pin.remaining_key_count == len(saved_keys)

        operation()

        assert novel_type_catalog._CONVERSION_KEYS.pin is None

    stale_view = NOVEL_TYPE_CATALOG.keys()
    list(stale_view)
    NOVEL_TYPE_CATALOG.items()
    list(stale_view)
    assert novel_type_catalog._CONVERSION_KEYS.pin is None


def test_runtime_catalog_key_error_clears_conversion_pin():
    saved_keys = list(NOVEL_TYPE_CATALOG.keys())
    first_key = saved_keys[0]
    pin = novel_type_catalog._CONVERSION_KEYS.pin
    pin.snapshot = dict(pin.snapshot)
    pin.snapshot.pop(str(first_key))

    with pytest.raises(KeyError):
        NOVEL_TYPE_CATALOG[first_key]

    assert novel_type_catalog._CONVERSION_KEYS.pin is None


def test_eastern_fantasy_catalog_options_explain_their_distinct_promises():
    xuanhuan = NOVEL_TYPE_CATALOG["xuanhuan"]
    xianxia = NOVEL_TYPE_CATALOG["xianxia"]

    assert xuanhuan.label == "东方玄幻"
    for term in ("自创力量", "异物机缘", "资源成长", "世界秘密"):
        assert term in xuanhuan.description

    assert xianxia.label == "修仙仙侠"
    for term in ("灵根修炼", "道法因果", "渡劫飞升", "长生求道"):
        assert term in xianxia.description


def test_normalize_novel_type_ids_reuses_alias_case_and_deduplication_rules():
    assert novel_type_catalog.normalize_novel_type_ids(
        [" 东方玄幻 ", "XUANHUAN", "修仙", "XIANXIA", "网游升级", "GAME_WEBNOVEL"]
    ) == ["xuanhuan", "xianxia", "game_webnovel"]


def test_explicit_non_game_type_recognizes_supported_metadata_shapes():
    samples = (
        "  xuanhuan  ",
        "xianxia",
        "genre: xuanhuan",
        "genre = xianxia",
        "genre: 东方玄幻",
        '{"genre": "xuanhuan"}',
        "{'genre': 'xianxia'}",
        "小说类型：xuanhuan",
        "xiaoshuoleixing=xianxia",
        '{"genre_plugin_ids": ["xuanhuan"]}',
        "{'genre_plugin_ids': ['xianxia']}",
        "genre_plugin_ids = ['xuanhuan']",
    )

    assert all(novel_type_catalog.has_explicit_non_game_type(sample) for sample in samples)


def test_explicit_non_game_type_rejects_type_words_embedded_in_prose():
    prose_samples = (
        "xuanhuan is the English keyword he searched for before entering the game.",
        "xuanhuan 这个词出现在正文里，不是类型字段。",
        "xianxia 白描 林照看守断香炉。",
        "修仙\n白描\n宗门成长",
        "修仙",
        "东方玄幻",
    )

    assert all(not novel_type_catalog.has_explicit_non_game_type(prose) for prose in prose_samples)
    assert is_game_genre(prose_samples[0] + " VRMMO 交易行") is True


def test_game_context_entrypoints_share_the_same_evidence_matrix():
    samples = (
        ("爆率", True),
        ("铜币", True),
        ("公会", False),
        ("玩家 公会", True),
        ("小说类型：xianxia 爆率", False),
        ("小说类型：xuanhuan 铜币", False),
        ("xuanhuan is only an English word in this sentence. 公会", False),
    )

    for text, expected in samples:
        assert is_game_genre(text) is expected, text
        assert _has_game_context(text, {}, []) is expected, text

        review = _review_chapter_body(1, text, {}, [])
        review_detected_game = any("游戏ID" in issue for issue in review["issues"])
        assert review_detected_game is expected, text


def test_explicit_novel_type_overrides_keyword_detection():
    project = NovelProject(
        project_id="p-urban",
        title="游戏公司里的都市翻盘",
        seed_outline="主角在游戏公司做项目，但故事核心是职场、合同和舆论。",
        world_blueprint={"genre_plugin_ids": ["urban"]},
    )

    plugins = select_genre_plugins(project)

    plugin_ids = [plugin.plugin_id for plugin in plugins]
    assert "urban" in plugin_ids
    assert "game_webnovel" not in plugin_ids


def test_explicit_non_game_type_blocks_negative_game_keyword_detection():
    text = "小说类型：xianxia。不要写网游面板、背包、铜币、掉落、任务牌或玩家生态。"

    assert is_game_genre(text) is False


def test_exact_plain_genre_value_blocks_negative_game_keyword_detection():
    text = " xianxia "

    assert is_game_genre(text) is False


def test_project_world_facts_include_explicit_novel_type():
    project = NovelProject(
        project_id="p-xianxia",
        title="我替宗门看守断香炉",
        seed_outline="外门弟子看守断香炉。",
        world_blueprint={"genre_plugin_ids": ["xianxia"], "premise": "断香炉里有未了因果。"},
    )

    facts = _project_world_facts(project)

    assert "小说类型：xianxia" in facts


def test_explicit_non_game_story_skips_chapter_seed_and_webgame_review_detection():
    story = StoryState(
        story_id="s-xianxia",
        outline="林照看守断香炉。",
        genre="修仙",
        style="白描",
        author_constraints=["不要写网游面板、背包、铜币、掉落、任务牌或玩家生态。"],
        world_facts=["小说类型：xianxia", "世界前提：断香炉里有未了因果。"],
    )

    assert chapter_seed_is_game_story(story) is False
    assert _has_game_context("林照站在祖祠里。", {}, story.world_facts + story.author_constraints) is False

    seed = build_chapter_seed(story, 2)
    assert "xianxia" in seed["genre_plugins"]
    assert "game_webnovel" not in seed["genre_plugins"]
    assert "千倍爆率" not in seed["phase"]


def test_explicit_xuanhuan_story_skips_game_seed_and_review_detection():
    story = StoryState(
        story_id="s-xuanhuan",
        outline="林照看守断香炉，追查炉中的旧事。",
        genre="xuanhuan",
        style="白描",
        author_constraints=["不要套用网游面板、背包、掉落或玩家生态。"],
        world_facts=["小说类型：xuanhuan", "世界前提：断香炉只给零碎反馈。"],
    )

    assert chapter_seed_is_game_story(story) is False
    assert _has_game_context("林照站在祖祠里。", {}, story.world_facts + story.author_constraints) is False

    seed = build_chapter_seed(story, 1)
    assert seed["genre_plugins"] == ["generic_webnovel", "eastern_fantasy", "xuanhuan"]
    assert "千倍爆率" not in seed["phase"]


def test_chapter_governance_keeps_xuanhuan_out_of_xianxia_rules():
    bundle = SimpleNamespace(chapter_number=1, event_plan={}, next_outline="查清遗物的第一次反应。")
    xuanhuan_story = StoryState(
        story_id="s-xuanhuan-governance",
        outline="主角接触一件来历不明的遗物。",
        genre="",
        style="白描",
        world_facts=["小说类型：xuanhuan"],
    )

    governance = build_chapter_governance(xuanhuan_story, bundle, chapter_number=1)
    intent_text = "\n".join(governance["chapter_intent"]["must_include"])
    hard_text = "\n".join(governance["rule_stack"]["hard_facts"])

    assert "东方玄幻" in hard_text
    for xianxia_term in ("外门", "宗门差事", "修仙题材规则"):
        assert xianxia_term not in intent_text
        assert xianxia_term not in hard_text

    prose_only_story = StoryState(
        story_id="s-xuanhuan-prose-only",
        outline="xuanhuan 只是角色在纸上写下的英文词。",
        genre="",
        style="白描",
    )
    prose_governance = build_chapter_governance(prose_only_story, bundle, chapter_number=1)
    prose_text = "\n".join(prose_governance["rule_stack"]["hard_facts"])
    assert "东方玄幻" not in prose_text
    assert "修仙题材规则" not in prose_text


def test_chapter_seed_normalizes_world_fact_chinese_genre_aliases():
    samples = (
        ("东方玄幻", "xuanhuan"),
        ("修仙", "xianxia"),
    )

    for alias, subtype in samples:
        story = StoryState(
            story_id=f"s-world-fact-{subtype}",
            outline="主角从一件具体差事中发现异常。",
            genre="",
            style="白描",
            world_facts=[f"小说类型：{alias}"],
        )

        seed = build_chapter_seed(story, 1)

        assert seed["genre_plugins"] == ["generic_webnovel", "eastern_fantasy", subtype]
        assert seed["simulation_blueprint"]["plugin_id"] == subtype


def test_xianxia_plugin_exposes_reusable_opening_method_card():
    project = NovelProject(
        project_id="p-xianxia-method",
        title="我替宗门看守断香炉",
        seed_outline="外门弟子看守祖祠里的断香炉。",
        world_blueprint={"genre_plugin_ids": ["xianxia"]},
    )

    plugins = select_genre_plugins(project)
    prompt_guide = plugin_prompt_guide(plugins)
    blueprint = plugin_simulation_blueprint(plugins)

    assert "xianxia" in prompt_guide
    assert "残缺机缘" in prompt_guide
    assert "宗门差事" in prompt_guide
    assert blueprint["plugin_id"] == "xianxia"
    assert any(scene["id"] == "low_status_assignment" for scene in blueprint["opening_scene_templates"])
    assert any("不要直接送完整传承" in item for item in blueprint["forbidden_conflict_modes"]["chapter_1"])
