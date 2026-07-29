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

    assert [spec.key for spec in specs] == ["opening", "pressure", "choice", "hook"]
    assert all(spec.goal for spec in specs)
    assert all(spec.entry_state for spec in specs)
    assert all(spec.exit_state for spec in specs)
    assert sum(spec.target_chars for spec in specs) >= 4200
    surface = " ".join(
        [
            *(spec.title for spec in specs),
            *(spec.goal for spec in specs),
            *(spec.required_surface for spec in specs),
        ]
    )
    assert "夜烬" not in surface
    assert "灰狼" not in surface
    assert "千倍爆率" not in surface


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
    assert "对话要完整" in prompt


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

    assert "本段事实边界" in prompt
    assert "入场状态" in prompt
    assert "出场状态" in prompt
    assert "交接约束" in prompt
    assert "交易行实际成交" in prompt
    assert "怪物统一为灰鼠" in prompt
    assert "诊断词禁止入正文" not in prompt
    assert "diagnostic_only" not in prompt


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

    assert "本段事实边界" in prompt
    assert "交易行实际成交" in prompt
    assert "诊断词禁止入正文" not in prompt
    assert "diagnostic_only" not in prompt


def test_segment_review_exposes_ai_flavor_review():
    specs = build_segment_specs(1, {})
    text = "他不是为了多拿一点，而是为了确认这件事是否成立。这不是选择，而是边界验证。"

    review = review_segment_output(specs[1], text, chapter_number=1)

    assert "ai_flavor_review" in review
    assert review["ai_flavor_review"]["scores"]["ai_flavor"] < 8
    assert review["ai_flavor_review"]["metrics"]["formula_count"] >= 1


def test_segment_review_exposes_patchwork_reader_feel():
    specs = build_segment_specs(1, {})
    text = (
        "旁人只看见他没交任务、没领铜币，也没往柜台递东西。"
        "夜烬收起法杖，绕到队伍后面。"
        "旁人只看见他没有交任务、没有领铜币，也没有往柜台递东西。"
    )

    review = review_segment_output(specs[1], text, chapter_number=1)

    assert "reader_feel_review" in review
    assert review["reader_feel_review"]["scores"]["patchwork"] <= 5


def test_segment_review_marks_command_style_dialogue_as_hard_issue():
    specs = build_segment_specs(1, {})
    text = "赵管事：先试，不深入。夜烬：先报我，别乱拆。"

    review = review_segment_output(specs[1], text, chapter_number=1)
    critical = review["critical_review"] if isinstance(review.get("critical_review"), dict) else {}

    assert "pass" in review
    assert any("对话口令化明显" in item for item in critical.get("hard_issues", []))
    assert review["revision_plan"]


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
