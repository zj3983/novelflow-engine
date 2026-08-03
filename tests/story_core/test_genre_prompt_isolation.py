import inspect
from pathlib import Path

import pytest

import packages.story_core.orchestrator as orchestrator_module
import packages.story_core.genre_stages.common_writer as common_writer_module
import packages.story_core.genre_stages.generic as generic_writer_module
import packages.story_core.genre_stages.game_webnovel.writer as game_writer_module
from packages.story_core.genre_stages.common_writer import (
    WriterContext,
    _compact_world_context_for_prompt,
    build_common_writer_sections,
)
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator


GAME_TERMS = (
    "游戏ID",
    "本章怪物卡",
    "属性面板",
    "装备耐久",
    "任务进度",
    "## 网游写法",
)

ORCHESTRATOR_GAME_STAGE_REFERENCES = (
    "normalize_legacy_economy_prompt_value",
    "review_web_game_chapter",
    "web_game_writer_method_lines",
    "web_game_revision_fact_lock",
    "_story_game_context",
    "first_chapter_market_exchange_authorized",
    "game_context",
    "game_story=",
    "game_story =",
    "game_story:",
    'profile_id == "game_webnovel"',
    "_normalize_web_game_terms",
    "_sanitize_chapter_two_webgame_terms",
    "_repair_outline_amount_anchors",
    "_scene_card_writing_protocol",
    "_sanitize_generated_body",
    "_merge_overfragmented_paragraphs",
    "_limit_metaphor_markers",
)


def test_orchestrator_prompt_pipeline_has_no_game_vocabulary():
    source = Path(orchestrator_module.__file__).read_text(encoding="utf-8")
    imports = source[: source.index("def _env_int")]
    review_region = source[
        source.index("def _review_chapter_body") : source.index("def _merge_writing_review_quality")
    ]
    world_review_region = source[
        source.index("def _build_world_state_review") : source.index("def _build_simulation_status")
    ]
    director_review_region = source[
        source.index("def _director_plan_quality_issues") : source.index("def _director_revision_prompt")
    ]
    authoring_utilities = source[
        source.index("def _rebalanced_body_is_acceptable") : source.index("def _priority_world_facts")
    ]
    length_region = source[
        source.index("def _render_expansion_length_prompt") : source.index("def _repair_generic_chapter_title")
    ]
    stage_assembly = source[
        source.index("    def _plan_prompt") : source.index("    def _extract_final_body_memory")
    ]
    boundary_source = "\n".join(
        (
            imports,
            authoring_utilities,
            director_review_region,
            review_region,
            length_region,
            stage_assembly,
        )
    )

    for term in (
        *GAME_TERMS,
        "怪物卡",
        "交易行",
        "官方兑换",
        "NPC服务",
        "背包",
        "掉落",
        "装备",
        "网游写法",
    ):
        assert term not in boundary_source
    for reference in ORCHESTRATOR_GAME_STAGE_REFERENCES:
        assert reference not in boundary_source

    strict_authoring_source = "\n".join(
        (authoring_utilities, director_review_region, review_region, length_region)
    )
    for term in ("NPC", "价格", "任务"):
        assert term not in strict_authoring_source
    for term in (
        "economy",
        "information_visibility",
        "npc_system",
        "progression_ledger",
        "opening_arc",
    ):
        assert term not in world_review_region


def test_orchestrator_web_game_prefixes_are_schema_only():
    source = Path(orchestrator_module.__file__).read_text(encoding="utf-8")
    review_region = source[
        source.index("def _review_chapter_body") : source.index("def _build_simulation_status")
    ]
    lines = [line.strip() for line in review_region.splitlines() if "web_game_" in line]

    assert lines
    assert all(
        "key.startswith" in line
        or "hard_review_prefixes" in line
        or '"web_game_review"' in line
        or "score namespace" in line
        for line in lines
    )


def test_writer_normalization_private_skip_marker_is_absent_from_stage_sources():
    stage_root = Path(orchestrator_module.__file__).parent / "genre_stages"
    sources = [Path(orchestrator_module.__file__), *stage_root.rglob("*.py")]

    assert all("_skip_writer_economy_normalization" not in path.read_text(encoding="utf-8") for path in sources)


