from __future__ import annotations

import logging
from copy import deepcopy
from dataclasses import asdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db.models import (
    AnalysisTask,
    ContextPackRecord,
    Dataset,
    Report,
    ReportFeedback,
)
from app.modules.context_pack import (
    builtin_pack_name,
    effective_version,
    load_default_context_pack,
    stamped_payload,
)
from app.modules.field_mapping import build_field_profile
from app.modules.schemas import TableData
from app.modules.task_fingerprint import build_schema_fingerprint
from app.timestamps import as_utc, parse_iso, utc_now

logger = logging.getLogger(__name__)


def save_dataset(
    session: Session,
    table: TableData,
    *,
    context_pack: dict[str, Any] | None = None,
) -> Dataset:
    dataset = Dataset(
        data_source_ref_json=asdict(table.data_source_ref),
        schema_summary_json=asdict(table.schema_summary),
        preview_json=asdict(table.preview),
        field_profile_json=asdict(build_field_profile(table.schema_summary, context_pack)),
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
    *,
    task_id: str | None = None,
    context_pack: dict[str, Any] | None = None,
) -> str:
    dataset = save_dataset(session, table, context_pack=context_pack)
    stored = save_report(session, dataset, task, report)
    stored.task_id = task_id
    return stored.id


def save_task(
    session: Session,
    report: Report,
    *,
    title: str | None = None,
) -> AnalysisTask:
    schema_fingerprint, schema_fingerprint_json = build_schema_fingerprint(
        report.dataset.field_profile_json,
        context_pack_name=report.context_pack_name,
        context_pack_version=report.context_pack_version,
    )
    task = AnalysisTask(
        title=report.task_title if title is None else title,
        analysis_goal=report.analysis_goal,
        structured_task_json=deepcopy(report.structured_task_json),
        schema_fingerprint=schema_fingerprint,
        schema_fingerprint_json=schema_fingerprint_json,
        context_pack_name=report.context_pack_name,
        context_pack_version=report.context_pack_version,
        source_dataset_id=report.dataset_id,
        status="active",
    )
    session.add(task)
    session.flush()
    report.task_id = task.id
    return task


FEEDBACK_VOTER = "local"


def upsert_report_feedback(
    session: Session,
    report_id: str,
    *,
    verdict: str,
    comment: str,
) -> ReportFeedback:
    """一报告一票：重复提交即改票，每次提交都刷新 updated_at（architecture.md §2.3 / §5.1）。

    单语句 ON CONFLICT upsert 而非先查后写：双击或并发提交收敛为同一行，不会撞唯一约束。
    """
    now = utc_now()
    statement = (
        sqlite_insert(ReportFeedback)
        .values(
            report_id=report_id,
            voter=FEEDBACK_VOTER,
            verdict=verdict,
            comment=comment,
            created_at=now,
            updated_at=now,
        )
        .on_conflict_do_update(
            index_elements=[ReportFeedback.report_id, ReportFeedback.voter],
            set_={"verdict": verdict, "comment": comment, "updated_at": now},
        )
    )
    session.execute(statement)
    return session.scalars(
        select(ReportFeedback)
        .where(ReportFeedback.report_id == report_id, ReportFeedback.voter == FEEDBACK_VOTER)
        .execution_options(populate_existing=True)
    ).one()


def report_feedback(session: Session, report_id: str) -> ReportFeedback | None:
    return session.scalars(
        select(ReportFeedback).where(
            ReportFeedback.report_id == report_id,
            ReportFeedback.voter == FEEDBACK_VOTER,
        )
    ).one_or_none()


def active_context_pack_record(session: Session) -> ContextPackRecord | None:
    return session.scalars(
        select(ContextPackRecord).where(ContextPackRecord.name == builtin_pack_name())
    ).one_or_none()


def seed_context_pack(session: Session) -> ContextPackRecord:
    """活动包缺失时以内置出厂包种子（revision 0）；已存在则原样返回（幂等）。"""
    record = active_context_pack_record(session)
    if record is not None:
        return record

    builtin = load_default_context_pack()
    base_version = str(builtin["meta"]["version"])
    record = ContextPackRecord(
        name=str(builtin["meta"]["name"]),
        base_version=base_version,
        revision=0,
        payload_json=stamped_payload(builtin, effective_version(base_version, 0)),
    )
    session.add(record)
    session.flush()
    return record


def save_context_pack(session: Session, payload: dict[str, Any]) -> ContextPackRecord:
    """保存活动包：revision + 1（永不重置回退），meta.version 由服务端按版本语义覆盖。"""
    record = seed_context_pack(session)
    record.revision += 1
    record.payload_json = stamped_payload(
        payload,
        effective_version(record.base_version, record.revision),
    )
    session.flush()
    return record


def reset_context_pack(session: Session) -> ContextPackRecord:
    """恢复出厂：payload 还原为内置内容，revision 照常 +1。"""
    return save_context_pack(session, load_default_context_pack())


def ensure_seeded_context_pack() -> None:
    """启动期种子；失败只记录日志不阻断启动（运行期读失败会回落内置包）。"""
    from app.db.engine import SessionLocal, get_engine

    try:
        with SessionLocal(bind=get_engine()) as session:
            seed_context_pack(session)
            session.commit()
    except SQLAlchemyError as exc:
        logger.warning(
            "Context Pack 种子写入失败（%s），运行期将回落内置出厂包。",
            type(exc).__name__,
        )


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
    """metadata.ran_at → 库列：带偏移的值先换算为 UTC；无偏移按 UTC；缺失或无法解析取当前时刻。"""
    if isinstance(value, datetime):
        return as_utc(value)
    parsed = parse_iso(value)
    return as_utc(parsed) if parsed is not None else utc_now()
