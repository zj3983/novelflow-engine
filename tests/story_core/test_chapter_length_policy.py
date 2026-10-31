import pytest

from packages.story_core.agents.contracts import DirectorArtifact, WriterRequest
from packages.story_core.agents.writer.agent import WriterAgent
from packages.story_core.agents.writer.prompt import build_writer_prompt
from packages.story_core.chapter_length_policy import acceptance_chars, target_chars
from packages.story_core.file_project_store import _chapter_length_review


@pytest.mark.parametrize("chars,accepted", [(2999,False),(3000,True),(3307,True),(4500,True),(4501,False)])
def test_default_length_gate_uses_3000_to_4500(chars, accepted):
    assert acceptance_chars() == {"min":3000,"max":4500}
    assert target_chars() == {"min":3000,"max":4500}
    assert _chapter_length_review("字" * chars)["acceptance_pass"] is accepted


def test_reused_3307_character_body_does_not_trigger_padding():
    class NoGeneration:
        def complete(self, request):
            pytest.fail("An accepted existing draft must not trigger generation or padding")

    request=WriterRequest(chapter_number=308,repair_length=True,
        director_artifact=DirectorArtifact(chapter_number=308,chapter_goal="完成交接",opening_state="等待交接",scene_beats=[],ending_state="交付完成"))
    body="甲" * 3307
    result=WriterAgent(NoGeneration(),allow_automatic_repair=True,repair_style_signals=False).run(request,draft_body=body)
    assert result.body == body
    assert len(result.revision_history) == 1
    prompt=build_writer_prompt(request)
    assert "低于3000字或超过4500字不能交稿" in prompt
    assert "不为靠近目标或上限补写" in prompt
