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
    assert qa["schema_version"] == 2
    assert qa["fixture_id"] == "period1"
    assert qa["order_count_rule"] == ["completed", "partial_refund"]
    assert set(qa["core_kpis"]["current"]) == {
        "sales_amount",
        "order_count",
        "average_order_value",
        "refund_rate",
    }
    assert set(qa["core_kpis"]["previous"]) == set(qa["core_kpis"]["current"])
    assert qa["checks"]["row_count_in_range"] is True
    assert qa["checks"]["required_columns_present"] is True
    assert qa["checks"]["sh001_sales_drop"] is True
    assert qa["checks"]["kids_refund_spike"] is True
    assert qa["checks"]["douyin_aov_drop_with_order_lift"] is True
    assert qa["checks"]["weekend_effect"] is True
    assert qa["checks"]["returning_customer_share_lift"] is True


def test_order_count_uses_completed_and_partial_refund_only():
    module = load_generator_module()
    frame = pd.DataFrame(
        [
            {"order_id": "completed", "order_status": "completed"},
            {"order_id": "partial", "order_status": "partial_refund"},
            {"order_id": "refunded", "order_status": "refunded"},
        ]
    )

    assert module.order_count(frame) == 2


def test_generate_period2_fixture_is_additive_and_advances_exactly_one_week(tmp_path: Path):
    module = load_generator_module()
    period1_dir = tmp_path / "period1"
    period1_qa_path = tmp_path / "period1.qa.json"
    period2_dir = tmp_path / "period2"

    period1_result = module.generate_sample_data(
        output_dir=period1_dir,
        qa_path=period1_qa_path,
    )
    period2_result = module.generate_period2_fixture(output_dir=period2_dir)

    period1 = pd.read_csv(period1_result["csv_path"])
    period2 = pd.read_csv(period2_result["csv_path"])
    period2_qa = json.loads(Path(period2_result["qa_path"]).read_text(encoding="utf-8"))

    assert period2.columns.tolist() == period1.columns.tolist()
    assert pd.to_datetime(period2["order_date"]).max() == (
        pd.to_datetime(period1["order_date"]).max() + pd.Timedelta(days=7)
    )
    pd.testing.assert_frame_equal(
        period2.iloc[: len(period1.index)].reset_index(drop=True),
        period1.reset_index(drop=True),
        check_dtype=False,
    )
    assert period2_qa["schema_version"] == 2
    assert period2_qa["fixture_id"] == "period2"
    assert period2_qa["windows"]["previous"] == period1_qa_path_data(period1_qa_path)[
        "windows"
    ]["current"]
    assert period2_qa["checks"]["sh001_sales_drop"] is True
    assert period2_qa["checks"]["kids_refund_spike"] is True
    assert period2_qa["checks"]["douyin_aov_drop_with_order_lift"] is True


def period1_qa_path_data(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_zh_header_fixture_is_period1_with_display_name_headers(tmp_path: Path):
    """capture 用例数据（§7 v0.13）：表头为内置口径 display_name，数据与 KPI 基准同 period1。"""
    module = load_generator_module()
    backend_dir = Path(__file__).resolve().parents[1]

    result = module.generate_zh_header_fixture(output_dir=tmp_path)

    zh = pd.read_csv(result["csv_path"])
    qa = json.loads(Path(result["qa_path"]).read_text(encoding="utf-8"))
    display_names = module.builtin_display_names()
    assert zh.columns.tolist() == [display_names[column] for column in module.COLUMNS]
    sample = pd.read_csv(backend_dir / "app" / "sample_data" / "retail_sales_orders.csv")
    renamed_back = zh.rename(columns={value: key for key, value in display_names.items()})
    pd.testing.assert_frame_equal(renamed_back, sample)

    period1_qa = json.loads((backend_dir / ".sample-data-qa.json").read_text(encoding="utf-8"))
    assert qa["fixture_id"] == "period1-zh"
    assert qa["header_variant"] == "display_name"
    assert qa["core_kpis"] == period1_qa["core_kpis"]
    assert qa["windows"] == period1_qa["windows"]
    assert all(qa["checks"].values())

    committed = backend_dir / "eval" / "fixtures" / "retail_sales_orders_zh.csv"
    assert Path(result["csv_path"]).read_bytes() == committed.read_bytes()
    assert Path(result["qa_path"]).read_bytes() == committed.with_suffix(".qa.json").read_bytes()
