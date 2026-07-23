from packages.story_core.game_level_gap import assess_level_gap, extract_level_gap_case, level_gap_rule_text


def test_two_level_gap_is_a_normal_challenge():
    result = assess_level_gap(player_level=5, monster_level=7, evidence_text="")

    assert result.allowed is True
    assert result.requires_special_reason is False


def test_three_level_gap_rejects_skill_claims_without_special_reason():
    result = assess_level_gap(
        player_level=5,
        monster_level=8,
        evidence_text="他靠走位和计算单杀精英怪，打完法力耗尽。",
    )

    assert result.allowed is False
    assert result.requires_special_reason is True
    assert result.reason_codes == ()


def test_three_level_gap_requires_visible_cost_with_special_reason():
    result = assess_level_gap(
        player_level=5,
        monster_level=8,
        evidence_text="任务道具先压制了精英怪，夜烬和三名队友合力击杀。",
    )

    assert result.allowed is False
    assert result.reason_codes == ("party", "quest_item")
    assert result.has_visible_cost is False


def test_three_level_gap_accepts_preexisting_advantage_and_visible_cost():
    result = assess_level_gap(
        player_level=5,
        monster_level=8,
        evidence_text="任务道具先压制了精英怪，夜烬和三名队友合力击杀，法力耗尽。",
    )

    assert result.allowed is True
    assert result.reason_codes == ("party", "quest_item")
    assert result.has_visible_cost is True


def test_rule_text_does_not_treat_skill_as_a_special_reason():
    text = level_gap_rule_text()

    assert "高出1至2级" in text
    assert "高出3级及以上" in text
    assert "走位、计算和操作不能单独" in text


def test_extract_level_gap_case_reads_player_and_monster_panels_before_kill():
    body = (
        "【游戏ID：夜烬】【等级：Lv.5】【生命：100/100】"
        "【腐沼鳄（精英）】【等级：Lv.8】【生命：400/400】"
        "任务道具缚鳄索先压住它，夜烬和队友合力击杀腐沼鳄，法力耗尽。"
    )

    case = extract_level_gap_case(body, context_text="四人组队计划")

    assert case is not None
    assert case.player_level == 5
    assert case.monster_level == 8
    assert "四人组队计划" in case.evidence_text
    assert "任务道具缚鳄索" in case.evidence_text


def test_extract_level_gap_case_ignores_encounter_without_kill():
    body = "【夜烬】【等级：Lv.5】【裂纹狼（精英）】【等级：Lv.9】夜烬看完面板便撤退。"

    assert extract_level_gap_case(body) is None


def test_extract_level_gap_case_reads_narrated_level_up_and_monster_info():
    body = (
        "苏叶打开角色面板，等级Lv.1，经验0/100。"
        "完成任务后，系统提示等级提升至Lv.2。"
        "系统弹出信息：裂纹狼（精英），等级Lv.5，生命320/320。"
        "夜烬只靠走位和计算完成击杀裂纹狼，法力耗尽。"
    )

    case = extract_level_gap_case(body)

    assert case is not None
    assert case.player_level == 2
    assert case.monster_level == 5
