from pathlib import Path
from types import SimpleNamespace
import json
import pytest

from packages.story_core import antigravity_cli_provider
from packages.story_core.http_retry import RetryConfig


def test_antigravity_cli_runs_isolated_single_output_request(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status':'SUCCESS','response':'生成结果\n','usage':{'output_tokens':4,'thinking_tokens':2},'num_turns':2}), stderr="")

    monkeypatch.setattr(
        antigravity_cli_provider,
        "_antigravity_command_prefix",
        lambda command: [command],
    )
    monkeypatch.setattr(antigravity_cli_provider.subprocess, "run", fake_run)

    result = antigravity_cli_provider.post_json_via_antigravity_cli(
        {
            "model": "gemini-3.1-pro",
            "messages": [{"role": "user", "content": "写一段"}],
            "reasoning_effort": "high",
        },
        command="agy-test",
    )

    args = captured["args"]
    assert args[:2] == ["agy-test", "--print"]
    assert args[args.index("--model") + 1] == "gemini-3.1-pro"
    assert args[args.index("--output-format") + 1] == "json"
    assert args[args.index("--effort") + 1] == "high"
    assert "--sandbox" in args
    assert Path(captured["cwd"]).name.startswith("novel_antigravity_")
    assert result["choices"][0]["message"]["content"] == "生成结果"
    assert result['usage']['output_tokens']==4
    assert result['usage']['thinking_tokens']==2
    assert result['usage']['visible_output_tokens']==2
    assert result['transport_metadata']['output_token_limit_supported'] is False


def test_antigravity_cli_does_not_duplicate_effort_encoded_in_model(monkeypatch):
    captured = {}

    def fake_run(args, **_kwargs):
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status':'SUCCESS','response':'ok\n'}), stderr="")

    monkeypatch.setattr(
        antigravity_cli_provider,
        "_antigravity_command_prefix",
        lambda command: [command],
    )
    monkeypatch.setattr(antigravity_cli_provider.subprocess, "run", fake_run)

    antigravity_cli_provider.post_json_via_antigravity_cli(
        {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "write"}],
            "reasoning_effort": "low",
        },
        command="agy-test",
    )

    assert "--effort" not in captured["args"]


@pytest.mark.parametrize("model", ["claude-sonnet-4-6", "claude-opus-4-6-thinking"])
def test_antigravity_claude_models_reject_separate_effort_flag(monkeypatch, model):
    def cli(_command, args, **_kwargs):
        if "--effort" in args:
            return SimpleNamespace(returncode=3, stdout="", stderr="--effort is not supported for model")
        return SimpleNamespace(returncode=0, stdout=json.dumps({"status":"SUCCESS", "response":"OK"}), stderr="")

    monkeypatch.setattr(antigravity_cli_provider, "_run", cli)
    result = antigravity_cli_provider.post_json_via_antigravity_cli(
        {"model":model,"reasoning_effort":"high","messages":[{"role":"user","content":"Reply OK"}]},
        config=RetryConfig(max_retries=1),
    )
    assert result["choices"][0]["message"]["content"] == "OK"


def test_antigravity_cli_retries_transient_command_failure(monkeypatch):
    calls = 0

    def fake_run(args, **_kwargs):
        nonlocal calls
        calls += 1
        if calls == 1:
            return SimpleNamespace(
                returncode=1,
                stdout="",
                stderr="temporary provider unavailable",
            )
        return SimpleNamespace(returncode=0, stdout=json.dumps({'status':'SUCCESS','response':'recovered\n'}), stderr="")

    monkeypatch.setattr(
        antigravity_cli_provider,
        "_antigravity_command_prefix",
        lambda command: [command],
    )
    monkeypatch.setattr(antigravity_cli_provider.subprocess, "run", fake_run)
    monkeypatch.setattr(antigravity_cli_provider.time, "sleep", lambda _delay: None)

    result = antigravity_cli_provider.post_json_via_antigravity_cli(
        {
            "model": "gemini-3.1-pro-high",
            "messages": [{"role": "user", "content": "write"}],
        },
        command="agy-test",
        config=RetryConfig(max_retries=2, initial_delay=0),
    )

    assert calls == 2
    assert result["choices"][0]["message"]["content"] == "recovered"


def test_antigravity_does_not_treat_cli_envelope_or_invalid_usage_as_prose(monkeypatch):
    monkeypatch.setattr(antigravity_cli_provider,'_run',lambda *_args,**_kwargs:SimpleNamespace(returncode=0,stdout='{"status":"ERROR","response":"not valid"}',stderr=''))
    with pytest.raises(ValueError,match='invalid_json_result'):
        antigravity_cli_provider.post_json_via_antigravity_cli({'model':'test','messages':[]},config=RetryConfig(max_retries=1))


def test_antigravity_cli_models_are_read_from_command(monkeypatch):
    def fake_run(args, **kwargs):
        assert args == ["agy-test", "models"]
        return SimpleNamespace(
            returncode=0,
            stdout="gemini-3.6-flash-high\ngemini-3.1-pro-high\n",
            stderr="",
        )

    monkeypatch.setattr(
        antigravity_cli_provider,
        "_antigravity_command_prefix",
        lambda command: [command],
    )
    monkeypatch.setattr(antigravity_cli_provider.subprocess, "run", fake_run)

    assert antigravity_cli_provider.read_antigravity_cli_models("agy-test") == [
        "gemini-3.6-flash-high",
        "gemini-3.1-pro-high",
    ]


