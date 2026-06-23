from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from packages.story_core.http_retry import RetryConfig


def _message_text(message: dict[str, Any]) -> str:
    content = message.get("content", "")
    if isinstance(content, list):
        parts: list[str] = []
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
    messages = payload.get("messages") or []
    sections: list[str] = [
        "你是小说写作系统里的模型后端。",
        "只输出最终内容，不要解释你在做什么，不要调用工具，不要修改文件。",
    ]
    if payload.get("response_format", {}).get("type") == "json_object":
        sections.append("本次必须只返回一个合法 JSON 对象，不能包裹 Markdown 代码块。")
    for message in messages:
        if not isinstance(message, dict):
            continue
        role = str(message.get("role") or "user").upper()
        text = _message_text(message)
        if text:
            sections.append(f"[{role}]\n{text}")
    return "\n\n".join(sections).strip()


def post_json_via_codex_cli(
    payload: dict[str, Any],
    *,
    command: str = "codex",
    config: RetryConfig | None = None,
) -> dict:
    cfg = config or RetryConfig()
    prompt = _build_prompt(payload)
    model = str(payload.get("model") or "").strip()
    command = command or "codex"

    with tempfile.TemporaryDirectory(prefix="novel_codexcli_") as temp_dir:
        output_path = Path(temp_dir) / "last_message.txt"
        resolved_command = shutil.which(command) or command
        command_prefix = (
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolved_command]
            if resolved_command.lower().endswith(".ps1")
            else [resolved_command]
        )
        args = [
            *command_prefix,
            "exec",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
            "--color",
            "never",
        ]
        if model and os.getenv("NOVEL_CODEX_USE_PAYLOAD_MODEL", "").strip() in {"1", "true", "yes"}:
            args.extend(["--model", model])
        args.append("-")

        completed = subprocess.run(
            args,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=cfg.timeout,
            cwd=os.getcwd(),
        )
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "").strip()
            raise RuntimeError(f"codexcli_failed:{detail[:500]}")

        content = output_path.read_text(encoding="utf-8").strip() if output_path.exists() else ""
        if not content:
            content = (completed.stdout or "").strip()

    return {
        "choices": [
            {
                "message": {
                    "role": "assistant",
                    "content": content,
                }
            }
        ]
    }
