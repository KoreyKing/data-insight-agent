from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session, selectinload

from app.api.history_serializers import (
    normalize_pagination,
    sanitize_report_payload,
    sanitize_task_payload,
    serialize_task_detail,
    serialize_task_list_item,
)
from app.api.runtime import error_response, resolve_table
from app.db.engine import get_db
from app.db.models import AnalysisTask, Report
from app.modules.context_pack import context_pack_display_names, load_active_context_pack
from app.modules.field_mapping import build_field_profile
from app.modules.file_ingestion import IngestionError
from app.modules.history_context import history_context_for_task
from app.modules.persistence import save_task
from app.modules.report_runner import execute_report_run
from app.modules.task_fingerprint import build_schema_fingerprint, canonical_fields_from_profile
from app.modules.task_parser import parse_analysis_goal

router = APIRouter()


@router.post("/tasks/parse")
def parse_task(payload: dict[str, Any]) -> dict[str, Any]:
    analysis_goal = str(payload.get("analysis_goal") or "帮我生成周度经营复盘")
    data_source_ref = payload.get("data_source_ref") or {
        "id": "sample-retail",
        "type": "csv",
        "name": "retail_sales_orders.csv",
        "location": "sample",
    }
    try:
        table = resolve_table(data_source_ref)
    except IngestionError as exc:
        return error_response(exc)

    # 一次请求只解析一次活动包：维度选项与结构化任务记录的口径版本必须同源。
    pack = load_active_context_pack()
    result = parse_analysis_goal(
        analysis_goal,
        asdict(table.data_source_ref),
        table.schema_summary,
        context_pack=pack,
    )
    result["task"] = sanitize_task_payload(result["task"], table.data_source_ref.name)
    # Expose the Context Pack dimension catalog (Chinese name + description) so the
    # frontend "添加维度" dropdown can offer human-readable dimensions.
    result["dimension_options"] = [
        {"name": dimension.get("name"), "description": dimension.get("description")}
        for dimension in pack.get("dimensions", [])
        if dimension.get("name")
    ]
    return result


@router.post("/tasks/{task_id}/rerun")
def rerun_task(
    task_id: str,
    payload: dict[str, Any],
    session: Annotated[Session, Depends(get_db)],
):
    task = session.get(AnalysisTask, task_id)
    if task is None:
        return task_error_response(
            "TASK_NOT_FOUND",
            "未找到分析任务。",
            status_code=404,
        )

    data_source_ref = payload.get("data_source_ref")
    source_id = data_source_ref.get("id") if isinstance(data_source_ref, dict) else None
    if (
        not isinstance(source_id, str)
        or not source_id.strip()
        or source_id.strip() == "sample-retail"
    ):
        return error_response(
            IngestionError("UPLOAD_NOT_FOUND", "未找到上传 session，请重新上传文件。")
        )

    try:
        table = resolve_table(data_source_ref)
    except IngestionError as exc:
        return error_response(exc)

    pack = load_active_context_pack()
    actual_fields = set(
        canonical_fields_from_profile(asdict(build_field_profile(table.schema_summary, pack)))
    )
    fingerprint = (
        task.schema_fingerprint_json if isinstance(task.schema_fingerprint_json, dict) else {}
    )
    saved_fields = {
        field.strip()
        for field in fingerprint.get("canonical_fields", [])
        if isinstance(field, str) and field.strip()
    }
    missing_fields = sorted(saved_fields - actual_fields)
    extra_fields = sorted(actual_fields - saved_fields)
    if missing_fields or extra_fields:
        display_names = context_pack_display_names(pack)
        return task_error_response(
            "SCHEMA_MISMATCH",
            "新文件的数据结构与这个任务不一致，无法对比重跑。",
            details={
                "missing_fields": missing_fields,
                "extra_fields": extra_fields,
                "missing_fields_display": [
                    display_names.get(name, name) for name in missing_fields
                ],
                "extra_fields_display": [display_names.get(name, name) for name in extra_fields],
            },
        )

    rerun_task_payload = deepcopy(task.structured_task_json)
    rerun_task_payload["data_source_ref"] = asdict(table.data_source_ref)
    # 链上有上期报告时构建 history_context（architecture.md §3.3）；首期重跑为 None。
    history_context = history_context_for_task(task)
    report_id, report = execute_report_run(
        table,
        rerun_task_payload,
        task_id=task.id,
        history_context=history_context,
        context_pack=pack,
    )
    response_report = sanitize_report_payload(report, table.data_source_ref.name)
    if report.get("status") == "failed":
        return JSONResponse(
            status_code=400,
            content={"code": "CSV_KEY_FIELD_MISSING", "report": response_report},
        )
    return {
        "report_id": report_id,
        "report": response_report,
    }


