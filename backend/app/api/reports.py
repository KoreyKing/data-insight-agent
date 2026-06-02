from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.history_serializers import (
    normalize_pagination,
    serialize_report_detail,
    serialize_report_list_item,
)
from app.api.runtime import error_response, resolve_table
from app.config import get_settings
from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import Report
from app.llm.client import get_llm_client
from app.modules.analysis_loop import run_analysis_loop
from app.modules.file_ingestion import IngestionError
from app.modules.persistence import save_report_run
from app.modules.reporting import default_structured_task, generate_traceable_report

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
            .order_by(Report.ran_at.desc(), Report.created_at.desc())
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
            select(Report).options(selectinload(Report.dataset)).where(Report.id == report_id)
        ).one_or_none()
        if report is None:
            return JSONResponse(
                status_code=404,
                content={"code": "REPORT_NOT_FOUND", "message": "未找到历史报告。"},
            )
        return serialize_report_detail(report)


@router.post("/reports/run")
def run_report(payload: dict[str, Any]):
    analysis_goal = str(payload.get("analysis_goal") or "帮我生成周度经营复盘")
    data_source_ref = payload.get("data_source_ref") or {}

    try:
        table = resolve_table(data_source_ref)
    except IngestionError as exc:
        return error_response(exc)

    settings = get_settings()
    llm_client = get_llm_client(settings)
    task = task_from_payload(payload, analysis_goal, asdict(table.data_source_ref))
    if llm_client is None:
        report = generate_traceable_report(table, analysis_goal)
    else:
        report = run_analysis_loop(
            table,
            task,
            llm_client,
            model_name=settings.llm_model,
        )
    if report.get("status") == "failed":
        return JSONResponse(
            status_code=400,
            content={"code": "CSV_KEY_FIELD_MISSING", "report": report},
        )

    init_db()
    with SessionLocal(bind=get_engine()) as session:
        report_id = save_report_run(session, table, task, report)
        session.commit()
    return {"report_id": report_id, "report": report}


def task_from_payload(
    payload: dict[str, Any],
    analysis_goal: str,
    data_source_ref: dict[str, Any],
) -> dict[str, Any]:
    task = default_structured_task(analysis_goal, data_source_ref)
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
