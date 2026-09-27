# Backend API image (FastAPI + agent pipeline). Build context: repository root.
#   docker build -t utechia-backend .
# Runs: uvicorn backend.main:app on port 8000. Health check: GET /health.
# Migrations/import (one-off): alembic upgrade head && python -m backend.legacy_import

FROM ghcr.io/astral-sh/uv:0.9 AS uv

FROM python:3.13-slim-bookworm AS base
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    HF_HOME=/opt/hf-cache \
    PATH=/opt/venv/bin:$PATH
# Docling's PDF/image stack needs these shared libraries at runtime.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app

# ---- dependencies (cached until pyproject.toml / uv.lock change) ----------
FROM base AS deps
COPY --from=uv /uv /usr/local/bin/uv
COPY pyproject.toml uv.lock ./
# --locked: fail instead of silently re-resolving; CPU-only torch on Linux.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# ---- runtime ---------------------------------------------------------------
FROM base AS runtime
COPY --from=deps /opt/venv /opt/venv
COPY alembic.ini ./
COPY src ./src
COPY pipeline ./pipeline
COPY generator ./generator
# Source data: taxonomy, proficiency scale, GitHub corpus, resumes, evidence,
# seed projects. Uploads and run artifacts are excluded by .dockerignore.
COPY data ./data
ENV PYTHONPATH=/app/src:/app \
    STORAGE_ROOT=/app/data/uploads

# Bake the PDF layout model into the image so tasks do not download it on
# every cold start (converting one bundled resume fetches exactly what is used).
RUN for attempt in 1 2 3 4 5; do \
        python -c "from src.profile_agent.pdf_extractor import extract_resume; extract_resume('data/resumes/rendered/applicant0001.pdf')" \
        && break; \
        [ "$attempt" = 5 ] && exit 1; echo "model download failed, retrying"; sleep 10; \
    done \
    && useradd --system --uid 10001 --home-dir /app app \
    && mkdir -p /app/data/uploads \
    && chown -R app:app /app/data /opt/hf-cache

# The GitHub collector caches API responses under /app/.cache (ephemeral).
RUN mkdir -p /app/.cache && chown app:app /app/.cache

# Use only the baked model; never reach Hugging Face from a running task.
ENV HF_HUB_OFFLINE=1
USER app
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=4).status == 200 else 1)"
# One worker per task: scale with ECS task count. Background pipeline jobs run
# in this process, so a larger task (CPU/RAM) matters more than more workers.
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