@router.post("/tasks", status_code=201)
def create_task(
    payload: dict[str, Any],
    session: Annotated[Session, Depends(get_db)],
):
    report_id = str(payload.get("report_id") or "")
    title = None
    if "title" in payload:
        title = normalize_title(payload.get("title"))
        if title is None:
            return task_error_response(
                "TASK_TITLE_INVALID",
                "任务标题须为 1–255 个字符。",
            )

    report = session.scalars(
        select(Report)
        .options(selectinload(Report.dataset), selectinload(Report.task))
        .where(Report.id == report_id)
    ).one_or_none()
    if report is None:
        return task_error_response(
            "REPORT_NOT_FOUND",
            "未找到历史报告。",
            status_code=404,
        )
    if report.task_id is not None:
        return task_error_response(
            "REPORT_ALREADY_LINKED",
            "该报告已归属于分析任务。",
            details={"task_id": report.task_id},
        )
    resolved_title = title if title is not None else normalize_title(report.task_title)
    if resolved_title is None:
        return task_error_response(
            "TASK_TITLE_INVALID",
            "任务标题须为 1–255 个字符。",
        )

    schema_fingerprint, _ = build_schema_fingerprint(
        report.dataset.field_profile_json,
        context_pack_name=report.context_pack_name,
        context_pack_version=report.context_pack_version,
    )
    existing_tasks = session.scalars(
        select(AnalysisTask)
        .where(AnalysisTask.schema_fingerprint == schema_fingerprint)
        .order_by(AnalysisTask.created_at.asc(), AnalysisTask.id.asc())
    ).all()
    warnings = [
        {"task_id": existing.id, "task_title": existing.title} for existing in existing_tasks
    ]

    try:
        task = save_task(session, report, title=resolved_title)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise

    task = load_task_detail(session, task.id)
    payload = serialize_task_detail(task)
    payload["warnings"] = warnings
    return payload


@router.get("/tasks")
def list_tasks(
    session: Annotated[Session, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    limit, offset = normalize_pagination(limit, offset)
    tasks = session.scalars(
        select(AnalysisTask)
        .options(selectinload(AnalysisTask.reports))
        .order_by(AnalysisTask.created_at.desc(), AnalysisTask.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "tasks": [serialize_task_list_item(task) for task in tasks],
        "limit": limit,
        "offset": offset,
    }


@router.get("/tasks/{task_id}")
def get_task(task_id: str, session: Annotated[Session, Depends(get_db)]):
    task = load_task_detail(session, task_id)
    if task is None:
        return task_error_response(
            "TASK_NOT_FOUND",
            "未找到分析任务。",
            status_code=404,
        )
    return serialize_task_detail(task)


@router.patch("/tasks/{task_id}")
def rename_task(
    task_id: str,
    payload: dict[str, Any],
    session: Annotated[Session, Depends(get_db)],
):
    if set(payload) != {"title"} or (title := normalize_title(payload.get("title"))) is None:
        return task_error_response(
            "TASK_TITLE_INVALID",
            "任务标题须为 1–255 个字符，且仅允许修改 title。",
        )

    task = load_task_detail(session, task_id)
    if task is None:
        return task_error_response(
            "TASK_NOT_FOUND",
            "未找到分析任务。",
            status_code=404,
        )
    task.title = title
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    return serialize_task_detail(task)


def load_task_detail(session: Session, task_id: str) -> AnalysisTask | None:
    return session.scalars(
        select(AnalysisTask)
        .options(
            selectinload(AnalysisTask.source_dataset),
            selectinload(AnalysisTask.reports),
        )
        .where(AnalysisTask.id == task_id)
        .execution_options(populate_existing=True)
    ).one_or_none()


def normalize_title(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    title = value.strip()
    if not 1 <= len(title) <= 255:
        return None
    try:
        # JSON 转义可带入孤立代理项（如 "\ud800"），无法以 UTF-8 落库：按入参非法处理而非 500。
        title.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return title


def task_error_response(
    code: str,
    message: str,
    *,
    status_code: int = 400,
    details: dict[str, Any] | None = None,
) -> JSONResponse:
    content: dict[str, Any] = {"code": code, "message": message}
    if details is not None:
        content["details"] = details
    return JSONResponse(status_code=status_code, content=content)
