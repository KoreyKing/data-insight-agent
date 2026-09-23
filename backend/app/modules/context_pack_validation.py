"""Context Pack 编辑保存的四层校验（architecture.md §6.4）。

任一 error 级问题整体拒绝保存（API 返回 400 + details.errors 全量）；warning 不阻断保存。
断言实现保持纯函数：输入候选包与内置出厂包，输出 errors / warnings 与规范化后的 payload。
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

import pandas as pd

from app.modules.context_pack import (
    REQUIRED_FIELD_ALIASES,
    REQUIRED_METRICS,
    ContextPackError,
    load_default_context_pack,
    validate_context_pack,
)
from app.modules.field_mapping import REQUIRED_FIELDS, build_field_profile, normalize_label
from app.modules.file_ingestion import build_schema_summary
from app.modules.task_parser import context_pack_for_llm

MAX_PAYLOAD_BYTES = 64 * 1024
PROMPT_TOKEN_WARNING = 6000
FROZEN_TABLE_NAME = "sales_orders"
ALLOWED_SEVERITIES = {"error", "warning"}

# calculation 引用层白名单：SQL 关键字与聚合函数不算字段引用。
SQL_TOKEN_WHITELIST = {
    "AND", "AS", "ASC", "AVG", "BETWEEN", "BY", "CASE", "CAST", "COALESCE", "COUNT", "DESC",
    "DISTINCT", "ELSE", "END", "FROM", "GROUP", "HAVING", "IN", "IS", "JOIN", "LEFT", "LIKE",
    "LIMIT", "MAX", "MIN", "NOT", "NULL", "NULLIF", "ON", "OR", "ORDER", "OVER", "PARTITION",
    "ROUND", "SELECT", "SUM", "THEN", "WHEN", "WHERE",
}
CHINESE_TOKEN_PATTERN = re.compile(r"[一-鿿]+")
ASCII_TOKEN_PATTERN = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
QUOTED_STRING_PATTERN = re.compile(r"'[^']*'|\"[^\"]*\"")
EXPRESSION_SIGNAL_PATTERN = re.compile(r"[A-Za-z_(){}+\-*/=<>]")


@dataclass(frozen=True)
class ValidationIssue:
    layer: int
    path: str
    message: str

    def as_dict(self) -> dict[str, Any]:
        return {"layer": self.layer, "path": self.path, "message": self.message}


@dataclass(frozen=True)
class EditValidation:
    errors: list[ValidationIssue]
    warnings: list[ValidationIssue]
    payload: dict[str, Any]

    @property
    def passed(self) -> bool:
        return not self.errors


def validate_context_pack_edit(
    candidate: Any,
    builtin: dict[str, Any] | None = None,
) -> EditValidation:
    """四层校验入口。返回的 payload 已按服务端强制项规范化，errors 为空时可直接落库。"""
    reference = builtin if builtin is not None else load_default_context_pack()
    if not isinstance(candidate, dict):
        issue = ValidationIssue(1, "", "业务口径内容必须是一个 JSON 对象。")
        return EditValidation([issue], [], deepcopy(reference))

    payload = normalize_candidate(candidate, reference)
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    errors.extend(check_structure(payload, reference))
    errors.extend(check_fields(payload, reference))
    reference_errors, reference_warnings = check_references(payload, reference)
    errors.extend(reference_errors)
    warnings.extend(reference_warnings)
    impact_errors, impact_warnings = check_impact(payload, reference)
    errors.extend(impact_errors)
    warnings.extend(impact_warnings)

    return EditValidation(errors, warnings, payload)


def normalize_candidate(candidate: dict[str, Any], builtin: dict[str, Any]) -> dict[str, Any]:
    """服务端强制项：meta.version 由保存时计算覆盖；history_context 忽略入参保留占位。"""
    payload = deepcopy(candidate)
    meta = payload.get("meta")
    if not isinstance(meta, dict):
        meta = {}
        payload["meta"] = meta
    meta["version"] = str(builtin["meta"]["version"])
    payload["history_context"] = deepcopy(builtin.get("history_context", {}))
    return payload


# ------------------------------------------------------------------ 1 结构层
def check_structure(payload: dict[str, Any], builtin: dict[str, Any]) -> list[ValidationIssue]:
    """编辑器可触发的结构错误（删必需指标 / 删光核心字段别名）逐项报业务文案；其余只可能
    来自绕过 UI 的 API 调用，统一包装原因（architecture.md §6.4 v0.13）。

    逐项报出的问题用出厂值补齐后再校验一次：仍失败说明还有别的结构错误，一并返回（全量）。
    """
    specific = [*missing_required_metrics(payload, builtin), *emptied_core_aliases(payload)]
    candidate = patched_for_specific_issues(payload, builtin) if specific else payload
    try:
        validate_context_pack(candidate)
    except ContextPackError as exc:
        return [*specific, ValidationIssue(1, "", f"业务口径结构不完整：{exc}")]
    return specific


def missing_required_metrics(
    payload: dict[str, Any],
    builtin: dict[str, Any],
) -> list[ValidationIssue]:
    names = [metric.get("name") for metric in metric_list(payload)]
    if any(not isinstance(name, str) for name in names):
        return []  # 名称本身不合法时交给通用结构错误与字段层报告，避免误报「被删除」
    missing = [
        metric["name"]
        for metric in builtin.get("metrics", [])
        if metric.get("name") in REQUIRED_METRICS and metric["name"] not in names
    ]
    if not missing:
        return []
    listed = "".join(f"「{name}」" for name in missing)
    return [ValidationIssue(1, "metrics", f"必需指标{listed}不可删除。")]


def emptied_core_aliases(payload: dict[str, Any]) -> list[ValidationIssue]:
    tables = table_list(payload)
    columns = tables[0].get("columns") if tables else None
    issues: list[ValidationIssue] = []
    for index, column in enumerate(columns if isinstance(columns, list) else []):
        name = column.get("name") if isinstance(column, dict) else None
        if not isinstance(name, str) or name not in REQUIRED_FIELD_ALIASES:
            continue
        aliases = column.get("aliases")
        if isinstance(aliases, list) and any(
            isinstance(alias, str) and alias.strip() for alias in aliases
        ):
            continue
        issues.append(
            ValidationIssue(
                1,
                f"data_dictionary.tables[0].columns[{index}].aliases",
                f"字段「{display_label(column)}」是核心分析字段，至少保留一个别名。",
            )
        )
    return issues


def patched_for_specific_issues(
    payload: dict[str, Any],
    builtin: dict[str, Any],
) -> dict[str, Any]:
    """用出厂内容补齐已逐项报告的问题，只为探测是否还有其他结构错误；不参与保存。"""
    patched = deepcopy(payload)
    metrics = patched.get("metrics")
    if isinstance(metrics, list):
        present = {
            metric["name"] for metric in metric_list(patched) if isinstance(metric.get("name"), str)
        }
        metrics.extend(
            deepcopy(metric)
            for metric in builtin.get("metrics", [])
            if metric.get("name") in REQUIRED_METRICS and metric["name"] not in present
        )
    builtin_aliases = {
        column["name"]: column.get("aliases", [])
        for column in column_list(builtin)
        if isinstance(column.get("name"), str)
    }
    tables = table_list(patched)
    columns = tables[0].get("columns") if tables else None
    for column in columns if isinstance(columns, list) else []:
        name = column.get("name") if isinstance(column, dict) else None
        if isinstance(name, str) and name in REQUIRED_FIELD_ALIASES:
            aliases = column.get("aliases")
            if not (
                isinstance(aliases, list)
                and any(isinstance(alias, str) and alias.strip() for alias in aliases)
            ):
                column["aliases"] = list(builtin_aliases.get(name) or [name])
    return patched


# ------------------------------------------------------------------ 2 字段层
def check_fields(payload: dict[str, Any], builtin: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    issues.extend(check_meta_name(payload, builtin))
    issues.extend(check_metrics(payload))
    issues.extend(check_table_and_columns(payload, builtin))
    issues.extend(check_alias_conflicts(payload))
    issues.extend(check_thresholds(payload))
    issues.extend(check_validation_rules(payload))
    return issues


def check_meta_name(payload: dict[str, Any], builtin: dict[str, Any]) -> list[ValidationIssue]:
    expected = str(builtin["meta"]["name"])
    actual = (payload.get("meta") or {}).get("name")
    if actual != expected:
        return [
            ValidationIssue(
                2,
                "meta.name",
                f"分析场景名称不可修改（应为「{expected}」）。",
            )
        ]
    return []


def check_metrics(payload: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return [ValidationIssue(2, "metrics", "指标列表格式不正确。")]

    seen: set[str] = set()
    for index, metric in enumerate(metrics):
        path = f"metrics[{index}]"
        if not isinstance(metric, dict):
            issues.append(ValidationIssue(2, path, "指标条目格式不正确。"))
            continue
        name = metric.get("name")
        if not isinstance(name, str) or not name.strip():
            issues.append(ValidationIssue(2, f"{path}.name", "指标名称不能为空。"))
        elif name in seen:
            issues.append(ValidationIssue(2, f"{path}.name", f"指标「{name}」重复定义。"))
        else:
            seen.add(name)
        calculation = metric.get("calculation")
        if not isinstance(calculation, str) or not calculation.strip():
            issues.append(
                ValidationIssue(2, f"{path}.calculation", f"指标「{name}」的口径表达式不能为空。")
            )
        issues.extend(check_alias_list(metric.get("aliases"), f"{path}.aliases"))
    return issues


def check_alias_list(aliases: Any, path: str) -> list[ValidationIssue]:
    if aliases is None:
        return []
    if not isinstance(aliases, list):
        return [ValidationIssue(2, path, "别名必须是字符串列表。")]
    if any(not isinstance(alias, str) or not alias.strip() for alias in aliases):
        return [ValidationIssue(2, path, "别名不能包含空值。")]
    return []


def check_table_and_columns(
    payload: dict[str, Any],
    builtin: dict[str, Any],
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    tables = table_list(payload)
    builtin_columns = {
        column["name"]: column for column in column_list(builtin) if isinstance(column, dict)
    }
    if len(tables) != 1:
        return [ValidationIssue(2, "data_dictionary.tables", "数据表结构不可增减（固定单表）。")]

    table = tables[0]
    if table.get("name") != FROZEN_TABLE_NAME:
        issues.append(
            ValidationIssue(
                2,
                "data_dictionary.tables[0].name",
                f"数据表名不可修改（应为 {FROZEN_TABLE_NAME}）。",
            )
        )

    columns = [column for column in table.get("columns", []) if isinstance(column, dict)]
    actual_names = [column.get("name") for column in columns]
    names = {name for name in actual_names if isinstance(name, str)}
    if len(names) != len(actual_names) and any(not isinstance(n, str) for n in actual_names):
        issues.append(
            ValidationIssue(2, "data_dictionary.tables[0].columns", "数据字段名必须是文本。")
        )
    if names != set(builtin_columns):
        missing = [
            display_label(builtin_columns[name])
            for name in builtin_columns
            if name not in names
        ]
        extra = sorted(name for name in names - set(builtin_columns) if name)
        detail = "；".join(
            part
            for part in (
                f"缺少字段：{'、'.join(missing)}" if missing else "",
                f"多出字段：{'、'.join(extra)}" if extra else "",
            )
            if part
        )
        issues.append(
            ValidationIssue(2, "data_dictionary.tables[0].columns", f"数据字段不可增减。{detail}")
        )

    for index, column in enumerate(columns):
        name = column.get("name")
        path = f"data_dictionary.tables[0].columns[{index}]"
        reference = builtin_columns.get(name) if isinstance(name, str) else None
        if reference is not None and column.get("display_name") != reference["display_name"]:
            issues.append(
                ValidationIssue(
                    2,
                    f"{path}.display_name",
                    f"字段「{reference['display_name']}」的业务显示名不可修改。",
                )
            )
        issues.extend(check_alias_list(column.get("aliases"), f"{path}.aliases"))
    return issues


def check_alias_conflicts(payload: dict[str, Any]) -> list[ValidationIssue]:
    """同一别名（归一化后）被两个字段认领时静默后写覆盖，必须在保存前拦下。"""
    owners: dict[str, list[str]] = {}
    spelled: dict[str, str] = {}
    labels: dict[str, str] = {}
    for column in column_list(payload):
        name = column.get("name")
        if not isinstance(name, str):
            continue
        labels.setdefault(name, display_label(column))
        aliases = column.get("aliases")
        aliases = aliases if isinstance(aliases, list) else []
        for alias in [name, *aliases]:
            if not isinstance(alias, str) or not alias.strip():
                continue
            key = normalize_label(alias)
            spelled.setdefault(key, alias.strip())
            claimants = owners.setdefault(key, [])
            if name not in claimants:
                claimants.append(name)

    issues: list[ValidationIssue] = []
    for key, claimants in owners.items():
        if len(claimants) > 1:
            listed = "".join(f"「{labels[claimant]}」" for claimant in claimants)
            issues.append(
                ValidationIssue(
                    2,
                    "data_dictionary.tables[0].columns[].aliases",
                    f"别名「{spelled[key]}」同时指向字段{listed}，请只保留一个。",
                )
            )
    return issues


def check_thresholds(payload: dict[str, Any]) -> list[ValidationIssue]:
    preferences = payload.get("report_preferences")
    preferences = preferences if isinstance(preferences, dict) else {}
    thresholds = preferences.get("anomaly_thresholds")
    path = "report_preferences.anomaly_thresholds"
    if not isinstance(thresholds, dict):
        return [ValidationIssue(2, path, "异常阈值缺失。")]

    values: dict[str, float] = {}
    issues: list[ValidationIssue] = []
    for key, label in (("significant_pct", "标黄阈值"), ("critical_pct", "标红阈值")):
        value = thresholds.get(key)
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            issues.append(ValidationIssue(2, f"{path}.{key}", f"{label}必须是数字。"))
            continue
        if value != value or value in (float("inf"), float("-inf")):  # noqa: PLR0124
            issues.append(ValidationIssue(2, f"{path}.{key}", f"{label}必须是有限数字。"))
            continue
        if value <= 0:
            issues.append(ValidationIssue(2, f"{path}.{key}", f"{label}必须大于 0。"))
            continue
        values[key] = float(value)

    if len(values) == 2 and values["significant_pct"] >= values["critical_pct"]:
        issues.append(
            ValidationIssue(2, path, "标黄阈值必须小于标红阈值。"),
        )
    return issues


def check_validation_rules(payload: dict[str, Any]) -> list[ValidationIssue]:
    rules = payload.get("validation_rules")
    if not isinstance(rules, list):
        return []
    issues: list[ValidationIssue] = []
    for index, rule in enumerate(rules):
        if not isinstance(rule, dict):
            issues.append(ValidationIssue(2, f"validation_rules[{index}]", "校验规则格式不正确。"))
            continue
        severity = rule.get("severity")
        if severity not in ALLOWED_SEVERITIES:
            issues.append(
                ValidationIssue(
                    2,
                    f"validation_rules[{index}].severity",
                    "校验规则等级只能是 error 或 warning。",
                )
            )
    return issues


# ------------------------------------------------------------------ 3 引用层
def check_references(
    payload: dict[str, Any],
    builtin: dict[str, Any],
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    """best-effort：只拦高置信的英文字段引用错误；中文指标互引未命中仅提示。"""
    del builtin
    canonical = {
        column["name"] for column in column_list(payload) if isinstance(column.get("name"), str)
    }
    metric_names = {
        metric.get("name")
        for metric in payload.get("metrics", [])
        if isinstance(metric, dict) and isinstance(metric.get("name"), str)
    }

    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []
    for index, metric in enumerate(payload.get("metrics", [])):
        if not isinstance(metric, dict):
            continue
        calculation = metric.get("calculation")
        if not isinstance(calculation, str) or not calculation.strip():
            continue
        path = f"metrics[{index}].calculation"
        name = metric.get("name")
        if not EXPRESSION_SIGNAL_PATTERN.search(calculation):
            # 纯中文说明（如「需用户提供库存字段」）不是引用表达式，跳过。
            continue

        stripped = QUOTED_STRING_PATTERN.sub(" ", calculation)
        for token in ASCII_TOKEN_PATTERN.findall(stripped):
            if token.upper() in SQL_TOKEN_WHITELIST or token in canonical:
                continue
            errors.append(
                ValidationIssue(
                    3,
                    path,
                    f"指标「{name}」的口径引用了不存在的字段 {token}。",
                )
            )
        for token in CHINESE_TOKEN_PATTERN.findall(stripped):
            if token in metric_names:
                continue
            warnings.append(
                ValidationIssue(
                    3,
                    path,
                    f"指标「{name}」的口径提到「{token}」，未匹配到已定义指标，请确认是否笔误。",
                )
            )
    return errors, warnings


# ------------------------------------------------------------------ 4 影响层
def check_impact(
    payload: dict[str, Any],
    builtin: dict[str, Any],
) -> tuple[list[ValidationIssue], list[ValidationIssue]]:
    errors: list[ValidationIssue] = []
    warnings: list[ValidationIssue] = []

    size = len(json.dumps(payload, ensure_ascii=False).encode("utf-8"))
    if size > MAX_PAYLOAD_BYTES:
        errors.append(
            ValidationIssue(
                4,
                "",
                f"口径内容过大（{size // 1024} KB），请精简说明后再保存（上限 64 KB）。",
            )
        )

    tokens = context_pack_prompt_tokens(payload)
    if tokens > PROMPT_TOKEN_WARNING:
        warnings.append(
            ValidationIssue(
                4,
                "",
                "口径内容较大，分析可能因资源限制提前收尾。",
            )
        )

    errors.extend(check_dry_run(payload, builtin))
    return errors, warnings


def check_dry_run(payload: dict[str, Any], builtin: dict[str, Any]) -> list[ValidationIssue]:
    """用业务显示名表头的合成 schema 试跑字段识别，必需字段必须仍可识别（§6.4 v0.11）。"""
    try:
        profile = build_field_profile(display_name_schema(builtin), payload)
    except ContextPackError:
        return []

    if profile.is_valid:
        return []

    display_names = {
        column["name"]: column.get("display_name", column["name"])
        for column in column_list(builtin)
        if isinstance(column, dict) and isinstance(column.get("name"), str)
    }
    missing = "、".join(
        display_names.get(field, field) for field in profile.missing_key_fields or REQUIRED_FIELDS
    )
    return [
        ValidationIssue(
            4,
            "data_dictionary.tables[0].columns[].aliases",
            f"按当前别名设置，示例数据将无法识别必需字段：{missing}。",
        )
    ]


def display_name_schema(builtin: dict[str, Any]):
    row = {
        column["display_name"]: sample_value(column)
        for column in column_list(builtin)
        if isinstance(column, dict) and isinstance(column.get("display_name"), str)
    }
    return build_schema_summary(pd.DataFrame([row]))


def sample_value(column: dict[str, Any]) -> Any:
    if column.get("name") == "order_date":
        return "2026-05-11"
    if column.get("data_type") in {"decimal", "integer", "number"}:
        return 1000
    return "示例值"


def context_pack_prompt_tokens(payload: dict[str, Any]) -> int:
    """与 Analysis Loop 同口径的分桶估算：中文按字符、ASCII 约 4 字符 1 token。"""
    text = json.dumps(context_pack_for_llm(payload), ensure_ascii=False)
    ascii_chars = sum(1 for char in text if ord(char) < 128)
    return max(1, ascii_chars // 4 + len(text) - ascii_chars)


# ------------------------------------------------------------------- helpers
def display_label(column: dict[str, Any]) -> str:
    """面向用户的字段名：业务显示名，缺失时回退 canonical 名。"""
    display_name = column.get("display_name")
    if isinstance(display_name, str) and display_name.strip():
        return display_name
    return str(column.get("name") or "")


def table_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    data_dictionary = payload.get("data_dictionary")
    data_dictionary = data_dictionary if isinstance(data_dictionary, dict) else {}
    tables = data_dictionary.get("tables")
    if not isinstance(tables, list):
        return []
    return [table for table in tables if isinstance(table, dict)]


def metric_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    metrics = payload.get("metrics")
    if not isinstance(metrics, list):
        return []
    return [metric for metric in metrics if isinstance(metric, dict)]


def column_list(payload: dict[str, Any]) -> list[dict[str, Any]]:
    columns: list[dict[str, Any]] = []
    for table in table_list(payload):
        table_columns = table.get("columns")
        if isinstance(table_columns, list):
            columns.extend(column for column in table_columns if isinstance(column, dict))
    return columns
