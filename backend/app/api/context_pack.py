"""业务口径（Context Pack）读取与编辑 API（architecture.md §2.3 / §6.4）。"""
from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.api.history_serializers import serialize_datetime
from app.db.engine import get_db
from app.db.models import ContextPackRecord
from app.modules.context_pack import effective_version, load_default_context_pack
from app.modules.context_pack_validation import validate_context_pack_edit
from app.modules.persistence import (
    reset_context_pack,
    save_context_pack,
    seed_context_pack,
)

router = APIRouter()


@router.get("/context-pack")
def get_context_pack(session: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    record = commit(session, seed_context_pack(session))
    return serialize_context_pack(record)


@router.put("/context-pack")
def put_context_pack(payload: dict[str, Any], session: Annotated[Session, Depends(get_db)]):
    candidate = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    validation = validate_context_pack_edit(candidate)
    if not validation.passed:
        return JSONResponse(
            status_code=400,
            content={
                "code": "CONTEXT_PACK_VALIDATION_FAILED",
                "message": "业务口径未通过校验，未保存任何修改。",
                "details": {"errors": [issue.as_dict() for issue in validation.errors]},
            },
        )

    record = commit(session, save_context_pack(session, validation.payload))
    return {
        **serialize_context_pack(record),
        "warnings": [issue.as_dict() for issue in validation.warnings],
    }


@router.post("/context-pack/reset")
def reset_context_pack_endpoint(session: Annotated[Session, Depends(get_db)]) -> dict[str, Any]:
    record = commit(session, reset_context_pack(session))
    return serialize_context_pack(record)


def serialize_context_pack(record: ContextPackRecord) -> dict[str, Any]:
    payload = record.payload_json
    return {
        "name": record.name,
        "version": effective_version(record.base_version, record.revision),
        "revision": record.revision,
        "is_modified": is_modified(payload),
        "updated_at": serialize_datetime(record.updated_at),
        "payload": payload,
    }


def is_modified(payload: Any) -> bool:
    """与内置内容比较（忽略服务端计算的 meta.version）：reset 后 revision 递增但仍为 false。"""
    return comparable(payload) != comparable(load_default_context_pack())


def comparable(payload: Any) -> Any:
    if not isinstance(payload, dict):
        return payload
    without_version = {key: value for key, value in payload.items() if key != "meta"}
    meta = payload.get("meta")
    if isinstance(meta, dict):
        without_version["meta"] = {key: value for key, value in meta.items() if key != "version"}
    return without_version


def commit(session: Session, record: ContextPackRecord) -> ContextPackRecord:
    try:
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    return record
