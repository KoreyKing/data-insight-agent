from __future__ import annotations

import json
from dataclasses import asdict

from app.modules.analysis_loop import run_analysis_loop
from app.modules.reporting import default_structured_task
from app.modules.sample_data import load_retail_sample


class FakeLLMClient:
    def __init__(self, responses: list[dict]):
        self.responses = [json.dumps(response, ensure_ascii=False) for response in responses]
        self.messages: list[list[dict[str, str]]] = []

    def complete(self, messages: list[dict[str, str]]) -> str:
        self.messages.append(messages)
        if not self.responses:
            raise AssertionError("FakeLLMClient has no queued response")
        return self.responses.pop(0)


def sample_task(max_iterations: int = 8) -> dict:
    table = load_retail_sample()
    task = default_structured_task("帮我生成周度经营复盘", asdict(table.data_source_ref))
    task["execution_limits"]["max_iterations"] = max_iterations
    return task


def test_analysis_loop_generates_findings_charts_and_steps_from_fixed_tools():
    table = load_retail_sample()
    llm = FakeLLMClient(
        [
            {
                "tool": "query_data",
                "args": {
                    "sql": """
                    SELECT store_name, SUM(net_sales_amount) AS sales
                    FROM sales_orders
                    WHERE order_status IN ('completed', 'partial_refund')
                    GROUP BY store_name
                    ORDER BY sales DESC
                    LIMIT 3
                    """,
                    "summary": "按门店汇总销售额",
                },
            },
            {
                "tool": "create_chart",
                "args": {
                    "data_ref": "query-1",
                    "chart_type": "bar",
                    "title": "门店销售额 Top 3",
                    "x_axis": "store_name",
                    "y_axis": "sales",
                },
            },
            {
                "tool": "record_finding",
                "args": {
                    "type": "trend",
                    "text": "头部门店贡献了主要销售额。",
                    "evidence": "query-1",
                    "confidence": "medium",
                    "chart_id": "chart-1",
                },
            },
            {
                "tool": "query_data",
                "args": {
                    "sql": """
                    SELECT category_l1,
                      COUNT(*) AS orders,
                      SUM(CASE WHEN order_status IN ('refunded', 'partial_refund')
                        THEN 1 ELSE 0 END) AS refund_orders
                    FROM sales_orders
                    WHERE order_date >= '2026-05-01'
                    GROUP BY category_l1
                    ORDER BY refund_orders DESC
                    LIMIT 4
                    """,
                    "summary": "按类目汇总退款订单",
                },
            },
            {
                "tool": "record_finding",
                "args": {
                    "type": "anomaly",
                    "text": "童装退款订单较多，需要复核 SKU 与退款原因。",
                    "evidence": "query-2",
                    "confidence": "high",
                },
            },
            {"tool": "finish", "args": {"summary": "已完成门店与类目下钻。"}},
        ]
    )

    report = run_analysis_loop(table, sample_task(), llm)

    assert report["status"] == "completed"
    assert report["summary"] == "已完成门店与类目下钻。"
    assert len(report["findings"]) == 2
    assert report["findings"][0]["evidence"]["sql"].lstrip().startswith("SELECT")
    assert report["findings"][0]["evidence"]["iteration"] == 3
    assert report["findings"][0]["chart"]["echarts_spec"]["series"][0]["data"]
    assert [step["tool"] for step in report["analysis_steps"]] == [
        "query_data",
        "create_chart",
        "record_finding",
        "query_data",
        "record_finding",
        "finish",
    ]
    assert report["metadata"]["iterations_used"] == 6
    assert [kpi["name"] for kpi in report["kpis"]] == ["销售额", "订单数", "客单价", "退款率"]
    assert report["metadata"]["model"] == "configured"


def test_analysis_loop_system_prompt_carries_sql_hard_rules():
    from app.modules.analysis_loop import SYSTEM_PROMPT

    assert "sales_orders" in SYSTEM_PROMPT
    assert "CTE" in SYSTEM_PROMPT
    assert "SELECT *" in SYSTEM_PROMPT
    assert "WHERE" in SYSTEM_PROMPT and "LIMIT" in SYSTEM_PROMPT
    assert "schema_summary" in SYSTEM_PROMPT


def test_analysis_loop_system_prompt_carries_strategy_directives():
    """Prompt must make the query → record_finding → finish rhythm explicit."""
    from app.modules.analysis_loop import SYSTEM_PROMPT

    assert "record_finding" in SYSTEM_PROMPT
    assert "iterations_left" in SYSTEM_PROMPT
    assert "finish" in SYSTEM_PROMPT


def test_default_limits_max_iterations_is_twelve():
    """Default loop budget gives the model room to record findings before finish."""
    from app.modules.analysis_loop import DEFAULT_LIMITS, HARD_LIMITS

    assert DEFAULT_LIMITS["max_iterations"] == 12
    assert DEFAULT_LIMITS["max_iterations"] <= HARD_LIMITS["max_iterations"]


def test_loop_messages_carry_iterations_left_in_state():
    """Each loop payload carries remaining iterations so the model can budget work."""
    from app.modules.analysis_loop import build_loop_messages
    from app.modules.dataset_store import materialize_table_to_sqlite
    from app.modules.tools import ToolRuntime

    handle = materialize_table_to_sqlite(load_retail_sample())
    runtime = ToolRuntime(handle=handle)
    task = sample_task(max_iterations=12)

    messages = build_loop_messages(
        task,
        handle.schema_summary,
        runtime,
        observation=None,
        iteration=4,
        max_iterations=12,
    )

    user_payload = json.loads(messages[1]["content"])
    assert user_payload["state"]["iteration"] == 4
    assert user_payload["state"]["iterations_left"] == 9


