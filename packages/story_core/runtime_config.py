from __future__ import annotations

import json
import os
from threading import RLock
from typing import Literal

from pydantic import BaseModel


AgentRuntimeName = Literal["character", "director", "writer", "memory"]
AGENT_RUNTIME_NAMES: tuple[AgentRuntimeName, ...] = ("character", "director", "writer", "memory")


class OpenAIRuntimeSettings(BaseModel):
    api_key: str = ""
    base_url: str = "https://api.openai.com/v1"


# 配置文件路径
CONFIG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "runtime_config.json")

_runtime_settings = OpenAIRuntimeSettings(
    api_key=os.getenv("OPENAI_API_KEY", ""),
    base_url=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
)
_agent_runtime_settings: dict[str, OpenAIRuntimeSettings] = {}
_lock = RLock()


def _empty_runtime_settings() -> OpenAIRuntimeSettings:
    return OpenAIRuntimeSettings(api_key="", base_url="")


def _load_config_from_file() -> None:
    """从文件加载配置"""
    global _runtime_settings, _agent_runtime_settings
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                if "global" in data:
                    _runtime_settings = OpenAIRuntimeSettings.model_validate(data["global"])
                if "agents" in data:
                    for agent_name, settings in data["agents"].items():
                        if agent_name in AGENT_RUNTIME_NAMES:
                            _agent_runtime_settings[agent_name] = OpenAIRuntimeSettings.model_validate(settings)
        except Exception:
            # 加载失败时使用默认值
            pass


def _save_config_to_file() -> None:
    """保存配置到文件"""
    with _lock:
        data = {
            "global": _runtime_settings.model_dump(),
            "agents": {
                agent_name: settings.model_dump()
                for agent_name, settings in _agent_runtime_settings.items()
            }
        }
        try:
            # 确保目录存在
            os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
            with open(CONFIG_FILE, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception:
            # 保存失败时忽略
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


def get_all_runtime_settings() -> dict[str, object]:
    with _lock:
        return {
            "global": _runtime_settings.model_copy(deep=True),
            "agents": {
                agent_name: _agent_runtime_settings.get(agent_name, _empty_runtime_settings()).model_copy(deep=True)
                for agent_name in AGENT_RUNTIME_NAMES
            },
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
        global_settings = OpenAIRuntimeSettings.model_validate(overrides.get("global", {}))
        agent_settings = (
            OpenAIRuntimeSettings.model_validate(overrides.get("agents", {}).get(agent_name, {}))
            if agent_name
            else _empty_runtime_settings()
        )
    return OpenAIRuntimeSettings(
        api_key=agent_settings.api_key or global_settings.api_key or os.getenv("OPENAI_API_KEY", ""),
        base_url=(
            agent_settings.base_url
            or global_settings.base_url
            or os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")
        ).rstrip("/"),
    )
