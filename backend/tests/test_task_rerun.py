from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.db.engine import SessionLocal, get_engine
from app.db.models import AnalysisTask, Dataset, Report
from app.main import app
from app.modules.report_runner import execute_report_run
from app.modules.reporting import default_structured_task
from app.modules.sample_data import load_retail_sample


@pytest.fixture(autouse=True)
def isolated_metadata_db(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", f"sqlite:///{tmp_path / 'metadata.db'}")


def test_execute_report_run_persists_unlinked_report_in_experience_mode(monkeypatch):
    monkeypatch.setattr("app.modules.report_runner.get_llm_client", lambda _settings=None: None)
    table = load_retail_sample()
    task = default_structured_task(
        "帮我生成周度经营复盘",
        asdict(table.data_source_ref),
    )

    report_id, report = execute_report_run(table, task)

    assert report_id
    assert report["status"] == "completed"
    with SessionLocal(bind=get_engine()) as session:
        stored = session.get(Report, report_id)
        assert stored is not None
        assert stored.task_id is None


def test_rerun_same_schema_creates_linked_report_and_updates_data_source_ref(tmp_path: Path):
    with TestClient(app) as client:
        task_id, founding_snapshot = create_task_from_csv(client)
        rerun_source = upload_csv(client, "same-schema.csv", base_csv_bytes())
        before = persisted_counts()
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": rerun_source},
        )
        assert response.status_code == 200

        task_response = client.get(f"/api/v1/tasks/{task_id}")
        report_response = client.get(f"/api/v1/reports/{response.json()['report_id']}")

    assert set(response.json()) == {"report_id", "report"}
    assert response.json()["report"]["metadata"]["data_source"]["location"] == "same-schema.csv"
    assert str(tmp_path) not in response.text
    assert str(Path.cwd()) not in response.text
    assert task_response.status_code == 200
    assert task_response.json()["report_count"] == 2
    assert report_response.status_code == 200
    assert report_response.json()["task_id"] == task_id
    assert str(Path.cwd()) not in task_response.text
    assert str(Path.cwd()) not in report_response.text

    with SessionLocal(bind=get_engine()) as session:
        task = session.get(AnalysisTask, task_id)
        report = session.get(Report, response.json()["report_id"])
        assert task is not None
        assert report is not None
        assert task.structured_task_json == founding_snapshot
        assert report.structured_task_json["data_source_ref"]["id"] == rerun_source["id"]
        assert report.task_id == task_id
    assert persisted_counts() == (before[0] + 1, before[1] + 1)


def test_rerun_sanitizes_failed_response_path(monkeypatch, tmp_path: Path):
    monkeypatch.setattr("app.api.uploads.UPLOAD_DIR", tmp_path / "uploads")
    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        rerun_source = upload_csv(client, "same-schema.csv", base_csv_bytes())

        def failed_report(
            table,
            task,
            *,
            task_id=None,
            history_context=None,
            context_pack=None,
        ):
            return "failed-report", {
                "status": "failed",
                "metadata": {"data_source": asdict(table.data_source_ref)},
            }

        monkeypatch.setattr("app.api.tasks.execute_report_run", failed_report)
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": rerun_source},
        )
        task_response = client.get(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 400
    assert set(response.json()) == {"code", "report"}
    assert response.json()["code"] == "CSV_KEY_FIELD_MISSING"
    assert response.json()["report"]["metadata"]["data_source"]["location"] == "same-schema.csv"
    assert str(tmp_path) not in response.text
    assert task_response.status_code == 200
    assert task_response.json()["report_count"] == 1


def test_rerun_rejects_missing_fields_without_persisting_report():
    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        source = upload_csv(
            client,
            "missing-channel-and-category.csv",
            csv_bytes(include_category=False, include_channel=False),
        )
        before = persisted_counts()
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": source},
        )

    assert response.status_code == 400
    assert response.json() == {
        "code": "SCHEMA_MISMATCH",
        "message": "新文件的数据结构与这个任务不一致，无法对比重跑。",
        "details": {
            "missing_fields": ["category_l1", "channel"],
            "extra_fields": [],
            "missing_fields_display": ["商品类目", "销售渠道"],
            "extra_fields_display": [],
        },
    }
    assert persisted_counts() == before


