from __future__ import annotations

import json
import logging
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


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
    """内置出厂镜像（只读）：种子来源、恢复默认还原源、活动包读失败时的回落、测试 fixture。"""
    return deepcopy(_load_default_context_pack_cached())


def builtin_pack_name() -> str:
    return str(_load_default_context_pack_cached()["meta"]["name"])


def builtin_base_version() -> str:
    return str(_load_default_context_pack_cached()["meta"]["version"])


def effective_version(base_version: str, revision: int) -> str:
    """版本语义（§6.4）：revision 0 为出厂版本串，之后为 {base}-local.{revision}。"""
    return base_version if revision <= 0 else f"{base_version}-local.{revision}"


def comparable_payload(payload: Any) -> Any:
    """比较口径内容时去掉服务端计算的 meta.version。"""
    if not isinstance(payload, dict):
        return payload
    without_version = {key: value for key, value in payload.items() if key != "meta"}
    meta = payload.get("meta")
    if isinstance(meta, dict):
        without_version["meta"] = {key: value for key, value in meta.items() if key != "version"}
    return without_version


def matches_factory(payload: Any) -> bool:
    """内容是否等于当前内置出厂包（忽略 meta.version）。"""
    return comparable_payload(payload) == comparable_payload(load_default_context_pack())


def stamped_payload(payload: dict[str, Any], version: str) -> dict[str, Any]:
    """把有效版本串写入 payload.meta.version（服务端计算，忽略入参版本）。"""
    stamped = deepcopy(payload)
    meta = stamped.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        stamped["meta"] = meta
    meta["version"] = version
    return stamped


def load_active_context_pack() -> dict[str, Any]:
    """活动包：每次运行时读 DB（不做进程缓存），读失败 / 校验失败回落内置出厂镜像。"""
    try:
        record = read_active_context_pack_record()
    except Exception as exc:  # noqa: BLE001 —— 表缺失 / 库不可读都必须容错回落
        logger.warning(
            "CONTEXT_PACK_NOT_FOUND: 读取活动 Context Pack 失败（%s），回落内置出厂包。",
            type(exc).__name__,
        )
        return load_default_context_pack()

    if record is None:
        return load_default_context_pack()

    payload, base_version, revision = record
    version = effective_version(base_version, revision)
    try:
        return validate_context_pack(stamped_payload(payload, version))
    except ContextPackError as exc:
        logger.warning(
            "CONTEXT_PACK_NOT_FOUND: 活动 Context Pack 校验失败（%s），回落内置出厂包。",
            exc,
        )
        return load_default_context_pack()


def read_active_context_pack_record() -> tuple[dict[str, Any], str, int] | None:
    """读取活动包记录 → (payload, base_version, revision)；无记录返回 None。"""
    from sqlalchemy import select

    from app.db.engine import SessionLocal, get_engine
    from app.db.models import ContextPackRecord

    with SessionLocal(bind=get_engine()) as session:
        record = session.scalars(
            select(ContextPackRecord).where(ContextPackRecord.name == builtin_pack_name())
        ).one_or_none()
        if record is None:
            return None
        if not isinstance(record.payload_json, dict):
            raise ContextPackError("context pack payload must be an object")
        return deepcopy(record.payload_json), record.base_version, record.revision


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

    for table in data_dictionary_tables(payload):
        for column in require_list(table.get("columns"), "data_dictionary.tables[].columns"):
            require_mapping(column, "data_dictionary.tables[].columns[]")
            require_string(
                column.get("display_name"), "data_dictionary.tables[].columns[].display_name"
            )

    return payload


def context_pack_identity(payload: dict[str, Any] | None = None) -> dict[str, str]:
    pack = payload if payload is not None else load_active_context_pack()
    meta = pack["meta"]
    return {"context_pack_name": meta["name"], "context_pack_version": meta["version"]}


def anomaly_thresholds(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """活动包异常阈值 significant_pct / critical_pct；缺失时返回空 dict。"""
    pack = load_active_context_pack() if payload is None else payload
    preferences = pack.get("report_preferences")
    preferences = preferences if isinstance(preferences, dict) else {}
    thresholds = preferences.get("anomaly_thresholds")
    return dict(thresholds) if isinstance(thresholds, dict) else {}


def context_pack_display_names(payload: dict[str, Any] | None = None) -> dict[str, str]:
    pack = load_active_context_pack() if payload is None else payload
    display_names: dict[str, str] = {}
    for table in data_dictionary_tables(pack):
        for column in require_list(table.get("columns"), "data_dictionary.tables[].columns"):
            require_mapping(column, "data_dictionary.tables[].columns[]")
            name = require_string(column.get("name"), "data_dictionary.tables[].columns[].name")
            display_name = column.get("display_name")
            display_names[name] = (
                display_name
                if isinstance(display_name, str) and display_name.strip()
                else name
            )
    return display_names


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
