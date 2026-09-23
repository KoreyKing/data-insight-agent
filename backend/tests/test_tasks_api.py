from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from app.api.tasks import normalize_title
from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import AnalysisTask, Report
from app.main import app
from app.modules.persistence import save_dataset, save_report
from app.modules.schemas import (
    ColumnSummary,
    DataSourceRef,
    PreviewData,
    SchemaSummary,
    TableData,
)


def test_create_task_from_report_links_founding_report_and_returns_201(tmp_path: Path):
    report_id, dataset_id = create_report_fixture(tmp_path, "founding")

    with TestClient(app) as client:
        response = client.post("/api/v1/tasks", json={"report_id": report_id})

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "周度零售经营复盘 founding"
    assert payload["analysis_goal"] == "分析 founding"
    assert payload["structured_task"]["task_title"] == "周度零售经营复盘 founding"
    assert payload["source_dataset_id"] == dataset_id
    assert payload["status"] == "active"
    assert payload["warnings"] == []
    assert payload["report_count"] == 1
    assert payload["reports"][0]["id"] == report_id

    with SessionLocal(bind=get_engine()) as session:
        task = session.get(AnalysisTask, payload["id"])
        report = session.get(Report, report_id)
        assert task is not None
        assert report is not None
        assert report.task_id == task.id
        assert task.analysis_goal == report.analysis_goal
        assert task.structured_task_json == report.structured_task_json
        assert task.source_dataset_id == report.dataset_id


def test_create_task_uses_report_pack_identity_and_stored_field_profile(tmp_path: Path):
    stored_profile = {
        "mappings": {
            "历史日期列": {"canonical_field": "order_date"},
            "旧系统口径": {"canonical_field": "legacy_metric"},
            "未映射列": {"canonical_field": None},
        },
        "is_valid": True,
        "missing_key_fields": [],
        "warnings": [],
    }
    report_id, _ = create_report_fixture(
        tmp_path,
        "snapshot",
        context_pack_name="Founding Pack",
        context_pack_version="2.3.4-local.7",
        field_profile_json=stored_profile,
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks",
            json={"report_id": report_id, "title": "  自定义周期任务  "},
        )

    assert response.status_code == 201
    payload = response.json()
    assert payload["title"] == "自定义周期任务"
    assert payload["context_pack_name"] == "Founding Pack"
    assert payload["context_pack_version"] == "2.3.4-local.7"
    assert payload["schema_fingerprint_json"] == {
        "version": 1,
        "canonical_fields": ["legacy_metric", "order_date"],
        "computed_with_pack": {"name": "Founding Pack", "version": "2.3.4-local.7"},
    }

    with SessionLocal(bind=get_engine()) as session:
        task = session.get(AnalysisTask, payload["id"])
        assert task is not None
        assert task.schema_fingerprint_json == payload["schema_fingerprint_json"]


def test_create_task_allows_same_fingerprint_with_warning(tmp_path: Path):
    first_report_id, _ = create_report_fixture(tmp_path, "first")
    second_report_id, _ = create_report_fixture(tmp_path, "second")

    with TestClient(app) as client:
        first_response = client.post(
            "/api/v1/tasks",
            json={"report_id": first_report_id, "title": "第一条任务"},
        )
        second_response = client.post(
            "/api/v1/tasks",
            json={"report_id": second_report_id, "title": "第二条任务"},
        )

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    assert second_response.json()["warnings"] == [
        {
            "task_id": first_response.json()["id"],
            "task_title": "第一条任务",
        }
    ]
    assert second_response.json()["id"] != first_response.json()["id"]


def test_create_task_rejects_missing_report():
    with TestClient(app) as client:
        response = client.post("/api/v1/tasks", json={"report_id": "missing-report"})

    assert response.status_code == 404
    assert response.json()["code"] == "REPORT_NOT_FOUND"


def test_create_task_rejects_already_linked_report_with_existing_task_id(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "linked")

    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", json={"report_id": report_id})
        response = client.post("/api/v1/tasks", json={"report_id": report_id})

    assert created.status_code == 201
    assert response.status_code == 400
    assert response.json() == {
        "code": "REPORT_ALREADY_LINKED",
        "message": "该报告已归属于分析任务。",
        "details": {"task_id": created.json()["id"]},
    }


@pytest.mark.parametrize(
    "founding_title",
    [pytest.param("   ", id="whitespace-only"), pytest.param("x" * 300, id="over-255")],
)
def test_create_task_rejects_invalid_founding_report_title(
    tmp_path: Path,
    founding_title: str,
):
    report_id, _ = create_report_fixture(
        tmp_path,
        f"invalid-founding-{len(founding_title)}",
        task_title=founding_title,
    )

    with TestClient(app) as client:
        response = client.post("/api/v1/tasks", json={"report_id": report_id})

    assert response.status_code == 400
    assert response.json()["code"] == "TASK_TITLE_INVALID"
    with SessionLocal(bind=get_engine()) as session:
        report = session.get(Report, report_id)
        assert session.scalar(select(func.count()).select_from(AnalysisTask)) == 0
        assert report is not None
        assert report.task_id is None


