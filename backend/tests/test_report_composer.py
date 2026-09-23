from app.modules.query_engine import QueryResult
from app.modules.report_composer import compose_report


def query_result() -> QueryResult:
    return QueryResult(
        columns=["store_name", "sales"],
        rows=[["徐汇店", 1200], ["天河店", 800]],
        row_count=2,
        exec_ms=3,
        sql="SELECT store_name, SUM(net_sales_amount) AS sales FROM sales_orders GROUP BY store",
    )


def test_auto_charts_finding_missing_chart_from_linked_query():
    finding = {
        "id": "finding-1",
        "type": "anomaly",
        "confidence": "high",
        "text": "徐汇店销售额领先。",
        "evidence": {"sql": "...", "data_source": "sales_orders", "evidence_ref": "query-1"},
    }

    report = compose_report(
        status="completed",
        title="周度零售经营复盘",
        analysis_goal="",
        summary="",
        kpis=[],
        findings=[finding],
        warnings=[],
        metadata={},
        query_results={"query-1": query_result()},
    )

    chart = report["findings"][0]["chart"]
    assert chart["type"] == "bar"
    spec = chart["echarts_spec"]
    assert spec["xAxis"]["data"] == ["徐汇店", "天河店"]
    assert spec["series"][0]["data"] == [1200.0, 800.0]


def test_keeps_existing_chart_and_does_not_override():
    existing_chart = {"id": "chart-1", "type": "pie", "title": "x", "echarts_spec": {"series": []}}
    finding = {
        "id": "finding-1",
        "type": "trend",
        "confidence": "medium",
        "text": "保留已有图表。",
        "evidence": {"evidence_ref": "query-1"},
        "chart": existing_chart,
    }

    report = compose_report(
        status="completed",
        title="t",
        analysis_goal="",
        summary="",
        kpis=[],
        findings=[finding],
        warnings=[],
        metadata={},
        query_results={"query-1": query_result()},
    )

    assert report["findings"][0]["chart"] is existing_chart


def test_skips_auto_chart_when_no_linked_query():
    finding = {
        "id": "finding-1",
        "type": "recommendation",
        "confidence": "low",
        "text": "无关联查询。",
        "evidence": {"evidence_ref": "missing"},
    }

    report = compose_report(
        status="partial",
        title="t",
        analysis_goal="",
        summary="",
        kpis=[],
        findings=[finding],
        warnings=[],
        metadata={},
        query_results={},
    )

    assert "chart" not in report["findings"][0]


def test_dedupes_warnings_and_adds_context_pack_identity():
    report = compose_report(
        status="partial",
        title="t",
        analysis_goal="",
        summary="",
        kpis=[],
        findings=[],
        warnings=[
            {"code": "LOOP_BUDGET_EXCEEDED", "message": "a"},
            {"code": "LOOP_BUDGET_EXCEEDED", "message": "b"},
        ],
        metadata={},
    )

    assert report["warnings"] == [{"code": "LOOP_BUDGET_EXCEEDED", "message": "a"}]
    assert report["context_pack_name"] == "Retail Operations"


def history_context_fixture() -> dict:
    return {
        "previous_report_id": "r-prev",
        "previous_ran_at": "2026-09-01T10:00:00+00:00",
        "previous_status": "completed",
        "previous_time_range": {"current_start": "2026-05-11", "current_end": "2026-05-17"},
        "last_run_summary": "上期摘要",
        "baseline_values": {"销售额": 100.0, "退款率": 4.5},
    }


def test_compose_report_attaches_previous_comparison_when_history_context_given():
    report = compose_report(
        status="completed",
        title="t",
        analysis_goal="",
        summary="",
        kpis=[
            {"name": "销售额", "current": 110.0, "previous": 100.0, "unit": "元"},
            {"name": "退款率", "current": 5.0, "previous": 4.0, "unit": "%"},
        ],
        findings=[],
        warnings=[],
        metadata={"time_range": {"current_start": "2026-05-18", "current_end": "2026-05-24"}},
        history_context=history_context_fixture(),
    )

    comparison = report["previous_comparison"]
    assert comparison["previous_report_id"] == "r-prev"
    assert comparison["previous_status"] == "completed"
    assert comparison["same_period"] is False
    assert comparison["summary_note"] == "上期摘要"
    # 内置包阈值 significant 10 / critical 30：+10% 恰好为 significant；率值只给 pp 且不着色
    assert [
        (entry["name"], entry["delta_value"], entry["delta_unit"], entry["severity"])
        for entry in comparison["baseline"]
    ] == [("销售额", 10.0, "%", "significant"), ("退款率", 0.5, "pp", None)]


def test_compose_report_omits_previous_comparison_without_history_context():
    report = compose_report(
        status="completed",
        title="t",
        analysis_goal="",
        summary="",
        kpis=[{"name": "销售额", "current": 110.0, "previous": 100.0, "unit": "元"}],
        findings=[],
        warnings=[],
        metadata={},
    )

    assert "previous_comparison" not in report
