from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from threading import RLock
from typing import Literal

from pydantic import BaseModel

from packages.story_core.env import load_environment_files
from packages.story_core.models import AgentSettings, default_fast_model_name, default_model_name


load_environment_files()


AgentRuntimeName = Literal["character", "director", "writer", "memory"]
AGENT_RUNTIME_NAMES: tuple[AgentRuntimeName, ...] = ("character", "director", "writer", "memory")


class OpenAIRuntimeSettings(BaseModel):
    api_key: str = ""
    base_url: str = ""


def _default_api_key() -> str:
    return os.getenv("OPENAI_API_KEY") or os.getenv("DASHSCOPE_API_KEY", "")


def _default_base_url() -> str:
    return (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("NOVEL_AUTOGROWTH_BASE_URL")
        or "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )


def _with_env_runtime_defaults(settings: OpenAIRuntimeSettings) -> OpenAIRuntimeSettings:
    configured_base = settings.base_url.rstrip("/") if settings.base_url else ""
    default_base = _default_base_url().rstrip("/")
    legacy_empty_openai_default = (
        configured_base == "https://api.openai.com/v1"
        and not settings.api_key
        and default_base != "https://api.openai.com/v1"
    )
    return OpenAIRuntimeSettings(
        api_key=settings.api_key or _default_api_key(),
        base_url=default_base if not configured_base or legacy_empty_openai_default else configured_base,
    )


def _is_legacy_default_strategy(settings: AgentSettings) -> bool:
    return (
        settings.global_model == "gpt-5.4"
        and settings.character_model == "gpt-5.4-mini"
        and settings.director_model == "gpt-5.4"
        and settings.writer_model == "gpt-5.4"
        and settings.memory_model == "gpt-5.4"
        and float(settings.temperature) == 0.7
    )


def _with_env_strategy_defaults(settings: AgentSettings) -> AgentSettings:
    if not _is_legacy_default_strategy(settings):
        return settings
    next_settings = settings.model_copy(deep=True)
    next_settings.global_model = default_model_name()
    next_settings.character_model = default_fast_model_name()
    next_settings.director_model = default_model_name()
    next_settings.writer_model = default_model_name()
    next_settings.memory_model = default_model_name()
    return next_settings


LEGACY_CONFIG_FILE = Path(os.path.dirname(os.path.abspath(__file__))) / "runtime_config.json"
CONFIG_FILE = Path(
    os.getenv(
        "NOVEL_AUTOGROWTH_RUNTIME_CONFIG_PATH",
        str(Path.home() / ".novel-autogrowth-engine" / "runtime_config.json"),
    )
)

_runtime_settings = OpenAIRuntimeSettings(
    api_key=_default_api_key(),
    base_url=_default_base_url(),
)
_agent_runtime_settings: dict[str, OpenAIRuntimeSettings] = {}
_runtime_strategy_settings = AgentSettings()
_lock = RLock()


def _empty_runtime_settings() -> OpenAIRuntimeSettings:
    return OpenAIRuntimeSettings(api_key="", base_url="")


def _partial_runtime_settings(data: dict | None) -> OpenAIRuntimeSettings:
    """Build settings from partial override data without injecting provider defaults."""
    data = data or {}
    return OpenAIRuntimeSettings(
        api_key=data.get("api_key") or "",
        base_url=data.get("base_url") or "",
    )


def _config_candidates() -> list[Path]:
    candidates = [CONFIG_FILE]
    if LEGACY_CONFIG_FILE != CONFIG_FILE:
        candidates.append(LEGACY_CONFIG_FILE)
    return candidates


def _load_config_from_file() -> None:
    """浠庨粯璁ゅ瓨鍌ㄤ綅缃垨鏃у瓨鍌ㄦ枃浠惰杞介厤缃�."""
    global _runtime_settings, _agent_runtime_settings, _runtime_strategy_settings

    for config_path in _config_candidates():
        if not config_path.exists():
            continue

        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if "global" in data:
                _runtime_settings = _with_env_runtime_defaults(OpenAIRuntimeSettings.model_validate(data["global"]))
            if "agents" in data:
                for agent_name, settings in data["agents"].items():
                    if agent_name in AGENT_RUNTIME_NAMES:
                        _agent_runtime_settings[agent_name] = OpenAIRuntimeSettings.model_validate(settings)
            if "strategy" in data:
                _runtime_strategy_settings = _with_env_strategy_defaults(AgentSettings.model_validate(data["strategy"]))

            if config_path == LEGACY_CONFIG_FILE and config_path != CONFIG_FILE:
                _save_config_to_file()
            return
        except Exception:
            # 加载失败时使用默认值。
            continue


def _save_config_to_file() -> None:
    """把当前运行时配置写入用户目录，避免跟工作区文件互相覆盖。"""
    with _lock:
        data = {
            "global": _runtime_settings.model_dump(mode="json"),
            "agents": {
                agent_name: settings.model_dump(mode="json")
                for agent_name, settings in _agent_runtime_settings.items()
            },
            "strategy": _runtime_strategy_settings.model_dump(mode="json"),
        }

        try:
            CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            serialized = json.dumps(data, indent=2, ensure_ascii=False)
            fd, temp_path = tempfile.mkstemp(
                dir=str(CONFIG_FILE.parent),
                prefix="runtime_config_",
                suffix=".json",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    f.write(serialized)
                os.replace(temp_path, CONFIG_FILE)
            finally:
                if os.path.exists(temp_path):
                    try:
                        os.remove(temp_path)
                    except OSError:
                        pass
        except Exception:
            # 保存失败时忽略，继续使用内存中的配置。
            pass


# 初始化时加载配置
_load_config_from_file()


def get_runtime_settings() -> OpenAIRuntimeSettings:
    with _lock:
        return _runtime_settings.model_copy(deep=True)


def set_runtime_settings(settings: OpenAIRuntimeSettings | dict) -> OpenAIRuntimeSettings:
    next_settings = OpenAIRuntimeSettings.model_validate(settings)
    with _lock:
        global _runtime_settings
        _runtime_settings = next_settings
        _save_config_to_file()
        return _runtime_settings.model_copy(deep=True)


def get_agent_runtime_settings(agent_name: AgentRuntimeName) -> OpenAIRuntimeSettings:
    with _lock:
        return _agent_runtime_settings.get(agent_name, _empty_runtime_settings()).model_copy(deep=True)


def set_agent_runtime_settings(
    agent_name: AgentRuntimeName,
    settings: OpenAIRuntimeSettings | dict,
) -> OpenAIRuntimeSettings:
    next_settings = OpenAIRuntimeSettings.model_validate(settings)
    with _lock:
        _agent_runtime_settings[agent_name] = next_settings
        _save_config_to_file()
        return _agent_runtime_settings[agent_name].model_copy(deep=True)


def get_runtime_strategy_settings() -> AgentSettings:
    with _lock:
        return _runtime_strategy_settings.model_copy(deep=True)


def set_runtime_strategy_settings(settings: AgentSettings | dict) -> AgentSettings:
    next_settings = AgentSettings.model_validate(settings)
    with _lock:
        global _runtime_strategy_settings
        _runtime_strategy_settings = next_settings
        _save_config_to_file()
        return _runtime_strategy_settings.model_copy(deep=True)


def get_all_runtime_settings() -> dict[str, object]:
    with _lock:
        return {
            "global": _runtime_settings.model_copy(deep=True),
            "agents": {
                agent_name: _agent_runtime_settings.get(agent_name, _empty_runtime_settings()).model_copy(deep=True)
                for agent_name in AGENT_RUNTIME_NAMES
            },
            "strategy": _runtime_strategy_settings.model_copy(deep=True),
        }


def set_all_runtime_settings(settings: dict) -> dict[str, object]:
    global_settings = settings.get("global")
    if global_settings is not None:
        set_runtime_settings(global_settings)

    agents = settings.get("agents")
    if isinstance(agents, dict):
        for agent_name in AGENT_RUNTIME_NAMES:
            if agent_name in agents:
                set_agent_runtime_settings(agent_name, agents[agent_name])

    strategy = settings.get("strategy")
    if strategy is not None:
        set_runtime_strategy_settings(strategy)

    _save_config_to_file()
    return get_all_runtime_settings()


def resolve_openai_runtime_settings(
    agent_name: AgentRuntimeName | None = None,
    overrides: dict | None = None,
) -> OpenAIRuntimeSettings:
    if overrides is None:
        global_settings = get_runtime_settings()
        agent_settings = get_agent_runtime_settings(agent_name) if agent_name else _empty_runtime_settings()
    else:
        global_settings = _partial_runtime_settings(overrides.get("global"))
        agent_settings = (
            _partial_runtime_settings((overrides.get("agents") or {}).get(agent_name))
            if agent_name
            else _empty_runtime_settings()
        )
    return OpenAIRuntimeSettings(
        api_key=agent_settings.api_key or global_settings.api_key or _default_api_key(),
        # Agent-level base_url overrides global, then env/default provider URL.
        base_url=(
            agent_settings.base_url
            or global_settings.base_url
            or _default_base_url()
        ).rstrip("/"),
    )
