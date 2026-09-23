from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.modules.field_mapping import build_field_profile
from app.modules.file_ingestion import build_schema_summary
from app.modules.schemas import DataSourceRef, SchemaSummary, TableData

CANONICAL_TABLE_NAME = "sales_orders"

# 订单状态取值归一化（architecture.md §6.4）：常见中英文写法映射到分析口径的三个取值。
# 键为归一化后的写法（去首尾空白、小写，空格与连字符视为下划线）；无法识别的取值保留原值。
ORDER_STATUS_ALIASES: dict[str, str] = {
    alias: canonical
    for canonical, aliases in {
        "completed": (
            "completed", "complete", "done", "success", "succeeded", "successful", "paid",
            "fulfilled", "shipped", "delivered",
            "已完成", "完成", "交易成功", "交易完成", "成功", "已支付", "已付款", "买家已付款",
            "待发货", "已发货", "卖家已发货", "已签收", "已收货",
        ),
        "partial_refund": (
            "partial_refund", "partially_refunded", "partial_refunded", "partial_return",
            "partially_returned", "部分退款", "部分退货", "部分退款成功",
        ),
        "refunded": (
            "refunded", "refund", "full_refund", "fully_refunded", "returned", "return",
            "已退款", "退款", "全额退款", "全部退款", "退款成功", "已退货", "退货", "退货退款",
        ),
    }.items()
    for alias in aliases
}
EMPTY_STATUS_LABEL = "（空值）"
MAX_STATUS_EXAMPLES = 5


@dataclass(frozen=True)
class DatasetHandle:
    connection: sqlite3.Connection
    table_name: str
    schema_summary: SchemaSummary
    data_source_ref: DataSourceRef
    row_count: int
    # 物化阶段发现的数据问题（如订单状态取值无法识别），由两条报告路径并入报告 warnings。
    warnings: tuple[dict[str, str], ...] = ()


class DatasetMaterializationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def materialize_table_to_sqlite(
    table: TableData,
    *,
    context_pack: dict[str, Any] | None = None,
) -> DatasetHandle:
    """物化为只读分析表 sales_orders；传入运行快照时按快照识别字段（§6.4 单次运行同源）。"""
    dataframe, warnings = canonicalize_for_query(table, context_pack=context_pack)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    dataframe.to_sql(CANONICAL_TABLE_NAME, connection, if_exists="replace", index=False)

    return DatasetHandle(
        connection=connection,
        table_name=CANONICAL_TABLE_NAME,
        schema_summary=build_schema_summary(dataframe),
        data_source_ref=table.data_source_ref,
        row_count=int(len(dataframe.index)),
        warnings=tuple(warnings),
    )


def canonicalize_for_query(
    table: TableData,
    *,
    context_pack: dict[str, Any] | None = None,
) -> tuple[pd.DataFrame, list[dict[str, str]]]:
    """映射为 canonical 列并归一化订单状态；返回（分析表数据, 数据层 warnings）。"""
    profile = build_field_profile(table.schema_summary, context_pack)
    if not profile.is_valid:
        missing = " / ".join(profile.missing_key_fields)
        raise DatasetMaterializationError("CSV_KEY_FIELD_MISSING", f"缺少关键字段：{missing}")

    canonical = pd.DataFrame()
    for mapping in profile.mappings.values():
        if mapping.canonical_field in canonical.columns:
            continue
        canonical[mapping.canonical_field] = table.dataframe[mapping.source_column]

    warnings: list[dict[str, str]] = []
    if "order_status" in canonical.columns:
        canonical["order_status"], unrecognized = normalize_order_status(canonical["order_status"])
        warning = order_status_warning(unrecognized)
        if warning is not None:
            warnings.append(warning)
    else:
        canonical["order_status"] = "completed"
    if "order_id" not in canonical.columns:
        canonical["order_id"] = [f"row-{index}" for index in canonical.index]

    return canonical, warnings


def status_key(value: Any) -> str | None:
    """订单状态的比对键；空值与空白串返回 None。"""
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    text = str(value).strip().lower()
    return re.sub(r"[\s\-]+", "_", text) or None


def normalize_order_status(values: pd.Series) -> tuple[pd.Series, dict[str, int]]:
    """映射到 completed / partial_refund / refunded；返回（归一化后的列, 无法识别取值 → 行数）。"""
    mapped = values.map(status_key).map(ORDER_STATUS_ALIASES)
    unknown = mapped.isna()
    labels = values[unknown].map(
        lambda value: EMPTY_STATUS_LABEL if status_key(value) is None else str(value).strip()
    )
    counts = {str(label): int(count) for label, count in labels.value_counts().items()}
    if bool(unknown.all()):
        return values, counts  # 一个取值都没映射上（如数字编码）：保留原列与原类型
    return mapped.where(~unknown, values).astype(object), counts


def order_status_warning(unrecognized: dict[str, int]) -> dict[str, str] | None:
    if not unrecognized:
        return None
    rows = sum(unrecognized.values())
    ordered = sorted(unrecognized.items(), key=lambda item: (-item[1], item[0]))
    examples = "、".join(f"{label}（{count} 行）" for label, count in ordered[:MAX_STATUS_EXAMPLES])
    more = f"等 {len(ordered)} 种取值" if len(ordered) > MAX_STATUS_EXAMPLES else ""
    return {
        "code": "ORDER_STATUS_UNRECOGNIZED",
        "message": (
            f"订单状态有 {rows} 行取值无法识别：{examples}{more}。"
            "这些行不参与销售额、订单数、客单价与退款率的计算；"
            "如需计入，请把取值改为已完成 / 部分退款 / 已退款"
            "（或 completed / partial_refund / refunded）。"
        ),
    }
