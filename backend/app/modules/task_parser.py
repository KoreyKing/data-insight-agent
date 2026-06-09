from __future__ import annotations

import json
import re
from typing import Any

from app.config import Settings, get_settings
from app.llm.client import LLMClientProtocol, get_llm_client
from app.modules.context_pack import load_default_context_pack
from app.modules.reporting import default_structured_task
from app.modules.schemas import ColumnSummary, SchemaSummary

WARNING_MESSAGES = {
    "LLM_NOT_CONFIGURED": (
        "体验模式：当前未配置 AI 大模型，使用默认模板产出示例报告。"
        "配置模型后，可用自然语言定制分析。"
    ),
    "LLM_CALL_FAILED": "模型调用失败：{detail}。已使用默认周度经营回顾模板。",
    "LLM_PARSE_FAILED": "未能完整理解你的描述，已切换为默认周度经营回顾模板，可手动调整。",
    "LLM_INTENT_MISMATCH": (
        "当前 Context Pack 是零售运营，未能识别到匹配场景。"
        "已使用默认周度经营回顾模板，可继续生成或改用零售相关问题。"
    ),
}
JSON_REPAIR_PROMPT = "上一次输出不是合法 JSON。请只返回一个 JSON object，不要解释。"
ALLOWED_MODEL_FIELDS = {
    "task_title",
    "metrics",
    "dimensions",
    "time_range",
    "comparison",
    "report_template",
}


def parse_analysis_goal(
    analysis_goal: str,
    data_source_ref: dict[str, Any],
    schema_summary: SchemaSummary,
    *,
    llm_client: LLMClientProtocol | None = None,
    settings: Settings | None = None,
) -> dict[str, Any]:
    base_task = default_structured_task(analysis_goal, data_source_ref)
    resolved_settings = settings or get_settings()
    client = llm_client if llm_client is not None else get_llm_client(resolved_settings)

    if client is None:
        return with_warning(base_task, "LLM_NOT_CONFIGURED")

    context_pack = load_default_context_pack()
    messages = build_parse_messages(analysis_goal, schema_summary, context_pack)

    try:
        raw = client.complete(messages)
    except Exception as exc:
        return with_warning(base_task, "LLM_CALL_FAILED", sanitize_error(exc))

    try:
        parsed = parse_llm_json(raw)
    except ValueError:
        # 仅在首次输出非合法 JSON 时重试一次做 JSON 修复；调用类失败已 fail-fast。
        repair_messages = [*messages, {"role": "user", "content": JSON_REPAIR_PROMPT}]
        try:
            retry_raw = client.complete(repair_messages)
        except Exception as exc:
            return with_warning(base_task, "LLM_CALL_FAILED", sanitize_error(exc))
        try:
            parsed = parse_llm_json(retry_raw)
        except ValueError:
            return with_warning(base_task, "LLM_PARSE_FAILED")

    if parsed.get("intent_match") is False:
        return with_warning(base_task, "LLM_INTENT_MISMATCH")

    return {"task": overlay_task(base_task, parsed), "warnings": []}


def build_parse_messages(
    analysis_goal: str,
    schema_summary: SchemaSummary,
    context_pack: dict[str, Any],
) -> list[dict[str, str]]:
    payload = {
        "analysis_goal": analysis_goal,
        "schema_summary": schema_for_llm(schema_summary),
        "context_pack": context_pack_for_llm(context_pack),
        "output_contract": {
            "intent_match": "boolean",
            "task_title": "string",
            "metrics": ["string"],
            "dimensions": ["string"],
            "time_range": {"mode": "string"},
            "comparison": "string",
            "report_template": "string",
        },
    }
    return [
        {
            "role": "system",
            "content": (
                "你是 Data Insight Agent 的任务解析器。"
                "只把零售经营分析目标解析为结构化 JSON，不要输出 Markdown。"
                "如果用户目标明显不属于当前 Retail Operations Context Pack，"
                "返回 intent_match=false。"
            ),
        },
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def schema_for_llm(schema_summary: SchemaSummary) -> dict[str, Any]:
    columns = [column_for_llm(column) for column in schema_summary.columns]
    return {
        "row_count_estimate": schema_summary.row_count_estimate,
        "tables": [
            {
                "name": table.get("name"),
                "row_count_estimate": table.get("row_count_estimate"),
                "columns": columns,
            }
            for table in schema_summary.tables
        ],
    }


def column_for_llm(column: ColumnSummary) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "name": column.name,
        "data_type": column.data_type,
        "nullable": column.nullable,
        "distinct_count": column.distinct_count,
    }
    if column.min_value is not None:
        payload["min"] = column.min_value
    if column.max_value is not None:
        payload["max"] = column.max_value
    return payload


def context_pack_for_llm(context_pack: dict[str, Any]) -> dict[str, Any]:
    return {
        "meta": context_pack.get("meta", {}),
        "business_context": context_pack.get("business_context", {}),
        "metrics": [
            {
                "name": metric.get("name"),
                "calculation": metric.get("calculation"),
                "aliases": metric.get("aliases", []),
                "notes": metric.get("notes"),
            }
            for metric in context_pack.get("metrics", [])
        ],
        "dimensions": [
            {
                "name": dimension.get("name"),
                "column_ref": dimension.get("column_ref"),
                "description": dimension.get("description"),
            }
            for dimension in context_pack.get("dimensions", [])
        ],
        "analysis_templates": [
            {
                "name": template.get("name"),
                "description": template.get("description"),
                "required_metrics": template.get("required_metrics", []),
                "default_dimensions": template.get("default_dimensions", []),
            }
            for template in context_pack.get("analysis_templates", [])
        ],
    }


def parse_llm_json(content: str) -> dict[str, Any]:
    stripped = content.strip()
    if not stripped:
        raise ValueError("empty LLM response")

    match = re.search(r"\{.*\}", stripped, flags=re.DOTALL)
    if match:
        stripped = match.group(0)

    payload = json.loads(stripped)
    if not isinstance(payload, dict):
        raise ValueError("LLM response must be a JSON object")
    return payload


def overlay_task(base_task: dict[str, Any], parsed: dict[str, Any]) -> dict[str, Any]:
    task = dict(base_task)
    for key in ALLOWED_MODEL_FIELDS:
        value = parsed.get(key)
        if is_usable_model_value(value):
            task[key] = value
    return task


def is_usable_model_value(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, list):
        return bool(value) and all(isinstance(item, str) and item.strip() for item in value)
    if isinstance(value, dict):
        return bool(value)
    return False


def with_warning(
    task: dict[str, Any],
    code: str,
    detail: str | None = None,
) -> dict[str, Any]:
    template = WARNING_MESSAGES[code]
    message = template.format(detail=detail or "未知错误")
    return {"task": task, "warnings": [{"code": code, "message": message}]}


def sanitize_error(exc: Exception) -> str:
    text = str(exc).strip() or exc.__class__.__name__
    text = re.sub(r"sk-[A-Za-z0-9_-]+", "sk-***", text)
    text = re.sub(r"AIza[A-Za-z0-9_-]+", "AIza***", text)
    text = re.sub(r"(?i)bearer\s+[A-Za-z0-9._-]+", "Bearer ***", text)
    return re.sub(r"https?://\S+", "[redacted-url]", text)
