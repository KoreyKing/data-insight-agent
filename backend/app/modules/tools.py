from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

import pandas as pd

from app.modules.dataset_store import DatasetHandle
from app.modules.query_engine import QueryResult, run_validated_query
from app.timestamps import utc_now_iso

QUERY_REF_PATTERN = re.compile(r"query-\d+")


@dataclass
class ToolRuntime:
    handle: DatasetHandle
    queries: dict[str, QueryResult] = field(default_factory=dict)
    charts: dict[str, dict[str, Any]] = field(default_factory=dict)
    findings: list[dict[str, Any]] = field(default_factory=list)


def query_data(runtime: ToolRuntime, args: dict[str, Any], iteration: int) -> dict[str, Any]:
    sql = required_string(args, "sql")
    result = run_validated_query(runtime.handle, sql)
    query_id = f"query-{len(runtime.queries) + 1}"
    runtime.queries[query_id] = result
    summary = args.get("summary") or f"查询返回 {result.row_count} 行。"
    return {
        "status": "completed",
        "summary": str(summary),
        "data_ref": query_id,
        "sql": result.sql,
        "row_count": result.row_count,
        "columns": result.columns,
        "rows_preview": result.rows[:5],
        "iteration": iteration,
    }


def profile_column(runtime: ToolRuntime, args: dict[str, Any], iteration: int) -> dict[str, Any]:
    column = required_string(args, "column")
    known = next(
        (item for item in runtime.handle.schema_summary.columns if item.name == column),
        None,
    )
    if known is None:
        raise ValueError(f"未知字段：{column}")

    result = run_validated_query(
        runtime.handle,
        f"""SELECT {column} AS value, COUNT(*) AS count
FROM sales_orders
WHERE {column} IS NOT NULL
GROUP BY {column}
ORDER BY count DESC
LIMIT 10;""",
    )
    values = [row[0] for row in result.rows if row]
    numeric_values = pd.to_numeric(pd.Series(values), errors="coerce").dropna()
    return {
        "status": "completed",
        "summary": f"{column} 已完成字段画像。",
        "profile": {
            "type": known.data_type,
            "distinct_count": known.distinct_count,
            "null_pct": None,
            "min": None if numeric_values.empty else float(numeric_values.min()),
            "max": None if numeric_values.empty else float(numeric_values.max()),
            "top_values": [
                {"value": row[0], "count": row[1]} for row in result.rows
            ],
        },
        "iteration": iteration,
    }


def create_chart(runtime: ToolRuntime, args: dict[str, Any], iteration: int) -> dict[str, Any]:
    data_ref = required_string(args, "data_ref")
    result = runtime.queries.get(data_ref)
    if result is None:
        raise ValueError(f"未知 query result：{data_ref}")

    chart_id = f"chart-{len(runtime.charts) + 1}"
    chart_type = str(args.get("chart_type") or "bar")
    title = str(args.get("title") or "分析图表")
    x_axis = str(args.get("x_axis") or (result.columns[0] if result.columns else "x"))
    y_axis = str(args.get("y_axis") or (result.columns[1] if len(result.columns) > 1 else x_axis))
    records = query_records(result)
    chart = {
        "id": chart_id,
        "type": chart_type,
        "title": title,
        "png_base64": "",
        "echarts_spec": build_echarts_spec(records, chart_type, title, x_axis, y_axis),
    }
    runtime.charts[chart_id] = chart
    return {
        "status": "completed",
        "summary": f"已生成图表：{title}",
        "chart_id": chart_id,
        "iteration": iteration,
    }


def record_finding(runtime: ToolRuntime, args: dict[str, Any], iteration: int) -> dict[str, Any]:
    finding_id = f"finding-{len(runtime.findings) + 1}"
    evidence_ref = str(args.get("evidence") or "")
    chart_id = args.get("chart_id")
    finding = {
        "id": finding_id,
        "type": str(args.get("type") or "trend"),
        "confidence": str(args.get("confidence") or "medium"),
        "text": required_string(args, "text"),
        "evidence": evidence_for(runtime, evidence_ref, iteration),
    }
    if isinstance(chart_id, str) and chart_id in runtime.charts:
        finding["chart"] = runtime.charts[chart_id]
    runtime.findings.append(finding)
    return {
        "status": "completed",
        "summary": f"已记录 finding：{finding['text']}",
        "finding_id": finding_id,
        "iteration": iteration,
    }