def test_game_postprocess_contains_only_game_specific_repairs_after_common_normalization():
    source = (Path(orchestrator_module.__file__).parent / "genre_stages" / "game_webnovel" / "postprocess.py").read_text(
        encoding="utf-8"
    )

    assert "normalize_generated_body(context=context)" in source
    assert "sanitize_prose_style" not in source
    assert "merge_overfragmented_paragraphs" not in source
    assert "def _sanitize_generated_body" not in source


def test_removed_game_postprocess_compatibility_name_has_zero_source_references():
    removed_name = "sanitize_game_" "chapter_output"
    story_core_root = Path(orchestrator_module.__file__).parent
    quality_test = Path(__file__).with_name("test_generation_quality_guardrails.py")
    sources = [*story_core_root.rglob("*.py"), quality_test]

    assert all(removed_name not in path.read_text(encoding="utf-8") for path in sources)


def _story(genre: str) -> StoryState:
    return StoryState(
        story_id=f"writer-isolation-{genre}",
        outline="主角进入陌生环境，处理眼前危机。",
        genre=genre,
        style="白描",
        characters=[
            CharacterState(
                name="林川",
                role="protagonist",
                game_id="夜烬",
                game_state={"current": {"任务进度": "1/3", "装备耐久": "8/10"}},
            )
        ],
        progression_ledger={"protagonist": {"game_id": "夜烬", "class_path": "见习法师"}},
        monster_profiles=[
            {
                "name": "灰狼",
                "level": 1,
                "hp": 30,
                "drops": ["狼牙：普通材料"],
            }
        ],
    )


def _plan() -> dict:
    return {
        "event_plan": {
            "chapter_title": "灰狼坡",
            "attribute_allocation_decision": {
                "mode": "allocate",
                "allocations": {"智力": 1},
                "remaining": 0,
            },
        },
        "scene_cards": [
            {
                "title": "遭遇灰狼",
                "goal": "击退灰狼",
                "required_surface": ["灰狼"],
                "state_delta": {"inventory": {"狼牙": 1}},
            }
        ],
    }


@pytest.mark.parametrize("genre", ["修仙", "玄幻", "都市", "悬疑"])
def test_non_game_writer_prompt_excludes_game_modules(genre):
    prompt = StoryOrchestrator()._body_prompt(_story(genre), 1, _plan())

    for term in GAME_TERMS:
        assert term not in prompt


def test_generic_writer_method_does_not_impose_hidden_advantage_or_cost_examples():
    prompt = StoryOrchestrator()._body_prompt(_story("都市"), 1, _plan())
    source = Path(common_writer_module.__file__).read_text(encoding="utf-8")

    for term in ("主角暗中多拿一步", "别人误判、犹豫、排队", "价钱、伤痛、等待"):
        assert term not in prompt
        assert term not in source


def test_game_writer_prompt_keeps_game_modules():
    prompt = StoryOrchestrator()._body_prompt(_story("网游"), 1, _plan())

    assert "游戏ID" in prompt
    assert "本章怪物卡" in prompt
    assert "属性面板" in prompt
    assert "## 网游写法" in prompt
    assert "狼牙" in prompt


def test_orchestrator_writer_input_helpers_are_genre_neutral():
    module_source = inspect.getsource(orchestrator_module)
    assert "from packages.story_core.dual_state import project_character_for_scene" not in module_source
    assert "scene_kind_for_cards" not in module_source

    character_source = inspect.getsource(orchestrator_module._compact_character_cards_for_prompt)
    character_source += inspect.getsource(orchestrator_module._character_context_for_prompt)
    for game_field in ("game_id", "real_state", "game_state", "game_panel", "project_character_for_scene"):
        assert game_field not in character_source

    plan_source = inspect.getsource(orchestrator_module._compact_writer_plan_for_prompt)
    assert "attribute_allocation_decision" not in plan_source
    assert '"inventory"' not in plan_source


def test_generic_character_context_excludes_raw_game_fields():
    context = orchestrator_module._character_context_for_prompt(_story("都市"), _plan())

    assert "夜烬" not in str(context)
    assert "game_state" not in str(context)
    assert "game_panel" not in str(context)


