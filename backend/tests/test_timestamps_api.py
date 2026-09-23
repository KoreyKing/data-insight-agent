"""时间戳契约的 API 层（architecture.md §2.4）：存量库只读换算、排序、全接口 UTC 走查。

存量库按真实存量数据的形态造：本地 dev（+8）生成的报告 legacy-local、Docker（UTC）生成的重跑报告
legacy-docker（上期为 legacy-local），两者归属同一任务；时刻列用 SQLAlchemy 的无时区文本格式写入。
"""
from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import selectinload

from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import AnalysisTask
from app.main import app
from app.modules.history_context import history_context_for_task
from tests.test_task_rerun import base_csv_bytes, create_task_from_csv, upload_csv

TIME_RANGE = {
    "current_start": "2026-05-11",
    "current_end": "2026-05-17",
    "previous_start": "2026-05-04",
    "previous_end": "2026-05-10",
}
SAMPLE_SOURCE = {"id": "sample-retail", "type": "csv", "name": "sample", "location": "sample"}


def report_payload(
    summary: str,
    *,
    ran_at: str,
    evidence_ran_at: str,
    previous_comparison: dict | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "status": "completed",
        "title": "周度零售经营复盘",
        "summary": summary,
        "kpis": [],
        "findings": [
            {
                "id": "finding-1",
                "type": "trend",
                "text": f"{summary} 结论",
                "evidence": {
                    "sql": "SELECT 1",
                    "data_source": "sales_orders",
                    "ran_at": evidence_ran_at,
                    "iteration": 3,
                    "evidence_ref": "query-1",
                },
            }
        ],
        "metadata": {
            "data_source": {"id": "sample-retail", "type": "csv", "name": "sample.csv"},
            "row_count": 10,
            "ran_at": ran_at,
            "model": "deepseek-flash",
            "iterations_used": 3,
            "token_used": 100,
            "time_range": dict(TIME_RANGE),
        },
    }
    if previous_comparison is not None:
        payload["previous_comparison"] = previous_comparison
    return payload


def insert_dataset(connection, dataset_id: str, created_at: str) -> None:
    connection.execute(
        text(
            "INSERT INTO datasets (id, created_at, data_source_ref_json, schema_summary_json, "
            "preview_json, field_profile_json, file_path, file_name, row_count, column_count) "
            "VALUES (:id, :created_at, :ref, :schema, :preview, :profile, :path, :name, 10, 5)"
        ),
        {
            "id": dataset_id,
            "created_at": created_at,
            "ref": json.dumps({"id": dataset_id, "type": "csv", "name": f"{dataset_id}.csv"}),
            "schema": json.dumps({"columns": []}),
            "preview": json.dumps({"head": [], "tail": []}),
            "profile": json.dumps({"is_valid": True, "mappings": {}}),
            "path": f"{dataset_id}.csv",
            "name": f"{dataset_id}.csv",
        },
    )


def insert_task(connection, task_id: str, *, dataset_id: str, created_at: str) -> None:
    connection.execute(
        text(
            "INSERT INTO analysis_tasks (id, created_at, title, analysis_goal, "
            "structured_task_json, schema_fingerprint, schema_fingerprint_json, "
            "context_pack_name, context_pack_version, source_dataset_id, status) "
            "VALUES (:id, :created_at, '周度经营复盘', '周度复盘', :task, 'v1:x', :fingerprint, "
            "'Retail Operations', '1.0.0', :dataset_id, 'active')"
        ),
        {
            "id": task_id,
            "created_at": created_at,
            "task": json.dumps({"task_title": "周度经营复盘", "analysis_goal": "周度复盘"}),
            "fingerprint": json.dumps({"version": 1, "canonical_fields": []}),
            "dataset_id": dataset_id,
        },
    )


def insert_report(
    connection,
    report_id: str,
    *,
    dataset_id: str,
    task_id: str | None,
    created_at: str,
    ran_at: str,
    payload: dict[str, Any],
) -> None:
    connection.execute(
        text(
            "INSERT INTO reports (id, created_at, dataset_id, task_id, task_title, analysis_goal, "
            "structured_task_json, metrics_json, dimensions_json, comparison, context_pack_name, "
            "context_pack_version, report_json, status, summary, model_used, iterations_used, "
            "token_used, ran_at) VALUES (:id, :created_at, :dataset_id, :task_id, :title, "
            "'周度复盘', :task, '[]', '[]', '环比', 'Retail Operations', '1.0.0', :payload, "
            "'completed', :summary, 'deepseek-flash', 3, 100, :ran_at)"
        ),
        {
            "id": report_id,
            "created_at": created_at,
            "dataset_id": dataset_id,
            "task_id": task_id,
            "title": f"周度零售经营复盘 {report_id}",
            "task": json.dumps({"task_title": "周度零售经营复盘"}),
            "payload": json.dumps(payload, ensure_ascii=False),
            "summary": payload["summary"],
            "ran_at": ran_at,
        },
    )


