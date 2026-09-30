# Multi-stage Dockerfile for DRI Agent

# Build stage — python:3.11-slim is already in the local Docker cache.
# numpy, scipy, and all other dependencies are installed via pre-built
# manylinux2014 wheels on linux/amd64, so no gcc/python3-dev is required.
FROM python:3.11-slim AS builder

WORKDIR /build

# Copy project files needed for packaging
COPY requirements.txt pyproject.toml ./
COPY src/ ./src/

# Upgrade pip so it resolves manylinux platform tags correctly (pip 24 inside
# the base image can fail with "from versions: none" on a slow/interrupted
# PyPI connection — upgrading pip and setting --timeout 120 prevents that).
# Install numpy first so scipy's dependency resolver finds it immediately.
RUN pip install --no-cache-dir --timeout 120 --upgrade pip && \
    pip install --no-cache-dir --timeout 120 "numpy>=1.24.0" && \
    pip install --no-cache-dir --timeout 120 --user -r requirements.txt && \
    pip install --no-cache-dir --timeout 120 --user .

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install ca-certificates for HTTPS webhook calls.
# This layer is cached as long as the Dockerfile doesn't change.
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Copy Python dependencies (including installed dri package) from builder
COPY --from=builder /root/.local /root/.local

# Copy application source and config
COPY src/ ./src/
COPY config/ ./config/

# Create data directory
RUN mkdir -p /var/lib/dri

# Set environment — run as root so the agent can access /var/run/docker.sock
ENV PATH=/root/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    DRI_CONFIG=/app/config/config.yaml

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health').read()" || exit 1

# Expose API port
EXPOSE 8000

# Run agent
CMD ["python", "-m", "dri.main", "--config", "/app/config/config.yaml", "--api-port", "8000"]
