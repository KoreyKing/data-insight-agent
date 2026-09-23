"""record_finding 的 evidence 引用解析（architecture.md §3.2 v0.12）。

模型常把 evidence 写成装饰性引用串；精确匹配失败会让结论丢失 SQL 追溯，
并连带让 Report Composer 的自动配图（按 evidence_ref 查 query_results）失效。
"""
from __future__ import annotations

import pytest

from app.modules.query_engine import QueryResult
from app.modules.tools import ToolRuntime, evidence_for, record_finding

SQL_ONE = "SELECT store_name, SUM(net_sales_amount) AS sales FROM sales_orders GROUP BY store_name"
SQL_FIVE = "SELECT channel, SUM(net_sales_amount) AS sales FROM sales_orders GROUP BY channel"


def runtime_with_queries() -> ToolRuntime:
    runtime = ToolRuntime(handle=None)  # evidence 解析只读 queries，不触碰数据集句柄
    runtime.queries["query-1"] = QueryResult(
        columns=["store_name", "sales"],
        rows=[["徐汇店", 1200]],
        row_count=1,
        exec_ms=3,
        sql=SQL_ONE,
    )
    runtime.queries["query-5"] = QueryResult(
        columns=["channel", "sales"],
        rows=[["抖音", 800]],
        row_count=1,
        exec_ms=4,
        sql=SQL_FIVE,
    )
    return runtime


def test_exact_reference_keeps_sql_and_reference():
    evidence = evidence_for(runtime_with_queries(), "query-1", iteration=3)

    assert evidence["sql"] == SQL_ONE
    assert evidence["evidence_ref"] == "query-1"
    assert evidence["validated_by"] == "sql_validator"
    assert evidence["row_count"] == 1


@pytest.mark.parametrize(
    ("decorated", "expected_ref", "expected_sql"),
    [
        ("query-1(整体), query-2(门店), query-3(类目)", "query-1", SQL_ONE),
        ("query-5（渠道维度本周与上周对比，合计 327,985 元）", "query-5", SQL_FIVE),
        ("见 query-5 的渠道汇总", "query-5", SQL_FIVE),
        ("query-5;query-1", "query-5", SQL_FIVE),
    ],
)
def test_decorated_reference_resolves_first_query_and_normalizes_ref(
    decorated: str,
    expected_ref: str,
    expected_sql: str,
):
    evidence = evidence_for(runtime_with_queries(), decorated, iteration=4)

    assert evidence["sql"] == expected_sql
    assert evidence["evidence_ref"] == expected_ref


@pytest.mark.parametrize(
    "unresolvable",
    ["query-99", "query-2(尚未执行)", "手工观察，无查询依据", "", "整体判断"],
)
def test_unresolvable_reference_falls_back_to_short_note(unresolvable: str):
    evidence = evidence_for(runtime_with_queries(), unresolvable, iteration=2)

    assert evidence["sql"] == ""
    assert evidence["evidence_ref"] == unresolvable
    assert "row_count" not in evidence


def test_record_finding_attaches_sql_for_decorated_reference():
    runtime = runtime_with_queries()

    record_finding(
        runtime,
        {
            "type": "anomaly",
            "text": "抖音渠道客单价下滑。",
            "evidence": "query-5（渠道维度，对比上期基线 390,037 元）",
            "confidence": "high",
        },
        iteration=6,
    )

    evidence = runtime.findings[0]["evidence"]
    assert evidence["sql"] == SQL_FIVE
    assert evidence["evidence_ref"] == "query-5"


def test_composer_auto_charts_finding_with_decorated_reference():
    from app.modules.report_composer import compose_report

    runtime = runtime_with_queries()
    record_finding(
        runtime,
        {
            "type": "trend",
            "text": "各渠道销售额分布。",
            "evidence": "query-5（渠道维度）",
            "confidence": "medium",
        },
        iteration=7,
    )

    report = compose_report(
        status="completed",
        title="t",
        analysis_goal="",
        summary="",
        kpis=[],
        findings=runtime.findings,
        warnings=[],
        metadata={},
        query_results=runtime.queries,
    )

    chart = report["findings"][0]["chart"]
    assert chart["echarts_spec"]["xAxis"]["data"] == ["抖音"]