@pytest.mark.parametrize("title", [None, "   ", "x" * 256])
def test_create_task_rejects_invalid_optional_title(tmp_path: Path, title: object):
    report_id, _ = create_report_fixture(tmp_path, f"invalid-{len(str(title))}")

    with TestClient(app) as client:
        response = client.post(
            "/api/v1/tasks",
            json={"report_id": report_id, "title": title},
        )

    assert response.status_code == 400
    assert response.json()["code"] == "TASK_TITLE_INVALID"


def test_list_tasks_is_lightweight_paginated_and_caps_limit(tmp_path: Path):
    report_ids = [create_report_fixture(tmp_path, f"list-{index}")[0] for index in range(3)]
    with TestClient(app) as client:
        for report_id in report_ids:
            created = client.post("/api/v1/tasks", json={"report_id": report_id})
            assert created.status_code == 201

        page_response = client.get("/api/v1/tasks", params={"limit": 1, "offset": 1})
        capped_response = client.get("/api/v1/tasks", params={"limit": 999, "offset": -2})

    assert page_response.status_code == 200
    page = page_response.json()
    assert set(page) == {"tasks", "limit", "offset"}
    assert page["limit"] == 1
    assert page["offset"] == 1
    assert len(page["tasks"]) == 1
    item = page["tasks"][0]
    assert set(item) == {
        "id",
        "title",
        "analysis_goal",
        "created_at",
        "status",
        "context_pack_name",
        "context_pack_version",
        "report_count",
        "last_run_at",
    }
    assert "structured_task" not in item
    assert "schema_fingerprint_json" not in item
    assert "reports" not in item
    assert "report" not in item
    assert "report_json" not in item
    assert capped_response.json()["limit"] == 50
    assert capped_response.json()["offset"] == 0
    assert len(capped_response.json()["tasks"]) == 3
    serialized = json.dumps(capped_response.json(), ensure_ascii=False)
    assert str(tmp_path) not in serialized


def test_get_task_returns_display_names_and_descending_report_chain(tmp_path: Path):
    older = datetime(2026, 8, 20, 9, 0, tzinfo=UTC)
    newer = older + timedelta(days=7)
    field_profile = {
        "mappings": {
            "日期": {"canonical_field": "order_date"},
            "旧指标": {"canonical_field": "legacy_metric"},
        },
        "is_valid": True,
        "missing_key_fields": [],
        "warnings": [],
    }
    older_report_id, _ = create_report_fixture(
        tmp_path,
        "older",
        ran_at=older,
        field_profile_json=field_profile,
    )

    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", json={"report_id": older_report_id})
    assert created.status_code == 201
    task_id = created.json()["id"]

    newer_report_id, _ = create_report_fixture(
        tmp_path,
        "newer",
        ran_at=newer,
        task_id=task_id,
        previous_comparison={},
    )

    with TestClient(app) as client:
        response = client.get(f"/api/v1/tasks/{task_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["canonical_fields"] == [
        {"name": "legacy_metric", "display_name": "legacy_metric"},
        {"name": "order_date", "display_name": "订单日期"},
    ]
    assert payload["report_count"] == 2
    assert payload["last_run_at"] == payload["reports"][0]["ran_at"]
    assert [report["id"] for report in payload["reports"]] == [
        newer_report_id,
        older_report_id,
    ]
    assert payload["reports"][0]["finding_count"] == 2
    assert payload["reports"][0]["has_previous_comparison"] is True
    assert payload["reports"][1]["has_previous_comparison"] is False
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized


def test_get_task_rejects_missing_task():
    with TestClient(app) as client:
        response = client.get("/api/v1/tasks/missing-task")

    assert response.status_code == 404
    assert response.json()["code"] == "TASK_NOT_FOUND"


def test_patch_task_only_renames_with_trimmed_valid_title(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "rename")
    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", json={"report_id": report_id})
        response = client.patch(
            f"/api/v1/tasks/{created.json()['id']}",
            json={"title": "  重命名后的任务  "},
        )

    assert created.status_code == 201
    assert response.status_code == 200
    assert response.json()["title"] == "重命名后的任务"
    assert response.json()["analysis_goal"] == created.json()["analysis_goal"]
    assert response.json()["structured_task"] == created.json()["structured_task"]

    with SessionLocal(bind=get_engine()) as session:
        task = session.get(AnalysisTask, created.json()["id"])
        assert task is not None
        assert task.title == "重命名后的任务"


def test_patch_task_rejects_blank_too_long_or_extra_fields(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "invalid-rename")
    with TestClient(app) as client:
        created = client.post("/api/v1/tasks", json={"report_id": report_id})
        task_id = created.json()["id"]
        responses = [
            client.patch(f"/api/v1/tasks/{task_id}", json={"title": "  "}),
            client.patch(f"/api/v1/tasks/{task_id}", json={"title": "x" * 256}),
            client.patch(
                f"/api/v1/tasks/{task_id}",
                json={"title": "新标题", "status": "inactive"},
            ),
            client.patch(f"/api/v1/tasks/{task_id}", json={}),
        ]

    assert all(response.status_code == 400 for response in responses)
    assert all(response.json()["code"] == "TASK_TITLE_INVALID" for response in responses)