def build_legacy_database() -> None:
    init_db()
    with get_engine().begin() as connection:
        insert_dataset(connection, "ds-local", "2026-09-15 09:52:33.647390")
        insert_dataset(connection, "ds-docker", "2026-09-21 11:46:52.197895")
        insert_task(
            connection,
            "task-legacy",
            dataset_id="ds-local",
            created_at="2026-09-15 09:52:43.775017",
        )
        insert_report(
            connection,
            "legacy-local",
            dataset_id="ds-local",
            task_id="task-legacy",
            created_at="2026-09-15 09:52:33.648970",
            ran_at="2026-09-15 17:52:33.000000",
            payload=report_payload(
                "第一期", ran_at="2026-09-15T17:52:33", evidence_ran_at="2026-09-15T17:52:10"
            ),
        )
        insert_report(
            connection,
            "legacy-docker",
            dataset_id="ds-docker",
            task_id="task-legacy",
            created_at="2026-09-21 11:46:52.201528",
            ran_at="2026-09-21 11:46:52.000000",
            payload=report_payload(
                "第二期",
                ran_at="2026-09-21T11:46:52",
                evidence_ran_at="2026-09-21T11:46:30",
                previous_comparison={
                    "previous_report_id": "legacy-local",
                    "previous_ran_at": "2026-09-15T17:52:33",
                    "previous_status": "completed",
                    "previous_time_range": dict(TIME_RANGE),
                    "same_period": False,
                    "baseline": [],
                    "summary_note": "第一期",
                },
            ),
        )


def add_upgrade_window_reports() -> None:
    """升级前 18:00（+8，实为 10:00 UTC）的本地存量报告 + 升级后 12:00 UTC 的新报告。"""
    with get_engine().begin() as connection:
        insert_dataset(connection, "ds-evening", "2026-09-22 10:00:00.300000")
        insert_dataset(connection, "ds-fresh", "2026-09-22 12:00:00.200000")
        insert_report(
            connection,
            "legacy-evening",
            dataset_id="ds-evening",
            task_id="task-legacy",
            created_at="2026-09-22 10:00:00.500000",
            ran_at="2026-09-22 18:00:00.000000",
            payload=report_payload(
                "第三期", ran_at="2026-09-22T18:00:00", evidence_ran_at="2026-09-22T17:59:40"
            ),
        )
        insert_report(
            connection,
            "fresh-noon",
            dataset_id="ds-fresh",
            task_id="task-legacy",
            created_at="2026-09-22 12:00:00.400000",
            ran_at="2026-09-22 12:00:00.000000",
            payload=report_payload(
                "第四期",
                ran_at="2026-09-22T12:00:00+00:00",
                evidence_ran_at="2026-09-22T11:59:40+00:00",
            ),
        )


def raw_timestamp_rows() -> list[tuple]:
    with get_engine().connect() as connection:
        reports = connection.execute(
            text("SELECT id, ran_at, created_at, report_json FROM reports ORDER BY id")
        ).all()
        others = connection.execute(
            text(
                "SELECT id, created_at FROM datasets UNION ALL "
                "SELECT id, created_at FROM analysis_tasks ORDER BY id"
            )
        ).all()
    return [tuple(row) for row in reports] + [tuple(row) for row in others]


