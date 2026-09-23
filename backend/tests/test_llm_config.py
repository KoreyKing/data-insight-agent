import json
import stat
from pathlib import Path

from fastapi.testclient import TestClient

from app.config import Settings, get_settings
from app.main import app


def isolated_config_path(monkeypatch, tmp_path: Path) -> Path:
    config_path = tmp_path / "llm_config.json"
    monkeypatch.setattr("app.llm.config_store.LLM_CONFIG_PATH", config_path)
    return config_path


def test_get_llm_config_returns_none_source_without_secrets(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.get("/api/v1/llm-config")

    assert response.status_code == 200
    assert response.json() == {
        "provider": None,
        "base_url": None,
        "model": None,
        "has_key": False,
        "source": "none",
        "enabled": True,
    }


def test_get_llm_config_returns_env_source_without_api_key(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "sk-env-secret")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    client = TestClient(app)

    response = client.get("/api/v1/llm-config")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "has_key": True,
        "source": "env",
        "enabled": True,
    }
    assert "sk-env-secret" not in json.dumps(payload)


def test_post_llm_config_saves_fixed_fields_with_0600_permissions(monkeypatch, tmp_path: Path):
    config_path = isolated_config_path(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/llm-config",
        json={
            "provider": "deepseek",
            "api_key": "sk-ui-secret",
            "base_url": "",
            "model": "deepseek-chat",
            "ignored": "field",
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "configured",
        "model": "deepseek-chat",
        "provider": "deepseek",
    }
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert set(saved) == {"provider", "api_key", "base_url", "model", "enabled", "updated_at"}
    assert saved["provider"] == "deepseek"
    assert saved["api_key"] == "sk-ui-secret"
    assert saved["base_url"] is None
    assert saved["model"] == "deepseek-chat"
    assert saved["enabled"] is True
    assert stat.S_IMODE(config_path.stat().st_mode) == 0o600


def test_ui_config_overrides_env_and_delete_falls_back_to_env(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-env-secret")
    monkeypatch.setenv("LLM_MODEL", "gpt-env")
    client = TestClient(app)

    save_response = client.post(
        "/api/v1/llm-config",
        json={
            "provider": "deepseek",
            "api_key": "sk-ui-secret",
            "base_url": "https://proxy.example.com/v1",
            "model": "deepseek-chat",
        },
    )
    assert save_response.status_code == 200

    settings = get_settings()
    assert settings.llm_provider == "deepseek"
    assert settings.llm_api_key == "sk-ui-secret"
    assert settings.llm_base_url == "https://proxy.example.com/v1"
    assert settings.llm_model == "deepseek-chat"
    get_response = client.get("/api/v1/llm-config")
    assert get_response.json()["source"] == "ui"
    assert get_response.json()["model"] == "deepseek-chat"

    delete_response = client.delete("/api/v1/llm-config")

    assert delete_response.status_code == 200
    assert delete_response.json() == {
        "status": "configured",
        "model": "gpt-env",
        "provider": "openai",
    }
    fallback = client.get("/api/v1/llm-config").json()
    assert fallback["source"] == "env"
    assert fallback["model"] == "gpt-env"
    assert fallback["enabled"] is True


def test_disabled_ui_config_controls_model_status_without_env_fallback(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("LLM_API_KEY", "sk-env-secret")
    monkeypatch.setenv("LLM_MODEL", "gpt-env")
    client = TestClient(app)

    save_response = client.post(
        "/api/v1/llm-config",
        json={
            "provider": "deepseek",
            "api_key": "sk-ui-secret",
            "model": "deepseek-chat",
            "enabled": False,
        },
    )

    assert save_response.status_code == 200
    assert save_response.json() == {
        "status": "disabled",
        "model": "deepseek-chat",
        "provider": "deepseek",
    }
    settings = get_settings()
    assert settings.is_llm_configured is False
    assert settings.llm_api_key is None
    assert settings.llm_model is None
    get_response = client.get("/api/v1/llm-config")
    assert get_response.json() == {
        "provider": "deepseek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-chat",
        "has_key": True,
        "source": "ui",
        "enabled": False,
    }


def test_post_llm_config_preserves_existing_key_when_api_key_is_omitted(
    monkeypatch,
    tmp_path: Path,
):
    config_path = isolated_config_path(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post(
        "/api/v1/llm-config",
        json={
            "provider": "deepseek",
            "api_key": "sk-ui-secret",
            "model": "deepseek-chat",
        },
    )

    response = client.post(
        "/api/v1/llm-config",
        json={
            "provider": "deepseek",
            "base_url": "https://proxy.example.com/v1",
            "model": "deepseek-reasoner",
            "enabled": True,
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "status": "configured",
        "model": "deepseek-reasoner",
        "provider": "deepseek",
    }
    saved = json.loads(config_path.read_text(encoding="utf-8"))
    assert saved["api_key"] == "sk-ui-secret"
    assert saved["model"] == "deepseek-reasoner"


def test_llm_config_test_endpoint_reuses_saved_key_without_persisting(
    monkeypatch,
    tmp_path: Path,
):
    config_path = isolated_config_path(monkeypatch, tmp_path)
    calls = []

    class FakeClient:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def complete(self, messages):
            calls.append({"settings": self.settings, "messages": messages})
            return "ok"

    monkeypatch.setattr("app.api.llm_config.OpenAICompatibleClient", FakeClient)
    client = TestClient(app)
    client.post(
        "/api/v1/llm-config",
        json={
            "provider": "deepseek",
            "api_key": "sk-saved-secret",
            "model": "deepseek-chat",
        },
    )
    before = config_path.read_text(encoding="utf-8")

    response = client.post(
        "/api/v1/llm-config/test",
        json={"provider": "deepseek", "model": "deepseek-reasoner"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert calls[0]["settings"].llm_api_key == "sk-saved-secret"
    assert calls[0]["settings"].llm_model == "deepseek-reasoner"
    assert config_path.read_text(encoding="utf-8") == before


def test_delete_llm_config_without_env_returns_not_configured(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    client = TestClient(app)
    client.post(
        "/api/v1/llm-config",
        json={
            "provider": "deepseek",
            "api_key": "sk-ui-secret",
            "model": "deepseek-chat",
        },
    )

    response = client.delete("/api/v1/llm-config")

    assert response.status_code == 200
    assert response.json() == {"status": "not_configured"}
    assert client.get("/api/v1/llm-config").json()["source"] == "none"


def test_post_llm_config_validates_required_fields(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    client = TestClient(app)

    missing_model = client.post(
        "/api/v1/llm-config",
        json={"provider": "deepseek", "api_key": "sk-ui-secret"},
    )
    missing_key = client.post(
        "/api/v1/llm-config",
        json={"provider": "deepseek", "model": "deepseek-chat"},
    )
    missing_base_url = client.post(
        "/api/v1/llm-config",
        json={"provider": "custom", "api_key": "sk-custom", "model": "custom-model"},
    )

    assert missing_model.status_code == 400
    assert missing_model.json()["code"] == "LLM_CONFIG_INVALID"
    assert missing_key.status_code == 400
    assert missing_key.json()["code"] == "LLM_CONFIG_INVALID"
    assert missing_base_url.status_code == 400
    assert missing_base_url.json()["code"] == "LLM_CONFIG_INVALID"


def test_local_provider_can_use_placeholder_api_key(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    client = TestClient(app)

    response = client.post(
        "/api/v1/llm-config",
        json={"provider": "ollama", "model": "llama3.1"},
    )

    assert response.status_code == 200
    settings = get_settings()
    assert settings.resolved_api_key == "ollama"
    assert settings.is_llm_configured is True


def test_llm_config_test_endpoint_success_and_failure_do_not_persist(
    monkeypatch,
    tmp_path: Path,
):
    config_path = isolated_config_path(monkeypatch, tmp_path)
    calls = []

    class FakeClient:
        def __init__(self, settings: Settings) -> None:
            self.settings = settings

        def complete(self, messages):
            calls.append({"settings": self.settings, "messages": messages})
            if self.settings.llm_model == "bad-model":
                raise RuntimeError(
                    "auth failed sk-test-secret at https://api.deepseek.com/v1 "
                    "Authorization: Bearer tok-secret"
                )
            return "ok"

    monkeypatch.setattr("app.api.llm_config.OpenAICompatibleClient", FakeClient)
    client = TestClient(app)

    success = client.post(
        "/api/v1/llm-config/test",
        json={"provider": "deepseek", "api_key": "sk-test-secret", "model": "deepseek-chat"},
    )
    failure = client.post(
        "/api/v1/llm-config/test",
        json={"provider": "deepseek", "api_key": "sk-test-secret", "model": "bad-model"},
    )

    assert success.status_code == 200
    assert success.json() == {"ok": True}
    assert failure.status_code == 200
    payload = failure.json()
    assert payload["ok"] is False
    assert "sk-test-secret" not in payload["error"]
    assert "tok-secret" not in payload["error"]
    assert "[redacted-url]" in payload["error"]
    assert not config_path.exists()
    assert calls[0]["settings"].llm_model == "deepseek-chat"


def test_app_db_url_defaults_and_env_override(monkeypatch, tmp_path: Path):
    isolated_config_path(monkeypatch, tmp_path)
    monkeypatch.delenv("APP_DB_URL")

    assert get_settings().app_db_url == "sqlite:///./data/app.db"

    monkeypatch.setenv("APP_DB_URL", "sqlite:////tmp/custom.db")

    assert get_settings().app_db_url == "sqlite:////tmp/custom.db"
