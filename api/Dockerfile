FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN pip install --no-cache-dir uv==0.4.15

ENV PATH="/app/.venv/bin:$PATH"
ENV UV_COMPILE_BYTECODE=1
ENV UV_LINK_MODE=copy

COPY ./api/pyproject.toml ./pyproject.toml
COPY ./api/uv.lock ./uv.lock

RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project

COPY ./api /app/api

EXPOSE 8000
EXPOSE 8001

CMD ["sh", "api/start.sh"]
# ci-pipeline test touch
