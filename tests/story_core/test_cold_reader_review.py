from packages.story_core.cold_reader_review import review_cold_reader_experience


def test_cold_reader_review_passes_clear_payoff_and_hook():
    body = (
        "苏叶关掉催租短信，登录游戏。\n"
        "夜烬杀掉第五只灰狼时，地上多出一枚灰色晶核。\n"
        "背包提示跳了一下：稀有材料，未鉴定。\n"
        "他没有卖，先收进背包。\n"
        "村口木牌上写着：散人材料收购，今晚只开一小时。\n"
        "手机又震了一下，房租倒计时还剩二十三小时。"
    )

    review = review_cold_reader_experience(body)

    assert review["reviewer"] == "cold_reader/v1"
    assert review["pass"] is True
    assert review["scores"]["page_turn"] >= 4
    assert not review["issues"]


def test_cold_reader_review_flags_missing_hook_and_low_reason_to_care():
    body = (
        "夜烬打开面板。\n"
        "他刷了五只灰狼。\n"
        "背包里多了几份材料。\n"
        "第一笔账还没赚到。\n"
        "成本已经先到了。"
    )

    review = review_cold_reader_experience(body)

    assert review["pass"] is False
    assert review["scores"]["page_turn"] <= 2
    assert any(issue["type"] == "missing_specific_hook" for issue in review["issues"])
    assert any(issue["type"] == "weak_why_care" for issue in review["issues"])


def test_cold_reader_review_flags_cognitive_overload():
    body = (
        "混沌之种、底层协议、灰烬王庭、星门议会、灵魂链路、七阶职业、"
        "天启拍卖行、白塔公会、神格碎片、深渊税则同时浮出。"
    )

    review = review_cold_reader_experience(body)

    assert review["pass"] is False
    assert review["scores"]["cognitive_load"] <= 2
    assert any(issue["type"] == "cognitive_overload" for issue in review["issues"])
