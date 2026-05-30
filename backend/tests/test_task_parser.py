from __future__ import annotations

from dataclasses import asdict

import pandas as pd
import pytest

from app.config import Settings
from app.llm.client import build_default_headers
from app.llm.providers import resolve_provider
from app.modules.file_ingestion import build_preview, build_schema_summary
from app.modules.reporting import DEFAULT_DIMENSIONS, DEFAULT_METRICS
from app.modules.schemas import DataSourceRef, TableData
from app.modules.task_parser import parse_analysis_goal, sanitize_error


class FakeLLMClient:
    def __init__(self, responses: list[str] | None = None, error: Exception | None = None) -> None:
        self.responses = responses or []
        self.error = error
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        if self.error:
            raise self.error
        if not self.responses:
            raise AssertionError("FakeLLMClient has no queued response")
        return self.responses.pop(0)


def test_provider_preset_resolves_known_base_url():
    assert resolve_provider("deepseek").base_url == "https://api.deepseek.com"
    assert resolve_provider("qwen").base_url == "https://dashscope.aliyuncs.com/compatible-mode/v1"
    assert resolve_provider("glm").base_url == "https://open.bigmodel.cn/api/paas/v4/"


def test_settings_explicit_base_url_overrides_provider_preset():
    settings = Settings(
        llm_api_key="sk-test",
        llm_provider="deepseek",
        llm_base_url="https://proxy.example.com/v1",
        llm_model="demo-model",
    )

    assert settings.resolved_base_url == "https://proxy.example.com/v1"
    assert settings.is_llm_configured is True


def test_custom_provider_requires_explicit_base_url():
    settings = Settings(
        llm_api_key="sk-test",
        llm_provider="custom",
        llm_model="demo-model",
    )

    assert settings.resolved_base_url is None
    assert settings.is_llm_configured is False


def test_openrouter_headers_only_include_configured_attribution_fields():
    empty = Settings(llm_api_key="sk-test", llm_provider="openrouter", llm_model="demo-model")
    configured = Settings(
        llm_api_key="sk-test",
        llm_provider="openrouter",
        llm_model="demo-model",
        llm_http_referer="https://example.com",
        llm_app_title="Data Insight Agent",
    )

    assert build_default_headers(empty) == {}
    assert build_default_headers(configured) == {
        "HTTP-Referer": "https://example.com",
        "X-OpenRouter-Title": "Data Insight Agent",
    }


def test_parse_analysis_goal_returns_default_template_without_llm_configuration():
    table = sample_table()

    result = parse_analysis_goal(
        "帮我生成周度经营复盘",
        asdict(table.data_source_ref),
        table.schema_summary,
        settings=Settings(llm_api_key=None, llm_model=None, llm_base_url=None),
    )

    assert result["task"]["task_title"] == "周度零售经营复盘"
    assert result["task"]["metrics"] == DEFAULT_METRICS
    assert result["task"]["dimensions"] == DEFAULT_DIMENSIONS
    assert result["task"]["context_pack_name"] == "Retail Operations"
    assert result["task"]["context_pack_version"] == "1.0.0"
    assert result["warnings"][0]["code"] == "LLM_NOT_CONFIGURED"


def test_parse_analysis_goal_uses_valid_llm_json_without_overwriting_backend_owned_fields():
    table = sample_table()
    llm = FakeLLMClient(
        [
            """{
              "intent_match": true,
              "task_title": "门店异常复盘",
              "analysis_goal": "不要覆盖用户原始目标",
              "metrics": ["销售额", "退款率"],
              "dimensions": ["门店"],
              "time_range": {"mode": "last_7_days"},
              "comparison": "同比",
              "report_template": "异常复盘",
              "context_pack_name": "Bad Pack",
              "execution_limits": {"max_iterations": 99}
            }"""
        ]
    )

    result = parse_analysis_goal(
        "帮我看异常门店",
        asdict(table.data_source_ref),
        table.schema_summary,
        llm_client=llm,
        settings=configured_settings(),
    )

    task = result["task"]
    assert result["warnings"] == []
    assert task["task_title"] == "门店异常复盘"
    assert task["analysis_goal"] == "帮我看异常门店"
    assert task["metrics"] == ["销售额", "退款率"]
    assert task["dimensions"] == ["门店"]
    assert task["time_range"] == {"mode": "last_7_days"}
    assert task["comparison"] == "同比"
    assert task["report_template"] == "异常复盘"
    assert task["context_pack_name"] == "Retail Operations"
    assert task["execution_limits"]["max_iterations"] == 12
    assert "row-1" not in llm.messages[0][1]["content"]
    assert "上海徐汇旗舰店" not in llm.messages[0][1]["content"]


