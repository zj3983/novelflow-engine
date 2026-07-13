from types import SimpleNamespace

from packages.story_core.writing_learning import learning_snapshot, lessons_from_quality_report, merge_writing_lessons
from packages.story_core.writing_packet import build_codex_writing_packet


def test_lessons_from_quality_report_ignores_unaccepted_feedback():
    quality = {
        "writing_review": {
            "editor_agent_review": {
                "role": "编辑 Agent",
                "issues": ["短段比例太高"],
                "revision_plan": ["合并相邻短段，写成连续场景"],
            }
        },
        "reader_agent_review": {
            "role": "读者 Agent",
            "issues": ["章末没有明确下一步"],
            "revision_plan": ["把结尾落到可执行目标"],
        },
    }

    lessons = lessons_from_quality_report(quality)

    assert lessons == []


def test_lessons_from_quality_report_records_only_accepted_revision_actions():
    quality = {
        "revision_safety": {"accepted": True, "selected": "candidate"},
        "accepted_revision_actions": ["把对话改成角色会说的完整口语。", "删除抽象总结。"],
    }

    lessons = lessons_from_quality_report(quality)

    assert lessons == [
        "已验证改法：把对话改成角色会说的完整口语。",
        "已验证改法：删除抽象总结。",
    ]


def test_lessons_from_quality_report_rejects_actions_when_candidate_was_not_accepted():
    quality = {
        "revision_safety": {"accepted": False, "selected": "original"},
        "accepted_revision_actions": ["删除抽象总结。"],
    }

    assert lessons_from_quality_report(quality) == []


def test_merge_writing_lessons_keeps_recent_unique_items():
    lessons = merge_writing_lessons(["旧经验"], ["旧经验", "新经验"], limit=2)

    assert lessons == ["旧经验", "新经验"]


def test_writing_packet_exposes_learning_snapshot():
    story = SimpleNamespace(
        story_id="s",
        outline="网游故事",
        genre="网游",
        style="白描",
        current_chapter=1,
        world_facts=[],
        author_constraints=[],
        writing_lessons=["编辑 Agent经验：下次合并短段。"],
        characters=[],
    )

    packet = build_codex_writing_packet(story, chapter_number=2)

    assert packet["writing_learning"]["schema_version"] == "writing-learning/v1"
    assert packet["writing_learning"]["lessons"] == ["编辑 Agent经验：下次合并短段。"]
    assert learning_snapshot(["x"])["usage"]
