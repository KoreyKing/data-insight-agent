from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from app.api import api_router
from app.db.engine import init_db


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    init_db()
    yield


app = FastAPI(title="Data Insight Agent", version="0.1.0", lifespan=lifespan)
app.include_router(api_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# 单容器部署时托管已构建的前端静态产物（SPA：未命中路由回落 index.html）。
# 挂载在所有 API 路由注册之后，/health 与 /api/v1/* 精确路由优先匹配。
# 本地开发时 dist 不存在，自动跳过，仍走 Vite dev server + 代理。
_frontend_dist = Path(__file__).resolve().parents[1] / "frontend" / "dist"
if _frontend_dist.is_dir():
    app.mount("/", StaticFiles(directory=str(_frontend_dist), html=True), name="frontend")
