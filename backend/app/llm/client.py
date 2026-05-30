from __future__ import annotations

from typing import Protocol

from openai import OpenAI

from app.config import Settings, get_settings


class LLMClientProtocol(Protocol):
    def complete(self, messages: list[dict[str, str]]) -> str:
        pass


class OpenAICompatibleClient:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.client = OpenAI(
            api_key=settings.resolved_api_key,
            base_url=settings.resolved_base_url,
            default_headers=build_default_headers(settings),
            timeout=60,
        )

    def complete(self, messages: list[dict[str, str]]) -> str:
        response = self.client.chat.completions.create(
            model=self.settings.llm_model,
            messages=messages,
            temperature=0.1,
        )
        content = response.choices[0].message.content
        return content or ""


def get_llm_client(settings: Settings | None = None) -> LLMClientProtocol | None:
    resolved_settings = settings or get_settings()
    if not resolved_settings.is_llm_configured:
        return None
    return OpenAICompatibleClient(resolved_settings)


def build_default_headers(settings: Settings) -> dict[str, str]:
    if settings.normalized_provider != "openrouter":
        return {}

    headers: dict[str, str] = {}
    if settings.llm_http_referer:
        headers["HTTP-Referer"] = settings.llm_http_referer
    if settings.llm_app_title:
        headers["X-OpenRouter-Title"] = settings.llm_app_title
    return headers
