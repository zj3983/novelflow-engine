"""Built-in model provider metadata and base URL detection."""

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit


ProviderProtocol = Literal[
    "openai_compatible",
    "anthropic",
    "gemini",
    "codex_cli",
]


@dataclass(frozen=True)
class ProviderDefinition:
    provider_id: str
    name: str
    protocol: ProviderProtocol
    default_base_url: str
    planner_models: tuple[str, ...]
    writer_models: tuple[str, ...]
    host_patterns: tuple[str, ...]
    requires_api_key: bool
    base_url_editable: bool
    help_text: str


_PROVIDERS = (
    ProviderDefinition(
        "openai",
        "OpenAI",
        "openai_compatible",
        "https://api.openai.com/v1",
        ("gpt-5", "gpt-4.1"),
        ("gpt-5", "gpt-4.1"),
        ("api.openai.com",),
        True,
        False,
        "OpenAI 官方接口，适合通用规划与长篇写作。",
    ),
    ProviderDefinition(
        "deepseek",
        "DeepSeek",
        "openai_compatible",
        "https://api.deepseek.com/v1",
        ("deepseek-reasoner", "deepseek-chat"),
        ("deepseek-chat", "deepseek-reasoner"),
        ("deepseek.com",),
        True,
        False,
        "DeepSeek 官方兼容接口，推理与中文写作成本友好。",
    ),
    ProviderDefinition(
        "kimi",
        "Kimi",
        "openai_compatible",
        "https://api.moonshot.cn/v1",
        ("kimi-k2.5", "moonshot-v1-128k"),
        ("kimi-k2.5", "moonshot-v1-128k"),
        ("moonshot.cn", "moonshot.ai"),
        True,
        False,
        "Kimi 官方接口，适合中文长上下文任务。",
    ),
    ProviderDefinition(
        "qwen",
        "通义千问",
        "openai_compatible",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        ("qwen3-max", "qwen-plus"),
        ("qwen3-max", "qwen-plus"),
        ("dashscope.aliyuncs.com", "dashscope-intl.aliyuncs.com"),
        True,
        False,
        "阿里云百炼兼容接口，可选多种通义千问模型。",
    ),
    ProviderDefinition(
        "glm",
        "智谱 GLM",
        "openai_compatible",
        "https://open.bigmodel.cn/api/paas/v4",
        ("glm-4.5", "glm-4-plus"),
        ("glm-4.5", "glm-4-plus"),
        ("open.bigmodel.cn",),
        True,
        False,
        "智谱开放平台接口，适合中文规划与创作。",
    ),
    ProviderDefinition(
        "doubao",
        "豆包",
        "openai_compatible",
        "https://ark.cn-beijing.volces.com/api/v3",
        ("doubao-seed-1-6", "doubao-pro-32k"),
        ("doubao-seed-1-6", "doubao-pro-32k"),
        (
            "ark.cn-beijing.volces.com",
            "ark.cn-shanghai.volces.com",
            "ark.ap-southeast-1.volces.com",
        ),
        True,
        False,
        "火山方舟兼容接口，模型名也可填写已创建的推理接入点。",
    ),
    ProviderDefinition(
        "minimax",
        "MiniMax",
        "openai_compatible",
        "https://api.minimaxi.com/v1",
        ("MiniMax-M2.7", "MiniMax-M2.5"),
        ("MiniMax-M2.7", "MiniMax-M2.5"),
        ("api.minimaxi.com", "api.minimax.chat"),
        True,
        False,
        "MiniMax 官方兼容接口，适合长上下文与中文内容生成。",
    ),
    ProviderDefinition(
        "siliconflow",
        "硅基流动",
        "openai_compatible",
        "https://api.siliconflow.cn/v1",
        ("deepseek-ai/DeepSeek-R1", "Qwen/Qwen3-235B-A22B"),
        ("deepseek-ai/DeepSeek-V3", "Qwen/Qwen3-235B-A22B"),
        ("api.siliconflow.cn", "api.siliconflow.com"),
        True,
        False,
        "硅基流动聚合接口，可按账号可用范围选择模型。",
    ),
    ProviderDefinition(
        "openrouter",
        "OpenRouter",
        "openai_compatible",
        "https://openrouter.ai/api/v1",
        ("anthropic/claude-sonnet-4", "openai/gpt-5"),
        ("anthropic/claude-sonnet-4", "openai/gpt-5"),
        ("openrouter.ai",),
        True,
        False,
        "OpenRouter 聚合接口，可使用平台支持的多家模型。",
    ),
    ProviderDefinition(
        "xai",
        "xAI",
        "openai_compatible",
        "https://api.x.ai/v1",
        ("grok-4", "grok-3"),
        ("grok-4", "grok-3"),
        ("api.x.ai",),
        True,
        False,
        "xAI 官方兼容接口，使用 Grok 系列模型。",
    ),
    ProviderDefinition(
        "anthropic",
        "Anthropic",
        "anthropic",
        "https://api.anthropic.com",
        ("claude-opus-4-1", "claude-sonnet-4"),
        ("claude-opus-4-1", "claude-sonnet-4"),
        ("api.anthropic.com",),
        True,
        False,
        "Anthropic 原生接口，适合复杂规划与长文本写作。",
    ),
    ProviderDefinition(
        "gemini",
        "Google Gemini",
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta",
        ("gemini-2.5-pro", "gemini-2.5-flash"),
        ("gemini-2.5-pro", "gemini-2.5-flash"),
        ("generativelanguage.googleapis.com",),
        True,
        False,
        "Google Gemini 原生接口，支持大上下文模型。",
    ),
    ProviderDefinition(
        "ollama",
        "Ollama",
        "openai_compatible",
        "http://localhost:11434/v1",
        ("qwen3:8b", "deepseek-r1:8b"),
        ("qwen3:8b", "qwen2.5:14b"),
        ("localhost", "127.0.0.1", "host.docker.internal"),
        False,
        True,
        "本地 Ollama 服务，无需 API Key，可修改服务地址。",
    ),
    ProviderDefinition(
        "codexcli",
        "Codex CLI",
        "codex_cli",
        "",
        ("gpt-5-codex",),
        ("gpt-5-codex",),
        (),
        False,
        False,
        "调用本机 Codex CLI，认证由 CLI 自身管理。",
    ),
    ProviderDefinition(
        "custom_openai",
        "自定义 OpenAI 兼容接口",
        "openai_compatible",
        "",
        (),
        (),
        (),
        True,
        True,
        "填写任意 OpenAI 兼容地址和模型名称。",
    ),
)

BUILTIN_PROVIDER_IDS = tuple(provider.provider_id for provider in _PROVIDERS)
_PROVIDERS_BY_ID = {provider.provider_id: provider for provider in _PROVIDERS}


def provider_definition(provider_id: str) -> ProviderDefinition:
    """Return metadata for a built-in provider."""

    return _PROVIDERS_BY_ID[provider_id]


def provider_id_for_base_url(base_url: str) -> str:
    """Identify a provider from a URL hostname, preserving hostname boundaries."""

    candidate = base_url.strip()
    parsed = urlsplit(candidate if "://" in candidate else f"//{candidate}")
    hostname = (parsed.hostname or "").lower().rstrip(".")
    for provider in _PROVIDERS:
        if any(
            hostname == pattern or hostname.endswith(f".{pattern}")
            for pattern in provider.host_patterns
        ):
            return provider.provider_id
    return "custom_openai"
