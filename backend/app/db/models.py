from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base


def utc_now() -> datetime:
    return datetime.now(UTC)


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    data_source_ref_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_summary_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    preview_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    field_profile_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    file_path: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(255), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False)
    column_count: Mapped[int] = mapped_column(Integer, nullable=False)

    reports: Mapped[list[Report]] = relationship(back_populates="dataset")


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    task_title: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_goal: Mapped[str] = mapped_column(Text, nullable=False)
    structured_task_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    metrics_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    dimensions_json: Mapped[list[Any]] = mapped_column(JSON, nullable=False)
    comparison: Mapped[str] = mapped_column(String(80), nullable=False)
    context_pack_name: Mapped[str] = mapped_column(String(120), nullable=False)
    context_pack_version: Mapped[str] = mapped_column(String(40), nullable=False)
    report_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    model_used: Mapped[str] = mapped_column(String(120), nullable=False)
    iterations_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    token_used: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ran_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        default=utc_now,
    )

    dataset: Mapped[Dataset] = relationship(back_populates="reports")
