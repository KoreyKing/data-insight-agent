import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook

from app.main import app


@pytest.fixture(autouse=True)
def isolated_metadata_db(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", f"sqlite:///{tmp_path / 'metadata.db'}")


def test_sample_dataset_returns_preview_and_valid_profile():
    client = TestClient(app)

    response = client.get("/api/v1/sample-dataset")

    assert response.status_code == 200
    payload = response.json()
    assert payload["data_source_ref"]["type"] == "csv"
    assert payload["context_pack_name"] == "Retail Operations"
    assert payload["context_pack_version"] == "1.0.0"
    assert payload["field_profile"]["is_valid"] is True
    assert 8000 <= payload["row_count"] <= 10000


def test_upload_csv_returns_session_preview_and_profile(tmp_path: Path):
    source = tmp_path / "orders.csv"
    source.write_text(
        "订单日期,销售额,门店,类目,渠道\n2026-05-11,1000,上海徐汇旗舰店,童装,线下\n",
        encoding="utf-8",
    )
    client = TestClient(app)

    with source.open("rb") as file_handle:
        response = client.post(
            "/api/v1/uploads",
            files={"file": ("orders.csv", file_handle, "text/csv")},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"]
    assert payload["context_pack_name"] == "Retail Operations"
    assert payload["context_pack_version"] == "1.0.0"
    assert payload["field_profile"]["is_valid"] is True
    assert payload["preview"]["head"][0]["门店"] == "上海徐汇旗舰店"


def test_upload_xlsx_and_switch_sheet(tmp_path: Path):
    source = tmp_path / "orders.xlsx"
    workbook = Workbook()
    first = workbook.active
    first.title = "may"
    first.append(["order_date", "net_sales_amount", "store_name", "category_l1", "channel"])
    first.append(["2026-05-11", 1200, "上海徐汇旗舰店", "童装", "线下"])
    second = workbook.create_sheet("june")
    second.append(["订单日期", "销售额", "门店", "类目", "渠道"])
    second.append(["2026-06-01", 500, "广州天河店", "服装", "抖音"])
    workbook.save(source)
    client = TestClient(app)

    with source.open("rb") as file_handle:
        upload_response = client.post(
            "/api/v1/uploads",
            files={
                "file": (
                    "orders.xlsx",
                    file_handle,
                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            },
        )

    assert upload_response.status_code == 200
    session_id = upload_response.json()["session_id"]
    sheet_response = client.get(f"/api/v1/uploads/{session_id}", params={"sheet": "june"})

    assert sheet_response.status_code == 200
    assert sheet_response.json()["selected_sheet"] == "june"
    assert sheet_response.json()["preview"]["head"][0]["门店"] == "广州天河店"


def test_upload_xls_returns_unsupported_type(tmp_path: Path):
    source = tmp_path / "orders.xls"
    source.write_bytes(b"legacy")
    client = TestClient(app)

    with source.open("rb") as file_handle:
        response = client.post(
            "/api/v1/uploads",
            files={"file": ("orders.xls", file_handle, "application/vnd.ms-excel")},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "UNSUPPORTED_FILE_TYPE"


def test_parse_task_uses_default_template_without_llm_configuration(monkeypatch):
    for name in ["LLM_API_KEY", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    client = TestClient(app)

    response = client.post(
        "/api/v1/tasks/parse",
        json={
            "analysis_goal": "帮我生成周度经营复盘，重点看异常门店和商品",
            "data_source_ref": {
                "id": "sample-retail",
                "type": "csv",
                "name": "sample",
                "location": "sample",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["task"]["task_title"] == "周度零售经营复盘"
    assert payload["task"]["context_pack_name"] == "Retail Operations"
    assert payload["task"]["context_pack_version"] == "1.0.0"
    assert payload["task"]["data_source_ref"]["id"] == "sample-retail"
    assert payload["warnings"] == [
        {
            "code": "LLM_NOT_CONFIGURED",
            "message": (
                "体验模式：当前未配置 AI 大模型，使用默认模板产出示例报告。"
                "配置模型后，可用自然语言定制分析。"
            ),
        }
    ]


def test_model_status_not_configured_without_env(monkeypatch):
    for name in ["LLM_API_KEY", "LLM_PROVIDER", "LLM_BASE_URL", "LLM_MODEL"]:
        monkeypatch.delenv(name, raising=False)
    client = TestClient(app)

    response = client.get("/api/v1/model-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload == {"status": "not_configured"}


def test_model_status_returns_provider_preset_without_secrets(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "deepseek")
    monkeypatch.setenv("LLM_API_KEY", "sk-secret-should-not-leak")
    monkeypatch.setenv("LLM_MODEL", "deepseek-chat")
    monkeypatch.delenv("LLM_BASE_URL", raising=False)
    client = TestClient(app)

    response = client.get("/api/v1/model-status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "configured"
    assert payload["model"] == "deepseek-chat"
    assert payload["provider"] == "deepseek"
    serialized = json.dumps(payload)
    assert "sk-secret-should-not-leak" not in serialized
    assert "api.deepseek.com" not in serialized
    assert "base_url" not in payload
    assert "api_key" not in payload


def test_run_report_returns_traceable_findings_for_sample_dataset():
    client = TestClient(app)

    response = client.post(
        "/api/v1/reports/run",
        json={
            "analysis_goal": "帮我生成周度经营复盘",
            "data_source_ref": {
                "id": "sample-retail",
                "type": "csv",
                "name": "sample",
                "location": "sample",
            },
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["report"]["title"] == "周度零售经营复盘"
    assert payload["report"]["kpis"]
    assert payload["report"]["findings"]
    for finding in payload["report"]["findings"]:
        evidence = finding["evidence"]
        assert evidence["sql"].lstrip().startswith("SELECT")
        assert "exec_ms" in evidence
        assert "row_count" in evidence
        assert "validated_by" in evidence
        assert evidence["validated_by"] == "sql_validator"
        assert finding["chart"]["echarts_spec"]["series"][0]["data"]
    assert payload["report"]["metadata"]["data_source"]["type"] == "csv"


def test_run_report_uses_analysis_loop_when_llm_is_configured(monkeypatch):
    class FakeLLMClient:
        def __init__(self):
            self.responses = [
                {
                    "tool": "record_finding",
                    "args": {
                        "type": "trend",
                        "text": "样例数据已进入 Analysis Loop。",
                        "evidence": "manual-observation",
                        "confidence": "medium",
                    },
                },
                {"tool": "finish", "args": {"summary": "Analysis Loop 已完成。"}},
            ]

        def complete(self, messages):
            return json.dumps(self.responses.pop(0), ensure_ascii=False)

    monkeypatch.setattr("app.api.reports.get_llm_client", lambda _settings=None: FakeLLMClient())
    client = TestClient(app)

    response = client.post(
        "/api/v1/reports/run",
        json={
            "analysis_goal": "帮我生成周度经营复盘",
            "task": {
                "execution_limits": {
                    "max_iterations": 8,
                    "max_tokens": 50000,
                    "max_duration_seconds": 300,
                }
            },
            "data_source_ref": {
                "id": "sample-retail",
                "type": "csv",
                "name": "sample",
                "location": "sample",
            },
        },
    )

    assert response.status_code == 200
    report = response.json()["report"]
    assert report["summary"] == "Analysis Loop 已完成。"
    assert report["findings"][0]["text"] == "样例数据已进入 Analysis Loop。"
    assert report["analysis_steps"][0]["tool"] == "record_finding"
    assert report["metadata"]["iterations_used"] == 2
    # composer 统一出口：Loop 报告补齐 context_pack 身份与 byline 所需 time_range
    assert report["context_pack_name"] == "Retail Operations"
    assert set(report["metadata"]["time_range"]) == {
        "current_start",
        "current_end",
        "previous_start",
        "previous_end",
    }
