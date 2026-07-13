from packages.story_core.prose_style_review import anti_ai_style_rules, sanitize_prose_style, review_prose_style


def test_anti_ai_style_rules_include_generation_and_revision_constraints():
    rules = anti_ai_style_rules()

    assert any("拒绝华丽辞藻堆砌" in rule for rule in rules)
    assert any("人物说话要完整自然" in rule for rule in rules)
    assert any("一章分3到4个叙事段落" in rule for rule in rules)
    assert any("动作 + 微表情 + 细微生理反应" in rule for rule in rules)
    assert any("番茄白话风" in rule for rule in rules)
    assert any("修辞配额" in rule for rule in rules)
    assert any("白描不是把句子全部切短" in rule for rule in rules)
    assert any("走到门口" in rule for rule in rules)


def test_prose_style_review_flags_ai_cliche_and_meta_explanation():
    body = (
        "霎时间，他心中一紧，脸色一变，眸光一凝。"
        "与此同时，爽点已经兑现，读者会明白这一段节奏的意义。"
        "他五味杂陈，不由得身形一闪，开始推进下一阶段剧情。"
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["cliche_terms"] < 8
    assert review["scores"]["meta_language"] < 8
    assert any("AI高频套话" in issue for issue in review["issues"])
    assert any("创作层术语" in issue for issue in review["issues"])
    assert any("动作、微表情和细微生理反应" in item for item in review["revision_plan"])


def test_prose_style_review_accepts_life_like_plain_prose():
    body = (
        "苏叶把鼠标推到一边，盯着屏幕右下角的余额看了两秒。"
        "风扇吱呀转着，吹不散屋里的泡面味。"
        "他没有急着点确认，只用指节敲了敲桌沿。"
        "交易行弹出手续费时，他才把那口气慢慢吐出来。"
    )

    review = review_prose_style(body)

    assert review["pass"]
    assert review["issues"] == []


def test_sanitize_prose_style_removes_safe_meta_language_without_changing_story_facts():
    body = "这一段爽点已经兑现，生成的节奏应该更快。夜烬看着交易行价格。"

    cleaned = sanitize_prose_style(body)

    assert "爽点" not in cleaned
    assert "生成" not in cleaned
    assert "节奏" not in cleaned
    assert "推进" in cleaned
    assert "夜烬" in cleaned


def test_sanitize_prose_style_replaces_stiff_threshold_wording():
    body = "夜烬没说阈值，只盯着柜台那条线。"

    cleaned = sanitize_prose_style(body)

    assert "阈值" not in cleaned
    assert "那条线" in cleaned


def test_prose_style_review_flags_mechanical_short_paragraph_texture():
    body = "\n\n".join(
        [
            "出租屋漏风。",
            "他看着账单。",
            "理由很直接。",
            "这意味着风险。",
            "不能全卖。",
            "也不能不卖。",
            "规则写得很清楚。",
            "数据异常。",
            "模型会报警。",
            "数字很干净。",
            "他继续操作。",
            "确认上架。",
            "提示音响起。",
            "风险也是。",
            "够了。",
            "他转身。",
            "夜风吹过。",
            "账本翻开。",
            "第一笔铜币落袋。",
            "风险还没散。",
        ]
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["mechanical_texture"] < 8
    assert any("机械切段" in issue for issue in review["issues"])


def test_prose_style_review_flags_stiff_backend_language():
    body = (
        "夜烬站在灰狼坡外，准备确认边界。"
        "这次验证规则很重要，能够看清服务节点的可见性和底层逻辑。"
        "他要先完成边界验证，再判断模型是否稳定。"
    )

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["plain_tomato_language"] < 8
    assert any("后台硬词" in issue for issue in review["issues"])


def test_prose_style_review_flags_unnatural_staff_shorthand():
    body = "夜烬修杖花了十八铜，又握杖退到墙边，杖尖抵着地面。裂纹杖芯还在背包里。"

    review = review_prose_style(body)

    assert not review["pass"]
    assert review["scores"]["game_term_precision"] < 8
    assert any("装备称呼不自然" in issue for issue in review["issues"])
