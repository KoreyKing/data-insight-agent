from __future__ import annotations

from dataclasses import asdict
from typing import Any

import pandas as pd

from app.modules.context_pack import context_pack_identity, load_active_context_pack
from app.modules.dataset_store import (
    DatasetHandle,
    DatasetMaterializationError,
    materialize_table_to_sqlite,
)
from app.modules.query_engine import QueryResult, run_validated_query
from app.modules.report_composer import compose_report
from app.modules.schemas import TableData
from app.modules.sql_validator import SQLValidationError
from app.timestamps import utc_now_iso

DEFAULT_METRICS = ["销售额", "订单数", "客单价", "退款率"]
DEFAULT_DIMENSIONS = ["日期", "门店", "商品类目", "渠道"]
# 参与核心指标的订单状态（§6.4）：退款率的分母只数这三种，无法识别的取值不参与任何核心指标
COUNTED_STATUSES = "order_status IN ('completed', 'partial_refund', 'refunded')"


def default_structured_task(
    analysis_goal: str,
    data_source_ref: dict[str, Any],
    *,
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        **context_pack_identity(context_pack),
        "task_title": "周度零售经营复盘",
        "data_source_ref": data_source_ref,
        "analysis_goal": analysis_goal,
        "metrics": DEFAULT_METRICS,
        "dimensions": DEFAULT_DIMENSIONS,
        "time_range": {"mode": "latest_complete_week"},
        "comparison": "环比",
        "report_template": "周度经营回顾",
        "execution_limits": {
            "max_iterations": 12,
            "max_tokens": 50000,
            "max_duration_seconds": 300,
        },
    }


