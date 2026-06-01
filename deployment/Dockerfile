# Multi-stage Dockerfile for DRI Agent

# Build stage
FROM python:3.11-slim as builder

WORKDIR /build

# Install build dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# Runtime stage
FROM python:3.11-slim

WORKDIR /app

# Install runtime dependencies (minimal)
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 dri

# Copy Python dependencies from builder
COPY --from=builder /root/.local /home/dri/.local

# Copy application code
COPY src/ ./src/
COPY config/ ./config/

# Create data directory
RUN mkdir -p /var/lib/dri && chown -R dri:dri /var/lib/dri /app

# Set environment
ENV PATH=/home/dri/.local/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DRI_CONFIG=/app/config/config.yaml

USER dri

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/v1/health').read()" || exit 1

# Expose API port
EXPOSE 8000

# Run agent
CMD ["python", "-m", "dri.main", "--api-port", "8000"]