def test_normalize_title_rejects_unencodable_title():
    """纵深防御：HTTP 入口由请求体边界校验先行拦截（见 test_request_validation.py），
    normalize_title 作为纯函数仍须自证——返回值必须是能落库的标题。"""
    assert normalize_title("  正常标题  ") == "正常标题"
    assert normalize_title("\ud800abc") is None
    assert normalize_title("abc\udfff") is None
    assert normalize_title("𝄞 成对代理项是合法字符") == "𝄞 成对代理项是合法字符"


def test_report_detail_exposes_nullable_task_identity_without_paths(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "unlinked-detail")

    with TestClient(app) as client:
        response = client.get(f"/api/v1/reports/{report_id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] is None
    assert payload["task_title"] is None
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized


def test_report_detail_exposes_linked_task_identity_without_paths(tmp_path: Path):
    report_id, _ = create_report_fixture(tmp_path, "linked-detail")
    with TestClient(app) as client:
        created = client.post(
            "/api/v1/tasks",
            json={"report_id": report_id, "title": "报告所属任务"},
        )
        response = client.get(f"/api/v1/reports/{report_id}")

    assert created.status_code == 201
    assert response.status_code == 200
    payload = response.json()
    assert payload["task_id"] == created.json()["id"]
    assert payload["task_title"] == "报告所属任务"
    serialized = json.dumps(payload, ensure_ascii=False)
    assert str(tmp_path) not in serialized


def create_report_fixture(
    tmp_path: Path,
    suffix: str,
    *,
    task_title: str | None = None,
    context_pack_name: str = "Retail Operations",
    context_pack_version: str = "1.0.0",
    field_profile_json: dict[str, object] | None = None,
    ran_at: datetime | None = None,
    task_id: str | None = None,
    previous_comparison: dict[str, object] | None = None,
) -> tuple[str, str]:
    init_db()
    location = tmp_path / "private" / f"{suffix}.csv"
    table = TableData(
        data_source_ref=DataSourceRef(
            id=f"dataset-{suffix}",
            type="csv",
            name=f"{suffix}.csv",
            location=str(location),
        ),
        dataframe=pd.DataFrame(
            [
                {
                    "订单日期": "2026-08-20",
                    "销售额": 100,
                    "门店": "成都店",
                }
            ]
        ),
        schema_summary=SchemaSummary(
            tables=[{"name": "sales_orders"}],
            columns=[
                ColumnSummary("订单日期", "date", False, ["2026-08-20"], 1),
                ColumnSummary("销售额", "number", False, [100], 1),
                ColumnSummary("门店", "string", False, ["成都店"], 1),
            ],
            row_count_estimate=1,
        ),
        preview=PreviewData(
            head=[{"订单日期": "2026-08-20", "销售额": 100, "门店": "成都店"}],
            tail=[],
        ),
        workbook_sheets=[],
    )
    resolved_task_title = (
        f"周度零售经营复盘 {suffix}" if task_title is None else task_title
    )
    task = {
        "task_title": resolved_task_title,
        "analysis_goal": f"分析 {suffix}",
        "metrics": ["销售额"],
        "dimensions": ["门店"],
        "comparison": "环比",
        "context_pack_name": context_pack_name,
        "context_pack_version": context_pack_version,
        "data_source_ref": {
            "id": f"dataset-{suffix}",
            "type": "csv",
            "name": f"{suffix}.csv",
            "location": str(location),
        },
    }
    report_payload: dict[str, object] = {
        "status": "completed",
        "title": f"周度零售经营复盘 {suffix}",
        "analysis_goal": f"分析 {suffix}",
        "summary": f"{suffix} summary",
        "context_pack_name": context_pack_name,
        "context_pack_version": context_pack_version,
        "findings": [
            {"type": "trend", "text": f"{suffix} trend"},
            {"type": "anomaly", "text": f"{suffix} anomaly"},
        ],
        "metadata": {
            "model": "not_configured",
            "ran_at": (ran_at or datetime(2026, 8, 20, 9, 0, tzinfo=UTC)).isoformat(),
            "iterations_used": 2,
            "token_used": 120,
            "data_source": {
                "id": f"dataset-{suffix}",
                "type": "csv",
                "name": f"{suffix}.csv",
                "location": str(location),
            },
        },
    }
    if previous_comparison is not None:
        report_payload["previous_comparison"] = previous_comparison

    with SessionLocal(bind=get_engine()) as session:
        dataset = save_dataset(session, table)
        if field_profile_json is not None:
            dataset.field_profile_json = field_profile_json
        report = save_report(session, dataset, task, report_payload)
        report.task_id = task_id
        session.commit()
        return report.id, dataset.id
