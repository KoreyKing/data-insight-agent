from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from app.config import normalize_optional_string
from app.llm.providers import resolve_provider

LLM_CONFIG_PATH = (
    Path("/app/data/llm_config.json")
    if Path("/app").exists()
    else Path(__file__).resolve().parents[3] / "data" / "llm_config.json"
)


class LLMConfigError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def load_ui_config() -> dict[str, Any] | None:
    if not LLM_CONFIG_PATH.exists():
        return None
    try:
        payload = json.loads(LLM_CONFIG_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        return normalize_config_payload(payload, require_api_key=True, include_updated_at=True)
    except LLMConfigError:
        return None


def save_ui_config(payload: dict[str, Any]) -> dict[str, Any]:
    existing = load_ui_config()
    config = normalize_config_payload(
        payload,
        require_api_key=True,
        include_updated_at=True,
        existing_api_key=existing["api_key"] if existing else None,
    )
    LLM_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    LLM_CONFIG_PATH.write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    os.chmod(LLM_CONFIG_PATH, 0o600)
    return config


def delete_ui_config() -> None:
    try:
        LLM_CONFIG_PATH.unlink()
    except FileNotFoundError:
        return


def normalize_config_payload(
    payload: dict[str, Any],
    *,
    require_api_key: bool,
    include_updated_at: bool = False,
    existing_api_key: str | None = None,
) -> dict[str, Any]:
    provider_name = normalize_optional_string(as_string(payload.get("provider")))
    model = normalize_optional_string(as_string(payload.get("model")))
    api_key = normalize_optional_string(as_string(payload.get("api_key")))
    base_url = normalize_optional_string(as_string(payload.get("base_url")))
    enabled = normalize_enabled(payload.get("enabled", True))

    if provider_name is None:
        raise LLMConfigError("请选择模型供应商。")
    if model is None:
        raise LLMConfigError("请填写模型名称。")

    try:
        preset = resolve_provider(provider_name)
    except ValueError as exc:
        raise LLMConfigError("暂不支持这个模型供应商。") from exc

    if preset.base_url is None and base_url is None:
        raise LLMConfigError("自定义供应商必须填写 Base URL。")
    if api_key is None:
        api_key = normalize_optional_string(existing_api_key)

    if require_api_key and api_key is None and preset.placeholder_api_key is None:
        raise LLMConfigError("请填写 API Key。")

    config: dict[str, Any] = {
        "provider": preset.name,
        "api_key": api_key,
        "base_url": base_url,
        "model": model,
        "enabled": enabled,
    }
    if include_updated_at:
        config["updated_at"] = normalize_optional_string(as_string(payload.get("updated_at"))) or (
            datetime.now(UTC).isoformat(timespec="seconds")
        )
    return config


def llm_config_response(settings: Any, source: str, *, enabled: bool = True) -> dict[str, Any]:
    if source == "none":
        return {
            "provider": None,
            "base_url": None,
            "model": None,
            "has_key": False,
            "source": "none",
            "enabled": True,
        }

    return {
        "provider": settings.normalized_provider,
        "base_url": settings.resolved_base_url,
        "model": settings.llm_model,
        "has_key": bool(settings.resolved_api_key),
        "source": source,
        "enabled": enabled,
    }


def llm_config_response_from_config(config: dict[str, Any]) -> dict[str, Any]:
    try:
        preset = resolve_provider(config["provider"])
    except ValueError:
        preset = resolve_provider("openai")
    return {
        "provider": config["provider"],
        "base_url": config["base_url"] or preset.base_url,
        "model": config["model"],
        "has_key": bool(config["api_key"] or preset.placeholder_api_key),
        "source": "ui",
        "enabled": bool(config.get("enabled", True)),
    }


def sanitize_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    text = re.sub(r"AIza[A-Za-z0-9_-]+", "AIza***", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer ***", text)
    return re.sub(r"https?://\S+", "[redacted-url]", text)


def as_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def normalize_enabled(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return True
    if isinstance(value, (int, float)):
        return value != 0
    return str(value).strip().lower() not in {"0", "false", "no", "off", "disabled"}
