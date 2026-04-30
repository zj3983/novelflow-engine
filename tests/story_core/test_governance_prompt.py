from packages.story_core.engine import ChapterBundle
from packages.story_core.models import CharacterState, StoryState
from packages.story_core.orchestrator import StoryOrchestrator


def _story() -> StoryState:
    return StoryState(
        story_id="s-prompt-governance",
        outline="网游开服，苏叶以夜烬身份低调验证千倍爆率。",
        genre="网游",
        style="升级流",
        current_chapter=1,
        characters=[CharacterState(name="苏叶", role="主角", game_id="夜烬")],
        world_facts=["灰烬村是新手村，低级收益主要使用铜币。"],
    )


def _governance() -> dict:
    return {
        "schema_version": "chapter-governance/v1",
        "chapter_intent": {
            "chapter_number": 1,
            "must_include": ["现实压力", "角色面板"],
            "must_avoid": ["交易行实际成交", "公会正面追查"],
            "ending_change": "完成首次小额验证。",
        },
        "runtime_context": {"protagonist": {"real_name": "苏叶", "game_id": "夜烬"}},
        "rule_stack": {
            "hard_facts": ["怪物统一为灰鼠，不要写成狼或其他怪。"],
            "soft_guidance": ["用动作、对话、界面表现设定。"],
            "diagnostic_only": ["爽点、节奏、读者期待只用于诊断，禁止进入正文。"],
        },
    }


def test_body_prompt_contains_governance_sections_with_diagnostic_boundary():
    prompt = StoryOrchestrator()._body_prompt(_story(), 1, {"governance": _governance()})

    assert "章节输入治理" in prompt
    assert "硬事实" in prompt
    assert "怪物统一为灰鼠" in prompt
    assert "禁止提前写" in prompt
    assert "交易行实际成交" in prompt
    assert "诊断词禁止入正文" in prompt
    assert "爽点" in prompt
    assert "治理层审计" in prompt


def test_revision_prompt_contains_governance_and_preserves_expression_boundary():
    prompt = StoryOrchestrator()._revision_prompt(
        _story(),
        1,
        "代价很小，但代价存在。",
        {"governance": _governance()},
        {"issues": ["解释腔"], "revision_plan": ["换成动作"]},
    )

    assert "章节输入治理" in prompt
    assert "表达权不等于事实权" in prompt
    assert "怪物统一为灰鼠" in prompt
    assert "诊断词禁止入正文" in prompt
    assert "治理层审计" in prompt


def test_body_prompt_warns_when_governance_gate_blocks_writing():
    dirty_governance = {
        "schema_version": "chapter-governance/v1",
        "chapter_intent": {"chapter_number": 1, "must_include": [], "must_avoid": ["论坛爆帖"]},
        "runtime_context": {},
        "rule_stack": {
            "hard_facts": ["正文要完成爽点并照顾读者期待。"],
            "soft_guidance": [],
            "diagnostic_only": [],
        },
    }

    prompt = StoryOrchestrator()._body_prompt(_story(), 1, {"governance": dirty_governance})

    assert "治理门禁" in prompt
    assert "fix_governance_before_writing" in prompt
    assert "先修治理层" in prompt
