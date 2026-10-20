FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1
WORKDIR /app
# curl supports the local Docker Compose health check; bash runs entrypoint.sh.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl bash \
    && rm -rf /var/lib/apt/lists/*
# Install Python dependencies separately to improve build-layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
# Copy backend source. .dockerignore excludes env files and local artifacts.
COPY . .
# Run the application as a non-root user.
RUN chmod +x /app/entrypoint.sh \
    && useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser
EXPOSE 8000
# entrypoint.sh handles local migrations, then forwards this command.
# Render provides PORT; local Docker uses 8000 by default.
ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port \"${PORT:-8000}\""]