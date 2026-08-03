from packages.story_core.chapter_governance import build_chapter_governance
from packages.story_core.engine import ChapterBundle
from packages.story_core.models import ChapterSummary, CharacterState, StoryState
from packages.story_core.writing_packet import build_codex_writing_packet


def _web_game_story() -> StoryState:
    return StoryState(
        story_id="s-governance",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        characters=[
            CharacterState(
                name="苏叶",
                role="主角",
                game_id="夜烬",
                goals=["安全升到10级", "隐藏混沌之种"],
            )
        ],
        world_facts=["灰烬村是新手村，低级收益主要使用铜币。"],
        author_constraints=["现实姓名和游戏ID必须分层。"],
    )


def test_first_chapter_governance_separates_intent_context_and_rule_stack():
    story = _web_game_story()
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 灰烬村的登录者",
        body="",
        next_outline="第2章继续确认任务和补给成本。",
        updated_story=story,
    )

    governance = build_chapter_governance(story, bundle, chapter_number=1)

    assert governance["schema_version"] == "chapter-governance/v1"
    assert governance["chapter_intent"]["chapter_number"] == 1
    assert "现实压力" in "、".join(governance["chapter_intent"]["must_include"])
    assert "交易行" in "、".join(governance["chapter_intent"]["must_avoid"])
    assert governance["runtime_context"]["protagonist"]["real_name"] == "苏叶"
    assert governance["runtime_context"]["protagonist"]["game_id"] == "夜烬"
    assert any("怪物统一为灰狼" in item for item in governance["rule_stack"]["hard_facts"])
    assert "爽点" in "、".join(governance["rule_stack"]["diagnostic_only"])


def test_first_chapter_market_exchange_contract_overrides_generic_trade_bans():
    story = _web_game_story()
    story.world_facts.append("第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账。")
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 第一笔到账",
        body="",
        next_outline="完成交易行出售和官方兑换并付清急账。",
        updated_story=story,
        event_plan={"turn": "第一章卖出裂纹狼心，再走官方兑换渠道解决现实急账。"},
    )

    governance = build_chapter_governance(story, bundle, chapter_number=1)

    must_include = "、".join(governance["chapter_intent"]["must_include"])
    must_avoid = "、".join(governance["chapter_intent"]["must_avoid"])
    assert "交易行游戏币成交 -> 官方兑换 -> 现实账户到账 -> 处理急账" in must_include
    assert "交易行实际成交" not in must_avoid
    assert "到账/手续费结算" not in must_avoid

    packet = build_codex_writing_packet(story, bundle)
    packet_locks = "、".join(packet["hard_locks"])
    assert "第一章禁止实际寄售成交" not in packet_locks
    assert "已冻结游戏币的现有求购单" in packet_locks
    assert "独立官方兑换页面" in packet_locks
    assert "担保交易" not in str(packet)


def test_writing_packet_embeds_governance_without_mixing_diagnostic_terms_into_hard_locks():
    story = _web_game_story()
    bundle = ChapterBundle(
        chapter_number=1,
        chapter_title="第1章 灰烬村的登录者",
        body="",
        next_outline="第2章继续确认任务和补给成本。",
        updated_story=story,
    )

    packet = build_codex_writing_packet(story, bundle)

    assert "governance" in packet
    assert packet["governance"]["rule_stack"]["diagnostic_only"]
    assert not any("爽点" in item for item in packet["hard_locks"])
    assert any("爽点" in item for item in packet["governance"]["rule_stack"]["diagnostic_only"])


def test_later_chapter_governance_uses_latest_context_without_first_chapter_bans():
    story = _web_game_story()
    story.current_chapter = 2
    bundle = ChapterBundle(
        chapter_number=2,
        chapter_title="第2章 第一瓶小法力药",
        body="",
        next_outline="夜烬确认补给成本。",
        updated_story=story,
        event_plan={"next_focus": "确认补给成本和任务回报。"},
    )

    governance = build_chapter_governance(story, bundle, chapter_number=2)

    assert governance["chapter_intent"]["chapter_number"] == 2
    assert any("承接上一章" in item for item in governance["chapter_intent"]["must_include"])
    assert not any("第一章禁止" in item for item in governance["chapter_intent"]["must_avoid"])
    assert governance["runtime_context"]["next_focus"] == "确认补给成本和任务回报。"


