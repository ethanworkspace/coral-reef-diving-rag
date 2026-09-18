FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8080

WORKDIR /app
COPY pyproject.toml README.md ./
COPY src ./src
COPY metadata ./metadata
RUN pip install --no-cache-dir .

RUN useradd --create-home --uid 10001 appuser && mkdir -p /app/data/processed && chown -R appuser:appuser /app
USER appuser

EXPOSE 8080
CMD ["sh", "-c", "python -m coral_rag bootstrap-public && uvicorn coral_rag.web:app --host 0.0.0.0 --port ${PORT}"]
