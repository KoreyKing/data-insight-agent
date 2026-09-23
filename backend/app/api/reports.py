from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.api.history_serializers import (
    normalize_pagination,
    sanitize_report_payload,
    serialize_report_detail,
    serialize_report_list_item,
)
from app.api.runtime import error_response, resolve_table
from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import Report
from app.modules.context_pack import load_active_context_pack
from app.modules.file_ingestion import IngestionError
from app.modules.report_runner import execute_report_run
from app.modules.reporting import default_structured_task

router = APIRouter()


@router.get("/reports")
def list_reports(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    init_db()
    limit, offset = normalize_pagination(limit, offset)
    with SessionLocal(bind=get_engine()) as session:
        total = session.scalar(select(func.count()).select_from(Report)) or 0
        reports = session.scalars(
            select(Report)
            .options(selectinload(Report.dataset))
            # created_at 恒为 UTC、与运行时刻相差不足 1 秒；存量 ran_at 列是生成进程本地时间，
            # 不能直接排序（architecture.md §2.4 第 6 条）。
            .order_by(Report.created_at.desc(), Report.id.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [serialize_report_list_item(report) for report in reports],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.get("/reports/{report_id}")
def get_report(report_id: str):
    init_db()
    with SessionLocal(bind=get_engine()) as session:
        report = session.scalars(
            select(Report)
            .options(selectinload(Report.dataset), selectinload(Report.task))
            .where(Report.id == report_id)
        ).one_or_none()
        if report is None:
            return JSONResponse(
                status_code=404,
                content={"code": "REPORT_NOT_FOUND", "message": "未找到历史报告。"},
            )
        return serialize_report_detail(report, previous_report_of(session, report))


def previous_report_of(session: Session, report: Report) -> Report | None:
    """previous_comparison 所指的上期报告：存量报告的上期时间按它自己的生成进程换算（§2.4）。"""
    comparison = report.report_json.get("previous_comparison")
    previous_id = comparison.get("previous_report_id") if isinstance(comparison, dict) else None
    if not isinstance(previous_id, str) or not previous_id:
        return None
    return session.get(Report, previous_id)


@router.post("/reports/run")
def run_report(payload: dict[str, Any]):
    analysis_goal = str(payload.get("analysis_goal") or "帮我生成周度经营复盘")
    data_source_ref = payload.get("data_source_ref") or {}

    try:
        table = resolve_table(data_source_ref)
    except IngestionError as exc:
        return error_response(exc)

    # 一次运行只解析一次活动包（§6.4）：任务快照、字段识别与报告口径版本同源。
    pack = load_active_context_pack()
    task = task_from_payload(payload, analysis_goal, asdict(table.data_source_ref), pack)
    report_id, report = execute_report_run(table, task, context_pack=pack)
    response_report = sanitize_report_payload(report, table.data_source_ref.name)
    if report.get("status") == "failed":
        return JSONResponse(
            status_code=400,
            content={"code": "CSV_KEY_FIELD_MISSING", "report": response_report},
        )
    return {"report_id": report_id, "report": response_report}


def task_from_payload(
    payload: dict[str, Any],
    analysis_goal: str,
    data_source_ref: dict[str, Any],
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = default_structured_task(analysis_goal, data_source_ref, context_pack=context_pack)
    incoming = payload.get("task")
    if not isinstance(incoming, dict):
        return task

    for key, value in incoming.items():
        if key == "execution_limits" and isinstance(value, dict):
            task[key] = {**task[key], **value}
        else:
            task[key] = value
    task["analysis_goal"] = analysis_goal
    task["data_source_ref"] = data_source_ref
    return task
