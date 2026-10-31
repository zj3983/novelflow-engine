from __future__ import annotations

import os
import json
import math
import re
import shutil
import subprocess
import tempfile
import time
from pathlib import Path
from typing import Any

from packages.story_core.http_retry import RetryConfig


# agy 1.4.7 explicitly returns SUCCESS with partial output at its print
# deadline. Only its precise diagnostic marks an incomplete turn; ordinary
# log lines mentioning a timeout must not invalidate a final answer.
_ANSI_ESCAPE = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_PRINT_TIMEOUT = re.compile(
    r"^\[agy\] print timeout after [^\r\n]{1,40} with turn in progress; returning partial output\r?$",
    re.MULTILINE,
)
_TOKEN_USAGE_FIELDS = frozenset({
    "input_tokens", "output_tokens", "thinking_tokens", "cache_read_tokens",
    "total_tokens", "visible_output_tokens",
})


class AntigravityCLITimeoutError(TimeoutError):
    """An unfinished CLI turn, with no prompt or partial output in diagnostics."""

    def __init__(self, reason: str, diagnostics: dict[str, Any], usage: dict[str, Any]):
        super().__init__(reason)
        self.diagnostics = diagnostics
        self.usage = usage


class AntigravityCLIResponseError(ValueError):
    """A successful envelope that contains no usable final answer."""

    def __init__(self, reason: str, diagnostics: dict[str, Any], usage: dict[str, Any]):
        super().__init__(reason)
        self.diagnostics = diagnostics
        self.usage = usage


def _normalized_usage(envelope: dict[str, Any]) -> dict[str, Any]:
    usage = envelope.get("usage")
    if not isinstance(usage, dict):
        return {}
    normalized = {key: value for key, value in usage.items()
        if isinstance(value, (int, float)) and not isinstance(value, bool)
        and (not isinstance(value, float) or math.isfinite(value)) and value >= 0}
    if "output_tokens" in normalized:
        # Thinking is a subset of output_tokens in agy's accounting.
        normalized["visible_output_tokens"] = max(
            0, normalized["output_tokens"] - normalized.get("thinking_tokens", 0))
    return normalized


def _failure_details(reason: str, envelope: dict[str, Any], *,
                     timeout_seconds: int, attempt: int, returncode: int | None):
    status = envelope.get("status")
    response = envelope.get("response")
    diagnostics: dict[str, Any] = {
        "failure_reason": reason,
        "cli_status": status if status in ("SUCCESS", "ERROR") else "UNKNOWN",
        "timeout_seconds": timeout_seconds,
        "attempt": attempt,
        "response_chars": len(response.strip()) if isinstance(response, str) else 0,
        "timed_out": reason in {"antigravity_cli_print_timeout", "antigravity_cli_process_timeout"},
    }
    if isinstance(returncode, int) and not isinstance(returncode, bool):
        diagnostics["returncode"] = returncode
    for key in ("duration_seconds", "num_turns"):
        value = envelope.get(key)
        if (isinstance(value, (int, float)) and not isinstance(value, bool)
                and (not isinstance(value, float) or math.isfinite(value)) and value >= 0):
            diagnostics[key] = value
    usage = {key: value for key, value in _normalized_usage(envelope).items() if key in _TOKEN_USAGE_FIELDS}
    return diagnostics, usage


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict):
                parts.append(str(block.get("text") or block.get("content") or ""))
            else:
                parts.append(str(block))
        return "\n".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        return str(content.get("text") or content.get("content") or "").strip()
    return str(content or "").strip()


def _build_prompt(payload: dict[str, Any]) -> str:
    sections = [
        "你是小说写作系统里的模型后端。",
        "只输出最终内容，不要解释处理过程，不要修改任何文件。",
    ]
    if payload.get("response_format", {}).get("type") == "json_object":
        sections.append("本次只返回一个合法 JSON 对象，不要使用 Markdown 代码块。")
    for message in payload.get("messages") or []:
        if not isinstance(message, dict):
            continue
        text = _message_text(message)
        if text:
            sections.append(f"[{str(message.get('role') or 'user').upper()}]\n{text}")
    return "\n\n".join(sections).strip()


def _antigravity_command_prefix(command: str) -> list[str]:
    resolved = shutil.which(command or "agy") or (command or "agy")
    lowered = resolved.lower()
    if lowered.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolved]
    if lowered.endswith((".cmd", ".bat")):
        return ["cmd", "/d", "/c", resolved]
    return [resolved]


def _run(command: str, args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_antigravity_command_prefix(command), *args],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        **kwargs,
    )


def _runtime_root(command: str) -> Path:
    configured = os.getenv("NOVEL_ANTIGRAVITY_RUNTIME_DIR", "").strip()
    if configured:
        root = Path(configured)
    else:
        command_path = Path(command)
        if command_path.is_absolute() and command_path.parent.name.lower() == "launcher":
            root = command_path.parent.parent / "workbench-runtime"
        else:
            root = Path(tempfile.gettempdir()) / "novel_antigravity_runtime"
    root.mkdir(parents=True, exist_ok=True)
    return root


def read_antigravity_cli_version(command: str = "agy") -> str:
    completed = _run(command, ["--version"], timeout=10)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"antigravity_cli_version_failed:{detail[:200]}")
    value = (completed.stdout or completed.stderr or "").strip()
    if not value:
        raise RuntimeError("antigravity_cli_version_empty")
    return value.splitlines()[0].strip()


