"""Phase 4 tests — forecasting (linear regression + SES path)."""

import asyncio
import pytest
from datetime import datetime, timedelta


def _make_sample(
    container_id: str = "abc123",
    cpu: float = 30.0,
    memory: float = 40.0,
    ts: datetime = None,
):
    from dri.utils.metrics import ContainerMetrics
    return ContainerMetrics(
        container_id=container_id,
        container_name="test-container",
        timestamp=ts or datetime.utcnow(),
        cpu_percent=cpu,
        cpu_count=2,
        memory_usage=int(memory * 1024 * 1024 * 10),
        memory_limit=1024 * 1024 * 1024,
        memory_percent=memory,
        net_io_in=0,
        net_io_out=0,
        block_io_read=0,
        block_io_write=0,
        pids=5,
    )


# ---------------------------------------------------------------------------
# Basic linear regression forecast correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forecast_trending_upward():
    """Upward trend: forecast should be above current value."""
    from dri.core.storage import MetricsStorage
    from dri.core.forecaster import MetricsForecaster

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    # Linear growth: 20% → 50% over 30 samples (1 per 30 min)
    for i in range(30):
        memory = 20.0 + (30.0 * i / 30)
        ts = now - timedelta(minutes=(30 - i) * 30)
        await storage.save_metrics(_make_sample(memory=memory, ts=ts))

    forecaster = MetricsForecaster(storage)
    result = await forecaster.forecast("abc123", horizon_hours=24, metric="memory_percent")

    assert result is not None
    assert result.predicted_value > result.current_value, (
        f"Upward trend: predicted ({result.predicted_value}) should exceed "
        f"current ({result.current_value})"
    )
    assert result.method_used in ("linear_regression", "ses")
    assert result.confidence_low <= result.predicted_value <= result.confidence_high

    await storage.close()


@pytest.mark.asyncio
async def test_forecast_flat_usage():
    """Flat usage: forecast should be close to current value."""
    from dri.core.storage import MetricsStorage
    from dri.core.forecaster import MetricsForecaster

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(20):
        ts = now - timedelta(minutes=(20 - i) * 15)
        await storage.save_metrics(_make_sample(memory=45.0, ts=ts))

    forecaster = MetricsForecaster(storage)
    result = await forecaster.forecast("abc123", horizon_hours=6, metric="memory_percent")

    assert result is not None
    # For flat data, predicted should be within ±10% of the current value
    assert abs(result.predicted_value - result.current_value) < 15.0, (
        f"Flat usage: predicted ({result.predicted_value}) too far from "
        f"current ({result.current_value})"
    )

    await storage.close()


@pytest.mark.asyncio
async def test_forecast_returns_none_on_insufficient_data():
    """forecast() returns None when < MIN_SAMPLES samples exist."""
    from dri.core.storage import MetricsStorage
    from dri.core.forecaster import MetricsForecaster

    storage = MetricsStorage(":memory:")
    await storage.init()

    for i in range(5):
        await storage.save_metrics(_make_sample())

    forecaster = MetricsForecaster(storage)
    result = await forecaster.forecast("abc123")

    assert result is None

    await storage.close()


@pytest.mark.asyncio
async def test_forecast_returns_none_for_unknown_container():
    """forecast() returns None for a container with no data."""
    from dri.core.storage import MetricsStorage
    from dri.core.forecaster import MetricsForecaster

    storage = MetricsStorage(":memory:")
    await storage.init()

    forecaster = MetricsForecaster(storage)
    result = await forecaster.forecast("unknownXYZ")

    assert result is None

    await storage.close()


@pytest.mark.asyncio
async def test_forecast_cpu_metric():
    """Forecaster works for cpu_percent as well."""
    from dri.core.storage import MetricsStorage
    from dri.core.forecaster import MetricsForecaster

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(20):
        ts = now - timedelta(minutes=(20 - i) * 20)
        await storage.save_metrics(_make_sample(cpu=float(15 + i), ts=ts))

    forecaster = MetricsForecaster(storage)
    result = await forecaster.forecast("abc123", horizon_hours=12, metric="cpu_percent")

    assert result is not None
    assert result.metric == "cpu_percent"
    assert result.predicted_value >= 0.0

    await storage.close()


@pytest.mark.asyncio
async def test_forecast_confidence_interval_ordering():
    """confidence_low <= predicted_value <= confidence_high always."""
    from dri.core.storage import MetricsStorage
    from dri.core.forecaster import MetricsForecaster

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    # Noisy data
    import random
    random.seed(42)
    for i in range(25):
        memory = 40.0 + random.uniform(-15, 15)
        ts = now - timedelta(minutes=(25 - i) * 20)
        await storage.save_metrics(_make_sample(memory=memory, ts=ts))

    forecaster = MetricsForecaster(storage)
    result = await forecaster.forecast("abc123", horizon_hours=48)

    assert result is not None
    assert result.confidence_low <= result.predicted_value, (
        f"CI low {result.confidence_low} > predicted {result.predicted_value}"
    )
    assert result.predicted_value <= result.confidence_high, (
        f"predicted {result.predicted_value} > CI high {result.confidence_high}"
    )

    await storage.close()


# ---------------------------------------------------------------------------
# /api/v1/forecast/{container_id} endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_forecast_endpoint_returns_data():
    """GET /api/v1/forecast/{id} returns valid forecast."""
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    import dri.api.routes as route_module
    from httpx import AsyncClient, ASGITransport

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(20):
        ts = now - timedelta(minutes=(20 - i) * 30)
        await storage.save_metrics(_make_sample(memory=float(35 + i), ts=ts))

    aggregator = MetricsAggregator(storage)
    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

        resp = await client.get("/api/v1/forecast/abc123?horizon_hours=24&metric=memory_percent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["container_id"] == "abc123"
        assert data["metric"] == "memory_percent"
        assert "predicted_value" in data
        assert "confidence_low" in data
        assert "confidence_high" in data

    await storage.close()


@pytest.mark.asyncio
async def test_forecast_endpoint_404_for_unknown():
    """GET /api/v1/forecast/{id} returns 404 for unknown container."""
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    import dri.api.routes as route_module
    from httpx import AsyncClient, ASGITransport

    storage = MetricsStorage(":memory:")
    await storage.init()

    aggregator = MetricsAggregator(storage)
    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

        resp = await client.get("/api/v1/forecast/doesnotexist")
        assert resp.status_code == 404

    await storage.close()
