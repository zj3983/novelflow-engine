from __future__ import annotations

import http.client
import json
import urllib.error
from pathlib import Path

import pytest

from packages.story_core.http_retry import RetryConfig, post_json_with_retry


class _Response:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self) -> bytes:
        return b'{"ok": true}'


def test_post_json_with_retry_retries_incomplete_read(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        if calls["count"] == 1:
            raise http.client.IncompleteRead(b'{"ok"', 5)
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    config = RetryConfig()
    config.max_retries = 2
    config.initial_delay = 0

    result = post_json_with_retry("http://api.test", "/chat", {"x": 1}, "key", config=config)

    assert result == {"ok": True}
    assert calls["count"] == 2


def _http_400() -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://api.test/chat", 400, "Bad Request", {}, None)


def test_post_json_with_retry_400_strips_compat_fields(monkeypatch):
    sent = []

    def fake_urlopen(request, timeout):
        sent.append(json.loads(request.data.decode("utf-8")))
        if len(sent) == 1:
            raise _http_400()
        return _Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    config = RetryConfig()
    config.initial_delay = 0
    payload = {
        "model": "m",
        "messages": [{"role": "user", "content": "ping"}],
        "temperature": 0.7,
        "parameters": {"enable_thinking": False},
        "response_format": {"type": "json_object"},
    }

    result = post_json_with_retry("http://api.test", "/chat", payload, "key", config=config)

    assert result == {"ok": True}
    assert len(sent) == 2
    assert sent[0] == payload
    assert sent[1] == {"model": "m", "messages": [{"role": "user", "content": "ping"}]}


def test_post_json_with_retry_400_without_compat_fields_raises(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise _http_400()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    config = RetryConfig()
    config.initial_delay = 0

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        post_json_with_retry("http://api.test", "/chat", {"x": 1}, "key", config=config)

    assert exc_info.value.code == 400
    assert calls["count"] == 1


def test_post_json_with_retry_400_persists_after_strip_raises(monkeypatch):
    calls = {"count": 0}

    def fake_urlopen(request, timeout):
        calls["count"] += 1
        raise _http_400()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    config = RetryConfig()
    config.initial_delay = 0
    payload = {"model": "m", "messages": [], "temperature": 0.7}

    with pytest.raises(urllib.error.HTTPError) as exc_info:
        post_json_with_retry("http://api.test", "/chat", payload, "key", config=config)

    assert exc_info.value.code == 400
    assert calls["count"] == 2


def test_post_json_with_retry_routes_codexcli(monkeypatch, tmp_path):
    captured = {}

    def fake_run(args, **kwargs):
        captured["args"] = args
        captured["input"] = kwargs["input"]
        captured["env"] = kwargs["env"]
        captured["isolated_auth_exists"] = (Path(kwargs["env"]["CODEX_HOME"]) / "auth.json").exists()
        output_path = args[args.index("--output-last-message") + 1]
        with open(output_path, "w", encoding="utf-8") as f:
            f.write('{"ok": true}')

        class _Completed:
            returncode = 0
            stdout = ""
            stderr = ""

        return _Completed()

    monkeypatch.setattr("packages.story_core.codex_cli_provider.shutil.which", lambda command: command)
    monkeypatch.setattr("packages.story_core.codex_cli_provider.subprocess.run", fake_run)
    source_codex_home = tmp_path / "source-codex-home"
    source_codex_home.mkdir()
    (source_codex_home / "auth.json").write_text('{"token":"test"}', encoding="utf-8")
    monkeypatch.setenv("CODEX_HOME", str(source_codex_home))
    config = RetryConfig()
    config.timeout = 5

    result = post_json_with_retry(
        "",
        "/chat/completions",
        {
            "model": "qwen3.6-plus",
            "messages": [{"role": "user", "content": "ping"}],
            "response_format": {"type": "json_object"},
        },
        "",
        config=config,
        provider="codexcli",
        codex_command="codex",
    )

    assert result["choices"][0]["message"]["content"] == '{"ok": true}'
    assert captured["args"][:2] == ["codex", "exec"]
    assert captured["args"][-1] == "-"
    assert "--ignore-user-config" in captured["args"]
    assert "--ignore-rules" in captured["args"]
    assert "--ephemeral" in captured["args"]
    assert captured["args"][captured["args"].index("--model") + 1] == "qwen3.6-plus"
    assert captured["env"]["CODEX_HOME"] != str(source_codex_home)
    assert captured["isolated_auth_exists"] is True
    assert "合法 JSON 对象" in captured["input"]
