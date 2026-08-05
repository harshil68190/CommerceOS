# Dockerfile
#
# Responsibility: builds the backend service image. Uses a slim Python
# base to keep image size down, installs OS-level build dependencies only
# where required by psycopg's binary wheel installation, and runs as a
# non-root user, which is a baseline production security practice (a
# container escape or RCE in the app process shouldn't hand the attacker
# root inside the container).
#
# The image is built once and run unchanged in both local dev and
# production. Environment-specific behavior (hot reload, source mounts)
# is layered on at runtime via docker-compose.dev.yml, never baked in
# here — so the production image has no dev-only dependencies.

FROM python:3.13-slim AS base

# Prevents Python from writing .pyc files and buffering stdout/stderr —
# the latter matters specifically so our JSON logs appear in `docker logs`
# immediately rather than being buffered.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# `curl` is installed solely so docker-compose's healthcheck (see
# docker-compose.yml) can call GET /api/v1/health from inside the
# container without adding a Python HTTP client dependency just for
# that purpose. `bash` is required by entrypoint.sh.
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl bash \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first, separately from application code, so Docker
# layer caching means `docker build` doesn't reinstall every package on
# every code change — only when requirements.txt itself changes.
COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

# Now copy the rest of the application.
COPY . .

# Make the entrypoint executable. It runs Alembic migrations, then exec's
# uvicorn — this is what makes one-command startup work (see entrypoint.sh).
RUN chmod +x /app/entrypoint.sh

# Run as a non-root user.
RUN useradd --create-home --shell /bin/bash appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

# No hardcoded healthcheck here — it's defined in docker-compose.yml,
# since the healthcheck command (curl) may differ between this bare image
# and however it's deployed in a real orchestrator (e.g. Kubernetes
# liveness probes configured at the deployment-manifest level instead).

# Run migrations automatically on startup, then launch uvicorn.
ENTRYPOINT ["/app/entrypoint.sh"]
# The default CMD is only used when the entrypoint is overridden; normally
# entrypoint.sh exec's uvicorn itself. Kept here as a sane fallback.
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
