"""Tests for API key authentication layer."""

import pytest
from httpx import AsyncClient, ASGITransport

from starlette.middleware.cors import CORSMiddleware

from dri.config import DRIConfig, APIConfig
from dri.core.storage import MetricsStorage
from dri.core.aggregator import MetricsAggregator
from dri.core.engine import PolicyEngine
from dri.api.server import DRIAPIServer


@pytest.mark.asyncio
async def test_auth_enabled_requires_valid_api_key():
    """When api_key is configured, requests without key or with invalid key return 401."""
    secret = "secret-token-12345"
    config = DRIConfig(api=APIConfig(api_key=secret))
    storage = MetricsStorage(":memory:")
    await storage.init()

    aggregator = MetricsAggregator(storage)
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    async with AsyncClient(
        transport=ASGITransport(app=server.app),
        base_url="http://test",
    ) as client:
        # 1. No header -> 401
        res = await client.get("/api/v1/metrics")
        assert res.status_code == 401
        assert res.json().get("detail") == "Invalid or missing API key"

        # 2. Wrong key -> 401
        res = await client.get(
            "/api/v1/metrics",
            headers={"X-Api-Key": "wrong-key"},
        )
        assert res.status_code == 401

        # 3. Correct key -> 200
        res = await client.get(
            "/api/v1/metrics",
            headers={"X-Api-Key": secret},
        )
        assert res.status_code == 200

        # 4. Other protected endpoints require key
        res = await client.get("/api/v1/policies")
        assert res.status_code == 401

        res = await client.get(
            "/api/v1/policies",
            headers={"X-Api-Key": secret},
        )
        assert res.status_code == 200

        # 5. Prometheus /metrics endpoint requires key
        res = await client.get("/metrics")
        assert res.status_code == 401

        res = await client.get(
            "/metrics",
            headers={"X-Api-Key": secret},
        )
        assert res.status_code == 200

        # 6. Health check endpoints remain open without key (for liveness probes)
        res = await client.get("/api/v1/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

        res = await client.get("/health")
        assert res.status_code == 200
        assert res.json()["status"] == "healthy"

    await storage.close()


@pytest.mark.asyncio
async def test_auth_disabled_by_default():
    """When api_key is None (default), requests succeed without X-Api-Key header."""
    config = DRIConfig(api=APIConfig(api_key=None))
    assert config.api.api_key is None

    storage = MetricsStorage(":memory:")
    await storage.init()

    aggregator = MetricsAggregator(storage)
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    async with AsyncClient(
        transport=ASGITransport(app=server.app),
        base_url="http://test",
    ) as client:
        # All endpoints succeed with no header
        res = await client.get("/api/v1/metrics")
        assert res.status_code == 200

        res = await client.get("/api/v1/policies")
        assert res.status_code == 200

        res = await client.get("/api/v1/alerts")
        assert res.status_code == 200

        res = await client.get("/metrics")
        assert res.status_code == 200

        res = await client.get("/api/v1/health")
        assert res.status_code == 200

        res = await client.get("/health")
        assert res.status_code == 200

    await storage.close()


@pytest.mark.asyncio
async def test_cors_configuration_wildcard():
    """Wildcard allowed_origins disables allow_credentials per CORS spec."""
    config = DRIConfig(api=APIConfig(allowed_origins=["*"]))
    storage = MetricsStorage(":memory:")
    await storage.init()

    aggregator = MetricsAggregator(storage)
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    cors_mw = next(m for m in server.app.user_middleware if m.cls == CORSMiddleware)
    assert cors_mw.kwargs["allow_origins"] == ["*"]
    assert cors_mw.kwargs["allow_credentials"] is False

    async with AsyncClient(
        transport=ASGITransport(app=server.app),
        base_url="http://test",
    ) as client:
        res = await client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == "*"
        assert "access-control-allow-credentials" not in res.headers

    await storage.close()


@pytest.mark.asyncio
async def test_cors_configuration_specific_origins():
    """Explicit allowed_origins enables allow_credentials for credentialed fetches."""
    origins = ["http://localhost:5173", "https://dashboard.example.com"]
    config = DRIConfig(api=APIConfig(allowed_origins=origins))
    storage = MetricsStorage(":memory:")
    await storage.init()

    aggregator = MetricsAggregator(storage)
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    cors_mw = next(m for m in server.app.user_middleware if m.cls == CORSMiddleware)
    assert cors_mw.kwargs["allow_origins"] == origins
    assert cors_mw.kwargs["allow_credentials"] is True

    async with AsyncClient(
        transport=ASGITransport(app=server.app),
        base_url="http://test",
    ) as client:
        res = await client.get("/health", headers={"Origin": "http://localhost:5173"})
        assert res.status_code == 200
        assert res.headers.get("access-control-allow-origin") == "http://localhost:5173"
        assert res.headers.get("access-control-allow-credentials") == "true"

    await storage.close()
