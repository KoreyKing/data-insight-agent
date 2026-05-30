from pathlib import Path

import pytest

from app.modules.dataset_store import materialize_table_to_sqlite
from app.modules.file_ingestion import load_table_from_path
from app.modules.query_engine import run_validated_query
from app.modules.sample_data import load_retail_sample
from app.modules.sql_validator import SQLValidationError


def test_query_engine_returns_rows_and_execution_metadata_for_sample_dataset():
    handle = materialize_table_to_sqlite(load_retail_sample())

    result = run_validated_query(
        handle,
        """
        SELECT store_name, SUM(net_sales_amount) AS sales
        FROM sales_orders
        WHERE order_status IN ('completed', 'partial_refund')
        GROUP BY store_name
        ORDER BY sales DESC
        LIMIT 5;
        """,
    )

    assert result.columns == ["store_name", "sales"]
    assert 1 <= result.row_count <= 5
    assert isinstance(result.rows[0][0], str)
    assert result.rows[0][1] > 0
    assert result.exec_ms >= 0
    assert result.sql.startswith("SELECT")


def test_materialized_dataset_uses_canonical_columns_for_chinese_upload(tmp_path: Path):
    source = tmp_path / "orders.csv"
    source.write_text(
        "订单日期,销售额,门店,商品类目,渠道,订单状态\n"
        "2026-05-01,1000,上海徐汇旗舰店,服装,线下,completed\n"
        "2026-05-02,500,上海徐汇旗舰店,服装,天猫,partial_refund\n",
        encoding="utf-8",
    )
    table = load_table_from_path(source, original_filename="orders.csv", source_id="upload-1")
    handle = materialize_table_to_sqlite(table)

    result = run_validated_query(
        handle,
        """
        SELECT store_name, SUM(net_sales_amount) AS sales
        FROM sales_orders
        WHERE order_date >= '2026-05-01'
        GROUP BY store_name
        LIMIT 10;
        """,
    )

    assert result.columns == ["store_name", "sales"]
    assert result.rows == [["上海徐汇旗舰店", 1500]]
    assert [column.name for column in handle.schema_summary.columns] == [
        "order_date",
        "net_sales_amount",
        "store_name",
        "category_l1",
        "channel",
        "order_status",
        "order_id",
    ]


def test_query_engine_rejects_invalid_sql_before_execution():
    handle = materialize_table_to_sqlite(load_retail_sample())

    with pytest.raises(SQLValidationError) as exc_info:
        run_validated_query(handle, "DELETE FROM sales_orders")

    assert exc_info.value.code == "SQL_VALIDATOR_REJECTED"