def test_common_writer_sections_expose_stable_public_contract():
    story = _story("都市")
    orchestrator = StoryOrchestrator()
    plan = _plan()
    context = WriterContext(
        story=story,
        chapter_number=1,
        plan=plan,
        style_guidance={},
        character_context=orchestrator_module._character_context_for_prompt(story, plan),
        dialogue_context={},
        chapter_seed={},
        skill_context={},
        include_genre_method=True,
        writer_plan_for_prompt=orchestrator_module._compact_writer_plan_for_prompt(plan),
        world_facts_for_prompt=[],
        trope_guidance=[],
        trope_contract_for_prompt={},
    )

    sections = build_common_writer_sections(context)

    assert tuple(sections) == (
        "output_section",
        "chapter_direction",
        "chapter_facts",
        "character_context",
        "prose_method",
    )
    assert all(isinstance(lines, list) for lines in sections.values())


def test_game_writer_depends_only_on_public_common_sections_builder():
    source = inspect.getsource(game_writer_module)

    assert "build_common_writer_sections" in source
    for old_private_alias in (
        "_common_writer_craft_section",
        "_common_writer_direction_section",
        "_writer_fact_section_from_context",
        "_writer_output_section",
    ):
        assert old_private_alias not in source
    assert "from packages.story_core.genre_stages.common_writer import _" not in source

    generic_source = inspect.getsource(generic_writer_module.render_generic_writer_prompt_raw)
    assert "build_common_writer_sections(context)" in generic_source
    assert "_writer_output_section" not in generic_source
    assert "_writer_fact_section" not in generic_source
    public_source = inspect.getsource(generic_writer_module.render_generic_writer_prompt)
    assert "render_generic_writer_prompt_raw(context=context)" in public_source


def test_game_writer_does_not_fallback_to_unapproved_proposed_characters():
    story = StoryState(
        story_id="proposed-only",
        outline="登录后寻找失踪的引路人。",
        genre="网游",
        style="白描",
        characters=[
            CharacterState(
                name="未批准引路人",
                role="NPC",
                lifecycle_state="proposed",
            )
        ],
    )

    plan = {"character_moves": [{"name": "未批准引路人", "action": "带路"}]}
    context = WriterContext(
        story=story,
        chapter_number=1,
        plan=plan,
        style_guidance={},
        character_context=orchestrator_module._character_context_for_prompt(story, plan),
        dialogue_context={},
        chapter_seed={},
        skill_context={},
        include_genre_method=True,
        writer_plan_for_prompt=orchestrator_module._compact_writer_plan_for_prompt(plan),
        world_facts_for_prompt=[],
        trope_guidance=[],
        trope_contract_for_prompt={},
    )

    raw_context = game_writer_module._raw_game_character_context(context)

    assert raw_context["cards"] == []


def test_common_world_context_prioritizes_late_relevant_rules_and_entities():
    world_context = {
        "world_rules": [
            "晨钟响起后外门开放。",
            "藏书阁借阅需要令牌。",
            "药圃每日辰时浇水。",
            "执法堂不得私斗。",
            "山门夜间关闭。",
            "灵兽园禁止喧哗。",
            "炼器房按序领火。",
            "膳堂月底结账。",
            "传功殿每旬开课。",
            "后坡仓库夜间只认黑铁凭证。",
        ],
        "locations": [
            {"name": "山门", "description": "弟子出入之处。"},
            {"name": "膳堂", "description": "供应饭食。"},
            {"name": "药圃", "description": "种植灵药。"},
            {"name": "后坡仓库", "description": "黑铁凭证核验处。"},
        ],
        "factions": [{"name": "执法堂", "description": "维护宗门秩序。"}],
    }

    compacted = _compact_world_context_for_prompt(
        world_context,
        "本章前往后坡仓库，出示黑铁凭证。",
        max_rules=2,
    )

    assert compacted["rules"][0] == "后坡仓库夜间只认黑铁凭证。"
    assert compacted["entities"][0].startswith("后坡仓库：")


def test_game_writer_recognizes_protagonist_tier_when_role_is_stale():
    story = StoryState(
        story_id="stale-role-game-lead",
        outline="进入游戏完成第一次试炼。",
        genre="网游",
        style="白描",
        characters=[
            CharacterState(
                name="陈默",
                role="supporting",
                character_tier="protagonist",
                game_id="孤灯",
            )
        ],
    )

    prompt = StoryOrchestrator()._body_prompt(story, 1, {})

    assert "游戏ID为孤灯" in prompt
