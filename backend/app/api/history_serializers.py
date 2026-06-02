from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from app.db.models import Dataset, Report

MAX_LIMIT = 50
DEFAULT_LIMIT = 20


def normalize_pagination(limit: int = DEFAULT_LIMIT, offset: int = 0) -> tuple[int, int]:
    return max(0, min(limit, MAX_LIMIT)), max(0, offset)


def serialize_report_list_item(report: Report) -> dict[str, Any]:
    findings = report_findings(report)
    return {
        "id": report.id,
        "dataset_id": report.dataset_id,
        "title": report.task_title,
        "summary": report.summary,
        "status": report.status,
        "ran_at": serialize_datetime(report.ran_at),
        "created_at": serialize_datetime(report.created_at),
        "model": report.model_used,
        "iterations_used": report.iterations_used,
        "token_used": report.token_used,
        "finding_count": len(findings),
        "anomaly_count": sum(1 for finding in findings if finding.get("type") == "anomaly"),
        "dataset": serialize_dataset_summary(report.dataset),
    }


def serialize_report_detail(report: Report) -> dict[str, Any]:
    return {
        **serialize_report_list_item(report),
        "report": sanitize_report_payload(report.report_json, report.dataset.file_name),
        "task": sanitize_task_payload(report.structured_task_json, report.dataset.file_name),
        "dataset": serialize_dataset_summary(report.dataset),
    }


def serialize_dataset_list_item(dataset: Dataset) -> dict[str, Any]:
    reports = sorted(dataset.reports, key=lambda report: report.ran_at, reverse=True)
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
        "latest_report_at": serialize_datetime(latest_report.ran_at) if latest_report else None,
    }


def serialize_dataset_detail(dataset: Dataset) -> dict[str, Any]:
    reports = sorted(dataset.reports, key=lambda report: report.ran_at, reverse=True)
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
        "ran_at": serialize_datetime(report.ran_at),
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


def dataset_status(dataset: Dataset) -> str:
    return "ready" if dataset.field_profile_json.get("is_valid") is True else "partial"


def serialize_datetime(value: datetime | None) -> str | None:
    return value.isoformat() if value is not None else None
