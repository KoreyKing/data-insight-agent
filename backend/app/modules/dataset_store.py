from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import pandas as pd

from app.modules.field_mapping import build_field_profile
from app.modules.file_ingestion import build_schema_summary
from app.modules.schemas import DataSourceRef, SchemaSummary, TableData

CANONICAL_TABLE_NAME = "sales_orders"


@dataclass(frozen=True)
class DatasetHandle:
    connection: sqlite3.Connection
    table_name: str
    schema_summary: SchemaSummary
    data_source_ref: DataSourceRef
    row_count: int


class DatasetMaterializationError(ValueError):
    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def materialize_table_to_sqlite(table: TableData) -> DatasetHandle:
    dataframe = canonicalize_for_query(table)
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    dataframe.to_sql(CANONICAL_TABLE_NAME, connection, if_exists="replace", index=False)

    return DatasetHandle(
        connection=connection,
        table_name=CANONICAL_TABLE_NAME,
        schema_summary=build_schema_summary(dataframe),
        data_source_ref=table.data_source_ref,
        row_count=int(len(dataframe.index)),
    )


def canonicalize_for_query(table: TableData) -> pd.DataFrame:
    profile = build_field_profile(table.schema_summary)
    if not profile.is_valid:
        missing = " / ".join(profile.missing_key_fields)
        raise DatasetMaterializationError("CSV_KEY_FIELD_MISSING", f"缺少关键字段：{missing}")

    canonical = pd.DataFrame()
    for mapping in profile.mappings.values():
        if mapping.canonical_field in canonical.columns:
            continue
        canonical[mapping.canonical_field] = table.dataframe[mapping.source_column]

    if "order_status" not in canonical.columns:
        canonical["order_status"] = "completed"
    if "order_id" not in canonical.columns:
        canonical["order_id"] = [f"row-{index}" for index in canonical.index]

    return canonical
