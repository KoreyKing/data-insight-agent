from dataclasses import dataclass
from typing import Any

from app.modules.context_pack import build_field_aliases, load_default_context_pack
from app.modules.schemas import SchemaSummary


@dataclass(frozen=True)
class FieldMapping:
    source_column: str
    canonical_field: str
    confidence: str
    method: str


@dataclass(frozen=True)
class FieldProfile:
    mappings: dict[str, FieldMapping]
    is_valid: bool
    missing_key_fields: list[str]
    warnings: list[str]


CANONICAL_ALIASES: dict[str, set[str]] = {
    "order_date": {
        "order_date",
        "date",
        "日期",
        "订单日期",
        "交易日期",
        "下单日期",
    },
    "net_sales_amount": {
        "net_sales_amount",
        "net_sales",
        "net sales",
        "sales",
        "gmv",
        "销售额",
        "净销售额",
        "营业额",
        "实付金额",
    },
    "store_name": {"store_name", "store", "门店", "门店名称", "店铺", "店铺名称"},
    "category_l1": {"category_l1", "category", "类目", "一级类目", "商品类目", "品类"},
    "channel": {"channel", "渠道", "销售渠道", "来源渠道"},
    "order_id": {"order_id", "订单号", "订单编号"},
    "order_status": {"order_status", "订单状态", "状态"},
    "quantity": {"quantity", "qty", "数量", "销售数量"},
    "unit_cost": {"unit_cost", "成本", "单位成本"},
}

REQUIRED_FIELDS = ["net_sales_amount", "order_date"]
DRILLDOWN_FIELDS = ["store_name", "category_l1", "channel"]


def normalize_label(value: str) -> str:
    return value.strip().lower().replace("_", "").replace(" ", "")


FALLBACK_ALIAS_LOOKUP: dict[str, str] = {
    normalize_label(alias): canonical
    for canonical, aliases in CANONICAL_ALIASES.items()
    for alias in aliases | {canonical}
}


def build_alias_lookup(context_pack: dict[str, Any] | None = None) -> dict[str, str]:
    pack = context_pack or load_default_context_pack()
    lookup: dict[str, str] = {}
    for canonical, aliases in build_field_aliases(pack).items():
        for alias in aliases:
            lookup[normalize_label(alias)] = canonical
    for alias, canonical in FALLBACK_ALIAS_LOOKUP.items():
        lookup.setdefault(alias, canonical)
    return lookup


def build_field_profile(
    schema_summary: SchemaSummary,
    context_pack: dict[str, Any] | None = None,
) -> FieldProfile:
    mappings: dict[str, FieldMapping] = {}
    canonical_found: set[str] = set()
    alias_lookup = build_alias_lookup(context_pack)
    fallback_aliases = set(FALLBACK_ALIAS_LOOKUP)

    for column in schema_summary.columns:
        normalized = normalize_label(column.name)
        canonical = alias_lookup.get(normalized)
        method = "exact"
        confidence = "high"

        if canonical is not None and normalized not in fallback_aliases:
            method = "context_pack_alias"

        if canonical is None:
            canonical, method, confidence = infer_by_name_and_type(column.name, column.data_type)

        if canonical is not None:
            if canonical in canonical_found and confidence != "high":
                continue
            mappings[column.name] = FieldMapping(
                source_column=column.name,
                canonical_field=canonical,
                confidence=confidence,
                method=method,
            )
            canonical_found.add(canonical)

    missing = [field for field in REQUIRED_FIELDS if field not in canonical_found]
    warnings: list[str] = []
    if not any(field in canonical_found for field in DRILLDOWN_FIELDS):
        warnings.append("未识别到门店、类目或渠道维度，报告将降级为整体趋势分析。")

    return FieldProfile(
        mappings=mappings,
        is_valid=len(missing) == 0,
        missing_key_fields=missing,
        warnings=warnings,
    )


def infer_by_name_and_type(column_name: str, data_type: str) -> tuple[str | None, str, str]:
    lowered = column_name.lower()
    if data_type == "date" or "日期" in column_name or "date" in lowered:
        return "order_date", "type_name", "medium"
    excluded_amount_terms = ["gross", "discount", "refund", "cost", "应付", "折扣", "退款", "成本"]
    if data_type == "number" and (
        "net" in lowered
        or "销售额" in column_name
        or "净销售" in column_name
        or ("sales" in lowered and not any(term in lowered for term in excluded_amount_terms))
        or (
            "金额" in column_name
            and not any(term in column_name for term in excluded_amount_terms)
        )
    ):
        return "net_sales_amount", "type_name", "medium"
    return None, "unmapped", "low"
