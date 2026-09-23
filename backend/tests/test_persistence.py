from __future__ import annotations

import json
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, inspect, select

from app.db.engine import SessionLocal, get_engine, init_db, normalize_database_url
from app.db.models import Dataset, Report
from app.main import app
from app.modules.context_pack import builtin_base_version

FACTORY_VERSION = builtin_base_version()


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path}"


def test_normalize_relative_sqlite_url_anchors_to_project_root(
    monkeypatch,
    tmp_path: Path,
):
    repository_root = Path(__file__).resolve().parents[2]
    monkeypatch.chdir(tmp_path)

    normalized_url = normalize_database_url("sqlite:///./data/app.db")

    assert normalized_url == sqlite_url(repository_root / "data/app.db")


def test_normalize_absolute_and_memory_sqlite_urls_without_rewriting(tmp_path: Path):
    absolute_url = sqlite_url(tmp_path / "app.db")

    assert normalize_database_url(absolute_url) == absolute_url
    assert normalize_database_url("sqlite:///:memory:") == "sqlite:///:memory:"


def test_get_engine_rejects_non_sqlite_application_database():
    expected = r"APP_DB_URL must use SQLite \(the only supported application database\)"
    with pytest.raises(ValueError, match=expected):
        get_engine("postgresql://user:password@localhost/app")


def test_init_db_creates_analysis_tasks_and_report_task_id_for_fresh_database(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))

    init_db()

    inspector = inspect(get_engine())
    assert "analysis_tasks" in inspector.get_table_names()
    report_columns = {column["name"] for column in inspector.get_columns("reports")}
    assert "task_id" in report_columns
    assert "ix_reports_task_id" in {index["name"] for index in inspector.get_indexes("reports")}
    assert "ix_analysis_tasks_schema_fingerprint" in {
        index["name"] for index in inspector.get_indexes("analysis_tasks")
    }
    with get_engine().connect() as connection:
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_list(reports)").mappings()
    assert any(
        foreign_key["from"] == "task_id"
        and foreign_key["table"] == "analysis_tasks"
        and foreign_key["to"] == "id"
        for foreign_key in foreign_keys
    )


def test_init_db_upgrades_old_reports_table_without_losing_data(
    monkeypatch,
    tmp_path: Path,
):
    database_url = sqlite_url(tmp_path / "p1-era.db")
    monkeypatch.setenv("APP_DB_URL", database_url)
    create_p1_era_database(database_url)

    init_db()

    engine = get_engine()
    inspector = inspect(engine)
    report_columns = {column["name"]: column for column in inspector.get_columns("reports")}
    assert "analysis_tasks" in inspector.get_table_names()
    assert report_columns["task_id"]["nullable"] is True
    assert "ix_reports_task_id" in {index["name"] for index in inspector.get_indexes("reports")}
    assert "ix_analysis_tasks_schema_fingerprint" in {
        index["name"] for index in inspector.get_indexes("analysis_tasks")
    }

    with SessionLocal(bind=engine) as session:
        report = session.get(Report, "p1-report")
        assert report is not None
        assert report.task_title == "legacy report"
        assert report.task_id is None


def test_init_db_old_schema_upgrade_is_idempotent(monkeypatch, tmp_path: Path):
    database_url = sqlite_url(tmp_path / "p1-era.db")
    monkeypatch.setenv("APP_DB_URL", database_url)
    create_p1_era_database(database_url)

    init_db()
    engine = get_engine()
    first_columns = [column["name"] for column in inspect(engine).get_columns("reports")]
    first_indexes = [index["name"] for index in inspect(engine).get_indexes("reports")]

    init_db()

    inspector = inspect(engine)
    report_columns = {column["name"]: column for column in inspector.get_columns("reports")}
    assert "analysis_tasks" in inspector.get_table_names()
    assert report_columns["task_id"]["nullable"] is True
    assert "ix_reports_task_id" in {index["name"] for index in inspector.get_indexes("reports")}
    assert "ix_analysis_tasks_schema_fingerprint" in {
        index["name"] for index in inspector.get_indexes("analysis_tasks")
    }
    assert [column["name"] for column in inspector.get_columns("reports")] == first_columns
    assert [index["name"] for index in inspector.get_indexes("reports")] == first_indexes
    assert first_columns.count("task_id") == 1
    assert first_indexes.count("ix_reports_task_id") == 1
    with engine.connect() as connection:
        foreign_keys = connection.exec_driver_sql("PRAGMA foreign_key_list(reports)").mappings()
    assert any(
        foreign_key["from"] == "task_id"
        and foreign_key["table"] == "analysis_tasks"
        and foreign_key["to"] == "id"
        for foreign_key in foreign_keys
    )

    with SessionLocal(bind=engine) as session:
        report = session.get(Report, "p1-report")
        assert report is not None
        assert report.task_title == "legacy report"
        assert report.task_id is None


