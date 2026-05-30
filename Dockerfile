# syntax=docker/dockerfile:1
# 单容器：构建前端静态产物，由后端 FastAPI 一并托管（API + 前端同在 8000）。
# 构建上下文 = 仓库根目录。

# ---- stage 1: 构建前端 ----
FROM node:20-alpine AS frontend
WORKDIR /frontend
RUN npm install -g pnpm@9.15.9
COPY frontend/package.json frontend/pnpm-lock.yaml* ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# ---- stage 2: 后端 + 前端 dist ----
FROM python:3.11-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
RUN pip install --no-cache-dir uv
COPY backend/pyproject.toml backend/uv.lock* ./
RUN uv sync --no-dev
COPY backend/app ./app
COPY --from=frontend /frontend/dist ./frontend/dist
EXPOSE 8000
CMD ["/app/.venv/bin/uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
