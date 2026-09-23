from __future__ import annotations

import json
import time
from dataclasses import asdict
from typing import Any

from app.llm.client import LLMClientProtocol
from app.modules.context_pack import load_active_context_pack
from app.modules.dataset_store import DatasetMaterializationError, materialize_table_to_sqlite
from app.modules.report_composer import compose_report
from app.modules.reporting import build_default_kpis, default_time_range
from app.modules.schemas import TableData
from app.modules.sql_validator import SQLValidationError
from app.modules.task_parser import context_pack_for_llm, sanitize_error, schema_for_llm
from app.modules.tools import ToolRuntime, run_tool
from app.timestamps import utc_now_iso

DEFAULT_LIMITS = {"max_iterations": 12, "max_tokens": 50000, "max_duration_seconds": 300}
HARD_LIMITS = {"max_iterations": 15, "max_tokens": 100000, "max_duration_seconds": 600}
LOOP_BUDGET_WARNING = {
    "code": "LOOP_BUDGET_EXCEEDED",
    "message": "分析因资源限制未完成，以下为部分结论。",
}


def run_analysis_loop(
    table: TableData,
    task: dict[str, Any],
    llm_client: LLMClientProtocol,
    *,
    model_name: str | None = None,
    history_context: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
) -> dict[str, Any]:
    pack = context_pack if context_pack is not None else load_active_context_pack()
    try:
        handle = materialize_table_to_sqlite(table, context_pack=pack)
    except DatasetMaterializationError as exc:
        return failed_report(task, table, exc.code, exc.message)

    runtime = ToolRuntime(handle=handle)
    limits = execution_limits(task)
    started = time.monotonic()
    analysis_steps: list[dict[str, Any]] = []
    warnings: list[dict[str, str]] = []
    summary = ""
    token_used = 0
    loop_rounds = 0
    observation: dict[str, Any] | None = None
    status = "partial"

    for iteration in range(1, limits["max_iterations"] + 1):
        if time.monotonic() - started > limits["max_duration_seconds"]:
            warnings.append(LOOP_BUDGET_WARNING)
            break

        messages = build_loop_messages(
            task,
            handle.schema_summary,
            runtime,
            observation,
            iteration=iteration,
            max_iterations=limits["max_iterations"],
            history_context=history_context,
            context_pack=pack,
        )
        try:
            loop_rounds += 1
            raw = llm_client.complete(messages)
        except Exception as exc:
            warnings.append(
                {
                    "code": "LLM_CALL_FAILED",
                    "message": f"模型调用失败：{sanitize_error(exc)}。已输出已有部分报告。",
                }
            )
            break

        token_used += estimate_tokens(messages, raw)
        if token_used > limits["max_tokens"]:
            warnings.append(LOOP_BUDGET_WARNING)
            break

        try:
            tool_call = parse_tool_call(raw)
        except (ValueError, json.JSONDecodeError) as exc:
            analysis_steps.append(failed_step(iteration, "unknown", "LLM_PARSE_FAILED", str(exc)))
            observation = {"status": "failed", "code": "LLM_PARSE_FAILED", "message": str(exc)}
            continue

        tool = tool_call["tool"]
        args = tool_call["args"]
        submitted_sql = args.get("sql") if isinstance(args, dict) else None
        try:
            result = run_tool(runtime, tool, args, iteration)
        except SQLValidationError as exc:
            analysis_steps.append(
                failed_step(iteration, tool, exc.code, exc.message, sql=submitted_sql)
            )
            observation = {
                "status": "failed",
                "code": exc.code,
                "message": exc.message,
                "submitted_sql": submitted_sql,
            }
            continue
        except ValueError as exc:
            analysis_steps.append(
                failed_step(
                    iteration,
                    tool,
                    "TOOL_INVOCATION_FAILED",
                    str(exc),
                    sql=submitted_sql,
                )
            )
            observation = {
                "status": "failed",
                "code": "TOOL_INVOCATION_FAILED",
                "message": str(exc),
            }
            continue

        step = completed_step(iteration, tool, result)
        analysis_steps.append(step)
        observation = result
        if result.get("finished") is True:
            status = "completed"
            summary = str(result.get("summary") or "分析已完成。")
            break
    else:
        warnings.append(LOOP_BUDGET_WARNING)

    if status != "completed":
        status = "partial"
        summary = summary or partial_summary(runtime.findings, warnings)

    kpis_payload = build_default_kpis(handle)
    metadata: dict[str, Any] = {
        "data_source": asdict(table.data_source_ref),
        "row_count": table.row_count,
        "query_engine": "sqlite",
        "ran_at": utc_now_iso(),
        "model": model_name or "configured",
        "loop_rounds": loop_rounds,
        "steps_recorded": len(analysis_steps),
        "iterations_used": len(analysis_steps),
        "token_used": token_used,
    }
    time_range = default_time_range(handle)
    if time_range is not None:
        metadata["time_range"] = time_range

    return compose_report(
        status=status,
        title=str(task.get("task_title") or "周度零售经营复盘"),
        analysis_goal=str(task.get("analysis_goal") or ""),
        summary=summary,
        kpis=kpis_payload,
        findings=runtime.findings,
        warnings=warnings,
        analysis_steps=analysis_steps,
        metadata=metadata,
        query_results=runtime.queries,
        history_context=history_context,
        context_pack=pack,
    )


