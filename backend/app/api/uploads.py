from __future__ import annotations

from pathlib import Path
from shutil import copyfileobj
from typing import Annotated, Any
from uuid import uuid4

from fastapi import APIRouter, File, UploadFile
from fastapi.responses import JSONResponse

from app.api.runtime import (
    UPLOAD_DIR,
    UPLOAD_SESSIONS,
    error_response,
    sanitize_filename,
)
from app.modules.file_ingestion import IngestionError, load_table_from_path, table_to_response
from app.modules.sample_data import load_retail_sample

router = APIRouter()
UPLOAD_FILE = File(...)


@router.get("/sample-dataset")
def sample_dataset() -> dict[str, Any]:
    table = load_retail_sample()
    return table_to_response(table)


@router.post("/uploads")
def upload_dataset(file: Annotated[UploadFile, UPLOAD_FILE]):
    session_id = uuid4().hex
    session_dir = UPLOAD_DIR / session_id
    session_dir.mkdir(parents=True, exist_ok=True)
    filename = sanitize_filename(file.filename or "upload")
    destination = session_dir / filename

    with destination.open("wb") as file_handle:
        copyfileobj(file.file, file_handle)

    try:
        table = load_table_from_path(destination, original_filename=filename, source_id=session_id)
    except IngestionError as exc:
        return error_response(exc)

    UPLOAD_SESSIONS[session_id] = {"path": str(destination), "filename": filename}
    payload = table_to_response(table)
    payload["session_id"] = session_id
    return payload


@router.get("/uploads/{session_id}")
def uploaded_dataset(session_id: str, sheet: str | None = None):
    session = UPLOAD_SESSIONS.get(session_id)
    if session is None:
        return JSONResponse(
            status_code=404,
            content={"code": "UPLOAD_NOT_FOUND", "message": "未找到上传 session，请重新上传文件。"},
        )

    try:
        table = load_table_from_path(
            Path(session["path"]),
            original_filename=session["filename"],
            selected_sheet=sheet,
            source_id=session_id,
        )
    except IngestionError as exc:
        return error_response(exc)

    payload = table_to_response(table)
    payload["session_id"] = session_id
    return payload
