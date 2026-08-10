# Multi-stage Dockerfile for DRI Agent

# Build stage
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy project files needed for packaging
COPY requirements.txt pyproject.toml ./
COPY src/ ./src/

# Install dependencies and the dri package itself
RUN pip install --no-cache-dir --user -r requirements.txt && \
    pip install --no-cache-dir --user .

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (minimal)
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
