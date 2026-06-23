"""Shared HTTP utilities with retry logic for LLM API calls.

All agents should use `post_json_with_retry` instead of raw urllib.request.urlopen.
"""

from __future__ import annotations

import json
import http.client
import time
import urllib.error
import urllib.request


class RetryConfig:
    """Configuration for retry behavior."""
    max_retries: int = 2
    initial_delay: float = 0.5  # seconds
    backoff_factor: float = 2.0
    max_delay: float = 2.0
    timeout: int = 360  # seconds; long webnovel chapters can require several minutes per LLM call
    retry_on_status: tuple[int, ...] = (429, 500, 502, 503, 504)


def post_json_with_retry(
    base_url: str,
    path: str,
    payload: dict,
    api_key: str,
    config: RetryConfig | None = None,
    provider: str = "openai",
    codex_command: str = "",
) -> dict:
    """POST JSON to an API endpoint with exponential backoff retry.
    
    Args:
        base_url: API base URL (e.g. "https://api.openai.com/v1")
        path: API path (e.g. "/chat/completions")
        payload: Request body dict
        api_key: Bearer token
        config: Optional retry configuration
    
    Returns:
        Parsed JSON response as dict
    
    Raises:
        urllib.error.URLError: After all retries exhausted
        json.JSONDecodeError: If response is not valid JSON
    """
    if provider == "codexcli":
        from packages.story_core.codex_cli_provider import post_json_via_codex_cli

        return post_json_via_codex_cli(
            payload,
            command=codex_command or "codex",
            config=config,
        )

    cfg = config or RetryConfig()
    url = f"{base_url}{path}"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    data = json.dumps(payload).encode("utf-8")
    
    last_error: Exception | None = None
    delay = cfg.initial_delay
    
    for attempt in range(1, cfg.max_retries + 1):
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=cfg.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_error = e
            if e.code not in cfg.retry_on_status:
                raise  # Non-retryable error (401, 403, etc.)
            if attempt < cfg.max_retries:
                # Check Retry-After header
                retry_after = e.headers.get("Retry-After")
                if retry_after:
                    try:
                        delay = float(retry_after)
                    except ValueError:
                        pass
                time.sleep(delay)
                delay = min(delay * cfg.backoff_factor, cfg.max_delay)
        except (urllib.error.URLError, TimeoutError, OSError, http.client.IncompleteRead, json.JSONDecodeError) as e:
            last_error = e
            if attempt < cfg.max_retries:
                time.sleep(delay)
                delay = min(delay * cfg.backoff_factor, cfg.max_delay)
    
    raise last_error or urllib.error.URLError("All retries exhausted")
