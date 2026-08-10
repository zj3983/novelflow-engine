from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from packages.story_core.http_retry import RetryConfig


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
    return list(
        dict.fromkeys(
            line.strip()
            for line in (completed.stdout or "").splitlines()
            if line.strip()
        )
    )


def post_json_via_antigravity_cli(
    payload: dict[str, Any],
    *,
    command: str = "agy",
    config: RetryConfig | None = None,
) -> dict[str, Any]:
    cfg = config or RetryConfig()
    model = str(payload.get("model") or "").strip()
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
            "text",
            "--print-timeout",
            f"{timeout_seconds}s",
            "--sandbox",
            "--disable-slash-commands",
        ]
        reasoning_effort = str(payload.get("reasoning_effort") or "").strip().lower()
        model_encodes_effort = re.search(r"-(?:low|medium|high)$", model.lower()) is not None
        if reasoning_effort in {"low", "medium", "high"} and not model_encodes_effort:
            args.extend(["--effort", reasoning_effort])
        completed = _run(
            command or "agy",
            args,
            timeout=cfg.timeout + 10,
            cwd=temp_dir,
            env=os.environ.copy(),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"antigravity_cli_failed:{detail[:500]}")
        content = (completed.stdout or "").strip()
        if not content:
            raise ValueError("antigravity_cli_empty")

    return {"choices": [{"message": {"role": "assistant", "content": content}}]}