def test_rerun_rejects_extra_fields_without_persisting_report():
    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        source = upload_csv(
            client,
            "extra-order-id-and-cost.csv",
            csv_bytes(include_order_id=True, include_unit_cost=True),
        )
        before = persisted_counts()
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": source},
        )

    assert response.status_code == 400
    assert response.json() == {
        "code": "SCHEMA_MISMATCH",
        "message": "新文件的数据结构与这个任务不一致，无法对比重跑。",
        "details": {
            "missing_fields": [],
            "extra_fields": ["order_id", "unit_cost"],
            "missing_fields_display": [],
            "extra_fields_display": ["订单编号", "单位成本"],
        },
    }
    assert persisted_counts() == before


def test_rerun_rejects_expired_upload_session():
    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        before = persisted_counts()
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": {"id": "expired-upload", "type": "csv"}},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "UPLOAD_NOT_FOUND"
    assert persisted_counts() == before


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"data_source_ref": {}},
        {"data_source_ref": {"id": "   ", "type": "csv"}},
        {"data_source_ref": {"id": "sample-retail", "type": "csv"}},
    ],
)
def test_rerun_rejects_invalid_source_without_persisting_or_appending(payload: dict[str, object]):
    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        before = persisted_counts()
        response = client.post(f"/api/v1/tasks/{task_id}/rerun", json=payload)
        task_response = client.get(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 400
    assert response.json()["code"] == "UPLOAD_NOT_FOUND"
    assert response.json()["message"] == "未找到上传 session，请重新上传文件。"
    assert persisted_counts() == before
    assert task_response.status_code == 200
    assert task_response.json()["report_count"] == 1
    assert len(task_response.json()["reports"]) == 1


def test_rerun_rejects_missing_task_before_resolving_upload():
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks/missing-task/rerun",
            json={"data_source_ref": {"id": "expired-upload", "type": "csv"}},
        )

    assert response.status_code == 404
    assert response.json().get("code") == "TASK_NOT_FOUND"


def test_rerun_uses_selected_xlsx_sheet_for_schema_matching():
    workbook = BytesIO()
    with pd.ExcelWriter(workbook, engine="openpyxl") as writer:
        pd.DataFrame([{"日期": "2026-05-11", "销售额": 1000}]).to_excel(
            writer,
            sheet_name="mismatch",
            index=False,
        )
        pd.DataFrame(
            [
                {
                    "订单日期": "2026-05-11",
                    "销售额": 1000,
                    "门店": "成都店",
                    "类目": "童装",
                    "渠道": "线下",
                }
            ]
        ).to_excel(writer, sheet_name="matching", index=False)

    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        source = upload_xlsx(client, "selected-sheet.xlsx", workbook.getvalue())
        response = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={
                "data_source_ref": {
                    **source,
                    "selected_sheet": "matching",
                }
            },
        )
        assert response.status_code == 200

    with SessionLocal(bind=get_engine()) as session:
        report = session.get(Report, response.json()["report_id"])
        assert report is not None
        assert report.task_id == task_id
        assert report.structured_task_json["data_source_ref"]["selected_sheet"] == "matching"


def create_task_from_csv(client: TestClient) -> tuple[str, dict[str, object]]:
    founding_source = upload_csv(client, "founding.csv", base_csv_bytes())
    run_response = client.post(
        "/api/v1/reports/run",
        json={
            "analysis_goal": "帮我生成周度经营复盘",
            "data_source_ref": founding_source,
        },
    )
    assert run_response.status_code == 200
    created = client.post("/api/v1/tasks", json={"report_id": run_response.json()["report_id"]})
    assert created.status_code == 201
    task_id = created.json()["id"]
    with SessionLocal(bind=get_engine()) as session:
        task = session.get(AnalysisTask, task_id)
        assert task is not None
        return task_id, deepcopy(task.structured_task_json)


def upload_csv(client: TestClient, filename: str, contents: bytes) -> dict[str, str]:
    response = client.post(
        "/api/v1/uploads",
        files={"file": (filename, contents, "text/csv")},
    )
    assert response.status_code == 200
    return {"id": response.json()["session_id"], "type": "csv"}


