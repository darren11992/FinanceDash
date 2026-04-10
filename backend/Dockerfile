# ===========================================================================
# Penny API — Production Dockerfile
# ===========================================================================
# Multi-stage build: installs dependencies in a builder stage, then copies
# only the runtime artifacts into a slim final image.
#
# Build:  docker build -t penny-api ./backend
# Run:    docker run -p 8000:8000 --env-file .env penny-api
# ===========================================================================

# ── Stage 1: Builder ─────────────────────────────────────────────────────
FROM python:3.13-slim AS builder

WORKDIR /build

# Install build dependencies (some pip packages need gcc for C extensions)
RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libffi-dev && \
    rm -rf /var/lib/apt/lists/*

# Copy only requirements first (Docker layer caching — deps rarely change)
COPY requirements.txt .

# Install into a virtual env so we can copy it cleanly to the final stage
RUN python -m venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt


# ── Stage 2: Runtime ─────────────────────────────────────────────────────
FROM python:3.13-slim

# Security: run as non-root user
RUN groupadd --gid 1000 penny && \
    useradd --uid 1000 --gid penny --shell /bin/bash --create-home penny

WORKDIR /home/penny/app

# Copy the pre-built virtualenv from builder
COPY --from=builder /opt/venv /opt/venv
ENV PATH="/opt/venv/bin:$PATH"

# Copy application code
COPY app/ ./app/

# Own everything by the non-root user
RUN chown -R penny:penny /home/penny/app

USER penny

# Fly.io exposes port 8000 by default (configured in fly.toml)
EXPOSE 8000

# Gunicorn with a single uvicorn worker.
# - 1 worker: prevents duplicate APScheduler runs. A single async worker
#   handles concurrency via the event loop — plenty for 2-10 users.
#   If ever scaling beyond one Machine, extract the scheduler into a
#   separate worker process and increase workers here.
# - graceful-timeout: allows in-flight requests to complete on deploy.
# - access-log: logs every request (useful for debugging, Fly.io captures stdout).
CMD ["gunicorn", "app.main:app", \
     "--worker-class", "uvicorn.workers.UvicornWorker", \
     "--workers", "1", \
     "--bind", "0.0.0.0:8000", \
     "--timeout", "120", \
     "--graceful-timeout", "30", \
     "--access-logfile", "-", \
     "--error-logfile", "-"]
