from packages.story_core.genre_profile import (
    GAME_PROFILE,
    GENERIC_PROFILE,
    PROFILE_REGISTRY,
    ROMANCE_PROFILE,
    RULES_MYSTERY_PROFILE,
    SUSPENSE_PROFILE,
    XIANXIA_PROFILE,
    GenreProfile,
    genre_profile_for_text,
    genre_profile_summary,
    select_genre_profile,
)
from packages.story_core.models import NovelProject
from packages.story_core.prose_rule_review import review_critical_prose_rules


# ---------------------------------------------------------------------------
# Profile registry sanity
# ---------------------------------------------------------------------------


def test_every_plugin_has_a_matching_profile():
    expected_ids = {
        "generic_webnovel",
        "game_webnovel",
        "xianxia",
        "urban",
        "romance",
        "suspense",
        "rules_mystery",
    }
    assert expected_ids <= set(PROFILE_REGISTRY.keys())


def test_profiles_are_distinct_not_clones():
    # Romance must prefer 情绪钩 above 危机钩;
    # game must prefer 危机钩 / 渴望钩 above 情绪钩.
    assert ROMANCE_PROFILE.hook.preferred_types[0] == "情绪钩"
    assert "情绪钩" not in GAME_PROFILE.hook.preferred_types[:1]
    # System tag budget differs by genre — webgame has 6, romance has 1.
    assert GAME_PROFILE.prosody.system_tag_max == 6
    assert ROMANCE_PROFILE.prosody.system_tag_max == 1
    # 修仙 allows more metaphor than universal default; webgame stays at 3.
    assert XIANXIA_PROFILE.prosody.metaphor_max_per_chapter > 3
    assert GAME_PROFILE.prosody.metaphor_max_per_chapter == 3
    # 规则怪谈 carries rule-text panels — system_tag budget must be high.
    assert RULES_MYSTERY_PROFILE.prosody.system_tag_max >= 6


# ---------------------------------------------------------------------------
# Selectors
# ---------------------------------------------------------------------------


def _make_project(*, title: str = "T", outline: str = "", world_summary: str = "") -> NovelProject:
    return NovelProject(
        project_id="p-test",
        title=title,
        seed_outline=outline,
        world_summary=world_summary,
        current_focus="",
        author_constraints=[],
    )


def test_select_genre_profile_picks_game_for_game_outline():
    project = _make_project(
        title="网游开服",
        outline="苏叶以夜烬身份登录VRMMO，验证千倍爆率，研究交易行批次和铜币流水。",
    )
    profile = select_genre_profile(project)
    assert profile.profile_id == "game_webnovel"


def test_select_genre_profile_picks_romance_for_romance_outline():
    project = _make_project(
        title="替身新娘",
        outline="豪门总裁与替身的甜宠虐恋，宫斗误会和家族婚约层层叠加。",
    )
    profile = select_genre_profile(project)
    assert profile.profile_id == "romance"


def test_select_genre_profile_picks_suspense_for_mystery_outline():
    project = _make_project(
        title="第七案",
        outline="侦探调查连环案件，嫌疑人和诡计交织，线索不断反转。",
    )
    profile = select_genre_profile(project)
    assert profile.profile_id == "suspense"


def test_select_genre_profile_falls_back_to_generic():
    project = _make_project(title="一段平淡的故事", outline="主角在小镇上度过几个晴朗的下午。")
    profile = select_genre_profile(project)
    assert profile.profile_id == "generic_webnovel"


def test_genre_profile_for_text_resolves_from_blob():
    text = "这是一个修仙玄幻故事。主角灵根资质中等，依赖宗门资源和法宝突破境界。"
    profile = genre_profile_for_text(text)
    assert profile.profile_id == "xianxia"


def test_genre_profile_for_text_empty_input_is_generic():
    assert genre_profile_for_text("").profile_id == "generic_webnovel"


# ---------------------------------------------------------------------------
# Summary shape
# ---------------------------------------------------------------------------


def test_genre_profile_summary_keeps_only_actionable_fields():
    summary = genre_profile_summary(GAME_PROFILE)
    assert summary["profile_id"] == "game_webnovel"
    # Hook / coolpoint / micropayoff / pacing / prosody_caps must each appear
    assert {"hook", "coolpoint", "micropayoff", "pacing", "prosody_caps"} <= set(summary)
    # Numeric thresholds preserved
    assert summary["pacing"]["stagnation_threshold"] == GAME_PROFILE.pacing.stagnation_threshold
    assert summary["prosody_caps"]["system_tag_max"] == 6


# ---------------------------------------------------------------------------
# Reviewer integration: prosody caps actually gate
# ---------------------------------------------------------------------------


def test_review_uses_genre_specific_system_tag_cap():
    # Build a body with exactly 5 system tags. Default cap is 4 → fails.
    # Game profile cap is 6 → passes. Romance cap is 1 → fails harder.
    body = "他走到柜台前。\n\n" + "\n\n".join(
        f"【系统提示：获得材料×{i}】" for i in range(5)
    )

    default_review = review_critical_prose_rules(body)
    game_review = review_critical_prose_rules(
        body,
        prosody_caps={
            "system_tag_max": GAME_PROFILE.prosody.system_tag_max,
            "metaphor_max_per_chapter": GAME_PROFILE.prosody.metaphor_max_per_chapter,
            "judgment_crutch_max_per_chapter": GAME_PROFILE.prosody.judgment_crutch_max_per_chapter,
        },
    )
    romance_review = review_critical_prose_rules(
        body,
        prosody_caps={
            "system_tag_max": ROMANCE_PROFILE.prosody.system_tag_max,
            "metaphor_max_per_chapter": ROMANCE_PROFILE.prosody.metaphor_max_per_chapter,
            "judgment_crutch_max_per_chapter": ROMANCE_PROFILE.prosody.judgment_crutch_max_per_chapter,
        },
    )

    # Default 4-cap → 5 tags trip system_tag_density (HARD).
    assert default_review["scores"].get("system_tag_density") == 5
    # Game 6-cap → 5 tags pass.
    assert game_review["scores"].get("system_tag_density") == 8
    # Romance 1-cap → 5 tags trip.
    assert romance_review["scores"].get("system_tag_density") == 5


def test_review_uses_genre_specific_metaphor_cap():
    # Build a body with exactly 4 metaphors. Default cap 3 → fails;
    # 修仙 cap 4 → passes; romance cap 5 → passes.
    body = (
        "他停在门口，"
        "像影子贴住墙，"
        "像风停了一秒，"
        "像水面收住光，"
        "像不肯出口的话。"
    )

    default_review = review_critical_prose_rules(body)
    xianxia_review = review_critical_prose_rules(
        body,
        prosody_caps={
            "metaphor_max_per_chapter": XIANXIA_PROFILE.prosody.metaphor_max_per_chapter,
        },
    )

    assert default_review["scores"].get("metaphor_density") == 5
    # 修仙 cap >= 4 → 4 metaphors don't trip.
    assert xianxia_review["scores"].get("metaphor_density") == 8
