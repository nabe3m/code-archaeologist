FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY . .
RUN uv sync --frozen --no-dev

EXPOSE 8080
# uv run は起動時に再 sync が走る（dev 依存まで入る）ため venv の uvicorn を直接叩く
CMD ["sh", "-c", "/app/.venv/bin/uvicorn code_archaeologist.web:app --host 0.0.0.0 --port ${PORT:-8080}"]
