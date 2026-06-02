from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict

from app.llm.providers import resolve_provider


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=("../.env", ".env"),
        extra="ignore",
    )

    llm_api_key: str | None = None
    llm_provider: str = "openai"
    llm_base_url: str | None = None
    llm_model: str | None = None
    llm_http_referer: str | None = None
    llm_app_title: str | None = None
    app_db_url: str = "sqlite:///./data/app.db"

    @property
    def normalized_provider(self) -> str:
        return normalize_optional_string(self.llm_provider) or "openai"

    @property
    def resolved_base_url(self) -> str | None:
        explicit = normalize_optional_string(self.llm_base_url)
        if explicit:
            return explicit

        try:
            return resolve_provider(self.normalized_provider).base_url
        except ValueError:
            return None

    @property
    def resolved_api_key(self) -> str | None:
        explicit = normalize_optional_string(self.llm_api_key)
        if explicit:
            return explicit

        try:
            provider = resolve_provider(self.normalized_provider)
        except ValueError:
            return None
        return provider.placeholder_api_key

    @property
    def is_llm_configured(self) -> bool:
        return bool(
            normalize_optional_string(self.llm_model)
            and self.resolved_base_url
            and self.resolved_api_key
        )


def get_settings() -> Settings:
    settings = Settings()

    from app.llm.config_store import load_ui_config

    ui_config = load_ui_config()
    if ui_config is None:
        return settings
    if ui_config.get("enabled") is False:
        return settings.model_copy(
            update={
                "llm_provider": ui_config["provider"],
                "llm_api_key": None,
                "llm_base_url": None,
                "llm_model": None,
            }
        )
    return settings.model_copy(
        update={
            "llm_provider": ui_config["provider"],
            "llm_api_key": ui_config["api_key"],
            "llm_base_url": ui_config["base_url"],
            "llm_model": ui_config["model"],
        }
    )


def normalize_optional_string(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    return stripped or None
