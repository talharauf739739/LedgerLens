# syntax=docker/dockerfile:1
FROM python:3.12-slim AS base

COPY --from=ghcr.io/astral-sh/uv:0.13.0 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy PYTHONUNBUFFERED=1

WORKDIR /app

# Dependencies first, for layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY ledgerlens ./ledgerlens
COPY migrations ./migrations
COPY alembic.ini README.md ./
RUN uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app
USER app
ENV PATH="/app/.venv/bin:$PATH"
EXPOSE 8000
