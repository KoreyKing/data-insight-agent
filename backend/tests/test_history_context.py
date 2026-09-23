from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

from app.modules.history_context import (
    build_history_context,
    build_previous_comparison,
    history_context_for_task,
    is_same_period,
    select_previous_report,
)

THRESHOLDS = {"significant_pct": 10.0, "critical_pct": 30.0}
PERIOD1_RANGE = {
    "current_start": "2026-05-11",
    "current_end": "2026-05-17",
    "previous_start": "2026-05-04",
    "previous_end": "2026-05-10",
}
PERIOD2_RANGE = {
    "current_start": "2026-05-18",
    "current_end": "2026-05-24",
    "previous_start": "2026-05-11",
    "previous_end": "2026-05-17",
}


def report_like(
    report_id: str,
    ran_at: datetime,
    *,
    created_at: datetime | None = None,
    status: str = "completed",
    summary: str = "上期摘要",
    kpis: list[dict] | None = None,
    time_range: dict | None = PERIOD1_RANGE,
) -> SimpleNamespace:
    metadata = {"ran_at": ran_at.isoformat()}
    if time_range is not None:
        metadata["time_range"] = dict(time_range)
    return SimpleNamespace(
        id=report_id,
        ran_at=ran_at,
        created_at=created_at or ran_at,
        status=status,
        summary=summary,
        report_json={
            "status": status,
            "summary": summary,
            "kpis": kpis if kpis is not None else [],
            "metadata": metadata,
        },
    )


def kpi(name: str, current, unit: str) -> dict:
    return {"name": name, "current": current, "previous": 0, "unit": unit}


def test_select_previous_report_picks_latest_ran_at_then_created_at_then_id():
    base = datetime(2026, 9, 1, 10, 0, tzinfo=UTC)
    older = report_like("r-old", base)
    tie_a = report_like("r-a", base + timedelta(hours=1), created_at=base)
    tie_b = report_like("r-b", base + timedelta(hours=1), created_at=base + timedelta(minutes=5))

    assert select_previous_report([older, tie_b, tie_a]) is tie_b
    same_created = report_like("r-z", base + timedelta(hours=1), created_at=tie_b.created_at)
    assert select_previous_report([tie_b, same_created]) is same_created


def test_select_previous_report_returns_none_for_empty_chain():
    assert select_previous_report([]) is None


def test_select_previous_report_tolerates_naive_and_aware_datetimes():
    aware = report_like("r-aware", datetime(2026, 9, 1, 10, 0, tzinfo=UTC))
    naive_later = report_like("r-naive", datetime(2026, 9, 1, 11, 0))

    assert select_previous_report([aware, naive_later]) is naive_later


def test_build_history_context_extracts_numeric_baseline_status_and_time_range():
    ran_at = datetime(2026, 9, 1, 10, 30, tzinfo=UTC)
    previous = report_like(
        "r-1",
        ran_at,
        status="partial",
        summary="本期销售额 390,037 元。",
        kpis=[
            kpi("销售额", 390037.19, "元"),
            kpi("订单数", 1288, "单"),
            kpi("退款率", 7.01, "%"),
            kpi("客单价", "N/A", "元"),
            kpi("标记", True, ""),
        ],
    )

    context = build_history_context(previous)

    assert context == {
        "previous_report_id": "r-1",
        "previous_ran_at": ran_at.isoformat(),
        "previous_status": "partial",
        "previous_time_range": PERIOD1_RANGE,
        "last_run_summary": "本期销售额 390,037 元。",
        "baseline_values": {"销售额": 390037.19, "订单数": 1288, "退款率": 7.01},
    }


def test_build_history_context_without_kpis_or_time_range_is_empty_but_valid():
    previous = report_like("r-2", datetime(2026, 9, 1, tzinfo=UTC), kpis=[], time_range=None)

    context = build_history_context(previous)

    assert context["previous_status"] == "completed"
    assert context["previous_time_range"] is None
    assert context["baseline_values"] == {}


def test_history_context_for_task_returns_none_without_reports_and_latest_otherwise():
    base = datetime(2026, 9, 1, tzinfo=UTC)
    task = SimpleNamespace(reports=[])
    assert history_context_for_task(task) is None

    task.reports = [report_like("r-first", base), report_like("r-second", base + timedelta(days=7))]
    assert history_context_for_task(task)["previous_report_id"] == "r-second"


def test_is_same_period_true_for_identical_or_overlapping_current_windows():
    assert is_same_period(PERIOD1_RANGE, PERIOD1_RANGE) is True
    overlapping = {"current_start": "2026-05-15", "current_end": "2026-05-21"}
    assert is_same_period(PERIOD1_RANGE, overlapping) is True
    touching = {"current_start": "2026-05-17", "current_end": "2026-05-23"}
    assert is_same_period(PERIOD1_RANGE, touching) is True