@pytest.mark.parametrize("content", ["", '{"answers":[]}'])
def test_print_deadline_is_timeout_even_when_cli_claims_success(monkeypatch, tmp_path, content):
    calls = []
    monkeypatch.setenv("NOVEL_ANTIGRAVITY_RUNTIME_DIR", str(tmp_path))

    def cli(*args, **kwargs):
        calls.append(args)
        return SimpleNamespace(returncode=0,
            stdout=json.dumps({"status":"SUCCESS", "response":content,"duration_seconds":180,
                "usage":{"input_tokens":100,"output_tokens":40,"thinking_tokens":40}}),
            stderr="[agy] print timeout after 3m0s with turn in progress; returning partial output\n")

    monkeypatch.setattr(antigravity_cli_provider, "_run", cli)
    with pytest.raises(TimeoutError, match="antigravity_cli_print_timeout") as error:
        antigravity_cli_provider.post_json_via_antigravity_cli(
            {"model":"test", "messages":[]},config=RetryConfig(timeout=180,max_retries=2))
    assert len(calls) == 1  # A spent print deadline must not restart the whole job.
    assert error.value.diagnostics["cli_status"] == "SUCCESS"
    assert error.value.diagnostics["response_chars"] == len(content)
    assert error.value.usage["thinking_tokens"] == 40


def test_success_without_final_reply_has_specific_safe_diagnostics(monkeypatch, tmp_path):
    monkeypatch.setenv("NOVEL_ANTIGRAVITY_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(antigravity_cli_provider, "_run", lambda *a,**k:SimpleNamespace(
        returncode=0,stdout=json.dumps({"status":"SUCCESS","response":"  ","duration_seconds":4,
            "usage":{"input_tokens":10,"output_tokens":20,"thinking_tokens":20,"api_key":"SECRET"}}),
        stderr="diagnostic private SECRET https://private.invalid?token=SECRET"))
    with pytest.raises(ValueError,match="antigravity_cli_no_final_response") as error:
        antigravity_cli_provider.post_json_via_antigravity_cli(
            {"model":"test", "messages":[]},config=RetryConfig(max_retries=1))
    assert error.value.diagnostics["failure_reason"] == "antigravity_cli_no_final_response"
    assert error.value.diagnostics["response_chars"] == 0
    assert "SECRET" not in json.dumps(error.value.diagnostics)
    assert error.value.usage["output_tokens"] == 20


def test_colored_timeout_marker_is_not_accepted_as_partial_json(monkeypatch):
    monkeypatch.setattr(antigravity_cli_provider,"_run",lambda *a,**k:SimpleNamespace(
        returncode=0,stdout='{"status":"SUCCESS","response":"{}"}',
        stderr="\x1b[33m[agy] print timeout after 2s with turn in progress; returning partial output\x1b[0m\r\n"))
    with pytest.raises(TimeoutError):
        antigravity_cli_provider.post_json_via_antigravity_cli(
            {"model":"test","messages":[]},config=RetryConfig(max_retries=1))


def test_unrelated_timeout_word_in_stderr_does_not_reject_final_answer(monkeypatch):
    monkeypatch.setattr(antigravity_cli_provider,"_run",lambda *a,**k:SimpleNamespace(
        returncode=0,stdout='{"status":"SUCCESS","response":"complete"}',
        stderr="debug: configured network timeout=180; all tasks completed\n"))
    result=antigravity_cli_provider.post_json_via_antigravity_cli(
        {"model":"test","messages":[]},config=RetryConfig(max_retries=1))
    assert result["choices"][0]["message"]["content"] == "complete"


def test_parent_process_timeout_is_safe_and_never_restarts(monkeypatch):
    calls=[]
    def cli(*args,**kwargs):
        calls.append(args)
        raise antigravity_cli_provider.subprocess.TimeoutExpired("SECRET_COMMAND",10,output="PRIVATE_PARTIAL",stderr="SECRET")
    monkeypatch.setattr(antigravity_cli_provider,"_run",cli)
    with pytest.raises(TimeoutError,match="antigravity_cli_process_timeout") as error:
        antigravity_cli_provider.post_json_via_antigravity_cli(
            {"model":"test","messages":[]},config=RetryConfig(max_retries=3))
    assert len(calls)==1 and error.value.diagnostics["cli_status"]=="UNKNOWN"
    assert "SECRET" not in str(error.value) and "PRIVATE_PARTIAL" not in json.dumps(error.value.diagnostics)


def test_cli_success_usage_discards_invalid_counters(monkeypatch):
    monkeypatch.setattr(antigravity_cli_provider,"_run",lambda *a,**k:SimpleNamespace(returncode=0,
        stdout=json.dumps({"status":"SUCCESS","response":"complete","usage":{"input_tokens":12,
            "output_tokens":20,"thinking_tokens":9,"negative":-1,"flag":True,"infinite":float('inf'),"nan":float('nan')}}),stderr=""))
    result=antigravity_cli_provider.post_json_via_antigravity_cli(
        {"model":"test","messages":[]},config=RetryConfig(max_retries=1))
    assert result["usage"]=={"input_tokens":12,"output_tokens":20,"thinking_tokens":9,"visible_output_tokens":11}
