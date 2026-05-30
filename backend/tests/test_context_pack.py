from __future__ import annotations

from copy import deepcopy

import pandas as pd
import pytest

from app.modules.context_pack import (
    ContextPackError,
    build_field_aliases,
    load_default_context_pack,
    validate_context_pack,
)
from app.modules.field_mapping import build_field_profile
from app.modules.file_ingestion import build_schema_summary


def test_default_context_pack_loads_with_required_runtime_contract():
    pack = load_default_context_pack()

    assert pack["meta"]["name"] == "Retail Operations"
    assert pack["meta"]["version"] == "1.0.0"
    assert {metric["name"] for metric in pack["metrics"]} >= {
        "销售额",
        "订单数",
        "客单价",
        "退款率",
    }


def test_context_pack_rejects_missing_required_metric():
    pack = load_default_context_pack()
    broken = deepcopy(pack)
    broken["metrics"] = [metric for metric in broken["metrics"] if metric["name"] != "销售额"]

    with pytest.raises(ContextPackError, match="required metric"):
        validate_context_pack(broken)


def test_context_pack_rejects_missing_core_field_aliases():
    pack = load_default_context_pack()
    broken = deepcopy(pack)
    columns = broken["data_dictionary"]["tables"][0]["columns"]
    for column in columns:
        if column["name"] == "net_sales_amount":
            column["aliases"] = []

    with pytest.raises(ContextPackError, match="required aliases"):
        validate_context_pack(broken)


def test_field_profile_uses_context_pack_aliases_before_fallback():
    dataframe = pd.DataFrame(
        [
            {
                "成交日期": "2026-05-11",
                "实收销售额": 1000,
                "店铺名称": "上海徐汇旗舰店",
                "一级品类": "童装",
                "销售渠道": "线下",
            }
        ]
    )
    schema_summary = build_schema_summary(dataframe)

    profile = build_field_profile(schema_summary)

    assert profile.is_valid is True
    assert profile.mappings["成交日期"].canonical_field == "order_date"
    assert profile.mappings["实收销售额"].canonical_field == "net_sales_amount"
    assert profile.mappings["店铺名称"].canonical_field == "store_name"
    assert profile.mappings["一级品类"].canonical_field == "category_l1"
    assert profile.mappings["销售渠道"].canonical_field == "channel"
    assert profile.mappings["实收销售额"].method == "context_pack_alias"


def test_build_field_aliases_includes_context_pack_column_names():
    aliases = build_field_aliases(load_default_context_pack())

    assert "net_sales_amount" in aliases
    assert {"net_sales_amount", "销售额", "实收销售额"}.issubset(aliases["net_sales_amount"])
