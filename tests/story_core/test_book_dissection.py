import pytest

from packages.story_core.book_dissection import diagnose_project_chapter, dissect_reference_text


def section(report: dict, key: str) -> list[str]:
    return report["sections"][key]


def test_dissect_reference_text_returns_required_sections():
    text = "\n".join(
        [
            "夜烬绕开人群，等灰狼落单才出手。",
            "短发玩家说：\"你怎么不接任务？\"",
            "夜烬说：\"还差两份材料，先把蓝回满。\"",
            "任务牌上写着清道夫委托需要十份毒腺。",
        ]
    )

    report = dissect_reference_text(text, genre="网游", focus="苟道幕后")

    assert report["schema_version"] == "book-dissection/v1"
    assert report["mode"] == "reference"
    for key in [
        "章节作用",
        "爽点来源",
        "主角进展",
        "冲突推进",
        "对话功能",
        "节奏拆解",
        "结尾钩子",
        "可学习写法",
        "不能照抄",
    ]:
        assert key in report["sections"]
        assert section(report, key)
    assert any("网游" in item or "任务" in item for item in section(report, "可学习写法"))


def test_diagnose_project_chapter_flags_common_webgame_issues():
    chapter = {
        "chapter_number": 2,
        "chapter_title": "提前转职",
        "body": "夜烬1级就接了转职任务。\n他说：\"行。\"\n他说：\"好。\"\n【货币：0铜】\n怪物面板弹出来。",
    }
    state = {
        "current_chapter": 2,
        "progression_ledger": {
            "protagonist": {"level": "Lv.1"},
            "economy": {"game_currency": "0铜"},
        },
    }

    report = diagnose_project_chapter({"state": state}, chapter)

    assert report["mode"] == "project"
    assert any("转职" in item for item in section(report, "设定冲突"))
    assert any("短" in item or "不像" in item for item in section(report, "对话问题"))
    assert any("货币：0铜" in item for item in section(report, "说明感问题"))
    assert section(report, "可写入提示词")


def test_dissect_reference_text_rejects_empty_text():
    with pytest.raises(ValueError, match="text_required"):
        dissect_reference_text("   ")


def test_diagnose_project_chapter_rejects_missing_body():
    with pytest.raises(ValueError, match="body_required"):
        diagnose_project_chapter({}, {"body": None})


def test_diagnose_project_chapter_rejects_non_mapping_chapter():
    with pytest.raises(ValueError, match="chapter_required"):
        diagnose_project_chapter({}, None)


def test_diagnose_project_chapter_rejects_non_string_body():
    with pytest.raises(ValueError, match="body_must_be_string"):
        diagnose_project_chapter({}, {"body": 123})


@pytest.mark.parametrize(
    "project_context",
    [
        {"state": None},
        {"state": {"progression_ledger": None}},
    ],
)
def test_diagnose_project_chapter_tolerates_malformed_optional_state(project_context):
    report = diagnose_project_chapter(project_context, {"body": "夜烬绕开人群，先观察任务牌。"})

    assert report["mode"] == "project"
