"""测试隔离：避免开发者本地 .env 污染对 LLM 配置敏感的测试。"""
from __future__ import annotations

import pytest

LLM_ENV_VARS = (
    "LLM_API_KEY",
    "LLM_PROVIDER",
    "LLM_BASE_URL",
    "LLM_MODEL",
    "LLM_HTTP_REFERER",
    "LLM_APP_TITLE",
)


@pytest.fixture(autouse=True)
def _isolate_llm_settings(monkeypatch):
    """让 Settings 在测试期间不读 .env，并清掉 LLM_* 环境变量。

    Settings.model_config 的 env_file 在 fixture 内被改为 None；monkeypatch 退出后恢复。
    """
    from app.config import Settings

    isolated_config = {**Settings.model_config, "env_file": None}
    monkeypatch.setattr(Settings, "model_config", isolated_config)
    for key in LLM_ENV_VARS:
        monkeypatch.delenv(key, raising=False)


@pytest.fixture(autouse=True)
def _isolate_app_database(monkeypatch, tmp_path):
    from app.db import engine as engine_module

    existing_urls = set(engine_module._engine_cache)
    monkeypatch.setenv("APP_DB_URL", f"sqlite:///{tmp_path / 'app.db'}")
    yield
    for database_url in set(engine_module._engine_cache) - existing_urls:
        engine_module._engine_cache.pop(database_url).dispose()


@pytest.fixture(autouse=True)
def _isolate_upload_dir(monkeypatch, tmp_path):
    """上传落盘目录与 session 索引隔离到用例临时目录，避免测试写入仓库 data/uploads/。

    uploads.py 以 from-import 绑定了 UPLOAD_DIR / UPLOAD_SESSIONS，两处模块属性须指向同一对象。
    """
    from app.api import runtime, uploads

    upload_dir = tmp_path / "uploads"
    sessions: dict[str, dict[str, str]] = {}
    monkeypatch.setattr(runtime, "DATA_DIR", tmp_path)
    monkeypatch.setattr(runtime, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(runtime, "UPLOAD_SESSIONS", sessions)
    monkeypatch.setattr(uploads, "UPLOAD_DIR", upload_dir)
    monkeypatch.setattr(uploads, "UPLOAD_SESSIONS", sessions)
