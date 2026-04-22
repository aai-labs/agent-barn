FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY --from=ghcr.io/astral-sh/uv:0.4.15 /uv /bin/uv

ENV PATH="/app/.venv/bin:$PATH"
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY ./api/pyproject.toml ./pyproject.toml
COPY ./api/uv.lock ./uv.lock

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY ./api /app/api

EXPOSE 8000

CMD ["fastapi", "run", "api/main.py", "--port", "8000"]