def test_is_same_period_false_for_adjacent_missing_or_invalid_windows():
    assert is_same_period(PERIOD1_RANGE, PERIOD2_RANGE) is False
    assert is_same_period(None, PERIOD2_RANGE) is False
    assert is_same_period(PERIOD1_RANGE, None) is False
    assert is_same_period({"current_start": "2026-05-11"}, PERIOD1_RANGE) is False
    invalid = {"current_start": "bad", "current_end": "2026-05-17"}
    assert is_same_period(invalid, PERIOD1_RANGE) is False


def period2_history_context() -> dict:
    return {
        "previous_report_id": "r-period1",
        "previous_ran_at": "2026-09-01T10:00:00+00:00",
        "previous_status": "completed",
        "previous_time_range": PERIOD1_RANGE,
        "last_run_summary": "上期摘要原文",
        "baseline_values": {
            "销售额": 390037.19,
            "订单数": 1288,
            "客单价": 302.82,
            "退款率": 7.01,
        },
    }


def test_build_previous_comparison_computes_percent_and_pp_deltas_with_severity():
    kpis = [
        kpi("销售额", 327985.38, "元"),
        kpi("订单数", 1290, "单"),
        kpi("客单价", 254.25, "元"),
        kpi("退款率", 7.09, "%"),
    ]

    comparison = build_previous_comparison(
        kpis, PERIOD2_RANGE, period2_history_context(), THRESHOLDS
    )

    assert comparison["previous_report_id"] == "r-period1"
    assert comparison["previous_ran_at"] == "2026-09-01T10:00:00+00:00"
    assert comparison["previous_status"] == "completed"
    assert comparison["previous_time_range"] == PERIOD1_RANGE
    assert comparison["same_period"] is False
    assert comparison["summary_note"] == "上期摘要原文"
    assert comparison["baseline"] == [
        {
            "name": "销售额",
            "unit": "元",
            "previous_value": 390037.19,
            "current_value": 327985.38,
            "delta_value": -15.91,
            "delta_unit": "%",
            "severity": "significant",
        },
        {
            "name": "订单数",
            "unit": "单",
            "previous_value": 1288,
            "current_value": 1290,
            "delta_value": 0.16,
            "delta_unit": "%",
            "severity": "normal",
        },
        {
            "name": "客单价",
            "unit": "元",
            "previous_value": 302.82,
            "current_value": 254.25,
            "delta_value": -16.04,
            "delta_unit": "%",
            "severity": "significant",
        },
        {
            "name": "退款率",
            "unit": "%",
            "previous_value": 7.01,
            "current_value": 7.09,
            "delta_value": 0.08,
            "delta_unit": "pp",
            "severity": None,
        },
    ]


def test_build_previous_comparison_marks_missing_or_zero_previous_as_not_comparable():
    context = period2_history_context()
    context["baseline_values"] = {"订单数": 0}
    kpis = [kpi("销售额", 100.0, "元"), kpi("订单数", 5, "单"), kpi("退款率", 3.5, "%")]

    baseline = build_previous_comparison(kpis, PERIOD2_RANGE, context, THRESHOLDS)["baseline"]

    assert baseline[0]["previous_value"] is None
    assert baseline[0]["delta_value"] is None
    assert baseline[0]["severity"] is None
    assert baseline[1] == {
        "name": "订单数",
        "unit": "单",
        "previous_value": 0,
        "current_value": 5,
        "delta_value": None,
        "delta_unit": "%",
        "severity": None,
    }
    assert baseline[2]["delta_value"] is None
    assert baseline[2]["delta_unit"] == "pp"


def test_build_previous_comparison_severity_uses_inclusive_threshold_boundaries():
    context = period2_history_context()
    context["baseline_values"] = {"a": 100, "b": 100, "c": 100, "d": 100}
    kpis = [
        kpi("a", 109.99, "元"),
        kpi("b", 110, "元"),
        kpi("c", 130, "元"),
        kpi("d", 70, "元"),
    ]

    baseline = build_previous_comparison(kpis, PERIOD2_RANGE, context, THRESHOLDS)["baseline"]

    severities = [entry["severity"] for entry in baseline]
    assert severities == ["normal", "significant", "critical", "critical"]


def test_build_previous_comparison_with_empty_kpis_keeps_section_with_empty_baseline():
    comparison = build_previous_comparison([], PERIOD2_RANGE, period2_history_context(), THRESHOLDS)

    assert comparison["baseline"] == []
    assert comparison["previous_report_id"] == "r-period1"
    assert comparison["summary_note"] == "上期摘要原文"


def test_build_previous_comparison_flags_same_period_and_partial_previous():
    context = period2_history_context()
    context["previous_status"] = "partial"

    comparison = build_previous_comparison(
        [kpi("销售额", 1.0, "元")], PERIOD1_RANGE, context, THRESHOLDS
    )

    assert comparison["same_period"] is True
    assert comparison["previous_status"] == "partial"
