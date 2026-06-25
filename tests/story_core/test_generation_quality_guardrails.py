from packages.story_core.agent_base import compact_list
from packages.story_core.ai_flavor_review import review_ai_flavor
from packages.story_core.models import NovelProject
from packages.story_core.models import StoryState
from packages.story_core.orchestrator import (
    _apply_ledger_updates,
    _extract_economy_anchors,
    _extract_equipment_ledger_updates,
    _extract_system_anchors,
    _merge_writing_review_quality,
    _normalize_chapter_summary,
    _normalize_web_game_terms,
    _review_chapter_body,
    _sanitize_chapter_output,
    _should_expand_chapter,
    _style_adapt_enabled,
)
from packages.story_core.prose_rule_review import review_emotion_quota, review_paragraph_form
from packages.story_core.world_enrichment import _merge_enrichment


def test_compact_list_treats_single_string_as_one_item():
    assert compact_list("混沌之种已经完成首次验证。", max_items=5) == ["混沌之种已经完成首次验证。"]


def test_first_chapter_sanitizer_adds_emotion_anchors():
    body = "\n\n".join(
        [
            "苏叶打开《天启之门》，给角色取名夜烬。",
            "夜烬选择元素法师学徒，拿到新手法杖。",
            "夜烬在灰狼坡试打一只灰狼，确认掉落判定×1000。",
            "夜烬看着背包里的灰狼毒腺，决定先不声张。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    review = review_emotion_quota(cleaned)

    assert review["scores"]["emotion_quota"] >= 8
    assert "喉咙发紧" in cleaned
    assert "掌心全是汗" in cleaned
    assert "不敢真的松下来" in cleaned


def test_review_chapter_body_handles_soft_low_scores_without_name_error(monkeypatch):
    def low_ai_flavor(body):
        return {
            "reviewer": "ai_flavor/v1",
            "pass": False,
            "scores": {"ai_flavor": 5},
            "issues": ["soft low"],
            "revision_plan": [],
        }

    monkeypatch.setattr("packages.story_core.orchestrator.review_ai_flavor", low_ai_flavor)

    review = _review_chapter_body(
        1,
        "《天启之门》开服，夜烬用新手法杖试打一只灰狼，混沌之种提示掉落判定×1000。旁边玩家只当他运气好，他把材料压进背包，下一步准备再刷一轮。",
        {"summary": "夜烬试打灰狼", "next_focus": "再刷一轮"},
        world_facts=["网游开服，夜烬低调验证千倍爆率。"],
    )

    assert "review_summary" in review
    assert review["review_summary"]["soft_passed"] is False


def test_review_chapter_body_treats_review_exception_as_failure(monkeypatch):
    def broken_web_game_review(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr("packages.story_core.orchestrator.review_web_game_chapter", broken_web_game_review)

    review = _review_chapter_body(
        1,
        "《天启之门》开服，夜烬用新手法杖试打一只灰狼，混沌之种提示掉落判定×1000。旁边玩家只当他运气好，他把材料压进背包，下一步准备再刷一轮。",
        {"summary": "夜烬试打灰狼", "next_focus": "再刷一轮"},
        world_facts=["网游开服，夜烬低调验证千倍爆率。"],
    )

    assert review["pass"] is False
    assert any("审稿器web_game异常" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_normalizes_panel_values_and_report_phrase():
    body = (
        "角色面板亮起：ID：夜烬等级：Lv.1经验：0/100生命：100/100法力：20/80"
        "主武器：新手法杖（耐久10/10）基础技能：基础火球术背包：空钱袋：空。\n\n"
        "面板边缘泛着微光，数据很干净。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "法力：60/60" in cleaned
    assert "数据很干净" not in cleaned
    assert "生命：100/100；法力" in cleaned


def test_first_chapter_sanitizer_adds_progression_hook_without_turning_in_quest():
    body = "\n\n".join(
        [
            "苏叶进入《天启之门》，游戏ID是夜烬。",
            "夜烬在灰狼坡击杀五只灰狼，背包里多了八份灰狼毒腺。",
            "他把背包关上，准备先回村。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "清道夫委托" in cleaned
    assert "只差两份" in cleaned
    assert "后坡探路" in cleaned
    assert "没有伸手接" in cleaned


def test_first_chapter_sanitizer_removes_premature_rewards_and_services():
    body = "\n\n".join(
        [
            "夜烬把灰狼毒腺递给窗口，钱袋里多了5枚铜币。",
            "夜烬把法杖递给铁匠，耐久条从6/10跳回9/10，扣掉3铜币。",
            "他走到药剂铺门口，看了一眼价牌。初级蓝药，10铜币一瓶。",
            "技能书残页还差九份。下一步，换技能书。",
            "夜烬回到村口，背包里还有灰狼毒腺八份。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "钱袋里多了" not in cleaned
    assert "扣掉" not in cleaned
    assert "买了药水" not in cleaned
    assert "买下药水" not in cleaned
    assert "技能书" not in cleaned
    assert "清道夫委托" in cleaned


def test_first_chapter_sanitizer_truncates_service_overrun():
    body = "\n\n".join(
        [
            "苏叶进入《天启之门》，游戏ID夜烬。夜烬在灰狼坡击杀五只灰狼，背包里有八份灰狼毒腺。",
            "回到村口，登记窗口前的人少了一半。他走过去，把两份毒腺放在柜台上。",
            "NPC说：清道夫委托完成。奖励铜币×50，经验×100。后坡通行木牌也给了他。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "清道夫委托完成" not in cleaned
    assert "奖励铜币" not in cleaned
    assert "后坡通行" not in cleaned
    assert "没有伸手接" in cleaned
    assert "八份毒腺" in cleaned
    assert "只差两份" in cleaned


def test_first_chapter_review_blocks_premature_rewards_and_services():
    body = (
        "《天启之门》开服，苏叶现实余额27.60元。夜烬完成角色创建，职业元素法师学徒。"
        "角色面板显示：游戏ID夜烬，Lv.1，职业元素法师学徒，经验0/100，生命100/100，法力60/60，钱袋空。"
        "他击杀灰狼后看见千倍爆率，灰狼毒腺掉进背包。"
        "窗口NPC盖章，钱袋里多了5枚铜币。夜烬又把法杖修好，想着下一步换技能书。"
    )

    review = _review_chapter_body(1, body, {}, ["网游"], {}, [], [])

    assert review["pass"] is False
    assert any("第一章账本越界" in issue for issue in review["issues"])


def test_first_chapter_review_allows_visible_prices_as_future_goal():
    body = (
        "《天启之门》开服，苏叶现实余额27.60元。夜烬完成角色创建，职业元素法师学徒。"
        "角色面板显示：游戏ID夜烬，Lv.1，职业元素法师学徒，经验0/100，生命100/100，法力60/60，钱袋空。"
        "村口任务牌写着清道夫委托：提交灰狼毒腺十份，奖励三十铜。旁边价牌挂着修理费和基础法力药水价格，"
        "但夜烬没有交材料，也没有买药水，只把背包扣紧。"
        "他击杀五只灰狼后看见千倍爆率，背包里有灰狼毒腺八份和粗糙狼皮七张，还差两份才能提交委托。"
    )

    review = _review_chapter_body(1, body, {}, ["网游"], {}, [], [])

    assert not any("第一章账本越界" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_preserves_price_and_precondition_surface():
    body = (
        "村口任务牌写着清道夫委托：提交灰狼毒腺十份，奖励三十铜。"
        "旁边价牌挂着修理费和基础法力药水价格，但夜烬没有交材料，也没有买药水。"
        "背包里现在只有灰狼毒腺八份，还差两份才能提交委托，后坡探路只是后续前置。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "基础法力药水价格" in cleaned
    assert "灰狼毒腺十份" in cleaned
    assert "奖励三十铜" in cleaned
    assert "还差两份" in cleaned
    assert "后坡探路" in cleaned


def test_first_chapter_sanitizer_inserts_safe_protagonist_speech():
    body = (
        "苏叶进入游戏，角色面板显示职业是元素法师学徒。"
        "任务牌写着清道夫委托需要灰狼毒腺十份。"
        "背包里现在只有灰狼毒腺八份，还差两份。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "夜烬把背包扣上，低声说" in cleaned
    assert "先不交" in cleaned
    assert "先修杖" not in cleaned


def test_first_chapter_review_allows_negated_arrival_wording():
    body = (
        "《天启之门》开服，苏叶现实余额27.60元。夜烬完成角色创建，职业元素法师学徒。"
        "任务牌写着清道夫委托需要灰狼毒腺十份，奖励三十铜。"
        "夜烬没有交材料，没有到账，也没有把材料挂出去，只把灰狼毒腺八份压进背包。"
    )

    review = _review_chapter_body(1, body, {}, ["网游"], {}, [], [])

    assert not any("第一章提前展开交易线" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_merges_overfragmented_paragraphs():
    body = "\n\n".join([f"夜烬看了一眼背包{i}。" for i in range(90)])

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert len([part for part in cleaned.split("\n\n") if part.strip()]) < 90


def test_first_chapter_sanitizer_merges_sentence_shards_until_paragraph_form_passes():
    body = "\n\n".join([f"法力栏见底{i}。夜烬退到石头后面。" for i in range(100)])

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    form_review = review_paragraph_form(cleaned)

    assert form_review["pass"] is True
    assert not any("段落形态过碎" in issue for issue in form_review["issues"])


def test_first_chapter_sanitizer_softens_repeated_state_openers():
    body = "\n\n".join([f"法力栏见底{i}。夜烬退到石头后面。" for i in range(30)])

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    review = _review_chapter_body(1, cleaned, {}, ["网游"], {}, [], [])

    assert not any("段首主语过度单调" in issue and "法力" in issue for issue in review["issues"])


def test_first_chapter_sanitizer_adds_protocol_anchor_even_when_login_exists():
    body = (
        "苏叶打开登录界面，完成角色创建，游戏ID夜烬。\n\n"
        "第一次击杀灰狼后，背包里多出几份毒腺。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "底层协议校验通过" in cleaned
    assert "混沌之种：未解析" in cleaned


def test_chapter_summary_string_fields_are_not_split_into_characters():
    summary = _normalize_chapter_summary(
        {
            "summary": "苏叶完成首次小额变现。",
            "facts": "混沌之种已经完成首次验证。",
            "unresolved_threads": "白袍公会是否会继续追查交易行异常？",
            "next_focus": "扩大刷怪收益。",
            "chapter_title": "蛰伏与首金",
        },
        1,
    )

    assert summary["facts"] == ["混沌之种已经完成首次验证。"]
    assert summary["unresolved_threads"] == ["白袍公会是否会继续追查交易行异常？"]


def test_economy_anchors_capture_price_fee_and_balance_for_continuity():
    body = (
        "市场价目前是10-11铜币/个，他定价8铜币。"
        "【确认寄售：灰鼠毒腺 × 49，单价 8铜币】"
        "【扣除手续费 5%，到账铜币：372】"
        "【当前余额：850铜币】"
    )

    anchors = _extract_economy_anchors(body)

    assert any("10-11铜币" in anchor for anchor in anchors)
    assert any("单价 8铜币" in anchor or "定价8铜币" in anchor for anchor in anchors)
    assert any("手续费 5%" in anchor for anchor in anchors)
    assert any("850铜币" in anchor for anchor in anchors)


def test_system_anchors_capture_class_equipment_and_npc_continuity():
    body = (
        "【职业倾向：元素法师（学徒）】夜烬打开武器栏。"
        "【粗糙的学徒法杖】耐久度：62%。"
        "药剂师洛婶在药剂铺柜台后报价，只收未污染毒腺，库存告急但看不到玩家面板。"
    )

    anchors = _extract_system_anchors(body)

    assert any("职业锚点" in anchor and "元素法师" in anchor for anchor in anchors)
    assert any("装备锚点" in anchor and "法杖" in anchor for anchor in anchors)
    assert any("NPC锚点" in anchor and "洛婶" in anchor for anchor in anchors)


def test_ledger_updates_are_mirrored_into_structured_game_ledger():
    story = StoryState(
        story_id="s-ledger",
        outline="网游开服。",
        genre="网游",
        style="升级流",
        progression_ledger={
            "protagonist": {"level": 1, "class_path": "法师学徒"},
            "economy": {"currency": "0金币0银币0铜币"},
            "equipment": {"weapon": "新手法杖", "durability": "正常"},
            "pressure": {},
            "level": 2,
            "exp": "45/200",
            "currency": "0金币21银币0铜币",
            "inventory": ["灰鼠毒腺×0"],
            "guild_attention": 1,
        },
    )

    _apply_ledger_updates(
        story,
        {"protagonist": {"class_path": "元素法师学徒"}, "equipment": {"weapon": "粗糙的学徒法杖", "durability": "62%"}},
    )

    assert story.progression_ledger["protagonist"]["level"] == 2
    assert story.progression_ledger["protagonist"]["exp"] == "45/200"
    assert story.progression_ledger["protagonist"]["class_path"] == "元素法师学徒"
    assert story.progression_ledger["economy"]["currency"] == "0金币21银币0铜币"
    assert story.progression_ledger["equipment"]["weapon"] == "粗糙的学徒法杖"
    assert story.progression_ledger["equipment"]["durability"] == "62%"
    assert story.progression_ledger["pressure"]["guild_attention"] == 1


def test_revised_body_ledger_extraction_captures_current_currency_level_and_exp():
    body = (
        "【当前等级：2。经验：45/200。】"
        "【当前资产：0金币 3银币 50铜币。】"
        "法杖耐久降至86%，短剑只是临时工具。"
    )

    updates = _extract_equipment_ledger_updates(body)

    assert updates["protagonist"]["level"] == 2
    assert updates["protagonist"]["exp"] == "45/200"
    assert updates["economy"]["currency"] == "0金币3银币50铜币"
    assert updates["currency"] == "0金币3银币50铜币"
    assert updates["equipment"]["durability"] == "86%"


def test_revised_body_ledger_uses_latest_balance_surface():
    body = (
        "【角色状态】等级：3 经验：120/400 货币：0金币 4银币 20铜币。"
        "他补给之后再次成交。余额栏跳动：0金币 5银币 8铜币。"
    )

    updates = _extract_equipment_ledger_updates(body)

    assert updates["economy"]["currency"] == "0金币5银币8铜币"
    assert updates["currency"] == "0金币5银币8铜币"


def test_opening_review_rejects_short_fanqie_style_chapter():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活混沌之种，确认千倍爆率生效。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 20

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
    )

    assert review["pass"] is False
    assert any("字数偏少" in issue for issue in review["issues"])


def test_quality_report_fails_when_prose_texture_review_fails_even_without_hard_score_drop():
    quality = {"ok": True, "issues": []}
    writing_review = {
        "pass": False,
        "scores": {"web_game_identity_layer": 8, "prose_style_meta_language": 8, "prose_quality_texture": 5},
        "prose_quality_review": {
            "pass": False,
            "overall": 68,
            "issues": [{"type": "mechanical_explanation", "quote": "意味着"}],
        },
        "adversarial_cut_review": {"pass": True, "cuts": []},
    }

    merged = _merge_writing_review_quality(quality, writing_review)

    assert merged["ok"] is False
    assert "writing_review" in merged["issues"]


def test_chapter_body_review_exposes_ai_flavor_critical_review():
    body = (
        "他不是为了多拿一点，而是为了确认这件事是否成立。"
        "这不是一次选择，而是一次边界验证。"
        "风险很清楚，逻辑也很完整。"
        "他需要在可见性和稳定性之间找到答案。"
    ) * 40

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["村口排队变长。"], "next_focus": "继续补材料。"},
    )

    assert "critical_review" in review
    assert "ai_flavor_review" in review
    assert review["critical_review"]["scores"]["ai_flavor"] < 8
    assert review["ai_flavor_review"]["metrics"]["formula_count"] >= 2
    assert any("AI味" in issue or "模型腔" in issue for issue in review["issues"])


def test_sanitizer_removes_ai_formula_and_report_clarity_phrase():
    body = (
        "不是一张皮，也不是一颗毒腺，而是好几份材料挤在一起。"
        "疼痛不重，却很清楚，像被钝刀刮了一下。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])
    ai_review = review_ai_flavor(cleaned)

    assert "不是一张皮" not in cleaned
    assert "而是" not in cleaned
    assert "很清楚" not in cleaned
    assert not any("不是X而是Y" in issue for issue in ai_review["issues"])


def test_sanitizer_inserts_protagonist_speech_when_name_action_is_not_dialogue():
    body = "\n\n".join(
        [
            "夜烬说完规则以后，把背包里的毒腺数了一遍。",
            "旁边的人还在问清道夫委托要几份材料。",
            "他没有递材料，也没有领铜币。",
        ]
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "夜烬把背包扣上，低声说：“先不交，我还差两份，回去补齐再说。”" in cleaned


def test_first_chapter_sanitizer_normalizes_starting_identity_and_stackable_bag():
    body = (
        "角色面板显示：游戏ID夜烬，职业元素法师学徒，Lv.1，背包：15/20。"
        "背包格子一下子亮了好几格，灰狼毒腺×8，粗糙狼皮×7。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "元素法师学徒" not in cleaned
    assert "见习冒险者（未转职）" in cleaned
    assert "背包：15/20" not in cleaned
    assert "背包：2/20" in cleaned
    assert "数量叠在图标角上" in cleaned


def test_chapter_body_review_uses_event_plan_protagonist_names_for_speech_gate():
    body = "苏叶站在柜台前，把背包里的毒腺数了一遍。铁栓看他一眼，继续翻账本。\n\n" * 90

    review = _review_chapter_body(
        1,
        body,
        {
            "ordered_actions": [{"name": "苏叶", "action": "询问仓库寄存"}],
            "world_reactions": ["村口排队变长。"],
            "next_focus": "继续补材料。",
        },
    )

    assert review["critical_review"]["scores"]["protagonist_speech"] < 8
    assert any("主角全章没有可识别的开口对话" in issue for issue in review["issues"])


def test_style_adapt_defaults_on_for_normal_generation_plans():
    assert (
        _style_adapt_enabled(
            {
                "chapter_number": 1,
                "simulation_plan": {
                    "chapter_goal": "确认边界",
                    "web_game_director_card": {"read_feel": "确认规则边界"},
                },
            }
        )
        is True
    )
    assert _style_adapt_enabled({"write_mode": "fast"}) is False
    assert _style_adapt_enabled({"chapter_number": 1}) is False


def test_style_adapt_disabled_for_regeneration_variants():
    assert (
        _style_adapt_enabled(
            {
                "chapter_number": 1,
                "simulation_plan": {
                    "chapter_goal": "重新推演第一章",
                    "simulation_variant": {"id": "boundary-inventory-route", "skip_style_adapt": True},
                },
            }
        )
        is False
    )


def test_regeneration_fast_path_skips_whole_chapter_expansion():
    short_body = "夜烬走到柜台前，把背包里的灰狼毒腺数了一遍。" * 120

    assert (
        _should_expand_chapter(
            short_body,
            {
                "simulation_plan": {
                    "simulation_variant": {
                        "id": "boundary-inventory-route",
                        "skip_expansion": True,
                    }
                }
            },
        )
        is False
    )


def test_chapter_body_review_uses_lower_minimum_for_regeneration_fast_path():
    body = "苏叶看着余额，夜烬进村问价，柜台只认铜币和任务牌。" * 150

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["村口排队变长。"], "next_focus": "继续补材料。"},
        simulation_plan={"simulation_variant": {"skip_expansion": True}},
    )

    assert review["scores"]["webnovel_hook"] == 8
    assert not any("字数偏少" in issue for issue in review["issues"])


def test_sanitize_chapter_output_repairs_regeneration_surface_traps():
    body = "\n\n".join(
        [
            "夜烬看着法力满格，继续往前走。",
            "夜烬把灰狼毒腺收进背包。",
            "夜烬没有急着笑。",
            "夜烬回头看了一眼。",
            "夜烬把法杖压低。",
            "夜烬走到柜台前。",
            "夜烬问了一句价格。",
            "夜烬把背包扣上。",
            "夜烬退到门边。",
        ]
    )
    scene_cards = [
        {
            "state_delta": {
                "game_world_simulation": {
                    "systemic_simulation": {"ledger_delta": {"cost_delta": {"mp": -60}}}
                }
            }
        }
    ]

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=scene_cards)

    assert "法力满" not in cleaned
    assert "法力只剩一截" in cleaned
    assert cleaned.count("\n\n夜烬") < body.count("\n\n夜烬")


def test_sanitize_chapter_output_keeps_first_chapter_to_one_npc_and_no_guild_overreach():
    body = (
        "夜烬走到仓库管理员铁栓面前，问背包能不能寄存。\n\n"
        "修理匠老葛也把修理价格和耐久规则说了一遍。\n\n"
        "白袍公会很快锁定坐标，知道了他的隐藏天赋。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=1, scene_cards=[])

    assert "铁栓" in cleaned
    assert "老葛" not in cleaned
    assert "锁定坐标" not in cleaned
    assert "隐藏天赋" not in cleaned


def test_opening_review_rejects_1000_times_wording_mixed_with_qianbei():
    body = (
        "《天启之门》开服当晚，苏叶在出租屋里看着账单登录全沉浸VRMMO。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常。"
        "他激活混沌之种，系统显示1000倍爆率，随后旁白又写千倍爆率。"
        "他通过交易行匿名寄售材料，注意到手续费、流水和风控异常提示。"
        "白袍公会、赤焰公会、星河商会和散人玩家都在争抢新手村资源。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
    )

    assert review["pass"] is False
    assert any("千倍爆率写法不统一" in issue for issue in review["issues"])


def test_review_rejects_decimal_game_currency_denominations():
    body = (
        "《天启之门》开服后，夜烬在灰烬村交易行匿名寄售毒腺。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒他别一次砸盘。"
        "交易行提示实际到账：银币0.18，铜币42，余额栏跳动。"
        "白袍公会外围只记录价格、数量批次和时间戳。"
    ) * 35

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"]},
        ["网游币制默认使用 1金币=100银币=10000铜币。"],
    )

    assert review["pass"] is False
    assert any("游戏币显示不应出现小数" in issue for issue in review["issues"])


def test_web_game_term_normalizer_keeps_formula_but_unifies_reader_terms():
    body = "系统显示1000倍爆率，旁白写放大了1000倍，但公式仍是掉落判定×1000。"

    normalized = _normalize_web_game_terms(body)

    assert "1000倍爆率" not in normalized
    assert "放大了1000倍" not in normalized
    assert "千倍爆率" in normalized
    assert "掉落判定×1000" in normalized


def test_opening_review_rejects_overpacked_first_chapter_pacing():
    body = (
        "《天启之门》开服当晚，苏叶登录游戏，旧头盔异常触发混沌之种。"
        "他立刻出村刷怪，灰狼连续掉落狼皮和狼牙。"
        "随后他回村进入交易行，拆单寄售材料。"
        "赵胖子这个商人当场登场试探价格，白袍公会外围也开始追查交易行异常。"
        "苏叶意识到公会、商人、NPC和风控都已经压了过来。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录异常。"], "next_focus": "继续低调变现。"},
    )

    assert review["pass"] is False
    assert any("第一章节奏过载" in issue for issue in review["issues"])


def test_opening_review_allows_world_channel_and_signpost_without_direct_pursuit():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村看见世界频道里白袍、赤焰和星河争抢资源点，但那只是开服生态背景。"
        "他出村小范围刷怪，验证混沌之种和千倍爆率后，回到村口交易行拆单寄售低级材料。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒解毒剂材料缺口大，别一次砸盘。"
        "交易行只留下匿名寄售、手续费、价格、数量批次和时间戳，没有暴露坐标或现实身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert "第一章节奏过载：登录、金手指、刷怪、回村交易、商人登场和公会追查被压进同一章。" not in review["issues"]


def test_opening_review_allows_protagonist_pricing_strategy_without_merchant_scene():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村看见世界频道里公会招募和商会收货，那只是开服生态背景。"
        "他出村小范围刷怪，验证混沌之种和千倍爆率后，回到村口交易行拆单寄售低级材料。"
        "药剂师洛婶在药剂铺报价回收毒腺，提醒解毒剂材料缺口大，别一次砸盘。"
        "夜烬选择主动压价一铜币走匿名批次，交易行只留下手续费、价格、数量批次和时间戳。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])


def test_opening_review_allows_negated_coordinate_locking():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬在灰烬村接任务后出村小范围刷怪，验证混沌之种和千倍爆率。"
        "他回到交易行拆单寄售低级材料，药剂师洛婶报价回收狼牙并提醒别一次砸盘。"
        "白袍公会外围只记录价格波动、数量批次和时间戳，没有锁定坐标，也没有锁定身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])
    assert not any("暴露坐标/身份" in issue for issue in review["issues"])


def test_opening_review_allows_resource_point_clearance_as_world_ecology():
    body = (
        "《天启之门》全沉浸开服当晚，苏叶在出租屋里看着账单登录游戏。"
        "他是失业外包测试员，旧头盔神经接驳时出现协议异常，角色创建界面确认游戏ID：夜烬。"
        "夜烬进入灰烬村，世界频道里白袍公会提醒黑水沼泽东侧清场，赤焰和星河在频道里吵资源点。"
        "他在低密度灰鼠坡小范围刷怪，验证混沌之种和千倍爆率后，回到交易行拆单寄售。"
        "药剂师洛婶报价回收毒腺，提醒低级材料不要砸盘。"
        "交易行只留下匿名流水、手续费、价格、数量批次和时间戳，没有坐标或现实身份。"
    ) * 28

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["交易行商人记录时间戳。"], "next_focus": "下一次验证。"},
        ["第1章冲突模式：现实压力、规则验证、交易行弱线索。"],
    )

    assert not any("第一章节奏过载" in issue for issue in review["issues"])


def test_second_chapter_rejects_rushing_element_corridor_completion():
    body = (
        "夜烬打开角色面板，等级1，经验30/100，职业：元素法师学徒，货币15铜币。"
        "他在灰烬村交易行分批寄售毒腺，药剂师洛婶提醒元素回廊前置需要材料。"
        "白袍公会外围只记录价格、数量批次和时间戳，没有锁定坐标或现实身份。"
        "夜烬随后去了职业导师艾伦面前，系统提示：元素回廊前置材料已提交，进度：10/10。"
        "【系统提示】任务完成。等级提升！当前等级：2。"
    ) * 30

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["交易行商人记录价格和时间戳。"], "next_focus": "继续低调变现。"},
        ["第2章必须承接第一章账本：夜烬等级1、经验30/100、职业元素法师学徒、货币15铜、库存毒腺×8狼皮×5。"],
    )

    assert review["pass"] is False
    assert any("第二章推进过快" in issue for issue in review["issues"])


def test_second_chapter_rejects_level_one_transfer_or_trial_start():
    body = (
        "夜烬打开角色面板，等级：Lv.1，经验40/100，职业：元素法师学徒。"
        "他拿着清道夫委托奖励去了法师塔，职业导师艾伦让他开始转职任务。"
        "系统提示：职业试炼已开启，进入元素试炼区域。"
        "短发玩家还在村口排队，夜烬已经踏进法师塔一层。"
    ) * 35

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["普通玩家还在排队。"], "next_focus": "继续任务。"},
        ["第2章必须承接第一章账本：夜烬仍是Lv.1，只能推进新手村任务。"],
    )

    assert review["pass"] is False
    assert any("Lv.1越级" in issue for issue in review["issues"])


def test_later_low_level_chapter_rejects_transfer_or_trial_start():
    body = (
        "夜烬打开角色面板，当前等级：4，经验210/500，职业：元素法师学徒。"
        "他刚从后坡交完一轮材料，就被职业导师艾伦叫进法师塔。"
        "系统提示：职业试炼已开启，进入元素试炼区域。"
        "旁边玩家还在排队修装备，他已经开始转职任务。"
    ) * 35

    review = _review_chapter_body(
        6,
        body,
        {"world_reactions": ["普通玩家还在新手村刷材料。"], "next_focus": "继续任务。"},
        ["第6章账本：夜烬等级4，仍在新手村低级地图推进，10级前不能正式接取转职任务或职业试炼。"],
    )

    assert review["pass"] is False
    assert any("低等级越级" in issue for issue in review["issues"])


def test_game_review_rejects_unexplained_full_exp_without_level_up():
    body = (
        "夜烬打开角色面板，等级：Lv.1，职业：元素法师学徒，经验：100/100（未升级），钱袋：5铜。"
        "他站在灰狼坡入口，旁边玩家还在交清道夫委托，洛婶只按十份毒腺验材料。"
        "他点开面板，经验条卡在100/100，没跳，只好继续往坡上走。"
    ) * 35

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["普通玩家还在新手村排队。"], "next_focus": "继续凑技能书钱。"},
        ["第2章必须承接第一章账本：夜烬仍是Lv.1元素法师学徒。"],
    )

    assert review["pass"] is False
    assert any("经验账本不清" in issue for issue in review["issues"])


def test_game_review_rejects_task_submission_contradiction():
    body = (
        "夜烬打开角色面板，等级：Lv.1，职业：元素法师学徒，经验：15/100，钱袋：空。"
        "他心里记着清道夫委托也没有提交，先绕到柜台前看价牌。"
        "洛婶验完十份灰狼毒腺，提示跳出：清道夫委托完成，奖励三十铜。"
    ) * 35

    review = _review_chapter_body(
        1,
        body,
        {"world_reactions": ["旁人只当他普通排队。"], "next_focus": "凑技能书钱。"},
        ["网游新手村开局，夜烬选择元素法师学徒。"],
    )

    assert review["pass"] is False
    assert any("任务账本自相矛盾" in issue for issue in review["issues"])


def test_game_review_rejects_repeated_newbie_task_loop():
    body = (
        "夜烬回村，村口的任务牌前排着队。洛婶验完材料，提示跳出：清道夫委托完成，奖励三十铜。"
        "他又回到灰狼坡刷怪，蓝条见底后再次回村，任务牌前的人少了一些。"
        "洛婶又验十份毒腺，提示跳出：清道夫委托完成，奖励三十铜。"
        "他第三次站到任务牌前，旁边玩家还在抱怨毒腺难出。"
    ) * 25

    review = _review_chapter_body(
        2,
        body,
        {"world_reactions": ["散人只看见他排队交任务。"], "next_focus": "继续刷怪。"},
        ["第2章仍在灰狼坡和灰烬村。"],
    )

    assert review["pass"] is False
    assert any("新手章流程重复" in issue for issue in review["issues"])


def test_game_world_enrichment_seeds_core_character_profiles():
    project = NovelProject(
        project_id="p-character-profiles",
        title="苟在网游里成神",
        seed_outline="网游开服，主角靠千倍爆率低调发育，交易行变现，被商人与公会逐步注意。",
        world_blueprint={"genre_plugin_ids": ["game_webnovel"]},
    )

    enriched = _merge_enrichment(project, {})
    names = {profile["name"] for profile in enriched.character_profiles}

    assert {"苏叶", "赵胖子", "药剂师洛婶", "职业导师艾伦", "白袍公会外围队长"}.issubset(names)


def test_sanitizer_rewrites_reader_facing_bad_game_terms():
    body = (
        "夜烬看见任务门槛还没满足，只能先修杖。"
        "他握杖退后，杖尖对着灰狼，系统提示火球术熟练度还差一点。"
    )

    cleaned = _sanitize_chapter_output(body, chapter_number=2, scene_cards=[])

    assert "门槛" not in cleaned
    assert "修杖" not in cleaned
    assert "握杖" not in cleaned
    assert "杖尖" not in cleaned
    assert "熟练度" not in cleaned
    assert "任务前置" in cleaned
    assert "修法杖" in cleaned
    assert "握着法杖" in cleaned
    assert "法杖前端" in cleaned
    assert "基础火球术记录" in cleaned
