"""Numeric, data-driven genre configuration.

This complements the textual ``GenrePlugin`` rulebooks (in ``genre_plugins.py``)
by encoding **concrete thresholds and preferences** that reviewers, writers and
the director can read directly. Inspired by lingfengQAQ/webnovel-writer's
``references/genre-profiles.md`` (v5.5).

Where ``GenrePlugin`` answers "what does this genre value", ``GenreProfile``
answers "what numbers does this genre run on":

  * Hook preferences and baseline strength
  * Coolpoint density and combo intervals
  * Micropayoff floor per chapter
  * Pacing red lines (stagnation, strand gaps, transition runs)
  * Override permissions (which soft constraints can a particular genre skip)
  * System-tag density cap (chapters in pure dialogue genres can't tolerate
    the same ``【系统提示】`` budget as a webgame chapter does)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from packages.story_core.genre_plugins import (
    GAME_WEBNOVEL,
    GENERIC_WEBNOVEL,
    PLUGIN_REGISTRY,
    ROMANCE,
    RULES_MYSTERY,
    SUSPENSE,
    URBAN,
    XIANXIA,
    GenrePlugin,
    select_genre_plugins,
)


# ---------------------------------------------------------------------------
# Sub-configs (frozen so caller can rely on identity / hashing)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class GenreHookConfig:
    """How chapter-end hooks should behave for this genre."""

    preferred_types: tuple[str, ...]
    """Hook types in priority order. Vocabulary: 危机钩 / 悬念钩 / 渴望钩 /
    情绪钩 / 选择钩 (per Reading Power Taxonomy)."""

    strength_baseline: str
    """Default chapter-end hook strength. One of {"strong", "medium", "weak"}."""

    chapter_end_required: bool
    """Whether each non-transition chapter MUST end on a hook."""

    transition_allowance: int
    """Maximum consecutive transition chapters allowed before a hook becomes
    mandatory."""


@dataclass(frozen=True)
class GenreCoolpointConfig:
    """How often readers expect a payoff/face-slap/win in this genre."""

    preferred_patterns: tuple[str, ...]
    density_per_chapter: str  # "high" (2+) | "medium" (1) | "low" (0-1)
    combo_interval: int       # Recommended chapters between combo-style payoffs
    milestone_interval: int   # Recommended chapters between major milestones


@dataclass(frozen=True)
class GenreMicropayoffConfig:
    """How many small wins per chapter keep readers reading."""

    preferred_types: tuple[str, ...]
    min_per_chapter: int
    transition_min: int


@dataclass(frozen=True)
class GenrePacingConfig:
    """Hard red lines for narrative stagnation and strand neglect."""

    stagnation_threshold: int       # consecutive no-progress chapters → HARD-003
    strand_quest_max: int           # max consecutive chapters on quest strand only
    strand_emotion_gap_max: int     # max chapters skipping the emotion strand
    transition_max_consecutive: int # max consecutive transition chapters


@dataclass(frozen=True)
class GenreOverrideConfig:
    """Which soft constraints this genre routinely tolerates."""

    overridable_softs: tuple[str, ...] = ()


@dataclass(frozen=True)
class GenreProsodyConfig:
    """Genre-specific prose density caps used by reviewers.

    Webgame chapters can carry ~6 ``【系统提示】`` tags before they feel like
    spam; a romance chapter of the same length tolerates exactly 1. Same logic
    applies to the metaphor cap and the judgment-crutch cap, which we leave at
    universal defaults for now but expose here so individual genres can lift or
    tighten them later without touching reviewer code.
    """

    system_tag_max: int = 4
    metaphor_max_per_chapter: int = 3
    judgment_crutch_max_per_chapter: int = 2


@dataclass(frozen=True)
class GenreProfile:
    profile_id: str
    name: str
    description: str
    tags: tuple[str, ...]
    hook: GenreHookConfig
    coolpoint: GenreCoolpointConfig
    micropayoff: GenreMicropayoffConfig
    pacing: GenrePacingConfig
    override: GenreOverrideConfig = field(default_factory=GenreOverrideConfig)
    prosody: GenreProsodyConfig = field(default_factory=GenreProsodyConfig)


# ---------------------------------------------------------------------------
# Concrete profiles (one per existing GenrePlugin)
# ---------------------------------------------------------------------------


GENERIC_PROFILE = GenreProfile(
    profile_id="generic_webnovel",
    name="通用网文",
    description="基础默认档案；适用于尚未识别题材的项目。",
    tags=("webnovel",),
    hook=GenreHookConfig(
        preferred_types=("悬念钩", "危机钩", "渴望钩"),
        strength_baseline="medium",
        chapter_end_required=True,
        transition_allowance=1,
    ),
    coolpoint=GenreCoolpointConfig(
        preferred_patterns=("反转", "兑现", "情绪爆发"),
        density_per_chapter="medium",
        combo_interval=10,
        milestone_interval=25,
    ),
    micropayoff=GenreMicropayoffConfig(
        preferred_types=("关系变化", "新线索", "立场反转", "认知变化"),
        min_per_chapter=1,
        transition_min=0,
    ),
    pacing=GenrePacingConfig(
        stagnation_threshold=4,
        strand_quest_max=6,
        strand_emotion_gap_max=10,
        transition_max_consecutive=2,
    ),
)


GAME_PROFILE = GenreProfile(
    profile_id="game_webnovel",
    name="网游升级流",
    description="数值、等级、面板、交易行驱动的爽感型网游。",
    tags=("game", "level-up", "panel"),
    hook=GenreHookConfig(
        preferred_types=("危机钩", "渴望钩", "悬念钩"),
        strength_baseline="medium",
        chapter_end_required=True,
        transition_allowance=1,
    ),
    coolpoint=GenreCoolpointConfig(
        preferred_patterns=("升级", "打脸", "稀有掉落", "拆台"),
        density_per_chapter="medium",
        combo_interval=8,
        milestone_interval=20,
    ),
    micropayoff=GenreMicropayoffConfig(
        preferred_types=("数字反馈", "面板更新", "稀有掉落", "任务推进"),
        min_per_chapter=1,
        transition_min=0,
    ),
    pacing=GenrePacingConfig(
        stagnation_threshold=3,
        strand_quest_max=5,
        strand_emotion_gap_max=20,
        transition_max_consecutive=2,
    ),
    override=GenreOverrideConfig(overridable_softs=("metaphor_density", "judgment_crutch")),
    prosody=GenreProsodyConfig(
        system_tag_max=6,
        metaphor_max_per_chapter=3,
        judgment_crutch_max_per_chapter=2,
    ),
)


XIANXIA_PROFILE = GenreProfile(
    profile_id="xianxia",
    name="修仙玄幻",
    description="境界、资源、宗门、因果驱动的越阶爽感型玄幻。",
    tags=("xianxia", "cultivation"),
    hook=GenreHookConfig(
        preferred_types=("危机钩", "渴望钩", "选择钩"),
        strength_baseline="strong",
        chapter_end_required=True,
        transition_allowance=1,
    ),
    coolpoint=GenreCoolpointConfig(
        preferred_patterns=("越阶打脸", "境界突破", "夺资源", "因果反扑"),
        density_per_chapter="high",
        combo_interval=5,
        milestone_interval=15,
    ),
    micropayoff=GenreMicropayoffConfig(
        preferred_types=("灵力/境界变化", "感悟", "资源入手", "宗门反应"),
        min_per_chapter=2,
        transition_min=1,
    ),
    pacing=GenrePacingConfig(
        stagnation_threshold=2,
        strand_quest_max=4,
        strand_emotion_gap_max=15,
        transition_max_consecutive=1,
    ),
    prosody=GenreProsodyConfig(
        system_tag_max=2,
        metaphor_max_per_chapter=4,  # 修仙允许更多比喻 (剑光如虹 / 灵气如潮)
        judgment_crutch_max_per_chapter=2,
    ),
)


URBAN_PROFILE = GenreProfile(
    profile_id="urban",
    name="都市现代",
    description="商业、职场、舆论、人际博弈驱动的都市爽感型。",
    tags=("urban", "modern"),
    hook=GenreHookConfig(
        preferred_types=("渴望钩", "危机钩", "选择钩"),
        strength_baseline="medium",
        chapter_end_required=True,
        transition_allowance=2,
    ),
    coolpoint=GenreCoolpointConfig(
        preferred_patterns=("打脸", "翻盘", "身份反差", "资源逆转"),
        density_per_chapter="medium",
        combo_interval=7,
        milestone_interval=18,
    ),
    micropayoff=GenreMicropayoffConfig(
        preferred_types=("合同/资金", "人际反应", "舆论变化", "情报差兑现"),
        min_per_chapter=1,
        transition_min=0,
    ),
    pacing=GenrePacingConfig(
        stagnation_threshold=3,
        strand_quest_max=5,
        strand_emotion_gap_max=8,
        transition_max_consecutive=2,
    ),
    prosody=GenreProsodyConfig(system_tag_max=2),
)


ROMANCE_PROFILE = GenreProfile(
    profile_id="romance",
    name="言情关系流",
    description="情绪、关系、误会、靠近驱动的女频/言情类。",
    tags=("romance", "female-focused"),
    hook=GenreHookConfig(
        preferred_types=("情绪钩", "选择钩", "悬念钩"),
        strength_baseline="medium",
        chapter_end_required=True,
        transition_allowance=2,
    ),
    coolpoint=GenreCoolpointConfig(
        preferred_patterns=("靠近", "误会化解", "保护", "甜蜜兑现", "吃醋"),
        density_per_chapter="medium",
        combo_interval=6,
        milestone_interval=12,
    ),
    micropayoff=GenreMicropayoffConfig(
        preferred_types=("称呼变化", "肢体距离", "情绪外露", "关心兑现"),
        min_per_chapter=1,
        transition_min=1,
    ),
    pacing=GenrePacingConfig(
        # 言情允许情感线慢，但感情线不能断档过久
        stagnation_threshold=5,
        strand_quest_max=3,
        strand_emotion_gap_max=2,
        transition_max_consecutive=2,
    ),
    override=GenreOverrideConfig(overridable_softs=("paragraph_form",)),
    prosody=GenreProsodyConfig(
        system_tag_max=1,
        metaphor_max_per_chapter=5,  # 言情允许更多比喻
        judgment_crutch_max_per_chapter=2,
    ),
)


SUSPENSE_PROFILE = GenreProfile(
    profile_id="suspense",
    name="悬疑推理",
    description="线索、证据链、嫌疑、反转驱动的悬疑/推理。",
    tags=("suspense", "mystery"),
    hook=GenreHookConfig(
        preferred_types=("悬念钩", "选择钩", "危机钩"),
        strength_baseline="strong",
        chapter_end_required=True,
        transition_allowance=1,
    ),
    coolpoint=GenreCoolpointConfig(
        preferred_patterns=("反转", "破案", "证据链兑现", "嫌疑翻转"),
        density_per_chapter="medium",
        combo_interval=8,
        milestone_interval=15,
    ),
    micropayoff=GenreMicropayoffConfig(
        preferred_types=("新线索", "嫌疑变更", "时间线钉死", "证据补全"),
        min_per_chapter=2,
        transition_min=1,
    ),
    pacing=GenrePacingConfig(
        stagnation_threshold=2,
        strand_quest_max=4,
        strand_emotion_gap_max=12,
        transition_max_consecutive=1,
    ),
    prosody=GenreProsodyConfig(system_tag_max=1),
)


RULES_MYSTERY_PROFILE = GenreProfile(
    profile_id="rules_mystery",
    name="规则怪谈",
    description="规则验证、禁忌代价、污染递进驱动的规则怪谈。",
    tags=("rules-mystery", "horror"),
    hook=GenreHookConfig(
        preferred_types=("危机钩", "悬念钩", "选择钩"),
        strength_baseline="strong",
        chapter_end_required=True,
        transition_allowance=0,
    ),
    coolpoint=GenreCoolpointConfig(
        preferred_patterns=("规则破解", "禁忌兑现", "反规则反转", "污染回弹"),
        density_per_chapter="high",
        combo_interval=5,
        milestone_interval=12,
    ),
    micropayoff=GenreMicropayoffConfig(
        preferred_types=("新规则", "规则代价", "规则漏洞", "异常实体出现"),
        min_per_chapter=2,
        transition_min=1,
    ),
    pacing=GenrePacingConfig(
        stagnation_threshold=2,
        strand_quest_max=3,
        strand_emotion_gap_max=20,
        transition_max_consecutive=0,
    ),
    prosody=GenreProsodyConfig(
        # 规则文本本身就是【】格式的内容，需要更多预算
        system_tag_max=8,
        metaphor_max_per_chapter=2,
        judgment_crutch_max_per_chapter=2,
    ),
)


# Registry indexed by profile_id (matches GenrePlugin.plugin_id 1-1).
PROFILE_REGISTRY: dict[str, GenreProfile] = {
    profile.profile_id: profile
    for profile in (
        GENERIC_PROFILE,
        GAME_PROFILE,
        XIANXIA_PROFILE,
        URBAN_PROFILE,
        ROMANCE_PROFILE,
        SUSPENSE_PROFILE,
        RULES_MYSTERY_PROFILE,
    )
}

# Map plugin → profile so ``select_genre_plugins`` can be reused as the source
# of truth for genre detection.
_PLUGIN_TO_PROFILE: dict[str, GenreProfile] = {
    plugin.plugin_id: PROFILE_REGISTRY[plugin.plugin_id]
    for plugin in PLUGIN_REGISTRY
    if plugin.plugin_id in PROFILE_REGISTRY
}


# ---------------------------------------------------------------------------
# Public selectors
# ---------------------------------------------------------------------------


def select_genre_profile(project: Any) -> GenreProfile:
    """Return the most-specific genre profile for a project.

    Reuses ``select_genre_plugins`` for keyword detection so plugin and profile
    selection always agree. The first non-generic plugin wins; falls back to
    ``GENERIC_PROFILE``.
    """
    plugins = select_genre_plugins(project, max_plugins=2, min_score=2)
    for plugin in plugins:
        if plugin.plugin_id == "generic_webnovel":
            continue
        profile = _PLUGIN_TO_PROFILE.get(plugin.plugin_id)
        if profile is not None:
            return profile
    return GENERIC_PROFILE


def genre_profile_for_text(text: str) -> GenreProfile:
    """Resolve a profile from a raw text blob (story outline / world facts).

    Useful when the caller has a ``StoryState`` rather than a ``NovelProject``.
    """
    if not text:
        return GENERIC_PROFILE
    for profile in PROFILE_REGISTRY.values():
        if profile.profile_id == "generic_webnovel":
            continue
        plugin: GenrePlugin | None = next(
            (p for p in PLUGIN_REGISTRY if p.plugin_id == profile.profile_id),
            None,
        )
        if plugin is None:
            continue
        if sum(1 for kw in plugin.keywords if kw and kw in text) >= 2:
            return profile
    return GENERIC_PROFILE


def genre_profile_summary(profile: GenreProfile) -> dict[str, Any]:
    """Compact dict suitable for dropping into a writer-prompt JSON packet.

    Only the fields the writer or director needs to act on are included; the
    full dataclass would bloat the prompt without adding instruction signal.
    """
    return {
        "profile_id": profile.profile_id,
        "name": profile.name,
        "hook": {
            "preferred_types": list(profile.hook.preferred_types),
            "strength_baseline": profile.hook.strength_baseline,
            "chapter_end_required": profile.hook.chapter_end_required,
        },
        "coolpoint": {
            "preferred_patterns": list(profile.coolpoint.preferred_patterns),
            "density_per_chapter": profile.coolpoint.density_per_chapter,
            "combo_interval": profile.coolpoint.combo_interval,
        },
        "micropayoff": {
            "preferred_types": list(profile.micropayoff.preferred_types),
            "min_per_chapter": profile.micropayoff.min_per_chapter,
        },
        "pacing": {
            "stagnation_threshold": profile.pacing.stagnation_threshold,
            "strand_quest_max": profile.pacing.strand_quest_max,
            "strand_emotion_gap_max": profile.pacing.strand_emotion_gap_max,
            "transition_max_consecutive": profile.pacing.transition_max_consecutive,
        },
        "prosody_caps": {
            "system_tag_max": profile.prosody.system_tag_max,
            "metaphor_max_per_chapter": profile.prosody.metaphor_max_per_chapter,
            "judgment_crutch_max_per_chapter": profile.prosody.judgment_crutch_max_per_chapter,
        },
    }
