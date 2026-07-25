from packages.story_core.web_game_author_craft import build_web_game_director_card, plain_writer_phrase


def test_plain_writer_phrase_preserves_valid_trade_language():
    text = "灰狼坡的第一笔到账；通过担保平台完成交割；材料成交后落到账本。"

    result = plain_writer_phrase(text)

    assert result == text
    assert "完交易完成割" not in result
    assert "收到反馈本" not in result


def test_plain_writer_phrase_translates_backend_server_and_quest_terms():
    text = "采用全球同服、分区承载架构，由区域分片维持并发运行；完成清道夫委托后登记巡查资格。"

    result = plain_writer_phrase(text)

    assert "区域分片" not in result
    assert "承载架构" not in result
    assert "登记巡查资格" not in result
    assert "分线" in result
    assert "可以接后坡巡查任务" in result


def test_trade_authorized_director_card_does_not_ban_trade_payoff():
    card = build_web_game_director_card(
        chapter_number=1,
        event_plan={"turn": "第一章必须通过裂纹狼心担保交易解决现实急账。"},
    )

    assert "成交" not in card["boundary_chapter_bans"]
    assert "到账" not in card["boundary_chapter_bans"]
