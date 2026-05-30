from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from typing import Any

from app.modules.dataset_store import DatasetHandle
from app.modules.sql_validator import SQLValidationError, validate_select_sql


@dataclass(frozen=True)
class QueryResult:
    columns: list[str]
    rows: list[list[Any]]
    row_count: int
    exec_ms: int
    sql: str


def run_validated_query(handle: DatasetHandle, sql: str) -> QueryResult:
    validated = validate_select_sql(sql, handle.schema_summary)
    connection = handle.connection
    connection.set_authorizer(read_only_authorizer)
    started = time.perf_counter()
    try:
        cursor = connection.execute(validated.executable_sql)
        records = cursor.fetchall()
    except sqlite3.DatabaseError as exc:
        raise SQLValidationError("SQL 执行前校验失败") from exc
    finally:
        connection.set_authorizer(None)

    exec_ms = int((time.perf_counter() - started) * 1000)
    columns = [description[0] for description in cursor.description or []]
    rows = [[normalize_sqlite_value(value) for value in row] for row in records]
    return QueryResult(
        columns=columns,
        rows=rows,
        row_count=len(rows),
        exec_ms=exec_ms,
        sql=validated.executable_sql,
    )


def read_only_authorizer(
    action_code: int,
    _arg1: str | None,
    _arg2: str | None,
    _database_name: str | None,
    _trigger_or_view: str | None,
) -> int:
    allowed = {
        sqlite3.SQLITE_SELECT,
        sqlite3.SQLITE_READ,
        sqlite3.SQLITE_FUNCTION,
    }
    return sqlite3.SQLITE_OK if action_code in allowed else sqlite3.SQLITE_DENY


def normalize_sqlite_value(value: Any) -> Any:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value
