from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProviderPreset:
    name: str
    base_url: str | None
    aliases: tuple[str, ...] = ()
    placeholder_api_key: str | None = None


PROVIDER_PRESETS: tuple[ProviderPreset, ...] = (
    ProviderPreset("openai", "https://api.openai.com/v1"),
    ProviderPreset("openrouter", "https://openrouter.ai/api/v1"),
    ProviderPreset("deepseek", "https://api.deepseek.com"),
    ProviderPreset(
        "dashscope",
        "https://dashscope.aliyuncs.com/compatible-mode/v1",
        aliases=("qwen", "tongyi"),
    ),
    ProviderPreset("kimi", "https://api.moonshot.ai/v1", aliases=("moonshot",)),
    ProviderPreset(
        "zhipu",
        "https://open.bigmodel.cn/api/paas/v4/",
        aliases=("glm", "bigmodel"),
    ),
    ProviderPreset(
        "gemini",
        "https://generativelanguage.googleapis.com/v1beta/openai/",
        aliases=("google",),
    ),
    ProviderPreset(
        "ollama",
        "http://localhost:11434/v1/",
        placeholder_api_key="ollama",
    ),
    ProviderPreset(
        "vllm",
        "http://localhost:8000/v1",
        placeholder_api_key="vllm-local",
    ),
    ProviderPreset("custom", None),
)


def resolve_provider(provider: str | None) -> ProviderPreset:
    normalized = (provider or "openai").strip().lower()
    for preset in PROVIDER_PRESETS:
        if normalized == preset.name or normalized in preset.aliases:
            return preset
    raise ValueError(f"Unsupported LLM provider: {provider}")
