from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pandas as pd


def load_generator_module():
    script_path = Path(__file__).resolve().parents[1] / "scripts" / "generate_sample_data.py"
    spec = importlib.util.spec_from_file_location("generate_sample_data", script_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["generate_sample_data"] = module
    spec.loader.exec_module(module)
    return module


def test_generate_sample_data_creates_quality_checked_csv_and_xlsx(tmp_path: Path):
    module = load_generator_module()
    qa_path = tmp_path / "sample-data-qa.json"

    result = module.generate_sample_data(output_dir=tmp_path, qa_path=qa_path)

    csv_path = Path(result["csv_path"])
    xlsx_path = Path(result["xlsx_path"])
    assert csv_path.exists()
    assert xlsx_path.exists()
    assert qa_path.exists()

    rows = pd.read_csv(csv_path)
    xlsx_rows = pd.read_excel(xlsx_path, sheet_name="sales_orders", engine="openpyxl")
    assert len(rows) == len(xlsx_rows)
    assert 8000 <= len(rows) <= 10000
    assert rows["order_date"].min() == "2026-03-23"
    assert rows["order_date"].max() == "2026-05-17"
    assert rows["store_id"].nunique() >= 12
    assert 80 <= rows["product_id"].nunique() <= 120

    expected_columns = [
        "order_id",
        "order_date",
        "store_id",
        "store_name",
        "product_id",
        "product_name",
        "category_l1",
        "category_l2",
        "channel",
        "customer_type",
        "quantity",
        "gross_sales_amount",
        "discount_amount",
        "net_sales_amount",
        "order_status",
        "refund_amount",
        "unit_cost",
    ]
    assert rows.columns.tolist() == expected_columns

    qa = json.loads(qa_path.read_text(encoding="utf-8"))
    assert qa["checks"]["row_count_in_range"] is True
    assert qa["checks"]["required_columns_present"] is True
    assert qa["checks"]["sh001_sales_drop"] is True
    assert qa["checks"]["kids_refund_spike"] is True
    assert qa["checks"]["douyin_aov_drop_with_order_lift"] is True
    assert qa["checks"]["weekend_effect"] is True
    assert qa["checks"]["returning_customer_share_lift"] is True
