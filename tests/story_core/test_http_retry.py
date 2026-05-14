from __future__ import annotations

import http.client

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
