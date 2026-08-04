from pathlib import Path
from types import SimpleNamespace

from packages.story_core import antigravity_cli_provider


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
            "model": "gemini-3.6-flash-high",
            "messages": [{"role": "user", "content": "写一段"}],
            "reasoning_effort": "high",
        },
        command="agy-test",
    )

    args = captured["args"]
    assert args[:2] == ["agy-test", "--print"]
    assert args[args.index("--model") + 1] == "gemini-3.6-flash-high"
    assert args[args.index("--output-format") + 1] == "text"
    assert args[args.index("--effort") + 1] == "high"
    assert "--sandbox" in args
    assert Path(captured["cwd"]).name.startswith("novel_antigravity_")
    assert result["choices"][0]["message"]["content"] == "生成结果"


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