def upload_xlsx(client: TestClient, filename: str, contents: bytes) -> dict[str, str]:
    response = client.post(
        "/api/v1/uploads",
        files={
            "file": (
                filename,
                contents,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert response.status_code == 200
    return {"id": response.json()["session_id"], "type": "xlsx"}


def persisted_counts() -> tuple[int, int]:
    with SessionLocal(bind=get_engine()) as session:
        return (
            session.scalar(select(func.count()).select_from(Dataset)) or 0,
            session.scalar(select(func.count()).select_from(Report)) or 0,
        )


def base_csv_bytes() -> bytes:
    return csv_bytes()


def csv_bytes(
    *,
    include_category: bool = True,
    include_channel: bool = True,
    include_order_id: bool = False,
    include_unit_cost: bool = False,
) -> bytes:
    fields = ["订单日期", "销售额", "门店"]
    values = ["2026-05-11", "1000", "成都店"]
    if include_category:
        fields.append("类目")
        values.append("童装")
    if include_channel:
        fields.append("渠道")
        values.append("线下")
    if include_order_id:
        fields.append("订单号")
        values.append("O20260511-0001")
    if include_unit_cost:
        fields.append("单位成本")
        values.append("100")
    return (",".join(fields) + "\n" + ",".join(values) + "\n").encode("utf-8")


def test_execute_report_run_persists_previous_comparison_in_experience_mode(monkeypatch):
    monkeypatch.setattr("app.modules.report_runner.get_llm_client", lambda _settings=None: None)
    table = load_retail_sample()
    task = default_structured_task("帮我生成周度经营复盘", asdict(table.data_source_ref))
    history_context = {
        "previous_report_id": "r-prev",
        "previous_ran_at": "2026-09-01T10:00:00+00:00",
        "previous_status": "partial",
        "previous_time_range": None,
        "last_run_summary": "上期摘要",
        "baseline_values": {"销售额": 390037.19},
    }

    report_id, report = execute_report_run(table, task, history_context=history_context)

    assert report["previous_comparison"]["previous_report_id"] == "r-prev"
    assert report["previous_comparison"]["previous_status"] == "partial"
    assert report["previous_comparison"]["same_period"] is False
    with SessionLocal(bind=get_engine()) as session:
        stored = session.get(Report, report_id)
        assert stored is not None
        assert stored.report_json["previous_comparison"]["previous_report_id"] == "r-prev"


def test_rerun_attaches_previous_comparison_linked_to_founding_report(tmp_path: Path):
    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        founding_id = client.get(f"/api/v1/tasks/{task_id}").json()["reports"][0]["id"]
        founding_report = client.get(f"/api/v1/reports/{founding_id}").json()["report"]
        assert "previous_comparison" not in founding_report

        first_source = upload_csv(client, "same-schema.csv", base_csv_bytes())
        first = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": first_source},
        )
        assert first.status_code == 200
        first_report_id = first.json()["report_id"]
        stored_first = client.get(f"/api/v1/reports/{first_report_id}").json()
        task_detail = client.get(f"/api/v1/tasks/{task_id}").json()

        second_source = upload_csv(client, "same-schema-2.csv", base_csv_bytes())
        second = client.post(
            f"/api/v1/tasks/{task_id}/rerun",
            json={"data_source_ref": second_source},
        )
        assert second.status_code == 200

    comparison = first.json()["report"]["previous_comparison"]
    assert comparison["previous_report_id"] == founding_id
    assert comparison["previous_status"] == "completed"
    assert comparison["previous_time_range"] == founding_report["metadata"]["time_range"]
    assert comparison["same_period"] is True
    assert comparison["summary_note"] == founding_report["summary"]
    assert [entry["name"] for entry in comparison["baseline"]] == [
        "销售额",
        "订单数",
        "客单价",
        "退款率",
    ]
    sales = comparison["baseline"][0]
    assert sales["previous_value"] == founding_report["kpis"][0]["current"]
    assert sales["current_value"] == first.json()["report"]["kpis"][0]["current"]
    assert sales["delta_value"] == 0.0
    assert sales["delta_unit"] == "%"
    assert sales["severity"] == "normal"
    assert comparison["baseline"][3]["delta_unit"] == "pp"
    assert str(tmp_path) not in first.text
    assert str(Path.cwd()) not in first.text

    assert stored_first["report"]["previous_comparison"]["previous_report_id"] == founding_id
    chain_flags = {item["id"]: item["has_previous_comparison"] for item in task_detail["reports"]}
    assert chain_flags == {founding_id: False, first_report_id: True}
    assert second.json()["report"]["previous_comparison"]["previous_report_id"] == first_report_id


def test_run_report_response_has_no_previous_comparison():
    with TestClient(app) as client:
        source = upload_csv(client, "founding.csv", base_csv_bytes())
        response = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘", "data_source_ref": source},
        )

    assert response.status_code == 200
    assert "previous_comparison" not in response.json()["report"]
