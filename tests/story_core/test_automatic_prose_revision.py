from hashlib import sha256
import json
from types import SimpleNamespace

import pytest

from packages.story_core.agents.contracts import DirectorArtifact, SceneBeat, WriterRequest, WriterResult
from packages.story_core.agents.writer.agent import WriterAgent, _apply_length_patch
from packages.story_core.agents._runtime_common import translate_request
from packages.story_core.automatic_prose_revision import revise_contextually
from packages.story_core.contextual_prose_review import review_contextual_prose
from packages.story_core.model_gateway.contracts import ModelRequest


def request():
    return WriterRequest(chapter_number=307, repair_length=True,
        director_artifact=DirectorArtifact(chapter_number=307, chapter_goal="交接", opening_state="维修完成",
            scene_beats=[SceneBeat(order=1,location="阀前",action="复测",result="学会判断")], ending_state="独立值守"))


class Runtime:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.requests = []
    def complete(self, request):
        self.requests.append(request)
        return SimpleNamespace(text=self.outputs.pop(0))


def test_measured_model_patch_converges_without_manual_cutting():
    required = "门人先读数，再将手指贴在接缝上。" * 230
    body = required + "\n\n" + "多余的解释。" * 600 + "\n\n夜色渐深。\n\n这次你别动。"
    replacement = "门人复核后记下了读数。" * 30
    patch = json.dumps({"edits":[{"paragraph":1,"replacement":replacement}]},ensure_ascii=False)
    runtime = Runtime([body,patch])
    result = WriterAgent(runtime,allow_automatic_repair=True).run(request())
    assert 3800 <= result.word_count <= 4500
    assert result.body == required + "\n\n" + replacement + "\n\n夜色渐深。\n\n这次你别动。"
    assert len(runtime.requests) == 2 and runtime.requests[1].json_mode
    assert '"chars":' in runtime.requests[1].prompt


@pytest.mark.parametrize("edits", [
    [{"paragraph":2,"replacement":""}], # protected ending
    [{"paragraph":True,"replacement":""}],
    [{"paragraph":0,"replacement":""},{"paragraph":0,"replacement":""}],
    [{"paragraph":0,"replacement":""}], # below minimum
])
def test_invalid_or_overdeleting_patch_never_changes_body(edits):
    body = "必要过程。" * 800 + "\n\n等待。\n\n门外有人。"
    assert _apply_length_patch(body,json.dumps({"edits":edits}),minimum=3800) == ""


def report(body, passed):
    return {"executed":True,"status":"completed","pass":passed,"body_sha256":sha256(body.encode()).hexdigest(),
            "issues":[] if passed else [{"message":"教学持续威吓偏离耐心交接", "evidence":"再错就滚出去。", "suggestion":"保留纠错，改成等待门人复核"}]}


def test_pressure_revision_is_automatic_and_freshly_reviewed():
    first = "再错就滚出去。" + "甲" * 4200
    revised = "他等门人重新读数。" + "甲" * 4200
    runtime = Runtime([json.dumps({'edits':[{'before':'再错就滚出去。','after':'他等门人重新读数。'}]},ensure_ascii=False)])
    agent = WriterAgent(runtime,allow_automatic_repair=True)
    seen = []
    def reviewer(body,context):
        seen.append(body)
        assert context["enforce_narrative_alignment"]
        return report(body,body == revised)
    result, review, history = revise_contextually(agent,request(),WriterResult(body=first,word_count=len(first)),{},reviewer=reviewer)
    assert seen == [first,revised]
    assert result.body == revised and review["pass"]
    assert len(history)==2 and history[0]["review"]["issues"]
    assert first in runtime.requests[0].prompt
    assert "保留纠错" in runtime.requests[0].prompt


def test_pressure_rewrite_also_gets_length_repair_before_re_review():
    first = "交接开始。\n\n" + "复测。" * 1400 + "\n\n夜色。\n\n别动。"
    runtime = Runtime([json.dumps({'edits':[{'before':'交接开始。','after':'解释。'*200}]},ensure_ascii=False),
                       json.dumps({"edits":[{"paragraph":0,"replacement":"交接开始。"}]},ensure_ascii=False)])
    seen=[]
    def reviewer(body,context):
        seen.append(body)
        return report(body,len(seen)>1)
    result,_,_=revise_contextually(WriterAgent(runtime,allow_automatic_repair=True),request(),
        WriterResult(body=first,word_count=4200),{},reviewer=reviewer)
    assert len(runtime.requests)==2 and len(seen)==2
    assert len(''.join(result.body.split()))<=4500
    assert seen[-1]==result.body


def test_review_failure_or_stale_review_is_never_a_pass():
    body="甲"*4200
    with pytest.raises(RuntimeError,match="review_incomplete"):
        revise_contextually(None,request(),WriterResult(body=body),{},reviewer=lambda *_:{**report("旧稿",True)})


def test_nonconverging_pressure_is_bounded_and_does_not_return_ready_text():
    body="教学。"+"甲"*4200
    runtime=Runtime([json.dumps({'edits':[{'before':'教学。','after':'教学一。'}]},ensure_ascii=False),
                     json.dumps({'edits':[{'before':'教学一。','after':'教学二。'}]},ensure_ascii=False)])
    with pytest.raises(RuntimeError,match="revision_not_converged"):
        revise_contextually(WriterAgent(runtime,allow_automatic_repair=True),request(),WriterResult(body=body),{},
                            reviewer=lambda body,_:report(body,False))
    assert len(runtime.requests)==2


