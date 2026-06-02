from fastapi import APIRouter

from app.api import datasets, llm_config, reports, tasks, uploads

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(llm_config.router)
api_router.include_router(uploads.router)
api_router.include_router(tasks.router)
api_router.include_router(reports.router)
api_router.include_router(datasets.router)
