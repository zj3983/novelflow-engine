from pathlib import Path
from types import SimpleNamespace

from packages.story_core import antigravity_cli_provider
from packages.story_core.http_retry import RetryConfig


def test_antigravity_cli_runs_isolated_single_output_request(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["cwd"] = kwargs["cwd"]
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(returncode=0, stdout="生成结果\n", stderr="")

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
    assert args[args.index("--output-format") + 1] == "text"
    assert args[args.index("--effort") + 1] == "high"
    assert "--sandbox" in args
    assert Path(captured["cwd"]).name.startswith("novel_antigravity_")
    assert result["choices"][0]["message"]["content"] == "生成结果"


def test_antigravity_cli_does_not_duplicate_effort_encoded_in_model(monkeypatch):
    captured = {}

    def fake_run(args, **_kwargs):
        captured["args"] = args
        return SimpleNamespace(returncode=0, stdout="ok\n", stderr="")

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
        return SimpleNamespace(returncode=0, stdout="recovered\n", stderr="")

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
