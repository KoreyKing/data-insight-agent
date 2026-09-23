from __future__ import annotations

from app.modules.task_fingerprint import (
    build_schema_fingerprint,
    canonical_fields_from_profile,
)


def test_canonical_fields_from_profile_reads_only_mapped_canonical_fields():
    field_profile = {
        "mappings": {
            "交易日期": {"canonical_field": "order_date"},
            "销售金额": {"canonical_field": "net_sales_amount"},
            "备注": {"canonical_field": None},
            "空白": {"canonical_field": "  "},
            "非字符串": {"canonical_field": 1},
            "无效映射": "order_id",
        },
        "unrelated": {"canonical_field": "should_not_be_read"},
    }

    assert canonical_fields_from_profile(field_profile) == [
        "net_sales_amount",
        "order_date",
    ]


def test_build_schema_fingerprint_is_sorted_unique_and_stable():
    first_profile = {
        "mappings": {
            "金额": {"canonical_field": "net_sales_amount"},
            "日期": {"canonical_field": "order_date"},
            "门店": {"canonical_field": "store_name"},
            "重复日期": {"canonical_field": "order_date"},
        }
    }
    second_profile = {
        "mappings": {
            "门店": {"canonical_field": "store_name"},
            "日期": {"canonical_field": "order_date"},
            "金额": {"canonical_field": "net_sales_amount"},
        }
    }

    first_fingerprint, first_detail = build_schema_fingerprint(
        first_profile,
        context_pack_name="Retail Operations",
        context_pack_version="1.0.0",
    )
    second_fingerprint, second_detail = build_schema_fingerprint(
        second_profile,
        context_pack_name="Retail Operations",
        context_pack_version="1.0.0",
    )

    assert first_fingerprint == (
        "v1:2eabfed91d1e9ed70a7a74f527bc4d54dc89e16151ab2e1b5394041cb73d061d"
    )
    assert first_fingerprint == second_fingerprint
    assert first_detail["canonical_fields"] == [
        "net_sales_amount",
        "order_date",
        "store_name",
    ]
    assert first_detail == second_detail


def test_build_schema_fingerprint_records_founding_pack_identity():
    fingerprint, detail = build_schema_fingerprint(
        {"mappings": {"日期": {"canonical_field": "order_date"}}},
        context_pack_name="Founding Pack",
        context_pack_version="2.3.4-local.5",
    )

    assert fingerprint == "v1:02b92c6592372f4353c30d10e1fe899d5ae913717ccb51b88be80533f576f78d"
    assert detail == {
        "version": 1,
        "canonical_fields": ["order_date"],
        "computed_with_pack": {"name": "Founding Pack", "version": "2.3.4-local.5"},
    }
