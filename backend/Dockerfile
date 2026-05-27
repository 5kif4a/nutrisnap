# syntax=docker/dockerfile:1.7

# ─── Stage 1: builder ──────────────────────────────────────────────
# uv resolves and installs dependencies into a standalone virtualenv that
# we copy into the runtime stage (multi-stage = smaller final image).
FROM python:3.12.7-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:0.5.0 /uv /uvx /usr/local/bin/

WORKDIR /app

# Cache deps separately from code (Rule 4 — manifests change rarely).
COPY pyproject.toml uv.lock ./

# --no-install-project: install only deps, not the app itself.
# --no-dev: skip dev tools (ruff, pytest) for a leaner runtime image.
RUN --mount=type=cache,id=uv-cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# ─── Stage 2: runtime ──────────────────────────────────────────────
FROM python:3.12.7-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app \
    PATH="/opt/venv/bin:$PATH"

# tini = proper PID 1 — forwards SIGTERM, reaps zombies (Rule 11).
# All in one RUN with cleanup in the same layer (Rule 5).
RUN apt-get update \
    && apt-get install --no-install-recommends -y tini \
    && rm -rf /var/lib/apt/lists/* /var/cache/apt/archives/*

# Non-root user (Rule 9).
RUN groupadd --system --gid 1000 app \
    && useradd --system --uid 1000 --gid app --create-home --home-dir /home/app app

# Copy resolved virtualenv from builder.
COPY --from=builder --chown=app:app /opt/venv /opt/venv

WORKDIR /app

# Copy app code (changes most frequently — last for cache efficiency).
COPY --chown=app:app app ./app
COPY --chown=app:app alembic ./alembic
COPY --chown=app:app alembic.ini ./alembic.ini
COPY --chown=app:app scripts ./scripts

USER app

EXPOSE 8000

# No image-level HEALTHCHECK — the port is fixed (8000) in docker-compose, but
# Railway assigns a dynamic $PORT, so a hard-coded probe would always fail there.
# docker-compose.dev.yml and Railway both define their own healthchecks.

# tini proxies signals so uvicorn / ptb shut down gracefully on SIGTERM.
ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
