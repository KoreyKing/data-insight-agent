from fastapi import APIRouter, Depends

from app.api import context_pack, datasets, feedback, llm_config, reports, tasks, uploads
from app.api.request_validation import reject_unencodable_body

# 请求体边界校验挂在路由器上，覆盖全部 /api/v1/* 端点（含日后新增的）。
api_router = APIRouter(prefix="/api/v1", dependencies=[Depends(reject_unencodable_body)])
api_router.include_router(llm_config.router)
api_router.include_router(context_pack.router)
api_router.include_router(uploads.router)
api_router.include_router(tasks.router)
api_router.include_router(reports.router)
api_router.include_router(feedback.router)
api_router.include_router(datasets.router)
