from __future__ import annotations

from copy import deepcopy
from datetime import date, datetime
from typing import Any

from app.timestamps import isoformat_utc, report_order_key, report_ran_at

"""history_context 运行时构建（architecture.md §3.3）。

来源是任务报告链而不是 Context Pack：从链上运行时刻最新的报告提取上期 id / 状态 / 时间窗 /
摘要 / KPI 基线，注入分析循环 user payload，并在 compose 时确定性组装顶层 previous_comparison。
本模块只依赖鸭子类型的报告对象（id / ran_at / created_at / status / summary / report_json），
不 import ORM，便于纯函数测试与 eval 复用。
"""


def select_previous_report(reports: Any) -> Any | None:
    """报告链取上期：运行时刻最新（§2.4 换算后）；并列时按 created_at、id 取后者。空链返回 None。"""
    candidates = list(reports or [])
    if not candidates:
        return None
    return max(candidates, key=report_order_key)


def history_context_for_task(task: Any) -> dict[str, Any] | None:
    previous = select_previous_report(getattr(task, "reports", None))
    if previous is None:
        return None
    return build_history_context(previous)


def build_history_context(report: Any) -> dict[str, Any]:
    report_json = getattr(report, "report_json", None)
    report_json = report_json if isinstance(report_json, dict) else {}
    metadata = report_json.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    time_range = metadata.get("time_range")
    summary = getattr(report, "summary", None) or report_json.get("summary") or ""
    return {
        "previous_report_id": str(getattr(report, "id", "") or ""),
        "previous_ran_at": isoformat_utc(report_ran_at(report), timespec="seconds"),
        "previous_status": normalize_previous_status(getattr(report, "status", None)),
        "previous_time_range": deepcopy(time_range) if isinstance(time_range, dict) else None,
        "last_run_summary": str(summary),
        "baseline_values": baseline_values(report_json.get("kpis")),
    }


def build_previous_comparison(
    kpis: Any,
    current_time_range: Any,
    history_context: Any,
    thresholds: Any,
) -> dict[str, Any]:
    """按本期 kpis 顺序与上期 baseline_values 对齐，代码计算差值与 severity（不依赖模型）。"""
    context = history_context if isinstance(history_context, dict) else {}
    baseline = context.get("baseline_values")
    baseline = baseline if isinstance(baseline, dict) else {}

    entries: list[dict[str, Any]] = []
    for item in kpis or []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        name = item["name"]
        unit = str(item.get("unit") or "")
        current = numeric_or_none(item.get("current"))
        previous = numeric_or_none(baseline.get(name))
        delta_unit = "pp" if unit == "%" else "%"
        delta_value = kpi_delta(current, previous, delta_unit)
        entries.append(
            {
                "name": name,
                "unit": unit,
                "previous_value": previous,
                "current_value": current,
                "delta_value": delta_value,
                "delta_unit": delta_unit,
                "severity": delta_severity(delta_value, delta_unit, thresholds),
            }
        )

    previous_time_range = context.get("previous_time_range")
    previous_time_range = (
        deepcopy(previous_time_range) if isinstance(previous_time_range, dict) else None
    )
    return {
        "previous_report_id": str(context.get("previous_report_id") or ""),
        "previous_ran_at": context.get("previous_ran_at"),
        "previous_status": normalize_previous_status(context.get("previous_status")),
        "previous_time_range": previous_time_range,
        "same_period": is_same_period(previous_time_range, current_time_range),
        "baseline": entries,
        "summary_note": str(context.get("last_run_summary") or ""),
    }


def is_same_period(previous_time_range: Any, current_time_range: Any) -> bool:
    """上期与本期的本期窗口相同或重叠（含端点相接）→ True；任一缺失或无法解析 → False。"""
    previous = _window(previous_time_range)
    current = _window(current_time_range)
    if previous is None or current is None:
        return False
    return previous[0] <= current[1] and current[0] <= previous[1]


def kpi_delta(current: float | None, previous: float | None, delta_unit: str) -> float | None:
    if current is None or previous is None:
        return None
    if delta_unit == "pp":
        return round(current - previous, 2)
    if previous == 0:
        return None
    return round((current - previous) / previous * 100, 2)


def delta_severity(delta_value: float | None, delta_unit: str, thresholds: Any) -> str | None:
    if delta_unit != "%" or delta_value is None:
        return None
    magnitude = abs(delta_value)
    critical = _threshold(thresholds, "critical_pct")
    significant = _threshold(thresholds, "significant_pct")
    if critical is not None and magnitude >= critical:
        return "critical"
    if significant is not None and magnitude >= significant:
        return "significant"
    return "normal"


def normalize_previous_status(status: Any) -> str:
    return "completed" if status == "completed" else "partial"


def baseline_values(kpis: Any) -> dict[str, float]:
    values: dict[str, float] = {}
    for item in kpis if isinstance(kpis, list) else []:
        if not isinstance(item, dict) or not isinstance(item.get("name"), str):
            continue
        current = numeric_or_none(item.get("current"))
        if current is not None:
            values[item["name"]] = current
    return values


def numeric_or_none(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return value


def _threshold(thresholds: Any, key: str) -> float | None:
    if not isinstance(thresholds, dict):
        return None
    return numeric_or_none(thresholds.get(key))


def _window(time_range: Any) -> tuple[date, date] | None:
    if not isinstance(time_range, dict):
        return None
    start = _parse_date(time_range.get("current_start"))
    end = _parse_date(time_range.get("current_end"))
    if start is None or end is None or start > end:
        return None
    return start, end


def _parse_date(value: Any) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value.strip()[:10])
    except ValueError:
        return None