def build_loop_messages(
    task: dict[str, Any],
    schema_summary: Any,
    runtime: ToolRuntime,
    observation: dict[str, Any] | None,
    *,
    iteration: int = 1,
    max_iterations: int = 8,
    history_context: dict[str, Any] | None = None,
    context_pack: dict[str, Any] | None = None,
) -> list[dict[str, str]]:
    iterations_left = max(0, max_iterations - iteration + 1)
    payload: dict[str, Any] = {
        "task": task,
        "schema_summary": schema_for_llm(schema_summary),
        "context_pack": context_pack_for_llm(
            context_pack if context_pack is not None else load_active_context_pack()
        ),
    }
    if history_context:
        # 仅任务重跑且链上有上期报告时注入（architecture.md §3.3 / §6.3 槽位 7）。
        payload["history_context"] = history_context
    payload |= {
        "available_tools": {
            "query_data": {"args": {"sql": "SELECT ...", "summary": "optional string"}},
            "profile_column": {"args": {"column": "canonical column name"}},
            "create_chart": {
                "args": {
                    "data_ref": "query-1",
                    "chart_type": "bar|line|pie|table",
                    "title": "string",
                    "x_axis": "column",
                    "y_axis": "column",
                }
            },
            "record_finding": {
                "args": {
                    "type": "trend|anomaly|recommendation",
                    "text": "business-facing finding",
                    "evidence": "query-1 or short note",
                    "confidence": "high|medium|low",
                    "chart_id": "optional chart id",
                }
            },
            "finish": {"args": {"summary": "short report summary"}},
        },
        "state": {
            "iteration": iteration,
            "iterations_left": iterations_left,
            "queries": list(runtime.queries),
            "charts": list(runtime.charts),
            "findings": [finding["text"] for finding in runtime.findings],
            "last_observation": observation,
        },
        "output_contract": {"tool": "tool name", "args": {}},
    }
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


SYSTEM_PROMPT = "\n".join(
    [
        "你是 Data Insight Agent 的有界分析循环。",
        "",
        '每轮只能返回一个 JSON object，格式为 {"tool":"...","args":{...}}。',
        "不要输出 Markdown，不要解释，不要包代码块。",
        "",
        "SQL 必须作为 query_data 的参数提交，由系统的 SQL Validator 校验。",
        "以下硬规则任意违反一条都会被立即拒绝：",
        "1. 只能查询 sales_orders 表；可用 CTE（WITH cte_name AS (...)），",
        "   CTE 别名可在主查询里继续引用",
        "2. 禁止写操作 / DDL / PRAGMA / ATTACH / 多语句",
        "3. 顶层和 CTE 内都不允许 SELECT *；必须显式列出列",
        "4. 非聚合查询必须带 WHERE 或 LIMIT；",
        "   含 GROUP BY 或顶层聚合函数（SUM/COUNT/AVG/MIN/MAX）的聚合查询可不带 WHERE，",
        "   但缺省 LIMIT 会被自动补到 10000",
        "5. 引用的字段必须出现在 schema_summary.columns 内；",
        "   日期/数值列的 min/max 已给出，请据此圈定时间窗",
        "",
        "示例可被 Validator 接受的 SQL（按门店统计近 7 天销售额）：",
        "SELECT store_name, SUM(net_sales_amount) AS sales",
        "FROM sales_orders",
        "WHERE order_status IN ('completed','partial_refund')",
        "  AND order_date BETWEEN '2026-05-16' AND '2026-05-22'",
        "GROUP BY store_name",
        "ORDER BY sales DESC",
        "LIMIT 10",
        "",
        "工作节奏（硬性策略，不要违反）：",
        "- 第 1-3 轮：用 query_data 取整体指标（销售额/订单数/退款率等的本期与对比期）",
        "- 第 4 轮开始：每跑完一次 query_data，必须紧接一轮 record_finding 把数据点变成结论",
        "- 不要重复取同一时间窗的相似指标；同一时间窗的全量数据一次拿够",
        "- 取到 2-3 个维度（门店/类目/渠道任选）的数据后立即调用 finish，",
        "  即使没穷尽所有维度也要 finish，不要继续探索",
        "- 每轮 user payload 的 state.iterations_left 是剩余轮次，",
        "  iterations_left <= 2 时只允许 record_finding 或 finish",
        "",
        "历史对照（仅当 user payload 含 history_context 时生效）：",
        "- history_context 是本任务上期报告的基线：baseline_values 是上期各核心指标的值，",
        "  last_run_summary 是上期摘要，previous_time_range 是上期时间窗",
        "- 结论须对照上期基线判断延续或反转（如「连续两期下滑」），",
        "  引用上期数值时必须注明来自上期报告",
        "- 上期数值只用于对照，不得当作本期数据写入结论；本期数据一律以 query_data 结果为准",
    ]
)


