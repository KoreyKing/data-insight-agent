from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.config import Settings, get_settings
from app.llm.client import OpenAICompatibleClient
from app.llm.config_store import (
    LLMConfigError,
    delete_ui_config,
    llm_config_response,
    llm_config_response_from_config,
    load_ui_config,
    normalize_config_payload,
    sanitize_error,
    save_ui_config,
)

router = APIRouter()


@router.get("/model-status")
def model_status() -> dict[str, Any]:
    ui_config = load_ui_config()
    if ui_config is not None and ui_config.get("enabled") is False:
        return {
            "status": "disabled",
            "model": ui_config["model"],
            "provider": ui_config["provider"],
        }
    settings = get_settings()
    if not settings.is_llm_configured:
        return {"status": "not_configured"}
    return {
        "status": "configured",
        "model": settings.llm_model,
        "provider": settings.normalized_provider,
    }


@router.get("/llm-config")
def get_llm_config() -> dict[str, Any]:
    ui_config = load_ui_config()
    if ui_config is not None:
        return llm_config_response_from_config(ui_config)
    settings = get_settings()
    if settings.is_llm_configured:
        return llm_config_response(settings, "env")
    return llm_config_response(settings, "none")


@router.post("/llm-config")
def save_llm_config(payload: dict[str, Any]):
    try:
        save_ui_config(payload)
    except LLMConfigError as exc:
        return config_error_response(exc.message)
    return model_status()


@router.post("/llm-config/test")
def test_llm_config(payload: dict[str, Any]) -> dict[str, Any]:
    try:
        existing = load_ui_config()
        config = normalize_config_payload(
            payload,
            require_api_key=True,
            existing_api_key=existing["api_key"] if existing else None,
        )
        settings = Settings(
            llm_provider=config["provider"],
            llm_api_key=config["api_key"],
            llm_base_url=config["base_url"],
            llm_model=config["model"],
        )
        OpenAICompatibleClient(settings).complete(
            [{"role": "user", "content": "Reply with ok to verify connectivity."}]
        )
    except LLMConfigError as exc:
        return {"ok": False, "error": exc.message}
    except Exception as exc:
        return {"ok": False, "error": sanitize_error(exc)}
    return {"ok": True}


@router.delete("/llm-config")
def delete_llm_config() -> dict[str, Any]:
    delete_ui_config()
    return model_status()


def config_error_response(message: str) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": "LLM_CONFIG_INVALID", "message": message},
    )
