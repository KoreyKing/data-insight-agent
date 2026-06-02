from __future__ import annotations

from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from app.api.history_serializers import (
    normalize_pagination,
    serialize_dataset_detail,
    serialize_dataset_list_item,
)
from app.db.engine import SessionLocal, get_engine, init_db
from app.db.models import Dataset

router = APIRouter()


@router.get("/datasets")
def list_datasets(limit: int = 20, offset: int = 0) -> dict[str, Any]:
    init_db()
    limit, offset = normalize_pagination(limit, offset)
    with SessionLocal(bind=get_engine()) as session:
        total = session.scalar(select(func.count()).select_from(Dataset)) or 0
        datasets = session.scalars(
            select(Dataset)
            .options(selectinload(Dataset.reports))
            .order_by(Dataset.created_at.desc())
            .limit(limit)
            .offset(offset)
        ).all()
        return {
            "items": [serialize_dataset_list_item(dataset) for dataset in datasets],
            "total": total,
            "limit": limit,
            "offset": offset,
        }


@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id: str):
    init_db()
    with SessionLocal(bind=get_engine()) as session:
        dataset = session.scalars(
            select(Dataset)
            .options(selectinload(Dataset.reports))
            .where(Dataset.id == dataset_id)
        ).one_or_none()
        if dataset is None:
            return JSONResponse(
                status_code=404,
                content={"code": "DATASET_NOT_FOUND", "message": "未找到数据源。"},
            )
        return serialize_dataset_detail(dataset)
