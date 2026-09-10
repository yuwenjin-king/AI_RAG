# 企业级 RAG 平台 backend 镜像
FROM python:3.11-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# apt 源切 https：明文 http 经本机代理（fake-ip 网关）时大文件常 502、
# release 签名也可被中间层破坏（trixie-security InRelease 报未签名即此类）；
# https 走 CONNECT 隧道穿透代理，与 pip 同路径（pip 默认 https 一直稳定）。
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' \
        /etc/apt/sources.list.d/debian.sources 2>/dev/null || true \
    && apt-get update && apt-get install -y --no-install-recommends \
        build-essential libpq-dev curl \
    && rm -rf /var/lib/apt/lists/*

# dev 目标：装全部依赖（含 dev extras）
# PIP_INDEX_URL：可选 pip 镜像源（如清华 https://pypi.tuna.tsinghua.edu.cn/simple），
# 经 compose build.args / .env 注入；默认官方源。弱网/代理环境冷构建差一个数量级。
FROM base AS dev
ARG PIP_INDEX_URL=""
COPY . .
RUN pip install --index-url "${PIP_INDEX_URL:-https://pypi.org/simple}" --upgrade pip \
    && pip install --index-url "${PIP_INDEX_URL:-https://pypi.org/simple}" -e ".[dev]"
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# prod 目标：仅运行时依赖
FROM base AS prod
ARG PIP_INDEX_URL=""
COPY . .
RUN pip install --index-url "${PIP_INDEX_URL:-https://pypi.org/simple}" --upgrade pip \
    && pip install --index-url "${PIP_INDEX_URL:-https://pypi.org/simple}" .
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
