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


def test_diagnose_project_chapter_extracts_concrete_webgame_progress():
    chapter = {
        "chapter_number": 1,
        "chapter_title": "灰狼坡试水",
        "body": "\n".join(
            [
                "夜烬击杀第五只灰狼。",
                "【经验：0/100】【生命：100/100】【法力：60/60】",
                "【经验：30/100】",
                "【获得：灰狼毒腺×58】【获得：粗糙狼皮×31】",
                "Lv.1，经验30/100。生命42/100。法力0/60。新手法杖4/10。灰狼毒腺八份，粗糙狼皮七张。",
                "【清道夫委托】",
                "【前置任务：提交灰狼毒腺×10】",
                "【奖励：30铜】",
                "【底层协议校验通过】",
                "【掉落判定×1000】",
                "【混沌之种：未解析】",
            ]
        ),
    }

    report = diagnose_project_chapter({"state": {}}, chapter)

    assert any("经验30/100" in item for item in section(report, "主角进展"))
    assert not any("经验0/100" in item for item in section(report, "主角进展"))
    assert any("毒腺8" in item or "毒腺八" in item for item in section(report, "主角进展"))
    assert any("清道夫委托" in item and "还差2份" in item for item in section(report, "冲突推进"))
    assert any("掉落判定×1000" in item for item in section(report, "爽点来源"))
    assert any("等法力" in item or "补齐2份" in item for item in section(report, "下一版改法"))
    joined = "\n".join(item for items in report["sections"].values() for item in items)
    assert "暂未命中" not in joined
    assert "未发现硬性错误" not in joined
