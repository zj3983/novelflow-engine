from packages.story_core.editor_agent import review_editor_agent
from packages.story_core.reader_agent import review_reader_agent
from packages.story_core.reviewer_agent import review_reviewer_agent


def test_reader_agent_wraps_cold_reader_report():
    body = "苏叶看着现实账单，接下委托。灰狼掉落异常，下一步去交易行找散人收材料。"

    review = review_reader_agent(body)

    assert review["reviewer"] == "reader_agent/v1"
    assert review["role"] == "读者 Agent"
    assert review["pass"] is True
    assert "cold_reader_review" in review


def test_reader_agent_flags_weak_pull():
    review = review_reader_agent("夜烬走到坡口，又打了一只狼。")

    assert review["pass"] is False
    assert review["issues"]


def test_editor_agent_exposes_prose_reviews():
    body = "夜烬看了一眼背包，把法杖递给修理匠，说：“先修这个，药水等会儿再买。”"

    review = review_editor_agent(body)

    assert review["reviewer"] == "editor_agent/v1"
    assert review["role"] == "编辑 Agent"
    assert "prose_quality_review" in review
    assert "prose_style_review" in review
    assert "ai_flavor_review" in review


def test_reviewer_agent_exposes_hard_rule_reviews():
    body = (
        "夜烬登录《天启之门》，游戏ID夜烬，职业元素法师学徒。"
        "他击杀灰狼后看到掉落判定×1000，背包里多了灰狼毒腺。"
        "下一步，他准备补完清道夫前置任务。"
    )

    review = review_reviewer_agent(chapter_number=1, body=body, event_plan={"next_focus": "补前置任务"})

    assert review["reviewer"] == "reviewer_agent/v1"
    assert review["role"] == "审稿 Agent"
    assert "critical_review" in review
    assert "web_game_review" in review
    assert "progression_lead_review" in review
