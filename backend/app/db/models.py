from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import uuid4

from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.engine import Dialect
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from app.db.base import Base
from app.timestamps import as_utc, utc_now


class UTCDateTime(TypeDecorator[datetime]):
    """SQLite 不存时区：写入换算为 UTC 后去掉时区，读出一律标注 UTC（architecture.md §2.4）。

    写入只接受带时区的 datetime：无时区值多半是误用 datetime.now()，静默落库会让本地时间冒充 UTC。
    DDL 与 DateTime 相同（DATETIME），既有库无需变更。存量 reports.ran_at 是生成进程本地时间，
    读出后仍被标为 UTC，由 app.timestamps.report_ran_at 换算。
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("UTCDateTime 只接受带时区的 datetime（architecture.md §2.4）")
        return as_utc(value).replace(tzinfo=None)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        return as_utc(value) if value is not None else None


class Dataset(Base):
    __tablename__ = "datasets"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
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

    reports: Mapped[list[Report]] = relationship(
        back_populates="dataset",
        foreign_keys="Report.dataset_id",
    )
    analysis_tasks: Mapped[list[AnalysisTask]] = relationship(
        back_populates="source_dataset",
        foreign_keys="AnalysisTask.source_dataset_id",
    )


class AnalysisTask(Base):
    __tablename__ = "analysis_tasks"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    analysis_goal: Mapped[str] = mapped_column(Text, nullable=False)
    structured_task_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    schema_fingerprint: Mapped[str] = mapped_column(String(80), nullable=False, index=True)
    schema_fingerprint_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    context_pack_name: Mapped[str] = mapped_column(String(120), nullable=False)
    context_pack_version: Mapped[str] = mapped_column(String(40), nullable=False)
    source_dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("datasets.id"),
        nullable=False,
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="active")

    source_dataset: Mapped[Dataset] = relationship(
        back_populates="analysis_tasks",
        foreign_keys=[source_dataset_id],
    )
    reports: Mapped[list[Report]] = relationship(
        back_populates="task",
        foreign_keys="Report.task_id",
    )


class ContextPackRecord(Base):
    """活动 Context Pack（当前单包）。内置 JSON 降级为出厂镜像：种子 / 恢复默认 / 读失败回落。"""

    __tablename__ = "context_packs"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    name: Mapped[str] = mapped_column(String(120), nullable=False, unique=True)
    base_version: Mapped[str] = mapped_column(String(40), nullable=False)
    revision: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    dataset_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("datasets.id"),
        nullable=False,
        index=True,
    )
    task_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("analysis_tasks.id"),
        nullable=True,
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
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )

    dataset: Mapped[Dataset] = relationship(
        back_populates="reports",
        foreign_keys=[dataset_id],
    )
    task: Mapped[AnalysisTask | None] = relationship(
        back_populates="reports",
        foreign_keys=[task_id],
    )


class ReportFeedback(Base):
    """报告反馈：一（报告 × 投票人）一票。投票人当前恒为 "local"，复合唯一键为多位读者投票预留。"""

    __tablename__ = "report_feedbacks"
    __table_args__ = (
        UniqueConstraint("report_id", "voter", name="uq_report_feedbacks_report_id_voter"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    report_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("reports.id"),
        nullable=False,
    )
    voter: Mapped[str] = mapped_column(String(64), nullable=False, default="local")
    verdict: Mapped[str] = mapped_column(String(16), nullable=False)
    comment: Mapped[str] = mapped_column(Text, nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
    )
    updated_at: Mapped[datetime] = mapped_column(
        UTCDateTime(),
        nullable=False,
        default=utc_now,
        onupdate=utc_now,
    )