def generate_traceable_report(
    table: TableData,
    analysis_goal: str,
    *,
    history_context: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    # 一次运行只解析一次活动包：物化列集与报告口径版本同源（§6.4 单次运行同源）。
    pack = context_pack if context_pack is not None else load_active_context_pack()
    try:
        handle = materialize_table_to_sqlite(table, context_pack=pack)
    except DatasetMaterializationError as exc:
        return {
            "status": "failed",
            "title": "周度零售经营复盘",
            "warnings": [{"code": exc.code, "message": exc.message}],
            "findings": [],
        }

    max_date = latest_order_date(handle)
    if max_date is None:
        return {
            "status": "failed",
            "title": "周度零售经营复盘",
            "warnings": [{"code": "CSV_KEY_FIELD_MISSING", "message": "未能识别有效日期数据"}],
            "findings": [],
        }

    current_start, current_end, previous_start, previous_end = week_windows(max_date)

    kpis = build_kpis(
        handle,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )
    findings = build_findings(
        handle,
        current_start,
        current_end,
        previous_start,
        previous_end,
    )

    return compose_report(
        status="completed",
        title="周度零售经营复盘",
        analysis_goal=analysis_goal,
        summary=build_summary(kpis, findings),
        kpis=kpis,
        findings=findings,
        warnings=[
            {"code": "FALLBACK_REPORT", "message": "当前为无 LLM 的固定报告闭环。"},
            *handle.warnings,
        ],
        history_context=history_context,
        context_pack=pack,
        metadata={
            "data_source": asdict(table.data_source_ref),
            "row_count": table.row_count,
            "query_engine": "sqlite",
            "ran_at": utc_now_iso(),
            "model": "not_configured",
            "loop_rounds": 0,
            "steps_recorded": 0,
            "iterations_used": 0,
            "token_used": 0,
            "time_range": {
                "current_start": current_start.date().isoformat(),
                "current_end": current_end.date().isoformat(),
                "previous_start": previous_start.date().isoformat(),
                "previous_end": previous_end.date().isoformat(),
            },
        },
    )


def latest_order_date(handle: DatasetHandle) -> pd.Timestamp | None:
    result = run_validated_query(
        handle,
        "SELECT MAX(order_date) AS max_order_date FROM sales_orders LIMIT 1;",
    )
    if not result.rows or result.rows[0][0] is None:
        return None
    parsed = pd.to_datetime(result.rows[0][0], errors="coerce")
    if pd.isna(parsed):
        return None
    return parsed.normalize()


def week_windows(
    max_order_date: pd.Timestamp,
) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    current_end = max_order_date.normalize()
    current_start = current_end - pd.Timedelta(days=6)
    previous_end = current_start - pd.Timedelta(days=1)
    previous_start = previous_end - pd.Timedelta(days=6)
    return current_start, current_end, previous_start, previous_end


def build_kpis(
    handle: DatasetHandle,
    current_start: pd.Timestamp,
    current_end: pd.Timestamp,
    previous_start: pd.Timestamp,
    previous_end: pd.Timestamp,
) -> list[dict[str, Any]]:
    return [
        kpi(
            "销售额",
            sales_amount(handle, current_start, current_end),
            sales_amount(handle, previous_start, previous_end),
            "元",
        ),
        kpi(
            "订单数",
            order_count(handle, current_start, current_end),
            order_count(handle, previous_start, previous_end),
            "单",
        ),
        kpi(
            "客单价",
            average_order_value(handle, current_start, current_end),
            average_order_value(handle, previous_start, previous_end),
            "元",
        ),
        kpi(
            "退款率",
            refund_rate(handle, current_start, current_end),
            refund_rate(handle, previous_start, previous_end),
            "%",
            percentage_points=True,
        ),
    ]


def build_default_kpis(handle: DatasetHandle) -> list[dict[str, Any]]:
    """根据数据集自带的最近一周窗口生成 4 个标准 KPI；数据缺失或查询失败时返回空列表。"""
    try:
        max_date = latest_order_date(handle)
        if max_date is None:
            return []
        current_start, current_end, previous_start, previous_end = week_windows(max_date)
        return build_kpis(handle, current_start, current_end, previous_start, previous_end)
    except SQLValidationError:
        return []


def default_time_range(handle: DatasetHandle) -> dict[str, str] | None:
    """根据数据集最近一周窗口返回 time_range，供报告 byline 使用；无有效日期时返回 None。"""
    try:
        max_date = latest_order_date(handle)
    except SQLValidationError:
        return None
    if max_date is None:
        return None
    current_start, current_end, previous_start, previous_end = week_windows(max_date)
    return {
        "current_start": current_start.date().isoformat(),
        "current_end": current_end.date().isoformat(),
        "previous_start": previous_start.date().isoformat(),
        "previous_end": previous_end.date().isoformat(),
    }


def build_findings(
    handle: DatasetHandle,
    current_start: pd.Timestamp,
    current_end: pd.Timestamp,
    previous_start: pd.Timestamp,
    previous_end: pd.Timestamp,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    if has_column(handle, "store_name"):
        findings.append(
            store_finding(
                handle,
                current_start,
                current_end,
                previous_start,
                previous_end,
            )
        )
    if has_column(handle, "category_l1"):
        findings.append(category_refund_finding(handle, current_start, current_end))
    if has_column(handle, "channel"):
        findings.append(
            channel_aov_finding(
                handle,
                current_start,
                current_end,
                previous_start,
                previous_end,
            )
        )
    return [finding for finding in findings if finding]


def kpi(
    name: str,
    current: float,
    previous: float,
    unit: str,
    *,
    percentage_points: bool = False,
) -> dict[str, Any]:
    delta = current - previous
    delta_pct = None if previous == 0 else delta / previous * 100
    return {
        "name": name,
        "current": round(current, 2),
        "previous": round(previous, 2),
        "delta": round(delta, 2),
        "delta_pct": None if delta_pct is None else round(delta_pct, 1),
        "unit": unit,
        "delta_unit": "pp" if percentage_points else "%",
    }


def sales_amount(handle: DatasetHandle, start: pd.Timestamp, end: pd.Timestamp) -> float:
    result = run_validated_query(
        handle,
        f"""SELECT COALESCE(SUM(net_sales_amount), 0) AS value
FROM sales_orders
WHERE order_status IN ('completed', 'partial_refund')
  AND order_date BETWEEN '{iso_date(start)}' AND '{iso_date(end)}';""",
    )
    return numeric(result.rows[0][0]) if result.rows else 0.0


def order_count(handle: DatasetHandle, start: pd.Timestamp, end: pd.Timestamp) -> float:
    result = run_validated_query(
        handle,
        f"""SELECT COUNT(DISTINCT order_id) AS value
FROM sales_orders
WHERE order_status IN ('completed', 'partial_refund')
  AND order_date BETWEEN '{iso_date(start)}' AND '{iso_date(end)}';""",
    )
    return numeric(result.rows[0][0]) if result.rows else 0.0


def average_order_value(handle: DatasetHandle, start: pd.Timestamp, end: pd.Timestamp) -> float:
    orders = order_count(handle, start, end)
    return 0.0 if orders == 0 else sales_amount(handle, start, end) / orders


def refund_rate(handle: DatasetHandle, start: pd.Timestamp, end: pd.Timestamp) -> float:
    result = run_validated_query(
        handle,
        f"""SELECT SUM(CASE WHEN {COUNTED_STATUSES} THEN 1 ELSE 0 END) AS total_orders,
  SUM(CASE WHEN order_status IN ('refunded', 'partial_refund') THEN 1 ELSE 0 END) AS refund_orders
FROM sales_orders
WHERE order_date BETWEEN '{iso_date(start)}' AND '{iso_date(end)}';""",
    )
    if not result.rows:
        return 0.0
    total_orders, refund_orders = result.rows[0]
    total = numeric(total_orders)
    return 0.0 if total == 0 else numeric(refund_orders) / total * 100


def store_finding(
    handle: DatasetHandle,
    current_start: pd.Timestamp,
    current_end: pd.Timestamp,
    previous_start: pd.Timestamp,
    previous_end: pd.Timestamp,
) -> dict[str, Any]:
    result = run_validated_query(
        handle,
        store_sql(current_start, current_end, previous_start, previous_end),
    )
    rows = query_rows(result)
    if not rows:
        return {}
    worst = rows[0]
    worst_store = str(worst["store_name"])
    impact = numeric(worst["sales_impact"])
    previous_value = numeric(worst["sales_previous"])
    current_value = numeric(worst["sales_current"])
    pct = 0.0 if previous_value == 0 else (current_value - previous_value) / previous_value * 100
    return {
        "id": "finding-store-drop",
        "type": "anomaly",
        "confidence": "high",
        "text": (
            f"{worst_store} 销售额环比 {pct:.1f}%，影响 {impact:,.0f} 元，"
            "是本次门店层面的优先复核对象。"
        ),
        "evidence": evidence_from_result(result),
        "chart": {
            "id": "store-sales-impact",
            "type": "bar",
            "title": "门店销售额环比影响",
            "echarts_spec": {
                "xAxis": {"type": "category", "data": [str(row["store_name"]) for row in rows]},
                "yAxis": {"type": "value"},
                "series": [
                    {
                        "type": "bar",
                        "data": [round(numeric(row["sales_impact"]), 2) for row in rows],
                    }
                ],
            },
        },
    }


def category_refund_finding(
    handle: DatasetHandle,
    current_start: pd.Timestamp,
    current_end: pd.Timestamp,
) -> dict[str, Any]:
    result = run_validated_query(handle, category_refund_sql(current_start, current_end))
    rows = query_rows(result)
    if not rows:
        return {}
    for row in rows:
        orders = numeric(row["orders"])
        row["refund_rate"] = 0.0 if orders == 0 else numeric(row["refund_orders"]) / orders * 100
    worst = max(rows, key=lambda row: numeric(row["refund_rate"]))
    category = str(worst["category_l1"])
    rate = numeric(worst["refund_rate"])
    return {
        "id": "finding-category-refund",
        "type": "anomaly",
        "confidence": "high" if rate >= 10 else "medium",
        "text": f"{category} 当前退款率为 {rate:.1f}%，需要优先核查具体 SKU 与退款原因。",
        "evidence": evidence_from_result(result),
        "chart": {
            "id": "category-refund-rate",
            "type": "bar",
            "title": "类目退款率",
            "echarts_spec": {
                "xAxis": {"type": "category", "data": [str(row["category_l1"]) for row in rows]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "bar", "data": [round(numeric(row["refund_rate"]), 2) for row in rows]}
                ],
            },
        },
    }


def channel_aov_finding(
    handle: DatasetHandle,
    current_start: pd.Timestamp,
    current_end: pd.Timestamp,
    previous_start: pd.Timestamp,
    previous_end: pd.Timestamp,
) -> dict[str, Any]:
    result = run_validated_query(
        handle,
        channel_aov_sql(current_start, current_end, previous_start, previous_end),
    )
    rows = query_rows(result)
    if not rows:
        return {}
    for row in rows:
        previous_value = numeric(row["aov_previous"])
        current_value = numeric(row["aov_current"])
        row["delta_pct"] = 0.0 if previous_value == 0 else (
            current_value - previous_value
        ) / previous_value * 100
    worst = min(rows, key=lambda row: numeric(row["delta_pct"]))
    channel = str(worst["channel"])
    pct = numeric(worst["delta_pct"])
    return {
        "id": "finding-channel-aov",
        "type": "trend",
        "confidence": "medium",
        "text": f"{channel} 渠道客单价环比 {pct:.1f}%，需结合订单数判断是否为活动拉量。",
        "evidence": evidence_from_result(result),
        "chart": {
            "id": "channel-aov",
            "type": "bar",
            "title": "渠道客单价环比",
            "echarts_spec": {
                "xAxis": {"type": "category", "data": [str(row["channel"]) for row in rows]},
                "yAxis": {"type": "value"},
                "series": [
                    {"type": "bar", "data": [round(numeric(row["delta_pct"]), 2) for row in rows]}
                ],
            },
        },
    }


def build_summary(kpis: list[dict[str, Any]], findings: list[dict[str, Any]]) -> str:
    sales = next(kpi_item for kpi_item in kpis if kpi_item["name"] == "销售额")
    lead = findings[0]["text"] if findings else "当前数据未识别到明确异常。"
    return f"本期销售额 {sales['current']:,.0f} 元，环比 {sales['delta_pct']}%。{lead}"


def query_rows(result: QueryResult) -> list[dict[str, Any]]:
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


def evidence_from_result(result: QueryResult) -> dict[str, Any]:
    return {
        "sql": result.sql,
        "data_source": "sales_orders",
        "ran_at": utc_now_iso(),
        "exec_ms": result.exec_ms,
        "row_count": result.row_count,
        "validated_by": "sql_validator",
    }


def has_column(handle: DatasetHandle, column_name: str) -> bool:
    return any(column.name == column_name for column in handle.schema_summary.columns)


def numeric(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)


def iso_date(value: pd.Timestamp) -> str:
    return value.date().isoformat()


def store_sql(
    current_start: pd.Timestamp,
    current_end: pd.Timestamp,
    previous_start: pd.Timestamp,
    previous_end: pd.Timestamp,
) -> str:
    return f"""SELECT store_name,
  SUM(CASE
    WHEN order_date BETWEEN '{current_start.date()}' AND '{current_end.date()}'
    THEN net_sales_amount
    ELSE 0
  END) AS sales_current,
  SUM(CASE
    WHEN order_date BETWEEN '{previous_start.date()}' AND '{previous_end.date()}'
    THEN net_sales_amount
    ELSE 0
  END) AS sales_previous,
  SUM(CASE
    WHEN order_date BETWEEN '{current_start.date()}' AND '{current_end.date()}'
    THEN net_sales_amount
    ELSE 0
  END)
  - SUM(CASE
    WHEN order_date BETWEEN '{previous_start.date()}' AND '{previous_end.date()}'
    THEN net_sales_amount
    ELSE 0
  END) AS sales_impact
FROM sales_orders
WHERE order_status IN ('completed', 'partial_refund')
GROUP BY store_name
ORDER BY sales_impact ASC
LIMIT 100;"""


def category_refund_sql(current_start: pd.Timestamp, current_end: pd.Timestamp) -> str:
    return f"""SELECT category_l1,
  SUM(CASE WHEN {COUNTED_STATUSES} THEN 1 ELSE 0 END) AS orders,
  SUM(CASE WHEN order_status IN ('refunded', 'partial_refund') THEN 1 ELSE 0 END) AS refund_orders
FROM sales_orders
WHERE order_date BETWEEN '{current_start.date()}' AND '{current_end.date()}'
GROUP BY category_l1
ORDER BY refund_orders * 1.0 / SUM(CASE WHEN {COUNTED_STATUSES} THEN 1 ELSE 0 END) DESC
LIMIT 100;"""


def channel_aov_sql(
    current_start: pd.Timestamp,
    current_end: pd.Timestamp,
    previous_start: pd.Timestamp,
    previous_end: pd.Timestamp,
) -> str:
    return f"""SELECT channel,
  SUM(CASE
    WHEN order_date BETWEEN '{current_start.date()}' AND '{current_end.date()}'
    THEN net_sales_amount
    ELSE 0
  END)
  / NULLIF(COUNT(DISTINCT CASE
    WHEN order_date BETWEEN '{current_start.date()}' AND '{current_end.date()}'
    THEN order_id
  END), 0) AS aov_current,
  SUM(CASE
    WHEN order_date BETWEEN '{previous_start.date()}' AND '{previous_end.date()}'
    THEN net_sales_amount
    ELSE 0
  END)
  / NULLIF(COUNT(DISTINCT CASE
    WHEN order_date BETWEEN '{previous_start.date()}' AND '{previous_end.date()}'
    THEN order_id
  END), 0) AS aov_previous
FROM sales_orders
WHERE order_status IN ('completed', 'partial_refund')
GROUP BY channel
LIMIT 100;"""
