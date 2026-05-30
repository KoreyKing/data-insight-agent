import pytest

from app.modules.schemas import ColumnSummary, SchemaSummary
from app.modules.sql_validator import SQLValidationError, validate_select_sql


def schema_summary() -> SchemaSummary:
    columns = [
        ColumnSummary("order_id", "string", False, ["ORD-1"], 1),
        ColumnSummary("order_date", "date", False, ["2026-05-01"], 1),
        ColumnSummary("store_name", "category", False, ["上海徐汇旗舰店"], 1),
        ColumnSummary("category_l1", "category", False, ["服装"], 1),
        ColumnSummary("channel", "category", False, ["线下"], 1),
        ColumnSummary("net_sales_amount", "number", False, [1000], 1),
        ColumnSummary("order_status", "category", False, ["completed"], 1),
    ]
    return SchemaSummary(
        tables=[
            {
                "name": "sales_orders",
                "columns": [column.__dict__ for column in columns],
                "row_count_estimate": 1,
            }
        ],
        columns=columns,
        row_count_estimate=1,
    )


def assert_rejected(sql: str) -> None:
    with pytest.raises(SQLValidationError) as exc_info:
        validate_select_sql(sql, schema_summary())
    assert exc_info.value.code == "SQL_VALIDATOR_REJECTED"


def test_accepts_aggregate_select_with_case_grouping_and_output_alias_ordering():
    sql = """
    SELECT store_name,
      SUM(CASE WHEN order_status IN ('completed', 'partial_refund')
        THEN net_sales_amount ELSE 0 END) AS sales_current
    FROM sales_orders
    WHERE order_date >= '2026-05-01'
    GROUP BY store_name
    ORDER BY sales_current ASC
    LIMIT 100;
    """

    result = validate_select_sql(sql, schema_summary())

    assert result.original_sql == sql
    assert "SUM(CASE" in result.executable_sql
    assert "ORDER BY sales_current" in result.executable_sql
    assert result.warnings == []


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO sales_orders (store_name) VALUES ('x')",
        "UPDATE sales_orders SET store_name = 'x'",
        "DELETE FROM sales_orders",
        "DROP TABLE sales_orders",
        "ALTER TABLE sales_orders ADD COLUMN x TEXT",
        "CREATE TABLE audit_log (id TEXT)",
        "PRAGMA table_info(sales_orders)",
        "ATTACH DATABASE 'other.db' AS other",
    ],
)
def test_rejects_non_select_or_dangerous_statements(sql: str):
    assert_rejected(sql)


def test_rejects_multiple_statements():
    assert_rejected("SELECT store_name FROM sales_orders LIMIT 10; SELECT 1;")


def test_rejects_unknown_table():
    assert_rejected("SELECT store_name FROM raw_orders LIMIT 10")


def test_rejects_unknown_column():
    assert_rejected("SELECT store_name, secret_margin FROM sales_orders LIMIT 10")


def test_rejects_top_level_select_star_but_allows_count_star():
    assert_rejected("SELECT * FROM sales_orders LIMIT 10")

    result = validate_select_sql(
        "SELECT COUNT(*) AS orders FROM sales_orders WHERE order_date >= '2026-05-01'",
        schema_summary(),
    )

    assert "COUNT(*)" in result.executable_sql
    assert "LIMIT 10000" in result.executable_sql


def test_non_aggregate_without_where_or_limit_auto_adds_limit():
    result = validate_select_sql("SELECT store_name FROM sales_orders", schema_summary())

    assert result.executable_sql.rstrip(";").endswith("LIMIT 10000")
    assert result.warnings == ["SQL_LIMIT_ADDED"]


def test_non_aggregate_join_without_where_or_limit_auto_adds_limit():
    sql = """
    WITH current_week AS (
      SELECT store_name, SUM(net_sales_amount) AS sales_current
      FROM sales_orders
      WHERE order_date BETWEEN '2026-05-16' AND '2026-05-22'
      GROUP BY store_name
    ),
    previous_week AS (
      SELECT store_name, SUM(net_sales_amount) AS sales_previous
      FROM sales_orders
      WHERE order_date BETWEEN '2026-05-09' AND '2026-05-15'
      GROUP BY store_name
    )
    SELECT current_week.store_name, current_week.sales_current, previous_week.sales_previous
    FROM current_week
    JOIN previous_week ON current_week.store_name = previous_week.store_name
    """
    result = validate_select_sql(sql, schema_summary())

    assert result.executable_sql.rstrip(";").endswith("LIMIT 10000")
    assert result.warnings == ["SQL_LIMIT_ADDED"]


def test_adds_default_limit_when_where_is_present_without_limit():
    result = validate_select_sql(
        "SELECT store_name FROM sales_orders WHERE order_date >= '2026-05-01'",
        schema_summary(),
    )

    assert result.executable_sql.endswith("LIMIT 10000")
    assert result.warnings == ["SQL_LIMIT_ADDED"]


def test_clamps_limit_above_max_rows():
    result = validate_select_sql(
        "SELECT store_name FROM sales_orders WHERE order_date >= '2026-05-01' LIMIT 99999",
        schema_summary(),
    )

    assert result.executable_sql.endswith("LIMIT 10000")
    assert result.warnings == ["SQL_LIMIT_CLAMPED"]


def test_allows_cte_referencing_sales_orders_and_outer_alias():
    sql = """
    WITH week_window AS (
      SELECT MAX(order_date) AS latest FROM sales_orders
    )
    SELECT store_name, SUM(net_sales_amount) AS sales
    FROM sales_orders, week_window
    WHERE order_date BETWEEN date(week_window.latest, '-6 days') AND week_window.latest
    GROUP BY store_name
    ORDER BY sales DESC
    LIMIT 10
    """
    result = validate_select_sql(sql, schema_summary())
    assert "WITH" in result.executable_sql.upper()
    assert "week_window" in result.executable_sql.lower()


def test_rejects_select_star_inside_cte():
    assert_rejected(
        """
        WITH all_orders AS (SELECT * FROM sales_orders)
        SELECT store_name FROM all_orders LIMIT 10
        """
    )


def test_aggregate_without_where_auto_adds_limit():
    result = validate_select_sql(
        "SELECT store_name, SUM(net_sales_amount) AS sales FROM sales_orders GROUP BY store_name",
        schema_summary(),
    )
    assert result.executable_sql.rstrip(";").endswith("LIMIT 10000")
    assert result.warnings == ["SQL_LIMIT_ADDED"]


def test_top_level_aggregate_function_without_where_or_group_is_allowed():
    result = validate_select_sql(
        "SELECT MAX(order_date) AS latest FROM sales_orders",
        schema_summary(),
    )
    assert "MAX" in result.executable_sql
    assert result.warnings == ["SQL_LIMIT_ADDED"]


def test_allows_having_alias_reference():
    sql = """
    SELECT store_name, SUM(net_sales_amount) AS sales
    FROM sales_orders
    WHERE order_status IN ('completed','partial_refund')
    GROUP BY store_name
    HAVING sales > 1000
    LIMIT 10
    """
    result = validate_select_sql(sql, schema_summary())
    assert "HAVING" in result.executable_sql.upper()
