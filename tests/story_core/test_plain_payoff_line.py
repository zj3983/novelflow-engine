from packages.story_core.prose_style_review import review_prose_style
from packages.story_core.writing_taskbook import build_writing_taskbook, format_taskbook_prompt_section


def test_taskbook_allows_plain_payoff_line_without_forcing_slogan():
    taskbook = build_writing_taskbook(chapter_number=2, plan={}, genre="网游", style="白描")

    section = format_taskbook_prompt_section(taskbook)

    assert "章末压句" in section
    assert "白话反打承诺" in section
    assert "不套成语、不喊口号" in section
    assert "先让他们抢" in section


def test_prose_style_review_flags_old_slogan_payoff_lines():
    body = (
        "夜烬看着任务牌，心里冷笑。"
        "三十年河东，三十年河西，莫欺少年穷。"
        "今日之辱，来日必还。"
    )

    review = review_prose_style(body)

    assert review["pass"] is False
    joined_issues = "\n".join(review["issues"])
    joined_plan = "\n".join(review["revision_plan"])
    assert "旧式口号" in joined_issues
    assert "莫欺少年穷" in joined_issues
    assert "白话" in joined_plan
    assert "当章具体矛盾" in joined_plan
