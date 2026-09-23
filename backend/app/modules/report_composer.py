from __future__ import annotations

from typing import Any

from app.modules.context_pack import (
    anomaly_thresholds,
    context_pack_identity,
    load_active_context_pack,
)
from app.modules.history_context import build_previous_comparison
from app.modules.query_engine import QueryResult
from app.modules.tools import build_echarts_spec, numeric, query_records

_DATE_HINTS = ("date", "日期", "month", "week", "day", "月", "周", "时间")
_SHARE_HINTS = ("占比", "比例", "构成", "share", "ratio", "proportion")


def compose_report(
    *,
    status: str,
    title: str,
    analysis_goal: str,
    summary: str,
    kpis: list[dict[str, Any]],
    findings: list[dict[str, Any]],
    warnings: list[dict[str, str]],
    metadata: dict[str, Any],
    analysis_steps: list[dict[str, Any]] | None = None,
    query_results: dict[str, QueryResult] | None = None,
    history_context: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """统一报告 payload 出口：固定报告与 Loop 报告共用。

    职责：规范化 findings/kpis/metadata、去重 warnings、对缺图 finding 自动配图；
    传入 history_context（任务重跑且链上有上期报告）时确定性组装顶层 previous_comparison
    （architecture.md §3.3），首期 / 未归属报告不出现该键。
    契约保持不变：{status,title,analysis_goal,summary,kpis,findings,warnings,metadata,...}。
    """
    pack = context_pack if context_pack is not None else load_active_context_pack()
    report: dict[str, Any] = {
        "status": status,
        "title": title,
        "analysis_goal": analysis_goal,
        "summary": summary,
        "kpis": list(kpis),
        "findings": _auto_chart_findings(findings, query_results or {}),
        "warnings": dedupe_warnings(warnings),
        "metadata": dict(metadata),
        **context_pack_identity(pack),
    }
    if analysis_steps is not None:
        report["analysis_steps"] = analysis_steps
    if history_context is not None:
        report["previous_comparison"] = build_previous_comparison(
            report["kpis"],
            report["metadata"].get("time_range"),
            history_context,
            anomaly_thresholds(pack),
        )
    return report


def dedupe_warnings(warnings: list[dict[str, str]]) -> list[dict[str, str]]:
    seen: set[str] = set()
    result: list[dict[str, str]] = []
    for warning in warnings:
        code = warning.get("code", "")
        if code in seen:
            continue
        seen.add(code)
        result.append(warning)
    return result


def _auto_chart_findings(
    findings: list[dict[str, Any]],
    query_results: dict[str, QueryResult],
) -> list[dict[str, Any]]:
    composed: list[dict[str, Any]] = []
    for finding in findings:
        if "chart" not in finding:
            evidence_ref = (finding.get("evidence") or {}).get("evidence_ref")
            result = query_results.get(evidence_ref) if evidence_ref else None
            chart = _build_finding_chart(finding, result) if result is not None else None
            if chart is not None:
                finding = {**finding, "chart": chart}
        composed.append(finding)
    return composed


def _build_finding_chart(
    finding: dict[str, Any],
    result: QueryResult,
) -> dict[str, Any] | None:
    if not result.columns or not result.rows:
        return None
    numeric_columns = _numeric_columns(result)
    if not numeric_columns:
        return None

    y_axis = numeric_columns[0]
    x_axis = next(
        (column for column in result.columns if column not in numeric_columns),
        result.columns[0],
    )
    records = query_records(result)
    chart_type = _choose_chart_type(x_axis, y_axis, result.row_count)
    title = str(finding.get("text") or "分析图表")[:40]
    return {
        "id": f"auto-{finding.get('id', 'finding')}",
        "type": chart_type,
        "title": title,
        "png_base64": "",
        "echarts_spec": build_echarts_spec(records, chart_type, title, x_axis, y_axis),
    }


def _numeric_columns(result: QueryResult) -> list[str]:
    columns: list[str] = []
    for index, column in enumerate(result.columns):
        values = [row[index] for row in result.rows if index < len(row)]
        non_null = [value for value in values if value is not None]
        if non_null and all(_is_number(value) for value in non_null):
            columns.append(column)
    return columns


def _choose_chart_type(x_axis: str, y_axis: str, row_count: int) -> str:
    lowered_x = x_axis.lower()
    if any(hint in lowered_x for hint in _DATE_HINTS):
        return "line"
    lowered_y = y_axis.lower()
    if 2 <= row_count <= 6 and any(hint in lowered_y for hint in _SHARE_HINTS):
        return "pie"
    return "bar"


def _is_number(value: Any) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, (int, float)):
        return True
    try:
        numeric(value)
        return True
    except (TypeError, ValueError):
        return False
