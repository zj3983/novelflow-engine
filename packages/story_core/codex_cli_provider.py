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


def _codex_command_prefix(command: str) -> list[str]:
    command = command or "codex"
    executable = shutil.which(f"{command}.exe") if not Path(command).suffix else None
    resolved_command = executable or shutil.which(command) or command
    lowered = resolved_command.lower()
    if lowered.endswith(".ps1"):
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", resolved_command]
    if lowered.endswith((".cmd", ".bat")):
        return ["cmd", "/d", "/c", resolved_command]
    return [resolved_command]


def read_codex_cli_version(command: str = "codex") -> str:
    completed = subprocess.run(
        [*_codex_command_prefix(command), "--version"],
        text=True,
        encoding="utf-8",
        errors="replace",
        capture_output=True,
        timeout=10,
    )
    if completed.returncode != 0:
        detail = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(f"codexcli_version_failed:{detail[:200]}")
    version = (completed.stdout or completed.stderr or "").strip()
    if not version:
        raise RuntimeError("codexcli_version_empty")
    return version.splitlines()[0].strip()


def post_json_via_codex_cli(
    payload: dict[str, Any],
    *,
    command: str = "codex",
    config: RetryConfig | None = None,
) -> dict:
    cfg = config or RetryConfig()
    prompt = _build_prompt(payload)
    model = str(payload.get("model") or "").strip()
    if not model:
        raise ValueError("codexcli_model_required")
    command = command or "codex"

    with tempfile.TemporaryDirectory(prefix="novel_codexcli_") as temp_dir:
        isolated_codex_home = Path(temp_dir) / "codex_home"
        isolated_codex_home.mkdir()
        source_codex_home = Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex"))
        source_auth = source_codex_home / "auth.json"
        if source_auth.is_file():
            shutil.copy2(source_auth, isolated_codex_home / "auth.json")
        for filename in ("cap_sid", "installation_id"):
            source_file = source_codex_home / filename
            if source_file.is_file():
                shutil.copy2(source_file, isolated_codex_home / filename)
        source_models_cache = source_codex_home / "models_cache.json"
        if source_models_cache.is_file():
            cache_text = source_models_cache.read_text(encoding="utf-8")
            cache_text = cache_text.replace('"effort": "max"', '"effort": "high"')
            (isolated_codex_home / "models_cache.json").write_text(cache_text, encoding="utf-8")
        subprocess_env = os.environ.copy()
        subprocess_env["CODEX_HOME"] = str(isolated_codex_home)
        output_path = Path(temp_dir) / "last_message.txt"
        command_prefix = _codex_command_prefix(command)
        args = [
            *command_prefix,
            "exec",
            "--ignore-user-config",
            "--ignore-rules",
            "--ephemeral",
            "--sandbox",
            "read-only",
            "--skip-git-repo-check",
            "--output-last-message",
            str(output_path),
            "--color",
            "never",
        ]
        if model:
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
            env=subprocess_env,
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
