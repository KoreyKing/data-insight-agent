from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.db.models import AnalysisTask, Dataset, Report
from app.modules.context_pack import context_pack_display_names
from app.timestamps import isoformat_utc, normalize_report_times, report_order_key, report_ran_at

MAX_LIMIT = 50
DEFAULT_LIMIT = 20
# SQLite 绑定参数是有符号 64 位整数，越界的 offset 会在驱动层抛 OverflowError（500）。
# 与 limit 同样按「夹逼后原样回显」处理：超出可表示范围等价于翻过所有行，返回空列表。
MAX_OFFSET = 2**63 - 1


def normalize_pagination(limit: int = DEFAULT_LIMIT, offset: int = 0) -> tuple[int, int]:
    return max(0, min(limit, MAX_LIMIT)), max(0, min(offset, MAX_OFFSET))


def serialize_report_list_item(report: Report) -> dict[str, Any]:
    findings = report_findings(report)
    return {
        "id": report.id,
        "dataset_id": report.dataset_id,
        "title": report.task_title,
        "summary": report.summary,
        "status": report.status,
        "ran_at": serialize_datetime(report_ran_at(report)),
        "created_at": serialize_datetime(report.created_at),
        "model": report.model_used,
        "loop_rounds": report_loop_rounds(report),
        "iterations_used": report.iterations_used,
        "token_used": report.token_used,
        "finding_count": len(findings),
        "anomaly_count": sum(1 for finding in findings if finding.get("type") == "anomaly"),
        "dataset": serialize_dataset_summary(report.dataset),
    }


def serialize_report_detail(
    report: Report,
    previous_report: Report | None = None,
) -> dict[str, Any]:
    """previous_report 是 previous_comparison 所指的上期报告，用于换算存量上期时间（§2.4）。"""
    payload = sanitize_report_payload(report.report_json, report.dataset.file_name)
    return {
        **serialize_report_list_item(report),
        "task_id": report.task_id,
        "task_title": report.task.title if report.task is not None else None,
        "report": normalize_report_times(payload, report, previous_report),
        "task": sanitize_task_payload(report.structured_task_json, report.dataset.file_name),
        "dataset": serialize_dataset_summary(report.dataset),
    }


def serialize_task_list_item(task: AnalysisTask) -> dict[str, Any]:
    reports = sorted(task.reports, key=report_order_key, reverse=True)
    last_report = reports[0] if reports else None
    return {
        "id": task.id,
        "title": task.title,
        "analysis_goal": task.analysis_goal,
        "created_at": serialize_datetime(task.created_at),
        "status": task.status,
        "context_pack_name": task.context_pack_name,
        "context_pack_version": task.context_pack_version,
        "report_count": len(reports),
        "last_run_at": serialize_datetime(report_ran_at(last_report)) if last_report else None,
    }


def serialize_task_detail(
    task: AnalysisTask,
    display_names: dict[str, str] | None = None,
) -> dict[str, Any]:
    reports = sorted(task.reports, key=report_order_key, reverse=True)
    display_names = display_names if display_names is not None else context_pack_display_names()
    canonical_field_names = task.schema_fingerprint_json.get("canonical_fields")
    if not isinstance(canonical_field_names, list):
        canonical_field_names = []
    canonical_fields = [
        {
            "name": name,
            "display_name": display_names.get(name, name),
        }
        for name in canonical_field_names
        if isinstance(name, str)
    ]
    return {
        **serialize_task_list_item(task),
        "structured_task": sanitize_task_payload(
            task.structured_task_json,
            task.source_dataset.file_name,
        ),
        "schema_fingerprint": task.schema_fingerprint,
        "schema_fingerprint_json": deepcopy(task.schema_fingerprint_json),
        "canonical_fields": canonical_fields,
        "source_dataset_id": task.source_dataset_id,
        "reports": [serialize_task_report_ref(report) for report in reports],
    }


