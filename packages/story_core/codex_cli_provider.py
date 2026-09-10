from __future__ import annotations

import json
import ntpath
import os
import re
import shutil
import subprocess
import tempfile
import urllib.request
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
    resolved_command = shutil.which(command) or command
    if os.name == "nt" and ntpath.isabs(resolved_command) and not ntpath.splitext(resolved_command)[1]:
        resolved_command = shutil.which(f"{command}.exe") or resolved_command
    lowered = resolved_command.lower()
    if os.name == "nt" and lowered.endswith((".cmd", ".bat")):
        path_ops = (
            ntpath
            if "\\" in resolved_command or ntpath.splitdrive(resolved_command)[0]
            else os.path
        )
        npm_entrypoint = path_ops.normpath(
            path_ops.join(
                path_ops.dirname(resolved_command),
                "node_modules",
                "@openai",
                "codex",
                "bin",
                "codex.js",
            )
        )
        if os.path.isfile(npm_entrypoint):
            node_command = shutil.which("node.exe") or shutil.which("node") or "node"
            return [node_command, npm_entrypoint]
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


def read_codex_cli_models() -> list[str]:
    codex_home = Path(os.getenv("CODEX_HOME") or (Path.home() / ".codex"))
    cache_path = codex_home / "models_cache.json"
    if not cache_path.is_file():
        return []
    try:
        payload = json.loads(cache_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []

    models: list[str] = []
    for item in payload.get("models", []):
        slug = str(item.get("slug", "")).strip() if isinstance(item, dict) else ""
        match = re.match(r"^gpt-(\d+)\.(\d+)(?:-|$)", slug)
        if not match or (int(match.group(1)), int(match.group(2))) < (5, 5):
            continue
        if slug not in models:
            models.append(slug)
    return models


def read_latest_codex_cli_version() -> str:
    request = urllib.request.Request(
        "https://registry.npmjs.org/@openai%2Fcodex/latest",
        headers={"Accept": "application/json", "User-Agent": "novel-autogrowth-engine"},
    )
    with urllib.request.urlopen(request, timeout=3) as response:
        payload = json.loads(response.read().decode("utf-8"))
    version = str(payload.get("version", "")).strip()
    if not re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
        raise RuntimeError("codexcli_latest_version_invalid")
    return version


def codex_cli_update_status(current_version: str, latest_version: str) -> str:
    current_match = re.search(r"(\d+)\.(\d+)\.(\d+)", current_version)
    latest_match = re.search(r"(\d+)\.(\d+)\.(\d+)", latest_version)
    if not current_match or not latest_match:
        return "unknown"
    current = tuple(int(part) for part in current_match.groups())
    latest = tuple(int(part) for part in latest_match.groups())
    return "available" if current < latest else "current"


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
        reasoning_effort = str(payload.get("reasoning_effort") or "").strip().lower()
        if reasoning_effort in {"minimal", "low", "medium", "high", "xhigh"}:
            args.extend(["--config", f'model_reasoning_effort="{reasoning_effort}"'])
        args.append("-")

        completed = subprocess.run(
            args,
            input=prompt,
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            timeout=cfg.timeout,
            cwd=temp_dir,
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
