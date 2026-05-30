from dataclasses import asdict, dataclass, field
from typing import Any, Literal

import pandas as pd

DataSourceType = Literal["csv", "xlsx", "mysql", "postgres"]


@dataclass(frozen=True)
class DataSourceRef:
    id: str
    type: DataSourceType
    name: str
    location: str
    selected_sheet: str | None = None
    credentials_ref: str | None = None


@dataclass(frozen=True)
class WorkbookSheet:
    name: str
    visible: bool
    empty: bool
    selected: bool = False


@dataclass(frozen=True)
class ColumnSummary:
    name: str
    data_type: str
    nullable: bool
    sample_values: list[Any]
    distinct_count: int
    min_value: Any = None
    max_value: Any = None


@dataclass(frozen=True)
class SchemaSummary:
    tables: list[dict[str, Any]]
    columns: list[ColumnSummary]
    row_count_estimate: int


@dataclass(frozen=True)
class PreviewData:
    head: list[dict[str, Any]]
    tail: list[dict[str, Any]]


@dataclass(frozen=True)
class TableData:
    data_source_ref: DataSourceRef
    dataframe: pd.DataFrame = field(repr=False)
    schema_summary: SchemaSummary
    preview: PreviewData
    workbook_sheets: list[WorkbookSheet]
    selected_sheet: str | None = None

    @property
    def row_count(self) -> int:
        return int(len(self.dataframe.index))

    @property
    def column_count(self) -> int:
        return int(len(self.dataframe.columns))


def dataclass_to_dict(value: Any) -> Any:
    return asdict(value)
