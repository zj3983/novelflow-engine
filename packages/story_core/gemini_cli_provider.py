"""Text-only Gemini CLI backend using the CLI's Google account login."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any

from packages.story_core.codex_cli_provider import _build_prompt
from packages.story_core.http_retry import RetryConfig


def _gemini_command_prefix(command: str = "gemini") -> list[str]:
    resolved = shutil.which(command or "gemini") or (command or "gemini")
    path = Path(resolved)
    if path.suffix.lower() in {".cmd", ".bat", ".ps1"}:
        # Run npm's JS entry directly: large Chinese prompts belong on stdin,
        # never in cmd.exe's argument string.
        for package in (path.parent.parent / "@google/gemini-cli", path.parent / "node_modules/@google/gemini-cli"):
            metadata = package / "package.json"
            if metadata.is_file():
                entry = json.loads(metadata.read_text(encoding="utf-8"))["bin"]["gemini"]
                return [shutil.which("node") or "node", str(package / entry)]
        raise RuntimeError("gemini_cli_not_installed")
    return [resolved]


def post_json_via_gemini_cli(
    payload: dict[str, Any], *, command: str = "gemini", config: RetryConfig | None = None,
) -> dict[str, Any]:
    cfg = config or RetryConfig()
    model = str(payload.get("model") or "").strip()
    if not model:
        raise ValueError("gemini_cli_model_required")
    env = os.environ.copy()
    for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY", "GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_GENAI_USE_GCA", "GEMINI_MODEL", "GEMINI_SYSTEM_MD", "GEMINI_CLI_SYSTEM_SETTINGS_PATH", "GEMINI_CLI_SYSTEM_DEFAULTS_PATH"):
        env.pop(key, None)
    with tempfile.TemporaryDirectory(prefix="novel_geminicli_") as temp_dir:
        settings_dir = Path(temp_dir) / ".gemini"
        settings_dir.mkdir()
        (settings_dir / "settings.json").write_text(json.dumps({
            "security": {"auth": {"selectedType": "oauth-personal", "enforcedType": "oauth-personal"}},
            "tools": {"core": []},
            "hooksConfig": {"enabled": False},
            "mcp": {"allowed": []},
            "context": {"fileName": []},
            "advanced": {"ignoreLocalEnv": True},
        }), encoding="utf-8")
        policy = Path(temp_dir) / "text-only.toml"
        policy.write_text('[[rule]]\ntoolName = "*"\ndecision = "deny"\npriority = 999\n', encoding="utf-8")
        args = [*_gemini_command_prefix(command), "--prompt", "请按标准输入中的要求输出最终答案。", "--model", model, "--output-format", "json", "--extensions", "none", "--policy", str(policy), "--skip-trust"]
        try:
            completed = subprocess.run(args, input=_build_prompt(payload), text=True, encoding="utf-8", errors="replace", capture_output=True, timeout=cfg.timeout, cwd=temp_dir, env=env)
        except FileNotFoundError as exc:
            raise RuntimeError("gemini_cli_not_installed") from exc
        try:
            output = json.loads(completed.stdout.strip())
        except (json.JSONDecodeError, TypeError) as exc:
            if completed.returncode:
                raise RuntimeError(_failure_code(completed.stderr)) from exc
            raise ValueError("gemini_cli_invalid_response") from exc
        if not isinstance(output, dict):
            raise ValueError("gemini_cli_invalid_response")
        if completed.returncode or output.get("error"):
            # Never expose raw CLI stderr, OAuth URLs, or credential contents.
            raise RuntimeError(_failure_code(json.dumps(output.get("error")) + completed.stderr))
        content = output.get("response")
        if not isinstance(content, str) or not content.strip():
            raise ValueError("gemini_cli_empty")
    return {"choices": [{"message": {"role": "assistant", "content": content.strip()}}]}


def _failure_code(detail: str) -> str:
    lowered = detail.lower()
    if any(marker in lowered for marker in ("ineligibletiererror", "unsupported_client", "this client is no longer supported")):
        return "gemini_cli_account_unsupported"
    if "invalid configuration" in lowered:
        return "gemini_cli_config_invalid"
    if any(marker in lowered for marker in ("autherror", "error authenticating", "please login", "please log in", "please sign in", "not logged in", "no authentication", "authentication required", "invalid_grant", "credentials not found", "invalid credentials")):
        return "gemini_cli_login_required"
    return "gemini_cli_failed"
