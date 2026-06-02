from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi.responses import JSONResponse

from app.modules.file_ingestion import IngestionError, load_table_from_path
from app.modules.sample_data import load_retail_sample

DATA_DIR = (
    Path("/app/data") if Path("/app").exists() else Path(__file__).resolve().parents[3] / "data"
)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_SESSIONS: dict[str, dict[str, str]] = {}


def resolve_table(data_source_ref: dict[str, Any]):
    source_id = str(data_source_ref.get("id") or "sample-retail")
    selected_sheet = data_source_ref.get("selected_sheet")
    if source_id == "sample-retail":
        return load_retail_sample()

    session = UPLOAD_SESSIONS.get(source_id)
    if session is None:
        raise IngestionError("UPLOAD_NOT_FOUND", "未找到上传 session，请重新上传文件。")

    return load_table_from_path(
        Path(session["path"]),
        original_filename=session["filename"],
        selected_sheet=selected_sheet,
        source_id=source_id,
    )


def sanitize_filename(filename: str) -> str:
    return Path(filename).name.replace("/", "_").replace("\\", "_")


def error_response(exc: IngestionError) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={"code": exc.code, "message": exc.message, "details": exc.details},
    )