def test_runtime_preserves_budget_and_review_system_instruction():
    original=ModelRequest(prompt="审稿",provider="",model="",operation="",system_prompt="只审上下文",
                          max_tokens=5500,json_mode=True,timeout_seconds=480)
    translated=translate_request(original,stage="consistency")
    assert translated.max_tokens==5500 and translated.json_mode
    assert translated.system_prompt==original.system_prompt and translated.timeout_seconds==480
    light=translate_request(SimpleNamespace(prompt="修订",metadata={},max_tokens=9000,json_mode=True,timeout_seconds=720),stage="writer")
    assert light.max_tokens==9000 and light.json_mode and light.timeout_seconds==720


class Gateway:
    def __init__(self,payload): self.payload=payload
    def complete_stage(self,*_): return SimpleNamespace(ok=True,text=json.dumps(self.payload,ensure_ascii=False))


def test_explicit_pressure_conclusion_cannot_be_lost_in_empty_issues():
    body="再错一个读数，全门人都得死在这里。"
    pressure={"planned_tone":"耐心交接","existing_costs":"旧伤持续","added_pressure":"全门死亡威胁",
              "teaching_tone":"以恐吓要求服从","verdict":"overpressured","quote":body,
              "risk_change":"新增死亡威胁","interaction_pressure":"用恐吓替代耐心指导","interaction_quotes":[body],
              "reason":"上游要求耐心交接且无新增代价，正文却以死亡恐吓门人纠错。","suggestion":"保留纠错步骤，去掉死亡恐吓。"}
    checked=review_contextual_prose(body,{"enforce_narrative_alignment":True},model_gateway=Gateway({"issues":[],"pressure_check":pressure}))
    assert not checked["pass"] and checked["issues"][0]["evidence"]==body


def test_production_review_requires_explicit_pressure_comparison():
    checked=review_contextual_prose("门人记录温降，随后独立复测。",{"enforce_narrative_alignment":True},model_gateway=Gateway({"issues":[]}))
    assert not checked["pass"] and checked["status"]=="failed"


def test_real_danger_warning_is_allowed_with_upstream_basis():
    body="敌兵撞开门，师父喝止弟子靠近断口，带着他们退到石墙后。"
    pressure={"planned_tone":"战斗中撤退","existing_costs":"敌兵闯入，断口仍有逆冲风险",
              "added_pressure":"没有新增威胁","teaching_tone":"必要的制止与撤退安排",
              "risk_change":"既有风险没有升级","interaction_pressure":"制止危险操作有计划依据","interaction_quotes":[],
              "verdict":"aligned","quote":"","reason":"严厉制止服务于既有撤退险情，没有超出计划。","suggestion":""}
    checked=review_contextual_prose(body,{"enforce_narrative_alignment":True,
        "upstream_chapter_plan":{"cost":"撤退消耗两枚灵石","emotional_change":"交战撤退"}},
        model_gateway=Gateway({"issues":[],"pressure_check":pressure}))
    assert checked["pass"]


def test_managed_pipeline_revises_before_extraction_and_semantic_review(tmp_path,monkeypatch):
    from packages.story_core.agents import pipeline
    from packages.story_core.context.writer_context import WriterContext
    from packages.story_core.continuity.delta import ContinuityDelta
    import packages.story_core.automatic_prose_revision as revision
    artifact=request().director_artifact
    first="再错就滚出去。"+"甲"*4200
    final="他等门人复核读数。"+"甲"*4200
    events=[]
    writer=Runtime([first,json.dumps({'edits':[{'before':'再错就滚出去。','after':'他等门人复核读数。'}]},ensure_ascii=False)])
    monkeypatch.setattr(pipeline,"plan_director_artifact",lambda **_:pipeline.DirectorPipelineResult(artifact=artifact,context=None))
    monkeypatch.setattr(pipeline,"_ensure_writer_context",lambda **_:WriterContext(chapter_number=307,director_artifact=artifact))
    from types import SimpleNamespace
    from packages.story_core.canon.registry import CanonRegistry
    monkeypatch.setattr(pipeline,"_ensure_canon_service",lambda *_:SimpleNamespace(registry=CanonRegistry.empty()))
    monkeypatch.setattr(pipeline,"_preflight_entities",lambda *_:({},[]))
    monkeypatch.setattr(pipeline,"_canon_view_for",lambda *_:{})
    monkeypatch.setattr(pipeline,"_default_writer_runtime",lambda *_:writer)
    def reviewer(body,context):
        events.append(('review',body))
        return report(body,body==final)
    class Consistency:
        def complete(self,request):
            assert final in request.prompt and first not in request.prompt
            events.append(('consistency',final))
            return {"issues":[]}
    class Extractor:
        def extract(self,context):
            events.append(('facts',context.body))
            return ContinuityDelta(chapter_number=307)
    monkeypatch.setattr(revision,"review_contextual_prose",reviewer)
    monkeypatch.setattr(pipeline,"_default_consistency_runtime",lambda *_:Consistency())
    bundle=pipeline.run_modular_pipeline(project_root=tmp_path,chapter_number=307,fact_extractor=Extractor())
    assert events==[('review',first),('review',final),('facts',final),('consistency',final)]
    assert bundle.body==final and bundle.contextual_review['body_sha256']==sha256(final.encode()).hexdigest()


@pytest.mark.parametrize('error,fragment',[
    ('writer_length_not_converged:5000:3800:4500','字数仍未达标'),
    ('automatic_context_revision_not_converged','仍未通过复审'),
    ('automatic_context_review_incomplete','不能判定通过'),
])
def test_bounded_failure_explains_unchanged_chapters(error,fragment):
    from packages.story_core.simplified_review import user_facing_generation_error
    message=user_facing_generation_error(RuntimeError(error))
    assert fragment in message and '原稿和现有候选稿未改动' in message