def test_parse_analysis_goal_retries_bad_json_once_then_uses_default_template():
    table = sample_table()
    llm = FakeLLMClient(["not json", "still not json"])

    result = parse_analysis_goal(
        "帮我看异常门店",
        asdict(table.data_source_ref),
        table.schema_summary,
        llm_client=llm,
        settings=configured_settings(),
    )

    assert len(llm.messages) == 2
    assert result["task"]["task_title"] == "周度零售经营复盘"
    assert result["warnings"][0]["code"] == "LLM_PARSE_FAILED"


def test_parse_analysis_goal_returns_intent_warning_for_non_retail_goal():
    table = sample_table()
    llm = FakeLLMClient(
        [
            """{
              "intent_match": false,
              "task_title": "代码仓库分析",
              "metrics": ["提交数"],
              "dimensions": ["作者"]
            }"""
        ]
    )

    result = parse_analysis_goal(
        "分析我的代码仓库",
        asdict(table.data_source_ref),
        table.schema_summary,
        llm_client=llm,
        settings=configured_settings(),
    )

    assert result["task"]["task_title"] == "周度零售经营复盘"
    assert result["warnings"][0]["code"] == "LLM_INTENT_MISMATCH"


def test_parse_analysis_goal_returns_call_failed_warning_without_retry_when_llm_raises():
    table = sample_table()
    llm = FakeLLMClient(error=RuntimeError("401 unauthorized"))

    result = parse_analysis_goal(
        "帮我看异常门店",
        asdict(table.data_source_ref),
        table.schema_summary,
        llm_client=llm,
        settings=configured_settings(),
    )

    assert len(llm.messages) == 1
    assert result["task"]["task_title"] == "周度零售经营复盘"
    assert result["warnings"][0]["code"] == "LLM_CALL_FAILED"
    assert "401 unauthorized" in result["warnings"][0]["message"]


def sample_table() -> TableData:
    dataframe = pd.DataFrame(
        [
            {
                "order_id": "row-1",
                "order_date": "2026-05-11",
                "net_sales_amount": 1000,
                "store_name": "上海徐汇旗舰店",
                "category_l1": "童装",
                "channel": "线下",
            }
        ]
    )
    return TableData(
        data_source_ref=DataSourceRef(
            id="sample-retail",
            type="csv",
            name="retail_sales_orders.csv",
            location="sample",
        ),
        dataframe=dataframe,
        schema_summary=build_schema_summary(dataframe),
        preview=build_preview(dataframe),
        workbook_sheets=[],
    )


def configured_settings() -> Settings:
    return Settings(
        llm_api_key="sk-test",
        llm_provider="openai",
        llm_model="demo-model",
    )


def test_unknown_provider_name_is_rejected():
    with pytest.raises(ValueError, match="Unsupported LLM provider"):
        resolve_provider("unknown")


def test_sanitize_error_redacts_keys_tokens_and_urls():
    text = sanitize_error(
        RuntimeError(
            "auth failed sk-abc123DEF key=AIzaSyD-1234567890 "
            "header 'Authorization: Bearer tok-xyz.789' at https://api.deepseek.com/v1"
        )
    )

    assert "sk-abc123DEF" not in text
    assert "AIzaSyD-1234567890" not in text
    assert "tok-xyz.789" not in text
    assert "https://api.deepseek.com/v1" not in text
    assert "sk-***" in text
    assert "AIza***" in text
    assert "Bearer ***" in text
    assert "[redacted-url]" in text