def finish(_runtime: ToolRuntime, args: dict[str, Any], iteration: int) -> dict[str, Any]:
    return {
        "status": "completed",
        "summary": str(args.get("summary") or "分析已完成。"),
        "finished": True,
        "iteration": iteration,
    }


def run_tool(
    runtime: ToolRuntime,
    tool: str,
    args: dict[str, Any],
    iteration: int,
) -> dict[str, Any]:
    registry = {
        "query_data": query_data,
        "profile_column": profile_column,
        "create_chart": create_chart,
        "record_finding": record_finding,
        "finish": finish,
    }
    handler = registry.get(tool)
    if handler is None:
        raise ValueError(f"未知工具：{tool}")
    return handler(runtime, args, iteration)


def resolve_evidence_ref(
    runtime: ToolRuntime,
    evidence_ref: str,
) -> tuple[str, QueryResult | None]:
    """解析 evidence 引用（architecture.md §3.2 v0.12）。

    模型常写装饰性引用串（`"query-1(整体), query-2(门店)"`、`"query-5（渠道维度…）"`）。
    先整串精确匹配，再按正则取首个可解析的 `query-N`；命中时把引用归一化为该 canonical
    引用，让 SQL 追溯与 Report Composer 的自动配图都能生效。均未命中则按 short note 处理。
    """
    result = runtime.queries.get(evidence_ref)
    if result is not None:
        return evidence_ref, result
    for candidate in QUERY_REF_PATTERN.findall(evidence_ref):
        result = runtime.queries.get(candidate)
        if result is not None:
            return candidate, result
    return evidence_ref, None


def evidence_for(runtime: ToolRuntime, evidence_ref: str, iteration: int) -> dict[str, Any]:
    resolved_ref, result = resolve_evidence_ref(runtime, evidence_ref)
    if result is None:
        return {
            "sql": "",
            "data_source": "sales_orders",
            "ran_at": utc_now_iso(),
            "iteration": iteration,
            "evidence_ref": resolved_ref,
        }
    return {
        "sql": result.sql,
        "data_source": "sales_orders",
        "ran_at": utc_now_iso(),
        "exec_ms": result.exec_ms,
        "row_count": result.row_count,
        "validated_by": "sql_validator",
        "iteration": iteration,
        "evidence_ref": resolved_ref,
    }


def query_records(result: QueryResult) -> list[dict[str, Any]]:
    return [dict(zip(result.columns, row, strict=True)) for row in result.rows]


def build_echarts_spec(
    records: list[dict[str, Any]],
    chart_type: str,
    title: str,
    x_axis: str,
    y_axis: str,
) -> dict[str, Any]:
    if chart_type == "pie":
        return {
            "title": {"text": title},
            "series": [
                {
                    "type": "pie",
                    "data": [
                        {"name": str(record.get(x_axis)), "value": numeric(record.get(y_axis))}
                        for record in records
                    ],
                }
            ],
        }
    if chart_type == "table":
        return {"title": {"text": title}, "dataset": {"source": records}, "series": []}

    series_type = "line" if chart_type == "line" else "bar"
    return {
        "title": {"text": title},
        "xAxis": {"type": "category", "data": [str(record.get(x_axis)) for record in records]},
        "yAxis": {"type": "value"},
        "series": [
            {"type": series_type, "data": [numeric(record.get(y_axis)) for record in records]}
        ],
    }


def required_string(args: dict[str, Any], key: str) -> str:
    value = args.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"缺少工具参数：{key}")
    return value


def numeric(value: Any) -> float:
    if value is None:
        return 0.0
    return float(value)
