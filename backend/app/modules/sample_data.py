from pathlib import Path

from app.modules.file_ingestion import load_table_from_path
from app.modules.schemas import TableData

SAMPLE_DATA_PATH = Path(__file__).resolve().parents[1] / "sample_data" / "retail_sales_orders.csv"


def load_retail_sample() -> TableData:
    return load_table_from_path(
        SAMPLE_DATA_PATH,
        original_filename="retail_sales_orders.csv",
        source_id="sample-retail",
    )
