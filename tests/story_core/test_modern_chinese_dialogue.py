from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.segmented_writing import build_segment_prompt, build_segment_specs
from packages.story_core.writing_taskbook import build_writing_taskbook, format_taskbook_prompt_section


def test_prose_style_review_flags_outline_and_translation_dialogue():
    body = (
        "短发玩家问：“一个人去？”"
        "夜烬说：“先试，不深入。”"
        "短发玩家摆手：“接了也没用，背包里没有毒腺，柜台不认。”"
    )

    review = review_prose_style(body)

    assert review["pass"] is False
    joined_issues = "\n".join(review["issues"])
    joined_plan = "\n".join(review["revision_plan"])
    assert "现代中文对话" in joined_issues
    assert "先试，不深入" in joined_issues
    assert "柜台不认" in joined_issues
    assert "我就在坡口打两只看看" in joined_plan
    assert "你手里没毒腺" in joined_plan


def test_prose_style_review_flags_single_command_like_line():
    body = "赵管事说：“你先报我。”"

    review = review_prose_style(body)

    assert review["pass"] is False
    assert any("电报码式台词" in item for item in review["issues"])
    assert any("不要只说‘先试，不深入’" in item or "先报我" in item for item in review["revision_plan"])


def test_prose_style_review_flags_telegraphic_rule_list_dialogue():
    body = "赵管事说：“炉灭了，记你失职。窗坏、瓦落、门锁坏，先报我，不许自己乱拆。”"

    review = review_prose_style(body)

    assert review["pass"] is False
    assert any("清单式短句" in issue for issue in review["issues"])
    assert any("要是窗子、屋瓦或者门锁出了问题" in item for item in review["revision_plan"])


def test_prose_style_review_flags_comma_separated_short_judgments_inside_long_dialogue():
    body = (
        "赵管事说：\u201c这差事前面已经换过两个人，谁都不肯久做。"
        "没油水，没记功，祖祠偏。香炉真要出了问题，最后还是要来问你。\u201d"
    )

    review = review_prose_style(body)

    assert review["pass"] is False
    assert any("没油水，没记功，祖祠偏" in issue for issue in review["issues"])
    assert any("完整口语" in item for item in review["revision_plan"])


def test_prose_style_review_flags_command_style_dialogue_without_reasoning():
    body = "赵管事说：“先发，先交，先走。”夜烬说：“你先报我。”"

    review = review_prose_style(body)

    assert review["pass"] is False
    assert any("电报码式台词" in issue for issue in review["issues"])
    assert any("台词" in item for item in review["revision_plan"])


def test_prose_style_review_flags_command_style_dialogue_without_standard_quotes():
    body = "赵管事：先试，不深入。夜烬：先报我。"

    review = review_prose_style(body)

    assert not review["pass"]
    assert any("电报码式台词" in issue for issue in review["issues"])
    assert any("完整口语" in item or "先试，不深入" in item for item in review["revision_plan"])


def test_taskbook_exposes_modern_chinese_dialogue_method():
    taskbook = build_writing_taskbook(chapter_number=1, plan={}, genre="网游", style="白描")

    section = format_taskbook_prompt_section(taskbook)

    assert "现代中文对话" in section
    assert "不要把后台事实直译成台词" in section
    assert "先试，不深入" in section
    assert "我就在坡口打两只看看" in section
    assert "柜台不认" in section
    assert "你手里没毒腺" in section
    assert "少解释只针对旁白" in section


def test_segment_prompt_includes_modern_chinese_dialogue_filter():
    spec = build_segment_specs(1, {})[0]

    prompt = build_segment_prompt(chapter_number=1, spec=spec, plan={})

    assert "现代中文对话" in prompt
    assert "话题先摆出来" in prompt
    assert "提纲句、翻译腔和系统腔改成普通说法" in prompt
