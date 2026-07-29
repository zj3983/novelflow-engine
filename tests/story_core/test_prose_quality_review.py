from packages.story_core.prose_quality_review import review_prose_quality
from packages.story_core.orchestrator import _review_chapter_body


def test_prose_quality_review_flags_explanatory_rule_sentence_with_quote():
    body = (
        "夜烬把毒腺往回收了半寸。洛婶也没追问，只把账本翻回原页，继续给药瓶贴签。"
        "柜台很窄，规矩也很窄。放上去的，她看；没放上去的，她不问。"
        "夜烬把毒腺收回背包，没再多问。"
    )

    review = review_prose_quality(body)

    assert not review["pass"]
    assert review["overall"] < 80
    issue = review["issues"][0]
    assert issue["type"] == "explanatory_rule_sentence"
    assert "放上去的，她看；没放上去的，她不问" in issue["quote"]
    assert "替规则说话" in issue["reason"]
    assert review["scores"]["scene_naturalness"] < 8


def test_prose_quality_review_rewards_natural_action_boundary():
    body = (
        "夜烬把毒腺往回收了半寸。洛婶也没追问，只把账本翻回原页，继续给药瓶贴签。"
        "洛婶的笔尖在账本上点了两下，人已经去拿下一张药瓶签。"
        "夜烬把毒腺收回背包，没再多问。"
    )

    review = review_prose_quality(body)

    assert review["pass"]
    assert review["overall"] >= 80
    assert review["issues"] == []


def test_prose_quality_review_reports_strengths_and_concrete_revision_for_ai_texture():
    body = (
        "下一步目标很简单：先按NPC门槛交一组，换出第一笔铜币。"
        "规则未明之前，他不碰第二只灰鼠。"
        "材料暂不外露。"
    )

    review = review_prose_quality(body)

    assert not review["pass"]
    assert any(issue["type"] == "validator_language" for issue in review["issues"])
    assert any("改成角色动作" in issue["suggestion"] for issue in review["issues"])
    assert "prose_quality" in review["reviewer"]


def test_prose_quality_review_flags_slogan_like_balanced_summary():
    body = (
        "旧端口回执出现后，法力少了一点。代价很小，但代价存在。"
        "声音一层压一层。热闹是真的，缺钱也是真的。"
    )

    review = review_prose_quality(body)

    assert not review["pass"]
    assert any(issue["type"] == "slogan_like_summary" for issue in review["issues"])
    assert review["scores"]["ai_trace"] < 8


def test_prose_quality_review_flags_report_voice_from_protagonist_background():
    body = (
        "苏叶以前做数据建模，习惯把每一笔支出拆成数据模型，算概率，算止损线。"
        "现在模型跑不动了，变量太多，现金流枯竭。"
        "提示框一闪，这意味着系统把溢出部分折算进了常规掉落池。"
    )

    review = review_prose_quality(body)

    assert not review["pass"]
    assert review["scores"]["ai_trace"] < 8
    quotes = " ".join(issue["quote"] for issue in review["issues"])
    assert "数据模型" in quotes
    assert "止损线" in quotes or "模型跑不动" in quotes


def test_chapter_review_includes_separate_prose_quality_review():
    body = (
        "第1章 灰烬村的登录者。"
        "【游戏ID：夜烬】【职业：元素法师学徒】【等级：Lv.1】【经验：0/100】【生命：100/100】【法力：80/80】"
        "夜烬取出一份灰鼠毒腺，放到柜台边缘。"
        "柜台很窄，规矩也很窄。放上去的，她看；没放上去的，她不问。"
        "【获得：灰鼠毒腺×18】千倍爆率的提示在角落闪了一下。混沌之种仍然发灰。"
    )

    review = _review_chapter_body(
        1,
        body,
        {"next_focus": "先交一组材料，再去导师处确认灰色标记。"},
        ["网游开服，夜烬选择元素法师学徒，灰烬村有拟真NPC。"],
    )

    assert "prose_quality_review" in review
    assert not review["prose_quality_review"]["pass"]
    assert any(
        issue["type"] == "explanatory_rule_sentence"
        for issue in review["prose_quality_review"]["issues"]
    )


def test_chapter_review_includes_adversarial_cut_review():
    body = (
        "第1章 灰烬村的登录者。"
        "夜烬看了一眼旧端口回执，法力条少了一截。"
        "代价很小，但代价存在。"
        "洛婶没问他有没有毒腺，也看不见他的背包。她只负责发委托、收材料、给药。"
    )

    review = _review_chapter_body(
        1,
        body,
        {"next_focus": "先交一组材料，再去导师处确认灰色标记。"},
        ["网游开服，夜烬选择元素法师学徒，灰烬村有拟真NPC。"],
    )

    assert "adversarial_cut_review" in review
    cut_review = review["adversarial_cut_review"]
    assert not cut_review["pass"]
    assert any(cut["action"] == "replace_with_scene_detail" for cut in cut_review["cuts"])


def test_chapter_review_uses_one_consolidated_gate_instead_of_three_duplicate_agent_passes():
    review = _review_chapter_body(
        2,
        "林照核对完账册，发现最后一页被人撕掉了。他问值夜弟子是谁，对方报出名字后又补了一句，昨晚库房换过锁。",
        {"next_focus": "找到被撕掉的账页。"},
        ["玄幻宗门正在清查库房。"],
        genre_context={"genre_plugin_ids": ["xuanhuan"]},
    )

    for key in ("reader_agent_review", "editor_agent_review", "reviewer_agent_review"):
        assert review[key]["mode"] == "consolidated"
        assert review[key]["issues"] == []