def test_governance_previous_summary_never_reads_target_or_future_chapters():
    story = StoryState(
        story_id="s-governance-history",
        outline="林照看守断香炉。",
        genre="xianxia",
        style="白描",
        chapter_summaries=[
            ChapterSummary(chapter_number=1, summary="第一章摘要"),
            ChapterSummary(chapter_number=2, summary="第二章未来摘要"),
        ],
    )
    bundle = ChapterBundle(chapter_number=1, body="", next_outline="", updated_story=story)

    first = build_chapter_governance(story, bundle, chapter_number=1)
    second = build_chapter_governance(story, bundle, chapter_number=2)

    assert first["runtime_context"]["previous_summary"] == ""
    assert second["runtime_context"]["previous_summary"] == "第一章摘要"


def test_xianxia_first_chapter_governance_uses_genre_specific_opening_rules():
    story = StoryState(
        story_id="s-xianxia-governance",
        outline="林照被分去祖祠看守断香炉，第三块青砖下藏着旧木牌。",
        genre="修仙",
        style="白描",
        world_facts=["小说类型：xianxia", "世界前提：断香炉只给零碎反馈。"],
        author_constraints=["不要写网游面板、背包、铜币、掉落、任务牌或玩家生态。"],
    )
    bundle = ChapterBundle(
        chapter_number=1,
        body="",
        next_outline="林照发现旧木牌后被人盯上。",
        updated_story=story,
    )

    governance = build_chapter_governance(story, bundle, chapter_number=1)

    include_text = "、".join(governance["chapter_intent"]["must_include"])
    avoid_text = "、".join(governance["chapter_intent"]["must_avoid"])
    hard_text = "、".join(governance["rule_stack"]["hard_facts"])

    assert "外门处境" in include_text
    assert "题材核心物件" in include_text
    assert "只兑现一个小反馈" in include_text
    assert "一章顿悟大功法" in avoid_text
    assert "废丹房捡漏" in avoid_text
    assert "修仙题材" in hard_text
    assert "残缺机缘" in hard_text
    assert "见习冒险者" not in hard_text


def test_xianxia_later_chapter_ignores_stale_game_keywords() -> None:
    story = StoryState(
        story_id="s-xianxia-contaminated",
        outline="林修在雪山神殿修复残镜。",
        genre="修仙仙侠",
        genre_plugin_ids=["xianxia"],
        style="白描",
        current_chapter=141,
        characters=[CharacterState(name="林修", role="protagonist")],
        world_facts=["旧数据曾提到交易行、任务和NPC服务。"],
    )
    bundle = ChapterBundle(
        chapter_number=142,
        body="",
        next_outline="林修承受寒毒，继续重校残镜器纹。",
        updated_story=story,
    )

    governance = build_chapter_governance(story, bundle, chapter_number=142)

    include_text = "、".join(governance["chapter_intent"]["must_include"])
    hard_text = "、".join(governance["rule_stack"]["hard_facts"])
    soft_text = "、".join(governance["rule_stack"]["soft_guidance"])
    assert "境界、资源、伤势或人物关系" in include_text
    assert "面板/背包/任务" not in include_text
    assert "修仙题材" in hard_text
    assert "苏叶" not in hard_text
    assert "夜烬" not in hard_text
    assert "game_panel" not in governance["runtime_context"]["protagonist"]
    assert "等级、经验、货币、背包" not in soft_text
    assert "术法、法宝、境界、伤势" in soft_text
    generated_rules = "、".join(
        [
            *governance["chapter_intent"]["must_avoid"],
            *governance["rule_stack"]["hard_facts"],
        ]
    )
    for term in ("网游", "面板", "背包", "掉落", "交易行", "铜币"):
        assert term not in generated_rules
