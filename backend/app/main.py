from dataclasses import asdict
from pathlib import Path
from shutil import copyfileobj
from typing import Annotated, Any
from uuid import uuid4

from fastapi import FastAPI, File, UploadFile
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from app.config import get_settings
from app.llm.client import get_llm_client
from app.modules.analysis_loop import run_analysis_loop
from app.modules.context_pack import load_default_context_pack
from app.modules.file_ingestion import IngestionError, load_table_from_path, table_to_response
from app.modules.reporting import default_structured_task, generate_traceable_report
from app.modules.sample_data import load_retail_sample
from app.modules.task_parser import parse_analysis_goal

app = FastAPI(title="Data Insight Agent", version="0.1.0")

DATA_DIR = (
    Path("/app/data") if Path("/app").exists() else Path(__file__).resolve().parents[2] / "data"
)
UPLOAD_DIR = DATA_DIR / "uploads"
UPLOAD_SESSIONS: dict[str, dict[str, str]] = {}
UPLOAD_FILE = File(...)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/model-status")
def model_status() -> dict[str, Any]:
    settings = get_settings()
    if not settings.is_llm_configured:
        return {"status": "not_configured"}
    return {
        "status": "configured",
        "model": settings.llm_model,
        "provider": settings.normalized_provider,
    }


@app.get("/api/v1/sample-dataset")
def sample_dataset() -> dict[str, Any]:
    table = load_retail_sample()
    return table_to_response(table)


@app.post("/api/v1/uploads")
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


@app.get("/api/v1/uploads/{session_id}")
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


@app.post("/api/v1/tasks/parse")
def parse_task(payload: dict[str, Any]) -> dict[str, Any]:
    analysis_goal = str(payload.get("analysis_goal") or "帮我生成周度经营复盘")
    data_source_ref = payload.get("data_source_ref") or {
        "id": "sample-retail",
        "type": "csv",
        "name": "retail_sales_orders.csv",
        "location": "sample",
    }
    try:
        table = resolve_table(data_source_ref)
    except IngestionError as exc:
        return error_response(exc)

    result = parse_analysis_goal(
        analysis_goal,
        asdict(table.data_source_ref),
        table.schema_summary,
    )
    # Expose the Context Pack dimension catalog (Chinese name + description) so the
    # frontend "添加维度" dropdown can offer human-readable dimensions.
    context_pack = load_default_context_pack()
    result["dimension_options"] = [
        {"name": dimension.get("name"), "description": dimension.get("description")}
        for dimension in context_pack.get("dimensions", [])
        if dimension.get("name")
    ]
    return result


@app.post("/api/v1/reports/run")
def run_report(payload: dict[str, Any]):
    analysis_goal = str(payload.get("analysis_goal") or "帮我生成周度经营复盘")
    data_source_ref = payload.get("data_source_ref") or {}

    try:
        table = resolve_table(data_source_ref)
    except IngestionError as exc:
        return error_response(exc)

    settings = get_settings()
    llm_client = get_llm_client(settings)
    if llm_client is None:
        report = generate_traceable_report(table, analysis_goal)
    else:
        report = run_analysis_loop(
            table,
            task_from_payload(payload, analysis_goal, asdict(table.data_source_ref)),
            llm_client,
            model_name=settings.llm_model,
        )
    if report.get("status") == "failed":
        return JSONResponse(
            status_code=400,
            content={"code": "CSV_KEY_FIELD_MISSING", "report": report},
        )
    return {"report": report}


def task_from_payload(
    payload: dict[str, Any],
    analysis_goal: str,
    data_source_ref: dict[str, Any],
) -> dict[str, Any]:
    task = default_structured_task(analysis_goal, data_source_ref)
    incoming = payload.get("task")
    if not isinstance(incoming, dict):
        return task

    for key, value in incoming.items():
        if key == "execution_limits" and isinstance(value, dict):
            task[key] = {**task[key], **value}
        else:
            task[key] = value
    task["analysis_goal"] = analysis_goal
    task["data_source_ref"] = data_source_ref
    return task


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


# 单容器部署时托管已构建的前端静态产物（SPA：未命中路由回落 index.html）。
# 挂载在所有 API 路由注册之后，/health 与 /api/v1/* 精确路由优先匹配。
# 本地开发时 dist 不存在，自动跳过，仍走 Vite dev server + 代理。
_frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
