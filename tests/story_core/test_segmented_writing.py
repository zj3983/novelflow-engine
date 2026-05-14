from packages.story_core.segmented_writing import (
    _compact_context,
    build_segment_prompt,
    build_segment_revision_prompt,
    build_segment_specs,
    merge_segment_outputs,
    review_segment_output,
)


def test_compact_context_respects_limit():
    text = "a" * 200

    compact = _compact_context(text, 45)

    assert len(compact) <= 45
    assert " ... " in compact


def test_first_chapter_segments_keep_opening_scope():
    specs = build_segment_specs(1, {"event_plan": {"chapter_title": "灰烬村的登录"}})

    assert [spec.key for spec in specs] == ["entry_login", "small_verification", "decision_hook"]
    assert "现实压力" in specs[0].title
    assert "职业" in specs[0].required_surface
    assert "夜烬建号完成" in specs[0].exit_state
    assert specs[0].title == "现实压力与登录建号"
    assert specs[1].title == "低级怪小验证"
    assert specs[2].title == "先不卖，留个问题"
    assert "小规模验证结束" in specs[1].exit_state
    assert "材料先收住" in specs[2].goal
    assert "确认边界" not in " ".join(spec.goal for spec in specs)
    assert "验边界" not in " ".join(spec.title for spec in specs)
    assert "材料处理成钱" in specs[0].forbidden_surface
    assert "玩家势力追查" in specs[1].forbidden_surface
    assert "寄售" not in " ".join(spec.forbidden_surface for spec in specs)
    assert "完整NPC服务戏" in specs[2].forbidden_surface


def test_segment_review_flags_only_local_first_chapter_overreach():
    specs = build_segment_specs(1, {})
    bad_text = "夜烬把毒腺挂到交易行，寄售成功后，白袍公会马上追查坐标。"

    review = review_segment_output(specs[1], bad_text, chapter_number=1)

    assert not review["pass"]
    assert any("本段提前写出第一章禁用内容" in issue for issue in review["issues"])
    assert any("只改这一段" in item for item in review["revision_plan"])


def test_segment_review_flags_underfilled_segment_before_merge():
    specs = build_segment_specs(1, {})
    short_text = "苏叶看着催租单，戴上旧头盔，登录《天启之门》。"

    review = review_segment_output(specs[0], short_text, chapter_number=1)

    assert not review["pass"]
    assert any("当前片段偏短" in issue for issue in review["issues"])


def test_segment_review_requires_exit_state_transition():
    specs = build_segment_specs(1, {})
    text = "夜烬在灰狼坡挥出火球，灰狼倒下，地上闪过掉落提示。"

    review = review_segment_output(specs[1], text, chapter_number=1)

    assert not review["pass"]
    assert any("出场状态" in issue for issue in review["issues"])
    assert any("资源变化" in item or "背包" in item for item in review["revision_plan"])


def test_segment_revision_prompt_limits_rewrite_scope():
    specs = build_segment_specs(1, {})
    prompt = build_segment_revision_prompt(
        specs[1],
        "夜烬心中一紧，开始解释规则。",
        {"issues": ["AI腔明显"], "revision_plan": ["用动作和对话替换解释腔"]},
        previous_segments=["苏叶看着催租单。"],
        next_segments=["灰狼倒下。"],
    )

    assert "只重写当前段" in prompt
    assert "不要重写上一段" in prompt
    assert "入场状态" in prompt
    assert "出场状态" in prompt
    assert "交接约束" in prompt
    assert "苏叶看着催租单。" in prompt
    assert "灰狼倒下。" in prompt


def test_segment_prompt_includes_governance_boundaries():
    specs = build_segment_specs(1, {})
    prompt = build_segment_prompt(
        chapter_number=1,
        spec=specs[0],
        plan={
            "governance": {
                "chapter_intent": {
                    "must_include": ["现实压力", "角色面板"],
                    "must_avoid": ["交易行实际成交", "公会正面追查"],
                },
                "rule_stack": {
                    "hard_facts": ["怪物统一为灰鼠，不要写成狼或其他怪。"],
                    "diagnostic_only": ["爽点、节奏只用于诊断，禁止进入正文。"],
                },
            }
        },
    )

    assert "分段输入治理" in prompt
    assert "入场状态" in prompt
    assert "出场状态" in prompt
    assert "交接约束" in prompt
    assert "交易行实际成交" in prompt
    assert "怪物统一为灰鼠" in prompt
    assert "诊断词禁止入正文" in prompt


def test_segment_revision_prompt_includes_governance_boundaries():
    specs = build_segment_specs(1, {})
    prompt = build_segment_revision_prompt(
        specs[0],
        "代价很小，但代价存在。",
        {"issues": ["解释腔"], "revision_plan": ["换成动作"]},
        governance={
            "chapter_intent": {"must_avoid": ["交易行实际成交"]},
            "rule_stack": {
                "hard_facts": ["怪物统一为灰鼠，不要写成狼。"],
                "diagnostic_only": ["爽点只用于诊断，禁止进入正文。"],
            },
        },
    )

    assert "分段输入治理" in prompt
    assert "表达权不等于事实权" in prompt
    assert "交易行实际成交" in prompt
    assert "诊断词禁止入正文" in prompt


def test_segment_review_exposes_ai_flavor_review():
    specs = build_segment_specs(1, {})
    text = "他不是为了多拿一点，而是为了确认这件事是否成立。这不是选择，而是边界验证。"

    review = review_segment_output(specs[1], text, chapter_number=1)

    assert "ai_flavor_review" in review
    assert review["ai_flavor_review"]["scores"]["ai_flavor"] < 8
    assert review["ai_flavor_review"]["metrics"]["formula_count"] >= 1


def test_merge_segment_outputs_strips_segment_labels():
    merged = merge_segment_outputs(
        [
            "【setup】\n苏叶看着催租单。",
            "### trigger\n他登录游戏，角色名夜烬。",
            "灰狼扑上来。",
        ]
    )

    assert "setup" not in merged
    assert "trigger" not in merged
    assert merged.index("苏叶") < merged.index("夜烬") < merged.index("灰狼")
