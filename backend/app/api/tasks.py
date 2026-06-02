from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter

from app.api.runtime import error_response, resolve_table
from app.modules.context_pack import load_default_context_pack
from app.modules.file_ingestion import IngestionError
from app.modules.task_parser import parse_analysis_goal

router = APIRouter()


@router.post("/tasks/parse")
def parse_task(payload: dict[str, Any]) -> dict[str, Any]:
    analysis_goal = str(payload.get("analysis_goal") or "帮我生成周度经营复盘")
    data_source_ref = payload.get("data_source_ref") or {
        "id": "sample-retail",
        "type": "csv",
        "name": "retail_sales_orders.csv",
        "location": "sample",
    }
    try:
        table = resolve_table(data_source_ref)
    except IngestionError as exc:
        return error_response(exc)

    result = parse_analysis_goal(
        analysis_goal,
        asdict(table.data_source_ref),
        table.schema_summary,
    )
    # Expose the Context Pack dimension catalog (Chinese name + description) so the
    # frontend "添加维度" dropdown can offer human-readable dimensions.
    context_pack = load_default_context_pack()
    result["dimension_options"] = [
        {"name": dimension.get("name"), "description": dimension.get("description")}
        for dimension in context_pack.get("dimensions", [])
        if dimension.get("name")
    ]
    return result
