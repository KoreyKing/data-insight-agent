"""订单状态取值归一化（architecture.md §6.4 v0.18）与无法识别取值的报告提示（§3.3）。"""
from __future__ import annotations

import json
from dataclasses import asdict, replace

import pandas as pd
import pytest

from app.modules.analysis_loop import run_analysis_loop
from app.modules.dataset_store import materialize_table_to_sqlite, normalize_order_status
from app.modules.file_ingestion import build_schema_summary
from app.modules.reporting import default_structured_task, generate_traceable_report
from app.modules.sample_data import load_retail_sample

GOAL = "帮我生成周度经营复盘"
CHINESE_STATUSES = {"completed": "已完成", "partial_refund": "部分退款", "refunded": "已退款"}


def with_frame(table, frame: pd.DataFrame):
    return replace(table, dataframe=frame, schema_summary=build_schema_summary(frame))


def with_cancelled_rows(table, count: int):
    frame = table.dataframe.copy()
    rows = frame.index[frame["order_status"] == "completed"][:count]
    frame.loc[rows, "order_status"] = "已取消"
    return with_frame(table, frame)


def warning_codes(report) -> list[str]:
    return [warning["code"] for warning in report["warnings"]]


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("已完成", "completed"),
        (" 交易成功 ", "completed"),
        ("Completed", "completed"),
        ("PAID", "completed"),
        ("已发货", "completed"),
        ("部分退款", "partial_refund"),
        ("Partially Refunded", "partial_refund"),
        ("partially-refunded", "partial_refund"),
        ("已退款", "refunded"),
        ("全额退款", "refunded"),
        ("Returned", "refunded"),
        ("refunded", "refunded"),
    ],
)
def test_known_status_spellings_map_to_the_three_canonical_values(raw, expected):
    normalized, unrecognized = normalize_order_status(pd.Series([raw]))

    assert normalized.tolist() == [expected]
    assert unrecognized == {}


def test_unknown_and_empty_statuses_are_kept_and_counted():
    normalized, unrecognized = normalize_order_status(
        pd.Series(["已取消", "已取消", None, "  ", "completed"])
    )

    assert normalized.tolist()[:2] == ["已取消", "已取消"]
    assert normalized.tolist()[4] == "completed"
    assert unrecognized == {"已取消": 2, "（空值）": 2}


def test_chinese_status_export_yields_the_same_kpis_as_canonical_values():
    table = load_retail_sample()
    frame = table.dataframe.copy()
    frame["order_status"] = frame["order_status"].map(CHINESE_STATUSES)

    canonical = generate_traceable_report(table, GOAL)
    chinese = generate_traceable_report(with_frame(table, frame), GOAL)

    assert chinese["status"] == "completed"
    assert chinese["kpis"] == canonical["kpis"]
    assert warning_codes(chinese) == ["FALLBACK_REPORT"]


def test_unrecognized_statuses_are_reported_and_kept_out_of_sales():
    table = with_cancelled_rows(load_retail_sample(), 3)

    report = generate_traceable_report(table, GOAL)
    handle = materialize_table_to_sqlite(table)

    warning = next(w for w in report["warnings"] if w["code"] == "ORDER_STATUS_UNRECOGNIZED")
    assert "3 行" in warning["message"]
    assert "已取消" in warning["message"]
    kept = handle.connection.execute(
        "SELECT COUNT(*) FROM sales_orders WHERE order_status = '已取消'"
    ).fetchone()[0]
    assert kept == 3


def test_refund_rate_counts_only_recognized_statuses():
    table = load_retail_sample()
    frame = table.dataframe.copy()
    dates = pd.to_datetime(frame["order_date"])
    current_week = dates >= dates.max().normalize() - pd.Timedelta(days=6)
    cancelled = frame.index[current_week & (frame["order_status"] == "completed")][:40]
    frame.loc[cancelled, "order_status"] = "已取消"

    report = generate_traceable_report(with_frame(table, frame), GOAL)

    counted = frame[current_week & frame["order_status"].isin(list(CHINESE_STATUSES))]
    expected = counted["order_status"].isin(["refunded", "partial_refund"]).mean() * 100
    refund = next(kpi for kpi in report["kpis"] if kpi["name"] == "退款率")
    assert refund["current"] == round(expected, 2)


def test_numeric_status_codes_keep_their_type_and_are_reported():
    normalized, unrecognized = normalize_order_status(pd.Series([1, 2, 2]))

    assert normalized.dtype.kind == "i"
    assert normalized.tolist() == [1, 2, 2]
    assert unrecognized == {"2": 2, "1": 1}

    table = load_retail_sample()
    frame = table.dataframe.copy()
    frame["order_status"] = 1
    handle = materialize_table_to_sqlite(with_frame(table, frame))
    stored = handle.connection.execute("SELECT DISTINCT typeof(order_status) FROM sales_orders")
    assert [row[0] for row in stored] == ["integer"]
    assert [warning["code"] for warning in handle.warnings] == ["ORDER_STATUS_UNRECOGNIZED"]


def test_missing_status_column_counts_every_row_as_completed_without_warning():
    table = load_retail_sample()
    frame = table.dataframe.drop(columns=["order_status"])

    handle = materialize_table_to_sqlite(with_frame(table, frame))

    assert handle.warnings == ()
    rows = handle.connection.execute("SELECT DISTINCT order_status FROM sales_orders")
    statuses = {row[0] for row in rows}
    assert statuses == {"completed"}


def test_analysis_loop_report_carries_the_dataset_warning():
    class FinishingClient:
        def complete(self, messages: list[dict[str, str]]) -> str:
            return json.dumps({"tool": "finish", "args": {"summary": "done"}})

    table = with_cancelled_rows(load_retail_sample(), 2)
    task = default_structured_task(GOAL, asdict(table.data_source_ref))

    report = run_analysis_loop(table, task, FinishingClient(), model_name="fake")

    assert "ORDER_STATUS_UNRECOGNIZED" in warning_codes(report)
