# AgentHowl 单镜像：前端静态文件由后端 uvicorn 同端口托管（create_app 在 /app/frontend/dist 存在时自动挂载）。
# 对局 / 档案 / Provider 密钥 / 跨局记忆都在 /app/backend/data，用 volume 留在宿主机。

# ---- 阶段 1：前端构建 ----
FROM node:20-alpine AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 阶段 2：后端运行时 ----
FROM python:3.11-slim AS runtime
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /uvx /bin/

ENV PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/backend/.venv

WORKDIR /app/backend
# 先装依赖再拷源码，源码改动不重装
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project --extra bedrock
COPY backend/ ./
RUN uv sync --frozen --no-dev --extra bedrock

# 前端产物放到 create_app 默认查找的位置（<repo>/frontend/dist）
COPY --from=frontend /src/frontend/dist /app/frontend/dist

# 非 root 运行；data 目录归属运行用户，Provider 密钥文件按 0600 写入
RUN useradd --create-home --uid 10001 agenthowl \
    && mkdir -p /app/backend/data \
    && chown -R agenthowl:agenthowl /app
USER agenthowl

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/v1/presets', timeout=4).status == 200 else 1)"]

# 单 worker：对局与 token 在进程内存里，多 worker 会互相看不见
CMD ["uv", "run", "--no-sync", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