def test_analysis_loop_records_sql_rejection_and_allows_retry():
    table = load_retail_sample()
    llm = FakeLLMClient(
        [
            {"tool": "query_data", "args": {"sql": "DELETE FROM sales_orders"}},
            {
                "tool": "query_data",
                "args": {
                    "sql": """
                    SELECT COUNT(*) AS orders
                    FROM sales_orders
                    WHERE order_date >= '2026-05-01'
                    LIMIT 1
                    """
                },
            },
            {
                "tool": "record_finding",
                "args": {
                    "type": "trend",
                    "text": "模型改写 SQL 后成功取得订单数。",
                    "evidence": "query-1",
                    "confidence": "medium",
                },
            },
            {"tool": "finish", "args": {"summary": "SQL 重试成功。"}},
        ]
    )

    report = run_analysis_loop(table, sample_task(), llm)

    assert report["status"] == "completed"
    assert report["analysis_steps"][0]["status"] == "failed"
    assert report["analysis_steps"][0]["code"] == "SQL_VALIDATOR_REJECTED"
    # 拒绝时保留模型提交的原 SQL，方便诊断和给模型下一轮反馈
    assert report["analysis_steps"][0]["sql"] == "DELETE FROM sales_orders"
    assert report["findings"][0]["text"] == "模型改写 SQL 后成功取得订单数。"


def test_analysis_loop_outputs_partial_report_when_iteration_budget_is_exceeded():
    table = load_retail_sample()
    llm = FakeLLMClient(
        [
            {
                "tool": "record_finding",
                "args": {
                    "type": "recommendation",
                    "text": "当前只有部分结论，需后续继续分析。",
                    "evidence": "manual-observation",
                    "confidence": "low",
                },
            },
            {"tool": "query_data", "args": {"sql": "SELECT store_name FROM sales_orders LIMIT 1"}},
        ]
    )

    report = run_analysis_loop(table, sample_task(max_iterations=1), llm)

    assert report["status"] == "partial"
    assert report["findings"][0]["text"] == "当前只有部分结论，需后续继续分析。"
    assert report["warnings"] == [
        {"code": "LOOP_BUDGET_EXCEEDED", "message": "分析因资源限制未完成，以下为部分结论。"}
    ]
    assert report["metadata"]["iterations_used"] == 1


def test_analysis_loop_clamps_execution_limits_to_hard_caps():
    table = load_retail_sample()
    llm = FakeLLMClient(
        [
            {
                "tool": "record_finding",
                "args": {
                    "type": "trend",
                    "text": f"第 {index} 条部分结论。",
                    "evidence": "manual-observation",
                    "confidence": "low",
                },
            }
            for index in range(20)
        ]
    )
    task = sample_task(max_iterations=50)
    task["execution_limits"]["max_tokens"] = 999999
    task["execution_limits"]["max_duration_seconds"] = 999999

    report = run_analysis_loop(table, task, llm)

    assert report["status"] == "partial"
    assert len(report["findings"]) == 15
    assert report["metadata"]["iterations_used"] == 15
    assert report["warnings"] == [
        {"code": "LOOP_BUDGET_EXCEEDED", "message": "分析因资源限制未完成，以下为部分结论。"}
    ]


def test_analysis_loop_returns_partial_report_when_llm_call_fails():
    class FailingLLMClient:
        def complete(self, messages: list[dict[str, str]]) -> str:
            raise RuntimeError("401 unauthorized sk-test-secret")

    table = load_retail_sample()

    report = run_analysis_loop(table, sample_task(), FailingLLMClient())

    assert report["status"] == "partial"
    assert report["metadata"]["iterations_used"] == 0
    assert report["warnings"][0]["code"] == "LLM_CALL_FAILED"
    assert "sk-test-secret" not in report["warnings"][0]["message"]
    assert report["summary"].startswith("模型调用失败")


def test_analysis_loop_uses_model_name_metadata_when_provided():
    table = load_retail_sample()
    llm = FakeLLMClient([{"tool": "finish", "args": {"summary": "no-op finish"}}])

    report = run_analysis_loop(table, sample_task(), llm, model_name="deepseek-chat")

    assert report["metadata"]["model"] == "deepseek-chat"


def test_analysis_loop_records_tool_invocation_failure_with_real_tool_name():
    table = load_retail_sample()
    llm = FakeLLMClient(
        [
            # 缺 text，会触发 tools.required_string 抛 ValueError → TOOL_INVOCATION_FAILED
            {
                "tool": "record_finding",
                "args": {
                    "type": "trend",
                    "evidence": "manual-observation",
                    "confidence": "low",
                },
            },
            {"tool": "finish", "args": {"summary": "tool 错误已被 loop 捕获并降级。"}},
        ]
    )

    report = run_analysis_loop(table, sample_task(), llm)

    assert report["status"] == "completed"
    assert report["analysis_steps"][0]["status"] == "failed"
    assert report["analysis_steps"][0]["tool"] == "record_finding"
    assert report["analysis_steps"][0]["code"] == "TOOL_INVOCATION_FAILED"
