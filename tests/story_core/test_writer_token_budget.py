import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core.writer_token_budget import calibrated_draft_budget
from packages.story_core.agents.contracts import DirectorArtifact,WriterRequest
from packages.story_core.agents.writer.agent import WriterAgent
from packages.story_core.agents.writer.runtime import GatewayWriterRuntime
from packages.story_core.model_gateway.contracts import ModelResponse
from packages.story_core.prompt_call_log import PromptCallLog,prompt_call_recording


def profile(path):
    path.write_text(json.dumps({'schema_version':'writer-token-calibration/v1','profiles':[{
        'provider':'antigravity','model':'test-model','protocol':'antigravity_cli','tokens_per_char':1.15,
        'budget_scale':0.95,'sample_count':3,'validated':True}]}),encoding='utf-8')
    return path


def test_budget_is_scoped_to_exact_provider_model_and_transport(tmp_path):
    settings=SimpleNamespace(provider_id='antigravity',model='test-model',protocol='antigravity_cli')
    path=profile(tmp_path/'profile.json')
    budget=calibrated_draft_budget(settings,target_chars={'min':4200,'max':4500},acceptance_chars={'min':3800,'max':4500},profile_path=path)
    assert budget['tokens']==4550 and budget['planned_chars']==4200
    assert budget['native_limit_supported'] is False
    for attr,value in [('provider_id','other'),('model','other'),('protocol','gemini')]:
        changed=SimpleNamespace(**{**vars(settings),attr:value})
        assert calibrated_draft_budget(changed,target_chars={'min':4200},acceptance_chars={'max':4500},profile_path=path) is None


def test_missing_or_invalid_calibration_never_looks_calibrated(tmp_path):
    settings=SimpleNamespace(provider_id='a',model='b',protocol='c')
    path=tmp_path/'missing'
    assert calibrated_draft_budget(settings,target_chars={},acceptance_chars={},profile_path=path) is None
    path.write_text('{bad',encoding='utf-8')
    assert calibrated_draft_budget(settings,target_chars={},acceptance_chars={},profile_path=path) is None


def test_unvalidated_fit_never_changes_production_budget(tmp_path):
    path=profile(tmp_path/'profile.json')
    data=json.loads(path.read_text(encoding='utf-8'))
    data['profiles'][0]['validated']=False
    path.write_text(json.dumps(data),encoding='utf-8')
    settings=SimpleNamespace(provider_id='antigravity',model='test-model',protocol='antigravity_cli')
    assert calibrated_draft_budget(settings,target_chars={'min':4200},acceptance_chars={'max':4500},profile_path=path) is None


def test_budget_reaches_initial_request_prompt_and_usage_log(tmp_path):
    request=WriterRequest(chapter_number=307,director_artifact=DirectorArtifact(chapter_number=307,
        chapter_goal='交接',opening_state='维修完成',scene_beats=[],ending_state='这次你别动'))
    seen=[]
    class Gateway:
        def complete_stage(self,stage,req):
            seen.append(req)
            return ModelResponse.success(req,text='完成交接。这次你别动。',usage={'output_tokens':12,'thinking_tokens':5},
                raw={'transport_metadata':{'output_token_limit_supported':False,'budget_mode':'prompt_guidance'}})
    class Runtime(GatewayWriterRuntime):
        def draft_token_budget(self,_):
            return {'tokens':4550,'planned_chars':4200,'sample_count':3,'native_limit_supported':False}
    log=PromptCallLog(tmp_path,project_id='test')
    with prompt_call_recording(log):
        result=WriterAgent(Runtime(Gateway())).run(request)
    assert seen[0].max_tokens==4550
    assert '约4550个输出token' in seen[0].prompt and '约4200个字符' in seen[0].prompt
    assert seen[0].metadata['draft_token_budget']['tokens']==4550
    entry=log.list()[0]
    assert entry['max_output_tokens']==4550 and entry['usage']['output_tokens']==12
    assert entry['usage']['thinking_tokens']==5
    assert entry['token_budget_transport']['output_token_limit_supported'] is False
    assert result.word_count==len(result.body)