def iter_timestamps(node: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    if isinstance(node, dict):
        for key, value in node.items():
            child = f"{path}.{key}"
            if key.endswith("_at") and not isinstance(value, dict | list):
                yield child, value
            else:
                yield from iter_timestamps(value, child)
    elif isinstance(node, list):
        for index, value in enumerate(node):
            yield from iter_timestamps(value, f"{path}[{index}]")


def assert_all_timestamps_utc(payload: Any, label: str) -> int:
    count = 0
    for path, value in iter_timestamps(payload):
        if value is None:
            continue
        assert isinstance(value, str), f"{label} {path}={value!r}"
        parsed = datetime.fromisoformat(value)
        assert parsed.tzinfo is not None, f"{label} {path}={value!r} 缺少偏移"
        assert parsed.utcoffset() == timedelta(0), f"{label} {path}={value!r} 不是 UTC"
        count += 1
    return count


# ------------------------------------------------------------------ 存量换算
def test_report_list_converts_legacy_run_times_and_orders_by_created_at():
    build_legacy_database()

    with TestClient(app) as client:
        items = client.get("/api/v1/reports").json()["items"]

    assert [item["id"] for item in items] == ["legacy-docker", "legacy-local"]
    docker, local = items
    assert docker["ran_at"] == "2026-09-21T11:46:52+00:00"
    assert docker["created_at"] == "2026-09-21T11:46:52.201528+00:00"
    assert local["ran_at"] == "2026-09-15T09:52:33+00:00"
    assert local["created_at"] == "2026-09-15T09:52:33.648970+00:00"


def test_report_detail_converts_legacy_payload_and_previous_run_time():
    build_legacy_database()

    with TestClient(app) as client:
        docker = client.get("/api/v1/reports/legacy-docker").json()
        local = client.get("/api/v1/reports/legacy-local").json()

    assert docker["ran_at"] == "2026-09-21T11:46:52+00:00"
    assert docker["report"]["metadata"]["ran_at"] == "2026-09-21T11:46:52+00:00"
    assert docker["report"]["findings"][0]["evidence"]["ran_at"] == "2026-09-21T11:46:30+00:00"
    # 上期出自 +8 进程：取上期报告自身换算后的运行时刻
    comparison = docker["report"]["previous_comparison"]
    assert comparison["previous_ran_at"] == "2026-09-15T09:52:33+00:00"
    assert comparison["previous_time_range"] == TIME_RANGE
    assert docker["report"]["metadata"]["time_range"] == TIME_RANGE

    assert local["report"]["metadata"]["ran_at"] == "2026-09-15T09:52:33+00:00"
    assert local["report"]["findings"][0]["evidence"]["ran_at"] == "2026-09-15T09:52:10+00:00"


def test_task_and_dataset_views_use_true_run_times():
    build_legacy_database()

    with TestClient(app) as client:
        task_item = client.get("/api/v1/tasks").json()["tasks"][0]
        task = client.get("/api/v1/tasks/task-legacy").json()
        datasets = {item["id"]: item for item in client.get("/api/v1/datasets").json()["items"]}
        dataset = client.get("/api/v1/datasets/ds-local").json()

    assert task_item["created_at"] == "2026-09-15T09:52:43.775017+00:00"
    assert task_item["last_run_at"] == "2026-09-21T11:46:52+00:00"
    assert [(ref["id"], ref["ran_at"]) for ref in task["reports"]] == [
        ("legacy-docker", "2026-09-21T11:46:52+00:00"),
        ("legacy-local", "2026-09-15T09:52:33+00:00"),
    ]
    assert datasets["ds-local"]["latest_report_at"] == "2026-09-15T09:52:33+00:00"
    assert datasets["ds-local"]["created_at"] == "2026-09-15T09:52:33.647390+00:00"
    assert datasets["ds-docker"]["latest_report_at"] == "2026-09-21T11:46:52+00:00"
    assert dataset["reports"][0]["ran_at"] == "2026-09-15T09:52:33+00:00"


def test_report_order_follows_true_run_time_across_the_upgrade():
    build_legacy_database()
    add_upgrade_window_reports()

    with TestClient(app) as client:
        task = client.get("/api/v1/tasks/task-legacy").json()
        listed = client.get("/api/v1/reports").json()["items"]

    expected = ["fresh-noon", "legacy-evening", "legacy-docker", "legacy-local"]
    assert [ref["id"] for ref in task["reports"]] == expected
    assert task["last_run_at"] == "2026-09-22T12:00:00+00:00"
    assert task["reports"][1]["ran_at"] == "2026-09-22T10:00:00+00:00"
    assert [item["id"] for item in listed] == expected

    with SessionLocal(bind=get_engine()) as session:
        stored_task = session.scalars(
            select(AnalysisTask)
            .options(selectinload(AnalysisTask.reports))
            .where(AnalysisTask.id == "task-legacy")
        ).one()
        context = history_context_for_task(stored_task)
    assert context["previous_report_id"] == "fresh-noon"
    assert context["previous_ran_at"] == "2026-09-22T12:00:00+00:00"


def test_reading_never_rewrites_legacy_rows():
    build_legacy_database()
    before = raw_timestamp_rows()

    with TestClient(app) as client:
        for path in [
            "/api/v1/reports",
            "/api/v1/reports/legacy-docker",
            "/api/v1/reports/legacy-local",
            "/api/v1/tasks",
            "/api/v1/tasks/task-legacy",
            "/api/v1/datasets",
            "/api/v1/datasets/ds-local",
        ]:
            assert client.get(path).status_code == 200

    assert raw_timestamp_rows() == before


def test_report_detail_survives_malformed_findings():
    build_legacy_database()
    with get_engine().begin() as connection:
        connection.execute(
            text(
                "UPDATE reports SET report_json = json_set(report_json, '$.findings', 1) "
                "WHERE id = 'legacy-local'"
            )
        )

    with TestClient(app) as client:
        response = client.get("/api/v1/reports/legacy-local")

    assert response.status_code == 200
    assert response.json()["report"]["metadata"]["ran_at"] == "2026-09-15T09:52:33+00:00"


def test_rerun_on_a_legacy_founding_report_uses_its_true_run_time():
    with TestClient(app) as client:
        task_id, _ = create_task_from_csv(client)
        founding_id = client.get(f"/api/v1/tasks/{task_id}").json()["reports"][0]["id"]
        # 把首期改写成本地 dev（+8）生成的存量形态：列与 payload 都是 +8 墙上时间、无偏移
        with get_engine().begin() as connection:
            ran_at_text = connection.execute(
                text("SELECT ran_at FROM reports WHERE id = :id"), {"id": founding_id}
            ).scalar_one()
            true_run = datetime.fromisoformat(ran_at_text)
            local_wall = true_run + timedelta(hours=8)
            connection.execute(
                text(
                    "UPDATE reports SET ran_at = :ran_at, report_json = json_set(report_json, "
                    "'$.metadata.ran_at', :stamp) WHERE id = :id"
                ),
                {
                    "ran_at": local_wall.strftime("%Y-%m-%d %H:%M:%S.%f"),
                    "stamp": local_wall.isoformat(timespec="seconds"),
                    "id": founding_id,
                },
            )
        expected = true_run.isoformat(timespec="seconds") + "+00:00"

        source = upload_csv(client, "same-schema.csv", base_csv_bytes())
        rerun = client.post(f"/api/v1/tasks/{task_id}/rerun", json={"data_source_ref": source})
        assert rerun.status_code == 200
        rerun_id = rerun.json()["report_id"]
        stored = client.get(f"/api/v1/reports/{rerun_id}").json()
        founding = client.get(f"/api/v1/reports/{founding_id}").json()
        task = client.get(f"/api/v1/tasks/{task_id}").json()

        # 写操作的响应体同样只带 UTC 时刻
        renamed = client.patch(f"/api/v1/tasks/{task_id}", json={"title": "改名后的任务"})
        voted = client.post(f"/api/v1/reports/{rerun_id}/feedback", json={"verdict": "useful"})
        pack = client.get("/api/v1/context-pack").json()
        saved_pack = client.put("/api/v1/context-pack", json={"payload": pack["payload"]})
        reset_pack = client.post("/api/v1/context-pack/reset")

    assert rerun.json()["report"]["previous_comparison"]["previous_ran_at"] == expected
    assert stored["report"]["previous_comparison"]["previous_ran_at"] == expected
    assert founding["ran_at"] == expected
    assert founding["report"]["metadata"]["ran_at"] == expected
    assert [ref["id"] for ref in task["reports"]] == [rerun_id, founding_id]
    for label, response in {
        "rerun": rerun,
        "patch task": renamed,
        "feedback": voted,
        "put pack": saved_pack,
        "reset pack": reset_pack,
    }.items():
        assert response.status_code == 200, label
        assert assert_all_timestamps_utc(response.json(), label) >= 1, label


# ------------------------------------------------------------------ 全接口走查
def test_every_timestamp_in_api_responses_is_utc_aware():
    build_legacy_database()

    with TestClient(app) as client:
        run = client.post(
            "/api/v1/reports/run",
            json={"analysis_goal": "帮我生成周度经营复盘", "data_source_ref": SAMPLE_SOURCE},
        )
        assert run.status_code == 200
        fresh_id = run.json()["report_id"]
        saved = client.post("/api/v1/tasks", json={"report_id": fresh_id})
        assert saved.status_code == 201
        feedback = client.post(
            f"/api/v1/reports/{fresh_id}/feedback", json={"verdict": "useful", "comment": "ok"}
        )
        assert feedback.status_code == 200

        responses = {"POST /reports/run": run.json(), "POST /tasks": saved.json()}
        paths = [
            "/api/v1/reports",
            f"/api/v1/reports/{fresh_id}",
            "/api/v1/reports/legacy-docker",
            "/api/v1/reports/legacy-local",
            "/api/v1/tasks",
            f"/api/v1/tasks/{saved.json()['id']}",
            "/api/v1/tasks/task-legacy",
            "/api/v1/datasets",
            "/api/v1/datasets/ds-local",
            f"/api/v1/reports/{fresh_id}/feedback",
            "/api/v1/feedback",
            "/api/v1/context-pack",
        ]
        for path in paths:
            response = client.get(path)
            assert response.status_code == 200, path
            responses[f"GET {path}"] = response.json()

    checked = sum(assert_all_timestamps_utc(body, label) for label, body in responses.items())
    assert checked >= 40
    # 新报告的 payload 时刻精确到秒
    fresh_report = responses["POST /reports/run"]["report"]
    assert datetime.fromisoformat(fresh_report["metadata"]["ran_at"]).microsecond == 0
