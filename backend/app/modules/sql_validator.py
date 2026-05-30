from __future__ import annotations

from dataclasses import dataclass

from sqlglot import errors as sqlglot_errors
from sqlglot import exp, parse

from app.modules.schemas import SchemaSummary

DEFAULT_MAX_ROWS = 10000
DEFAULT_TABLE = "sales_orders"


@dataclass(frozen=True)
class ValidatedSQL:
    original_sql: str
    executable_sql: str
    warnings: list[str]


class SQLValidationError(ValueError):
    def __init__(self, message: str):
        self.code = "SQL_VALIDATOR_REJECTED"
        self.message = message
        super().__init__(message)


def validate_select_sql(
    sql: str,
    schema_summary: SchemaSummary,
    *,
    max_rows: int = DEFAULT_MAX_ROWS,
) -> ValidatedSQL:
    expression = parse_single_select(sql)
    validate_tables(expression, schema_summary)
    validate_projection(expression)
    validate_columns(expression, schema_summary)
    executable_sql, warnings = apply_limit_policy(expression, max_rows)
    return ValidatedSQL(original_sql=sql, executable_sql=executable_sql, warnings=warnings)


def parse_single_select(sql: str) -> exp.Select:
    try:
        expressions = [
            item for item in parse(sql, read="sqlite") if not isinstance(item, exp.Semicolon)
        ]
    except sqlglot_errors.ParseError as exc:
        raise SQLValidationError("SQL 语法无法解析") from exc

    if len(expressions) != 1 or not isinstance(expressions[0], exp.Select):
        raise SQLValidationError("仅允许单条 SELECT 查询")
    return expressions[0]


def validate_tables(expression: exp.Select, schema_summary: SchemaSummary) -> None:
    allowed_tables = table_names(schema_summary) | cte_aliases(expression)
    tables = list(expression.find_all(exp.Table))
    if not tables:
        raise SQLValidationError("查询必须引用数据表")

    for table in tables:
        if normalize(table.name) not in allowed_tables:
            raise SQLValidationError(f"未知数据表：{table.name}")


def validate_projection(expression: exp.Select) -> None:
    # CTE 内部子 SELECT 同样禁止顶层 SELECT *，由 find_all 统一覆盖
    for select in expression.find_all(exp.Select):
        for projection in select.expressions:
            if isinstance(projection, exp.Star):
                raise SQLValidationError("不允许顶层 SELECT *")
            if isinstance(projection, exp.Column) and isinstance(projection.this, exp.Star):
                raise SQLValidationError("不允许顶层 SELECT *")


def validate_columns(expression: exp.Select, schema_summary: SchemaSummary) -> None:
    allowed_columns = {normalize(column.name) for column in schema_summary.columns}
    relation_aliases = table_relation_aliases(expression) | cte_aliases(expression)
    # 只收集显式 AS 别名；裸 SELECT col 的 alias_or_name 返回 col 自身，会把任意列误放行
    projection_aliases = {
        normalize(projection.alias_or_name)
        for select in expression.find_all(exp.Select)
        for projection in select.expressions
        if isinstance(projection, exp.Alias)
    }

    for column in expression.find_all(exp.Column):
        if isinstance(column.this, exp.Star):
            continue

        column_name = normalize(column.name)
        table_name = normalize(column.table)
        if table_name and table_name not in relation_aliases:
            raise SQLValidationError(f"未知数据表：{column.table}")

        if column_name in allowed_columns:
            continue
        if column_name in projection_aliases:
            # CTE / ORDER BY / HAVING / 外层 SELECT 引用别名都在这里放行
            continue
        raise SQLValidationError(f"未知字段：{column.name}")


def apply_limit_policy(expression: exp.Select, max_rows: int) -> tuple[str, list[str]]:
    # 任意缺省 LIMIT 的查询都自动补到 max_rows 以圈定结果集，
    # 不再因「非聚合缺 WHERE/LIMIT」硬拒——多 CTE 联接、非聚合带 JOIN
    # 等合法分析查询本就被此处的自动补 LIMIT 圈定，硬拒只会浪费模型轮次。
    warnings: list[str] = []
    limit_value = literal_limit_value(expression)

    executable = expression.copy()
    if limit_value is None:
        executable = executable.limit(max_rows)
        warnings.append("SQL_LIMIT_ADDED")
    elif limit_value > max_rows:
        executable = executable.limit(max_rows)
        warnings.append("SQL_LIMIT_CLAMPED")

    return executable.sql(dialect="sqlite"), warnings


def cte_aliases(expression: exp.Select) -> set[str]:
    return {
        normalize(cte.alias_or_name)
        for cte in expression.find_all(exp.CTE)
        if cte.alias_or_name
    }


def literal_limit_value(expression: exp.Select) -> int | None:
    limit = expression.args.get("limit")
    if limit is None:
        return None
    literal = limit.expression
    if not isinstance(literal, exp.Literal) or literal.is_string:
        raise SQLValidationError("LIMIT 必须是数字常量")
    try:
        value = int(literal.this)
    except (TypeError, ValueError) as exc:
        raise SQLValidationError("LIMIT 必须是数字常量") from exc
    if value < 1:
        raise SQLValidationError("LIMIT 必须大于 0")
    return value


def table_names(schema_summary: SchemaSummary) -> set[str]:
    names = {normalize(table.get("name", "")) for table in schema_summary.tables}
    names.discard("")
    return names or {DEFAULT_TABLE}


def table_relation_aliases(expression: exp.Select) -> set[str]:
    aliases: set[str] = set()
    for table in expression.find_all(exp.Table):
        aliases.add(normalize(table.name))
        aliases.add(normalize(table.alias_or_name))
    aliases.discard("")
    return aliases


def normalize(value: str | None) -> str:
    return (value or "").strip().lower()
