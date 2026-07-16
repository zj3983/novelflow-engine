from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.story_core import codex_cli_provider


def test_codex_cli_always_uses_payload_model_when_environment_conflicts(monkeypatch, tmp_path):
    captured: dict[str, object] = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["env"] = kwargs["env"]
        output_path = Path(args[args.index("--output-last-message") + 1])
        output_path.write_text("ok", encoding="utf-8")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setenv("NOVEL_CODEX_MODEL", "environment-model")
    monkeypatch.setenv("NOVEL_CODEX_USE_PAYLOAD_MODEL", "false")
    source_codex_home = tmp_path / "source-codex-home"
    source_codex_home.mkdir()
    monkeypatch.setenv("CODEX_HOME", str(source_codex_home))
    monkeypatch.setattr(codex_cli_provider.shutil, "which", lambda command: command)
    monkeypatch.setattr(codex_cli_provider.subprocess, "run", fake_run)

    codex_cli_provider.post_json_via_codex_cli(
        {"model": "payload-model", "messages": [{"role": "user", "content": "hello"}]}
    )

    args = captured["args"]
    assert args[args.index("--model") + 1] == "payload-model"
    assert "--ignore-user-config" in args
    assert "--ignore-rules" in args
    assert "--ephemeral" in args
    assert args[args.index("--sandbox") + 1] == "read-only"
    assert "--skip-git-repo-check" in args
    assert captured["env"]["CODEX_HOME"] != str(source_codex_home)


def test_codex_cli_rejects_empty_payload_model(monkeypatch):
    monkeypatch.setenv("NOVEL_CODEX_MODEL", "environment-model")
    monkeypatch.setenv("NOVEL_CODEX_USE_PAYLOAD_MODEL", "true")
    monkeypatch.setattr(
        codex_cli_provider.subprocess,
        "run",
        lambda *args, **kwargs: pytest.fail("empty model must fail before invoking Codex CLI"),
    )

    with pytest.raises(ValueError, match="^codexcli_model_required$"):
        codex_cli_provider.post_json_via_codex_cli(
            {"model": "  ", "messages": [{"role": "user", "content": "hello"}]}
        )


def test_codex_cli_version_reports_command_output(monkeypatch):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["timeout"] = kwargs["timeout"]
        return SimpleNamespace(returncode=0, stdout="codex-cli 0.135.0\n", stderr="")

    monkeypatch.setattr(codex_cli_provider, "_codex_command_prefix", lambda command: ["codex.exe"])
    monkeypatch.setattr(codex_cli_provider.subprocess, "run", fake_run)

    assert codex_cli_provider.read_codex_cli_version("codex") == "codex-cli 0.135.0"
    assert captured == {"args": ["codex.exe", "--version"], "timeout": 10}


def test_codex_cli_models_only_return_gpt_5_5_and_newer(monkeypatch, tmp_path):
    codex_home = tmp_path / "codex-home"
    codex_home.mkdir()
    (codex_home / "models_cache.json").write_text(
        '{"models": ['
        '{"slug":"gpt-5.6-sol"},'
        '{"slug":"gpt-5.6-terra"},'
        '{"slug":"gpt-5.5"},'
        '{"slug":"gpt-5.4"},'
        '{"slug":"gpt-5.4-mini"},'
        '{"slug":"gpt-5.3-codex-spark"},'
        '{"slug":"codex-auto-review"}'
        ']}',
        encoding="utf-8",
    )
    monkeypatch.setenv("CODEX_HOME", str(codex_home))

    assert codex_cli_provider.read_codex_cli_models() == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.5",
    ]


def test_codex_cli_latest_version_reads_official_package_metadata(monkeypatch):
    class FakeResponse:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def read(self):
            return b'{"version":"0.145.0"}'

    monkeypatch.setattr(
        codex_cli_provider.urllib.request,
        "urlopen",
        lambda request, timeout: FakeResponse(),
    )

    assert codex_cli_provider.read_latest_codex_cli_version() == "0.145.0"
    assert codex_cli_provider.codex_cli_update_status("codex-cli 0.144.5", "0.145.0") == "available"
    assert codex_cli_provider.codex_cli_update_status("codex-cli 0.145.0", "0.145.0") == "current"