def read_antigravity_cli_models(command: str = "agy") -> list[str]:
    completed = _run(command, ["models"], timeout=20)
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"antigravity_cli_models_failed:{detail[:300]}")
    models: list[str] = []
    for raw_line in (completed.stdout or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        model_id = line.split("\t")[0].strip()
        if model_id and model_id not in models:
            models.append(model_id)
    return models


def post_json_via_antigravity_cli(
    payload: dict[str, Any],
    *,
    command: str = "agy",
    config: RetryConfig | None = None,
) -> dict[str, Any]:
    cfg = config or RetryConfig()
    if payload.get("max_tokens") is not None:
        raise ValueError("max_output_limit_not_enforceable")
    model = str(payload.get("model") or "").strip()
    if "\t" in model:
        model = model.split("\t")[0].strip()
    if not model:
        raise ValueError("antigravity_cli_model_required")

    with tempfile.TemporaryDirectory(
        prefix="novel_antigravity_",
        dir=_runtime_root(command or "agy"),
    ) as temp_dir:
        request_path = Path(temp_dir) / "request.txt"
        request_path.write_text(_build_prompt(payload), encoding="utf-8")
        prompt = (
            f"请调用 read_file 工具直接读取这个绝对路径：{request_path}。"
            "严格执行文件中的要求，只返回最终答案。禁止搜索目录，禁止调用 command，禁止修改文件。"
        )
        timeout_seconds = max(1, int(cfg.timeout))
        args = [
            "--print",
            prompt,
            "--model",
            model,
            "--output-format",
            "json",
            "--print-timeout",
            f"{timeout_seconds}s",
            "--sandbox",
            "--dangerously-skip-permissions",
            "--disable-slash-commands",
        ]
        reasoning_effort = str(payload.get("reasoning_effort") or "").strip().lower()
        model_encodes_effort = re.search(r"-(?:low|medium|high)$", model.lower()) is not None
        # Claude's CLI entries choose their own thinking mode and reject --effort.
        if not model_encodes_effort and not model.lower().startswith("claude-"):
            effort = reasoning_effort if reasoning_effort in {"low", "medium", "high"} else "high"
            args.extend(["--effort", effort])
        attempts = max(1, int(cfg.max_retries))
        delay = max(0.0, float(cfg.initial_delay))
        content = ""
        detail = ""
        for attempt in range(1, attempts + 1):
            try:
                completed = _run(
                    command or "agy",
                    args,
                    timeout=cfg.timeout + 10,
                    cwd=temp_dir,
                    env=os.environ.copy(),
                )
            except subprocess.TimeoutExpired:
                reason = "antigravity_cli_process_timeout"
                diagnostics, usage = _failure_details(reason, {}, timeout_seconds=timeout_seconds,
                    attempt=attempt, returncode=None)
                raise AntigravityCLITimeoutError(reason, diagnostics, usage) from None
            content = (completed.stdout or "").strip()
            try:
                parsed = json.loads(content)
            except (ValueError, TypeError):
                parsed = None
            envelope = parsed if isinstance(parsed, dict) else {}
            if _PRINT_TIMEOUT.search(_ANSI_ESCAPE.sub("", completed.stderr or "")):
                reason = "antigravity_cli_print_timeout"
                diagnostics, usage = _failure_details(reason, envelope, timeout_seconds=timeout_seconds,
                    attempt=attempt, returncode=completed.returncode)
                # Restarting would spend the full deadline again and still would
                # not finish this turn. Never publish its partial text as final.
                raise AntigravityCLITimeoutError(reason, diagnostics, usage)
            if completed.returncode == 0 and content:
                try:
                    if not isinstance(parsed, dict) or envelope.get("status") != "SUCCESS" or not isinstance(envelope.get("response"), str):
                        raise ValueError("antigravity_cli_invalid_envelope")
                    content = envelope["response"].strip()
                    if not content:
                        reason = "antigravity_cli_no_final_response"
                        diagnostics, usage = _failure_details(reason, envelope, timeout_seconds=timeout_seconds,
                            attempt=attempt, returncode=completed.returncode)
                        raise AntigravityCLIResponseError(reason, diagnostics, usage)
                    break
                except AntigravityCLIResponseError:
                    if attempt >= attempts:
                        raise
                    time.sleep(delay)
                    delay = min(delay * cfg.backoff_factor, cfg.max_delay)
                    continue
                except (ValueError,TypeError) as exc:
                    if attempt >= attempts:
                        raise ValueError("antigravity_cli_invalid_json_result") from exc
                    time.sleep(delay)
                    continue
            detail = (completed.stderr or completed.stdout or "").strip()
            if attempt >= attempts:
                if completed.returncode != 0:
                    raise RuntimeError(f"antigravity_cli_failed:{detail[:500]}")
                raise ValueError("antigravity_cli_empty")
            time.sleep(delay)
            delay = min(delay * cfg.backoff_factor, cfg.max_delay)

    normalized_usage = _normalized_usage(envelope)
    return {"choices": [{"message": {"role": "assistant", "content": content}}],
            "usage": normalized_usage,
            "transport_metadata": {"output_token_limit_supported":False,
                                   "requested_max_output_tokens":payload.get("max_tokens"),
                                   "budget_mode":"prompt_guidance" if payload.get("draft_token_budget") else "unsupported",
                                   "output_tokens_include_thinking":True,
                                   "num_turns":envelope.get("num_turns")}}
