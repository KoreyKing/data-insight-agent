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
