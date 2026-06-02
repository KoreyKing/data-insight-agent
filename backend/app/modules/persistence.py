from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime
from typing import Any

from sqlalchemy.orm import Session

from app.db.models import Dataset, Report
from app.modules.field_mapping import build_field_profile
from app.modules.schemas import TableData


def save_dataset(session: Session, table: TableData) -> Dataset:
    dataset = Dataset(
        data_source_ref_json=asdict(table.data_source_ref),
        schema_summary_json=asdict(table.schema_summary),
        preview_json=asdict(table.preview),
        field_profile_json=asdict(build_field_profile(table.schema_summary)),
        file_path=table.data_source_ref.location,
        file_name=table.data_source_ref.name,
        row_count=table.row_count,
        column_count=table.column_count,
    )
    session.add(dataset)
    session.flush()
    return dataset


def save_report(
    session: Session,
    dataset: Dataset,
    task: dict[str, Any],
    report: dict[str, Any],
) -> Report:
    metadata = report.get("metadata") if isinstance(report.get("metadata"), dict) else {}
    stored = Report(
        dataset_id=dataset.id,
        task_title=as_string(task.get("task_title")) or as_string(report.get("title")) or "",
        analysis_goal=as_string(task.get("analysis_goal"))
        or as_string(report.get("analysis_goal"))
        or "",
        structured_task_json=task,
        metrics_json=as_list(task.get("metrics")),
        dimensions_json=as_list(task.get("dimensions")),
        comparison=as_string(task.get("comparison")) or "",
        context_pack_name=as_string(report.get("context_pack_name"))
        or as_string(task.get("context_pack_name"))
        or "",
        context_pack_version=as_string(report.get("context_pack_version"))
        or as_string(task.get("context_pack_version"))
        or "",
        report_json=report,
        status=as_string(report.get("status")) or "",
        summary=as_string(report.get("summary")) or "",
        model_used=as_string(metadata.get("model")) or "",
        iterations_used=as_int(metadata.get("iterations_used")),
        token_used=as_int(metadata.get("token_used")),
        ran_at=parse_datetime(metadata.get("ran_at")),
    )
    session.add(stored)
    session.flush()
    return stored


def save_report_run(
    session: Session,
    table: TableData,
    task: dict[str, Any],
    report: dict[str, Any],
) -> str:
    dataset = save_dataset(session, table)
    stored = save_report(session, dataset, task, report)
    return stored.id


def as_string(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def as_list(value: Any) -> list[Any]:
    return list(value) if isinstance(value, list) else []


def as_int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def parse_datetime(value: Any) -> datetime:
    if isinstance(value, datetime):
        return ensure_timezone(value)
    if isinstance(value, str):
        try:
            return ensure_timezone(datetime.fromisoformat(value))
        except ValueError:
            pass
    return datetime.now(UTC)


def ensure_timezone(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value
