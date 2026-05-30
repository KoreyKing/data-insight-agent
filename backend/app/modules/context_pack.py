from __future__ import annotations

import json
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any


class ContextPackError(ValueError):
    pass


DEFAULT_CONTEXT_PACK_PATH = (
    Path(__file__).resolve().parents[1] / "context_packs" / "retail_operations_v1.json"
)
REQUIRED_METRICS = {"销售额", "订单数", "客单价", "退款率"}
REQUIRED_FIELD_ALIASES = {
    "order_date",
    "net_sales_amount",
    "store_name",
    "category_l1",
    "channel",
}


def load_default_context_pack() -> dict[str, Any]:
    return deepcopy(_load_default_context_pack_cached())


@lru_cache(maxsize=1)
def _load_default_context_pack_cached() -> dict[str, Any]:
    with DEFAULT_CONTEXT_PACK_PATH.open(encoding="utf-8") as file_handle:
        payload = json.load(file_handle)
    return validate_context_pack(payload)


def validate_context_pack(payload: dict[str, Any]) -> dict[str, Any]:
    require_mapping(payload, "context pack")
    meta = require_mapping(payload.get("meta"), "meta")
    require_string(meta.get("name"), "meta.name")
    require_string(meta.get("version"), "meta.version")

    require_mapping(payload.get("business_context"), "business_context")
    require_mapping(payload.get("data_dictionary"), "data_dictionary")
    require_list(payload.get("analysis_templates"), "analysis_templates")
    require_list(payload.get("validation_rules"), "validation_rules")
    require_mapping(payload.get("report_preferences"), "report_preferences")
    require_mapping(payload.get("history_context"), "history_context")

    metric_names = {
        require_string(metric.get("name"), "metrics[].name") for metric in metrics(payload)
    }
    missing_metrics = sorted(REQUIRED_METRICS - metric_names)
    if missing_metrics:
        raise ContextPackError(f"Missing required metric: {', '.join(missing_metrics)}")

    explicit_aliases = explicit_field_aliases(payload)
    missing_aliases = sorted(
        field for field in REQUIRED_FIELD_ALIASES if not explicit_aliases.get(field)
    )
    if missing_aliases:
        raise ContextPackError(f"Missing required aliases: {', '.join(missing_aliases)}")

    return payload


def context_pack_identity(payload: dict[str, Any] | None = None) -> dict[str, str]:
    pack = payload or load_default_context_pack()
    meta = pack["meta"]
    return {"context_pack_name": meta["name"], "context_pack_version": meta["version"]}


def build_field_aliases(payload: dict[str, Any]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for table in data_dictionary_tables(payload):
        for column in require_list(table.get("columns"), "data_dictionary.tables[].columns"):
            require_mapping(column, "data_dictionary.tables[].columns[]")
            name = require_string(column.get("name"), "data_dictionary.tables[].columns[].name")
            column_aliases = column.get("aliases")
            if column_aliases is None:
                column_aliases = []
            aliases[name] = {name, *require_string_list(column_aliases, f"{name}.aliases")}
    return aliases


def explicit_field_aliases(payload: dict[str, Any]) -> dict[str, set[str]]:
    aliases: dict[str, set[str]] = {}
    for table in data_dictionary_tables(payload):
        for column in require_list(table.get("columns"), "data_dictionary.tables[].columns"):
            require_mapping(column, "data_dictionary.tables[].columns[]")
            name = require_string(column.get("name"), "data_dictionary.tables[].columns[].name")
            column_aliases = column.get("aliases")
            if column_aliases is None:
                column_aliases = []
            aliases[name] = set(require_string_list(column_aliases, f"{name}.aliases"))
    return aliases


def metrics(payload: dict[str, Any]) -> list[dict[str, Any]]:
    return require_mapping_list(payload.get("metrics"), "metrics")


def data_dictionary_tables(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data_dictionary = require_mapping(payload.get("data_dictionary"), "data_dictionary")
    return require_mapping_list(data_dictionary.get("tables"), "data_dictionary.tables")


def require_mapping(value: Any, name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ContextPackError(f"{name} must be an object")
    return value


def require_list(value: Any, name: str) -> list[Any]:
    if not isinstance(value, list):
        raise ContextPackError(f"{name} must be a list")
    return value


def require_mapping_list(value: Any, name: str) -> list[dict[str, Any]]:
    items = require_list(value, name)
    for item in items:
        require_mapping(item, f"{name}[]")
    return items


def require_string_list(value: Any, name: str) -> list[str]:
    items = require_list(value, name)
    invalid = [item for item in items if not isinstance(item, str) or not item.strip()]
    if invalid:
        raise ContextPackError(f"{name} must contain non-empty strings")
    return items


def require_string(value: Any, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContextPackError(f"{name} must be a non-empty string")
    return value