def test_init_db_creates_dataset_and_report_tables(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))

    init_db()

    inspector = inspect(get_engine())
    assert {"datasets", "reports"}.issubset(set(inspector.get_table_names()))

    dataset_columns = {column["name"] for column in inspector.get_columns("datasets")}
    assert {
        "id",
        "created_at",
        "data_source_ref_json",
        "schema_summary_json",
        "preview_json",
        "field_profile_json",
        "file_path",
        "file_name",
        "row_count",
        "column_count",
    }.issubset(dataset_columns)

    report_columns = {column["name"] for column in inspector.get_columns("reports")}
    assert {
        "id",
        "created_at",
        "dataset_id",
        "task_title",
        "analysis_goal",
        "structured_task_json",
        "metrics_json",
        "dimensions_json",
        "comparison",
        "context_pack_name",
        "context_pack_version",
        "report_json",
        "status",
        "summary",
        "model_used",
        "iterations_used",
        "token_used",
        "ran_at",
    }.issubset(report_columns)


def test_dataset_and_report_models_round_trip_json_fields(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    init_db()

    engine = get_engine()
    with SessionLocal(bind=engine) as session:
        dataset = Dataset(
            data_source_ref_json={
                "id": "sample-retail",
                "type": "csv",
                "name": "sample",
                "location": "sample",
            },
            schema_summary_json={"tables": [{"name": "sales_orders"}], "columns": []},
            preview_json={"head": [{"门店": "上海徐汇旗舰店"}], "tail": []},
            field_profile_json={"is_valid": True},
            file_path="backend/app/sample_data/retail_sales_orders.csv",
            file_name="retail_sales_orders.csv",
            row_count=9000,
            column_count=12,
        )
        session.add(dataset)
        session.flush()

        report = Report(
            dataset_id=dataset.id,
            task_title="周度零售经营复盘",
            analysis_goal="帮我生成周度经营复盘",
            structured_task_json={"analysis_goal": "帮我生成周度经营复盘"},
            metrics_json=["销售额", "订单数"],
            dimensions_json=["门店", "商品类目"],
            comparison="环比",
            context_pack_name="Retail Operations",
            context_pack_version="1.0.0",
            report_json={"status": "completed", "summary": "ok"},
            status="completed",
            summary="ok",
            model_used="not_configured",
            iterations_used=0,
            token_used=0,
        )
        session.add(report)
        session.commit()
        report_id = report.id

    with SessionLocal(bind=engine) as session:
        stored = session.scalars(select(Report).where(Report.id == report_id)).one()
        assert stored.dataset_id
        assert stored.dataset.data_source_ref_json["type"] == "csv"
        assert stored.structured_task_json["analysis_goal"] == "帮我生成周度经营复盘"
        assert stored.context_pack_name == "Retail Operations"
        assert stored.context_pack_version == "1.0.0"
        assert stored.report_json["status"] == "completed"
        assert isinstance(stored.created_at, datetime)
        assert isinstance(stored.ran_at, datetime)


def test_app_startup_initializes_metadata_db(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "startup.db"
    monkeypatch.setenv("APP_DB_URL", sqlite_url(db_path))

    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    assert db_path.exists()
    assert {"datasets", "reports"}.issubset(set(inspect(get_engine()).get_table_names()))


def test_run_report_persists_sample_dataset_and_report(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))

    with TestClient(app) as client:
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
    report_id = payload["report_id"]
    UUID(report_id)

    with SessionLocal(bind=get_engine()) as session:
        stored = session.scalars(select(Report).where(Report.id == report_id)).one()
        assert (
            stored.report_json["metadata"]["data_source"]["location"]
            == stored.dataset.data_source_ref_json["location"]
        )
        assert payload["report"]["metadata"]["data_source"]["location"] == stored.dataset.file_name
        expected_response_report = deepcopy(stored.report_json)
        expected_response_report["metadata"]["data_source"]["location"] = stored.dataset.file_name
        assert expected_response_report == payload["report"]
        assert stored.status == "completed"
        assert stored.summary == payload["report"]["summary"]
        assert stored.model_used == "not_configured"
        assert stored.context_pack_name == "Retail Operations"
        assert stored.context_pack_version == FACTORY_VERSION
        assert stored.structured_task_json["analysis_goal"] == "帮我生成周度经营复盘"
        assert stored.metrics_json == stored.structured_task_json["metrics"]
        assert stored.dimensions_json == stored.structured_task_json["dimensions"]
        assert stored.comparison == "环比"
        assert stored.iterations_used == payload["report"]["metadata"]["iterations_used"]
        assert stored.token_used == payload["report"]["metadata"]["token_used"]
        assert isinstance(stored.ran_at, datetime)
        assert stored.dataset.data_source_ref_json["id"] == "sample-retail"
        assert stored.dataset.file_name == "retail_sales_orders.csv"
        assert stored.dataset.row_count > 0
        assert stored.dataset.field_profile_json["is_valid"] is True


def test_run_report_persists_uploaded_csv_dataset(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    source = tmp_path / "orders.csv"
    source.write_text(
        "订单日期,销售额,门店,类目,渠道\n2026-05-11,1000,上海徐汇旗舰店,童装,线下\n",
        encoding="utf-8",
    )

    with TestClient(app) as client:
        with source.open("rb") as file_handle:
            upload_response = client.post(
                "/api/v1/uploads",
                files={"file": ("orders.csv", file_handle, "text/csv")},
            )
        assert upload_response.status_code == 200
        data_source_ref = upload_response.json()["data_source_ref"]

        response = client.post(
            "/api/v1/reports/run",
            json={
                "analysis_goal": "帮我生成周度经营复盘",
                "data_source_ref": data_source_ref,
            },
        )

    assert response.status_code == 200
    report_id = response.json()["report_id"]

    with SessionLocal(bind=get_engine()) as session:
        stored = session.scalars(select(Report).where(Report.id == report_id)).one()
        assert stored.dataset.data_source_ref_json["id"] == data_source_ref["id"]
        assert stored.dataset.file_name == "orders.csv"
        assert stored.dataset.file_path.endswith("orders.csv")
        assert stored.dataset.schema_summary_json["row_count_estimate"] == 1
        assert stored.dataset.preview_json["head"][0]["门店"] == "上海徐汇旗舰店"
        assert stored.dataset.field_profile_json["is_valid"] is True


def test_run_report_does_not_persist_failed_report(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    source = tmp_path / "invalid.csv"
    source.write_text("门店\n上海徐汇旗舰店\n", encoding="utf-8")

    with TestClient(app) as client:
        with source.open("rb") as file_handle:
            upload_response = client.post(
                "/api/v1/uploads",
                files={"file": ("invalid.csv", file_handle, "text/csv")},
            )
        assert upload_response.status_code == 200

        response = client.post(
            "/api/v1/reports/run",
            json={
                "analysis_goal": "帮我生成周度经营复盘",
                "data_source_ref": upload_response.json()["data_source_ref"],
            },
        )

    assert response.status_code == 400
    payload = response.json()
    assert payload["report"]["status"] == "failed"
    assert "report_id" not in payload

    with SessionLocal(bind=get_engine()) as session:
        assert session.scalar(select(func.count()).select_from(Dataset)) == 0
        assert session.scalar(select(func.count()).select_from(Report)) == 0


def test_run_report_persists_partial_llm_report(monkeypatch, tmp_path: Path):
    class PartialLLMClient:
        def complete(self, messages):
            return json.dumps(
                {
                    "tool": "record_finding",
                    "args": {
                        "type": "trend",
                        "text": "当前只有部分结论。",
                        "evidence": "manual-observation",
                        "confidence": "medium",
                    },
                },
                ensure_ascii=False,
            )

    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    monkeypatch.setattr(
        "app.modules.report_runner.get_llm_client", lambda _settings=None: PartialLLMClient()
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/reports/run",
            json={
                "analysis_goal": "帮我生成周度经营复盘",
                "task": {"execution_limits": {"max_iterations": 1}},
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
    assert payload["report"]["status"] == "partial"

    with SessionLocal(bind=get_engine()) as session:
        stored = session.scalars(select(Report).where(Report.id == payload["report_id"])).one()
        assert stored.status == "partial"
        assert (
            stored.report_json["metadata"]["data_source"]["location"]
            == stored.dataset.data_source_ref_json["location"]
        )
        assert payload["report"]["metadata"]["data_source"]["location"] == stored.dataset.file_name
        expected_response_report = deepcopy(stored.report_json)
        expected_response_report["metadata"]["data_source"]["location"] = stored.dataset.file_name
        assert expected_response_report == payload["report"]


def test_history_report_and_dataset_lists_are_empty(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))

    with TestClient(app) as client:
        reports_response = client.get("/api/v1/reports")
        datasets_response = client.get("/api/v1/datasets")

    assert reports_response.status_code == 200
    assert reports_response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}
    assert datasets_response.status_code == 200
    assert datasets_response.json() == {"items": [], "total": 0, "limit": 20, "offset": 0}


def test_report_history_list_is_lightweight_sorted_and_paginated(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    older = datetime(2026, 5, 20, 9, 0, tzinfo=UTC)
    newer = datetime(2026, 5, 27, 9, 0, tzinfo=UTC)
    older_report_id = create_dataset_report_pair(
        "older",
        file_path="/tmp/private/older.csv",
        report_status="completed",
        report_summary="older summary",
        report_findings=[{"type": "trend", "text": "old"}],
        ran_at=older,
    )[1]
    newer_report_id = create_dataset_report_pair(
        "newer",
        file_path="/Users/alice/private/newer.csv",
        report_status="completed",
        report_summary="newer summary",
        report_findings=[
            {"type": "anomaly", "text": "high risk"},
            {"type": "trend", "text": "growth"},
        ],
        ran_at=newer,
        loop_rounds=0,
    )[1]

    with TestClient(app) as client:
        response = client.get("/api/v1/reports", params={"limit": 99, "offset": -5})

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 2
    assert payload["limit"] == 50
    assert payload["offset"] == 0
    assert [item["id"] for item in payload["items"]] == [newer_report_id, older_report_id]
    first = payload["items"][0]
    assert first["title"] == "周度零售经营复盘 newer"
    assert first["summary"] == "newer summary"
    assert first["status"] == "completed"
    assert first["model"] == "not_configured"
    assert first["loop_rounds"] == 0
    assert first["iterations_used"] == 2
    assert first["token_used"] == 120
    assert first["finding_count"] == 2
    assert first["anomaly_count"] == 1
    assert first["dataset"]["file_name"] == "newer.csv"
    assert first["dataset"]["row_count"] == 10
    assert payload["items"][1]["loop_rounds"] is None
    assert "report" not in first
    assert "report_json" not in first
    assert "task" not in first
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "file_path" not in serialized
    assert "/tmp/private" not in serialized
    assert "/Users/alice" not in serialized


def test_report_history_detail_returns_report_task_and_dataset_summary(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    dataset_id, report_id = create_dataset_report_pair(
        "detail",
        file_path=str(tmp_path / "uploads" / "detail.csv"),
        report_status="partial",
        report_summary="detail summary",
        report_findings=[{"type": "trend", "text": "detail"}],
        ran_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )

    with TestClient(app) as client:
        response = client.get(f"/api/v1/reports/{report_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == report_id
    assert payload["dataset_id"] == dataset_id
    assert payload["report"]["summary"] == "detail summary"
    assert payload["report"]["status"] == "partial"
    assert payload["loop_rounds"] is None
    assert payload["task"]["analysis_goal"] == "分析 detail"
    assert payload["dataset"] == {
        "id": dataset_id,
        "file_name": "detail.csv",
        "row_count": 10,
        "column_count": 5,
    }
    serialized = json.dumps(payload, ensure_ascii=False)
    assert "file_path" not in serialized
    assert str(tmp_path) not in serialized


def test_dataset_list_and_detail_return_sanitized_readonly_payload(
    monkeypatch,
    tmp_path: Path,
):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    dataset_id, report_id = create_dataset_report_pair(
        "dataset",
        file_path=str(tmp_path / "uploads" / "dataset.csv"),
        report_status="completed",
        report_summary="dataset summary",
        report_findings=[{"type": "anomaly", "text": "dataset anomaly"}],
        ran_at=datetime(2026, 5, 27, 9, 0, tzinfo=UTC),
    )

    with TestClient(app) as client:
        list_response = client.get("/api/v1/datasets")
        detail_response = client.get(f"/api/v1/datasets/{dataset_id}")

    assert list_response.status_code == 200
    list_payload = list_response.json()
    assert list_payload["total"] == 1
    item = list_payload["items"][0]
    assert item["id"] == dataset_id
    assert item["file_name"] == "dataset.csv"
    assert item["data_source_type"] == "csv"
    assert item["status"] == "ready"
    assert item["report_count"] == 1
    assert item["latest_report_at"]

    assert detail_response.status_code == 200
    detail = detail_response.json()
    assert detail["id"] == dataset_id
    assert detail["data_source_ref"]["location"] == "dataset.csv"
    assert detail["schema_summary"]["row_count_estimate"] == 10
    assert detail["preview"]["head"][0]["门店"] == "上海徐汇旗舰店"
    assert detail["field_profile"]["is_valid"] is True
    assert detail["report_count"] == 1
    assert detail["reports"][0]["id"] == report_id
    assert detail["reports"][0]["title"] == "周度零售经营复盘 dataset"
    serialized = json.dumps({"list": list_payload, "detail": detail}, ensure_ascii=False)
    assert "file_path" not in serialized
    assert str(tmp_path) not in serialized


def test_history_api_returns_not_found_errors(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))

    with TestClient(app) as client:
        report_response = client.get("/api/v1/reports/missing-report")
        dataset_response = client.get("/api/v1/datasets/missing-dataset")

    assert report_response.status_code == 404
    assert report_response.json() == {
        "code": "REPORT_NOT_FOUND",
        "message": "未找到历史报告。",
    }
    assert dataset_response.status_code == 404
    assert dataset_response.json() == {
        "code": "DATASET_NOT_FOUND",
        "message": "未找到数据源。",
    }


def test_failed_report_is_not_visible_in_history_apis(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("APP_DB_URL", sqlite_url(tmp_path / "metadata.db"))
    source = tmp_path / "invalid.csv"
    source.write_text("门店\n上海徐汇旗舰店\n", encoding="utf-8")

    with TestClient(app) as client:
        with source.open("rb") as file_handle:
            upload_response = client.post(
                "/api/v1/uploads",
                files={"file": ("invalid.csv", file_handle, "text/csv")},
            )
        assert upload_response.status_code == 200

        run_response = client.post(
            "/api/v1/reports/run",
            json={
                "analysis_goal": "帮我生成周度经营复盘",
                "data_source_ref": upload_response.json()["data_source_ref"],
            },
        )
        reports_response = client.get("/api/v1/reports")
        datasets_response = client.get("/api/v1/datasets")

    assert run_response.status_code == 400
    assert reports_response.json()["total"] == 0
    assert datasets_response.json()["total"] == 0


def create_dataset_report_pair(
    suffix: str,
    *,
    file_path: str,
    report_status: str,
    report_summary: str,
    report_findings: list[dict[str, str]],
    ran_at: datetime,
    loop_rounds: int | None = None,
) -> tuple[str, str]:
    init_db()
    with SessionLocal(bind=get_engine()) as session:
        dataset = Dataset(
            data_source_ref_json={
                "id": f"dataset-{suffix}",
                "type": "csv",
                "name": f"{suffix}.csv",
                "location": file_path,
            },
            schema_summary_json={
                "tables": [{"name": "sales_orders"}],
                "columns": [{"name": "门店", "data_type": "string"}],
                "row_count_estimate": 10,
            },
            preview_json={"head": [{"门店": "上海徐汇旗舰店"}], "tail": []},
            field_profile_json={
                "mappings": {},
                "is_valid": True,
                "missing_key_fields": [],
                "warnings": [],
            },
            file_path=file_path,
            file_name=f"{suffix}.csv",
            row_count=10,
            column_count=5,
        )
        session.add(dataset)
        session.flush()

        metadata = {
            "model": "not_configured",
            "iterations_used": 2,
            "token_used": 120,
            "ran_at": ran_at.isoformat(),
        }
        if loop_rounds is not None:
            metadata["loop_rounds"] = loop_rounds

        report = Report(
            dataset_id=dataset.id,
            task_title=f"周度零售经营复盘 {suffix}",
            analysis_goal=f"分析 {suffix}",
            structured_task_json={
                "task_title": f"周度零售经营复盘 {suffix}",
                "analysis_goal": f"分析 {suffix}",
                "metrics": ["销售额"],
                "dimensions": ["门店"],
                "comparison": "环比",
            },
            metrics_json=["销售额"],
            dimensions_json=["门店"],
            comparison="环比",
            context_pack_name="Retail Operations",
            context_pack_version="1.0.0",
            report_json={
                "status": report_status,
                "title": f"周度零售经营复盘 {suffix}",
                "summary": report_summary,
                "findings": report_findings,
                "metadata": metadata,
            },
            status=report_status,
            summary=report_summary,
            model_used="not_configured",
            iterations_used=2,
            token_used=120,
            ran_at=ran_at,
        )
        session.add(report)
        session.commit()
        return dataset.id, report.id


def create_p1_era_database(database_url: str) -> None:
    engine = create_engine(database_url)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            """
            CREATE TABLE datasets (
                id VARCHAR(36) PRIMARY KEY,
                created_at DATETIME NOT NULL,
                data_source_ref_json JSON NOT NULL,
                schema_summary_json JSON NOT NULL,
                preview_json JSON NOT NULL,
                field_profile_json JSON NOT NULL,
                file_path TEXT NOT NULL,
                file_name VARCHAR(255) NOT NULL,
                row_count INTEGER NOT NULL,
                column_count INTEGER NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            CREATE TABLE reports (
                id VARCHAR(36) PRIMARY KEY,
                created_at DATETIME NOT NULL,
                dataset_id VARCHAR(36) NOT NULL REFERENCES datasets(id),
                task_title VARCHAR(255) NOT NULL,
                analysis_goal TEXT NOT NULL,
                structured_task_json JSON NOT NULL,
                metrics_json JSON NOT NULL,
                dimensions_json JSON NOT NULL,
                comparison VARCHAR(80) NOT NULL,
                context_pack_name VARCHAR(120) NOT NULL,
                context_pack_version VARCHAR(40) NOT NULL,
                report_json JSON NOT NULL,
                status VARCHAR(32) NOT NULL,
                summary TEXT NOT NULL,
                model_used VARCHAR(120) NOT NULL,
                iterations_used INTEGER NOT NULL,
                token_used INTEGER NOT NULL,
                ran_at DATETIME NOT NULL
            )
            """
        )
        connection.exec_driver_sql(
            """
            INSERT INTO datasets (
                id, created_at, data_source_ref_json, schema_summary_json, preview_json,
                field_profile_json, file_path, file_name, row_count, column_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "p1-dataset",
                "2026-08-29T00:00:00+00:00",
                '{"id": "p1-dataset"}',
                "{}",
                "{}",
                "{}",
                "/tmp/p1.csv",
                "p1.csv",
                1,
                1,
            ),
        )
        connection.exec_driver_sql(
            """
            INSERT INTO reports (
                id, created_at, dataset_id, task_title, analysis_goal, structured_task_json,
                metrics_json, dimensions_json, comparison, context_pack_name,
                context_pack_version, report_json, status, summary, model_used,
                iterations_used, token_used, ran_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "p1-report",
                "2026-08-29T00:00:00+00:00",
                "p1-dataset",
                "legacy report",
                "legacy goal",
                "{}",
                "[]",
                "[]",
                "none",
                "Retail Operations",
                "1.0.0",
                "{}",
                "completed",
                "legacy summary",
                "not_configured",
                0,
                0,
                "2026-08-29T00:00:00+00:00",
            ),
        )
    engine.dispose()