def serialize_task_report_ref(report: Report) -> dict[str, Any]:
    return {
        "id": report.id,
        "status": report.status,
        "ran_at": serialize_datetime(report_ran_at(report)),
        "summary": report.summary,
        "finding_count": len(report_findings(report)),
        "has_previous_comparison": "previous_comparison" in report.report_json,
    }


def serialize_dataset_list_item(dataset: Dataset) -> dict[str, Any]:
    reports = sorted(dataset.reports, key=report_order_key, reverse=True)
    latest_report = reports[0] if reports else None
    return {
        "id": dataset.id,
        "file_name": dataset.file_name,
        "data_source_type": dataset.data_source_ref_json.get("type") or "",
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
        "created_at": serialize_datetime(dataset.created_at),
        "status": dataset_status(dataset),
        "report_count": len(reports),
        "latest_report_at": (
            serialize_datetime(report_ran_at(latest_report)) if latest_report else None
        ),
    }


def serialize_dataset_detail(dataset: Dataset) -> dict[str, Any]:
    reports = sorted(dataset.reports, key=report_order_key, reverse=True)
    return {
        **serialize_dataset_list_item(dataset),
        "data_source_ref": sanitized_data_source_ref(dataset),
        "schema_summary": dataset.schema_summary_json,
        "preview": dataset.preview_json,
        "field_profile": dataset.field_profile_json,
        "reports": [serialize_dataset_report_ref(report) for report in reports],
    }


def serialize_dataset_summary(dataset: Dataset) -> dict[str, Any]:
    return {
        "id": dataset.id,
        "file_name": dataset.file_name,
        "row_count": dataset.row_count,
        "column_count": dataset.column_count,
    }


def serialize_dataset_report_ref(report: Report) -> dict[str, Any]:
    findings = report_findings(report)
    return {
        "id": report.id,
        "title": report.task_title,
        "summary": report.summary,
        "status": report.status,
        "ran_at": serialize_datetime(report_ran_at(report)),
        "created_at": serialize_datetime(report.created_at),
        "model": report.model_used,
        "finding_count": len(findings),
        "anomaly_count": sum(1 for finding in findings if finding.get("type") == "anomaly"),
    }


def sanitized_data_source_ref(dataset: Dataset) -> dict[str, Any]:
    data_source_ref = deepcopy(dataset.data_source_ref_json)
    data_source_ref["location"] = dataset.file_name
    data_source_ref.setdefault("name", dataset.file_name)
    return data_source_ref


def sanitize_report_payload(report: dict[str, Any], file_name: str) -> dict[str, Any]:
    payload = deepcopy(report)
    metadata = payload.get("metadata")
    if isinstance(metadata, dict):
        data_source = metadata.get("data_source")
        if isinstance(data_source, dict):
            data_source["location"] = file_name
            data_source.setdefault("name", file_name)
    return payload


def sanitize_task_payload(task: dict[str, Any], file_name: str) -> dict[str, Any]:
    payload = deepcopy(task)
    data_source_ref = payload.get("data_source_ref")
    if isinstance(data_source_ref, dict):
        data_source_ref["location"] = file_name
        data_source_ref.setdefault("name", file_name)
    return payload


def report_findings(report: Report) -> list[dict[str, Any]]:
    findings = report.report_json.get("findings")
    if not isinstance(findings, list):
        return []
    return [finding for finding in findings if isinstance(finding, dict)]


def report_loop_rounds(report: Report) -> int | None:
    metadata = report.report_json.get("metadata")
    if not isinstance(metadata, dict):
        return None
    value = metadata.get("loop_rounds")
    if isinstance(value, bool) or not isinstance(value, int):
        return None
    return value


def dataset_status(dataset: Dataset) -> str:
    return "ready" if dataset.field_profile_json.get("is_valid") is True else "partial"


def serialize_datetime(value: datetime | None) -> str | None:
    """对外时刻一律带 `+00:00`（§2.4 第 3 条）。"""
    return isoformat_utc(value)
