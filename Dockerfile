# Web demo image. Works on Hugging Face Spaces (Docker) and any container host.
# The judgment database is NOT baked in: set PRAMAAN_DB_URL and PRAMAAN_DB_SHA256 (see DEPLOY.md).
FROM python:3.11-slim
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
RUN useradd -m -u 1000 app
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src ./src
RUN uv sync --frozen --no-dev
ENV PATH="/app/.venv/bin:$PATH" \
    PRAMAAN_DB_PATH=/data/pramaan.db
RUN mkdir /data && chown app /data && chown -R app /app
USER app
EXPOSE 7860
CMD ["uvicorn", "pramaan.api.app:app", "--host", "0.0.0.0", "--port", "7860"]