def parse_tool_call(content: str) -> dict[str, Any]:
    payload = json.loads(extract_json_object(content))
    if not isinstance(payload, dict):
        raise ValueError("LLM tool call must be a JSON object")
    tool = payload.get("tool")
    args = payload.get("args", {})
    if not isinstance(tool, str) or not tool:
        raise ValueError("LLM tool call missing tool")
    if not isinstance(args, dict):
        raise ValueError("LLM tool args must be an object")
    return {"tool": tool, "args": args}


def extract_json_object(content: str) -> str:
    stripped = content.strip()
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError("empty JSON tool call")
    return stripped[start : end + 1]


def completed_step(iteration: int, tool: str, result: dict[str, Any]) -> dict[str, Any]:
    step = {
        "iteration": iteration,
        "tool": tool,
        "status": "completed",
        "summary": str(result.get("summary") or ""),
    }
    for key in ["data_ref", "chart_id", "finding_id", "sql", "row_count"]:
        if key in result:
            step[key] = result[key]
    return step


def failed_step(
    iteration: int,
    tool: str,
    code: str,
    message: str,
    *,
    sql: str | None = None,
) -> dict[str, Any]:
    step: dict[str, Any] = {
        "iteration": iteration,
        "tool": tool,
        "status": "failed",
        "summary": message,
        "code": code,
    }
    if sql:
        step["sql"] = sql
    return step


def execution_limits(task: dict[str, Any]) -> dict[str, int]:
    raw = task.get("execution_limits") if isinstance(task, dict) else None
    values = dict(DEFAULT_LIMITS)
    if isinstance(raw, dict):
        for key in values:
            if isinstance(raw.get(key), int) and raw[key] > 0:
                values[key] = min(raw[key], HARD_LIMITS[key])
    return values


def estimate_tokens(messages: list[dict[str, str]], raw: str) -> int:
    # 中文一个字符 ≈ 1 token；ASCII 大约 4 字符 ≈ 1 token。分桶估算避免低估中文 prompt。
    text = raw + "".join(message.get("content", "") for message in messages)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, ascii_chars // 4 + non_ascii_chars)


def partial_summary(findings: list[dict[str, Any]], warnings: list[dict[str, str]]) -> str:
    codes = {warning["code"] for warning in warnings}
    if "LLM_CALL_FAILED" in codes:
        prefix = "模型调用失败"
    else:
        prefix = "分析因资源限制未完成"
    if not findings:
        return f"{prefix}，尚未形成可信结论。"
    return f"{prefix}，以下为部分结论。"


def failed_report(
    task: dict[str, Any],
    table: TableData,
    code: str,
    message: str,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "title": str(task.get("task_title") or "周度零售经营复盘"),
        "summary": "",
        "kpis": [],
        "findings": [],
        "warnings": [{"code": code, "message": message}],
        "analysis_steps": [],
        "metadata": {
            "data_source": asdict(table.data_source_ref),
            "row_count": table.row_count,
            "ran_at": utc_now_iso(),
            "model": "configured",
            "loop_rounds": 0,
            "steps_recorded": 0,
            "iterations_used": 0,
            "token_used": 0,
        },
    }
