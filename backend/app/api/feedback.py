"""报告反馈 API（architecture.md §2.3 v0.14 / §5.1）：一报告一票，只落本地库，无任何外发。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Body, Depends
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.history_serializers import normalize_pagination, serialize_datetime
from app.db.engine import get_db
from app.db.models import Report, ReportFeedback
from app.modules.persistence import report_feedback, upsert_report_feedback

router = APIRouter()

VERDICTS = ("useful", "not_useful")
MAX_COMMENT_LENGTH = 500


class FeedbackInvalid(ValueError):
    pass


@router.post("/reports/{report_id}/feedback")
def submit_feedback(
    report_id: str,
    session: Annotated[Session, Depends(get_db)],
    # 缺省 body 与 JSON null 进入统一校验（→ FEEDBACK_INVALID），不交给框架 422。
    payload: Annotated[Any, Body()] = None,
):
    try:
        verdict, comment = parse_feedback(payload)
    except FeedbackInvalid as exc:
        return JSONResponse(
            status_code=400,
            content={"code": "FEEDBACK_INVALID", "message": str(exc)},
        )
    if not report_exists(session, report_id):
        return report_not_found()

    try:
        feedback = upsert_report_feedback(session, report_id, verdict=verdict, comment=comment)
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    return serialize_feedback(feedback)


@router.get("/reports/{report_id}/feedback")
def get_feedback(report_id: str, session: Annotated[Session, Depends(get_db)]):
    if not report_exists(session, report_id):
        return report_not_found()
    feedback = report_feedback(session, report_id)
    return {"feedback": serialize_feedback(feedback) if feedback is not None else None}


@router.get("/feedback")
def list_feedback(
    session: Annotated[Session, Depends(get_db)],
    limit: int = 20,
    offset: int = 0,
) -> dict[str, Any]:
    limit, offset = normalize_pagination(limit, offset)
    counts: dict[str, int] = dict(
        session.execute(
            select(ReportFeedback.verdict, func.count()).group_by(ReportFeedback.verdict)
        ).all()
    )
    # 只取报告标题，不加载整份 report_json。
    rows = session.execute(
        select(ReportFeedback, Report.task_title)
        .outerjoin(Report, Report.id == ReportFeedback.report_id)
        .order_by(ReportFeedback.updated_at.desc(), ReportFeedback.id.desc())
        .limit(limit)
        .offset(offset)
    ).all()
    return {
        "items": [serialize_feedback_list_item(feedback, title) for feedback, title in rows],
        "total": sum(counts.values()),
        "limit": limit,
        "offset": offset,
        # 统计全部反馈、不随分页变化；「有用占比」由消费方计算。
        "aggregate": {
            "useful_count": counts.get("useful", 0),
            "not_useful_count": counts.get("not_useful", 0),
        },
    }


def parse_feedback(payload: Any) -> tuple[str, str]:
    """未知字段（含 voter）一律忽略：投票人当前恒为 "local"，API 不暴露。"""
    if not isinstance(payload, dict):
        raise FeedbackInvalid("反馈内容格式不正确。")
    verdict = payload.get("verdict")
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        raise FeedbackInvalid("请选择「有用」或「没用」。")
    comment = payload.get("comment")
    if comment is None:
        comment = ""
    if not isinstance(comment, str):
        raise FeedbackInvalid("反馈内容格式不正确。")
    try:
        # JSON 转义可带入孤立代理项（如 "\ud800"），无法以 UTF-8 落库：按入参非法处理而非 500。
        comment.encode("utf-8")
    except UnicodeEncodeError as exc:
        raise FeedbackInvalid("反馈内容格式不正确。") from exc
    comment = comment.strip()
    if len(comment) > MAX_COMMENT_LENGTH:
        raise FeedbackInvalid(f"反馈内容过长（最多 {MAX_COMMENT_LENGTH} 字）。")
    return verdict, comment


def serialize_feedback(feedback: ReportFeedback) -> dict[str, Any]:
    return {
        "report_id": feedback.report_id,
        "verdict": feedback.verdict,
        "comment": feedback.comment,
        "updated_at": serialize_datetime(feedback.updated_at),
    }


def serialize_feedback_list_item(
    feedback: ReportFeedback,
    report_title: str | None,
) -> dict[str, Any]:
    return {
        "id": feedback.id,
        **serialize_feedback(feedback),
        "report_title": report_title or "",
    }


def report_exists(session: Session, report_id: str) -> bool:
    return session.scalar(select(Report.id).where(Report.id == report_id)) is not None


def report_not_found() -> JSONResponse:
    return JSONResponse(
        status_code=404,
        content={"code": "REPORT_NOT_FOUND", "message": "未找到历史报告。"},
    )
