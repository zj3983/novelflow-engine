from pathlib import Path


def test_novel_autogrowth_skill_is_genre_neutral() -> None:
    skill = (
        Path(__file__).resolve().parents[2]
        / "plugins"
        / "novel-autogrowth"
        / "skills"
        / "novel-autogrowth"
        / "SKILL.md"
    ).read_text(encoding="utf-8-sig")

    assert "本书默认偏执点" not in skill
    assert "网游类型规则" not in skill
    assert "背包、装备耐久" not in skill
    assert "只读取当前项目已启用的题材模块" in skill
