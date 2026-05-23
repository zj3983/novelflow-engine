from packages.story_core.web_game_review import review_web_game_chapter


def test_web_game_review_rejects_material_inventory_contradiction():
    body = """
《天启之门》开服，夜烬进入灰烬村交易行。
药剂师洛婶在药剂铺给出毒腺回收任务，说明只看材料和任务记录，不知道隐藏天赋。
【获得：灰狼毒腺×1】
【获得：灰狼毒腺×1】
【获得：灰狼毒腺×1】
半小时后，背包里多了八份灰狼毒腺。
【上架成功：灰狼毒腺×3，单价18铜币。】
【上架成功：灰狼毒腺×5，单价18铜币。】
【背包：灰狼毒腺×3】
洛婶接过他递过去的五份毒腺，完成任务登记。
交易行商人只记录价格、数量批次和时间戳，不知道他的现实身份。
"""

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["药剂师洛婶回收毒腺。"]},
        world_facts=["《天启之门》网游世界；关键材料账本必须闭合。"],
    )

    assert review["pass"] is False
    assert any("材料账本不闭合" in issue for issue in review["issues"])


def test_web_game_review_allows_closed_material_inventory():
    body = """
《天启之门》开服，夜烬进入灰烬村交易行。
药剂师洛婶在药剂铺给出毒腺回收任务，说明只看材料和任务记录，不知道隐藏天赋。
背包里有了八份灰狼毒腺。
【上架成功：灰狼毒腺×3，单价18铜币。】
夜烬把剩下五份毒腺递过去，完成洛婶的日常回收。
【背包：灰狼毒腺×0】
交易行商人只记录价格、数量批次和时间戳，不知道他的现实身份。
"""

    review = review_web_game_chapter(
        chapter_number=1,
        body=body,
        event_plan={"npc_beats": ["药剂师洛婶回收毒腺。"]},
        world_facts=["《天启之门》网游世界；关键材料账本必须闭合。"],
    )

    assert not any("材料账本不闭合" in issue for issue in review["issues"])


def test_web_game_review_counts_chapter_two_bonus_venom_before_submission():
    body = """
夜烬打开背包，灰狼毒腺×8。
他在坡口补打一只灰狼，摸出灰狼毒腺×2，原本的八份凑成十份。
夜烬把十份毒腺递过去，清道夫委托完成。
洛婶只按清单收钱拿药，不问夜烬这一趟来得快不快。
"""

    review = review_web_game_chapter(
        chapter_number=2,
        body=body,
        event_plan={"npc_beats": ["清道夫委托提交。"]},
        world_facts=["第一章章末灰狼毒腺8份，第二章补齐2份后提交10份。"],
    )

    assert not any("材料账本不闭合" in issue for issue in review["issues"])


def test_web_game_review_flags_trade_payout_and_task_progress_mismatch():
    body = (
        "《天启之门》开服，夜烬清点库存，一共三十八枚毒腺。他点开寄售栏，数量填10。单价填4铜。"
        "第三笔。10单位。4铜。上架。最后一笔。8单位。4铜。上架。"
        "提示音接连响起。苏叶看着余额栏。数字停在42铜。"
        "他划出十枚。放进任务栏。稍后打开面板：【任务进度：2/10】。"
    )

    review = review_web_game_chapter(chapter_number=1, body=body, event_plan={}, world_facts=[])

    assert review["pass"] is False
    assert review["scores"]["economy_rules"] < 8
    assert any("交易/任务账本" in issue for issue in review["issues"])
