"""
Phase 5 tests — composite index, circuit breaker, recommendation/forecast cache,
global exception handler, and collector parallelism.
"""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch


def _make_sample(
    container_id: str = "abc123",
    cpu: float = 30.0,
    memory: float = 40.0,
    memory_usage: int = 400 * 1024 * 1024,
    memory_limit: int = 1024 * 1024 * 1024,
    ts: datetime = None,
):
    from dri.utils.metrics import ContainerMetrics
    return ContainerMetrics(
        container_id=container_id,
        container_name="test-container",
        timestamp=ts or datetime.utcnow(),
        cpu_percent=cpu,
        cpu_count=2,
        memory_usage=memory_usage,
        memory_limit=memory_limit,
        memory_percent=memory,
        net_io_in=0,
        net_io_out=0,
        block_io_read=0,
        block_io_write=0,
        pids=5,
    )


# ---------------------------------------------------------------------------
# Item 2: Composite index verification
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_composite_index_exists_on_metrics_samples():
    """
    After init(), the metrics_samples table must have a composite index that
    covers both container_id AND timestamp.  We query sqlite_master for it.
    """
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()

    async with storage.get_session() as session:
        loop = asyncio.get_running_loop()

        def _check():
            from sqlalchemy import text
            rows = session.execute(
                text("SELECT name, tbl_name, sql FROM sqlite_master WHERE type='index'")
            ).fetchall()
            return rows

        rows = await loop.run_in_executor(None, _check)

    # Filter to indexes on metrics_samples
    ms_indexes = [r for r in rows if r[1] == "metrics_samples"]
    index_sqls = " ".join(r[2] or "" for r in ms_indexes)
    index_names = [r[0] for r in ms_indexes]

    # The composite index must reference both columns
    assert any(
        ("container_id" in (r[2] or "") and "timestamp" in (r[2] or ""))
        for r in ms_indexes
    ), (
        f"Expected a composite index covering container_id+timestamp. "
        f"Found indexes: {index_names}\nSQL: {index_sqls}"
    )

    await storage.close()


# ---------------------------------------------------------------------------
# Item 6: WebhookDispatcher circuit breaker
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_webhook_circuit_breaker_opens_after_threshold():
    """
    After N all-retry-exhausted failures, the circuit opens and the next
    dispatch returns False immediately without making any HTTP request.
    """
    from dri.utils.webhooks import WebhookDispatcher

    dispatcher = WebhookDispatcher(
        max_retries=1,
        circuit_breaker_threshold=3,
        cooldown_seconds=60,
    )

    call_count = 0

    async def fake_post(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        raise Exception("Connection refused")

    # We patch the aiohttp session directly
    mock_session = MagicMock()
    mock_session.post = MagicMock(side_effect=fake_post)
    # Make post return an async context manager that raises
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(side_effect=Exception("Connection refused"))
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session.post = MagicMock(return_value=mock_cm)
    dispatcher._session = mock_session

    url = "http://example.com/hook"

    # Trigger enough failures to open the circuit
    for _ in range(3):
        result = await dispatcher.dispatch(url, "test", {})
        assert result is False

    # Circuit should now be open — next call must skip HTTP and return False
    calls_before = mock_session.post.call_count
    result = await dispatcher.dispatch(url, "test", {})
    assert result is False
    assert mock_session.post.call_count == calls_before, (
        "No new HTTP calls should be made when circuit is open"
    )


@pytest.mark.asyncio
async def test_webhook_circuit_breaker_resets_on_success():
    """A successful dispatch resets the failure count."""
    from dri.utils.webhooks import WebhookDispatcher

    dispatcher = WebhookDispatcher(
        max_retries=1,
        circuit_breaker_threshold=5,
        cooldown_seconds=60,
    )

    # Manually set some failures
    dispatcher._consecutive_failures["http://example.com/hook"] = 4

    # Simulate a success response
    mock_response = MagicMock()
    mock_response.status = 200
    mock_cm = MagicMock()
    mock_cm.__aenter__ = AsyncMock(return_value=mock_response)
    mock_cm.__aexit__ = AsyncMock(return_value=False)
    mock_session = MagicMock()
    mock_session.post = MagicMock(return_value=mock_cm)
    dispatcher._session = mock_session

    result = await dispatcher.dispatch("http://example.com/hook", "test", {})
    assert result is True
    assert dispatcher._consecutive_failures.get("http://example.com/hook", 0) == 0


def test_webhook_circuit_breaker_cooldown_expires():
    """After cooldown, _is_circuit_open returns False and allows retry."""
    from dri.utils.webhooks import WebhookDispatcher

    dispatcher = WebhookDispatcher(circuit_breaker_threshold=3, cooldown_seconds=1)
    url = "http://example.com/hook"

    # Manually open the circuit with a past expiry (already expired)
    dispatcher._circuit_open_until[url] = time.monotonic() - 1  # expired 1 second ago
    dispatcher._consecutive_failures[url] = 5

    assert not dispatcher._is_circuit_open(url), (
        "Circuit should be closed after cooldown expires"
    )
    # State should be reset
    assert dispatcher._consecutive_failures.get(url, 0) == 0


# ---------------------------------------------------------------------------
# Item 3: Recommendation cache — stored and served
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_cache_stored_and_served():
    """
    Write a recommendation to the cache, then verify the route serves it
    without calling compute_recommendation (call count = 0).
    """
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    import dri.api.routes as route_module
    from httpx import AsyncClient, ASGITransport

    storage = MetricsStorage(":memory:")
    await storage.init()

    # Pre-populate cache with a fake recommendation
    fake_payload = {
        "container_id": "abc123",
        "container_name": "test-container",
        "recommended_cpu_pct": 55.0,
        "recommended_memory_bytes": 600 * 1024 * 1024,
        "p95_cpu": 45.0,
        "p95_memory_bytes": 500 * 1024 * 1024,
        "p95_memory_pct": 48.0,
        "sample_count": 200,
        "lookback_days": 7,
        "lookback_actual_days": 6.9,
        "safety_margin": 0.20,
        "data_completeness": "6.9 of 7.0 days available",
        "confidence_tier": "medium",
        "is_memory_leak": False,
        "memory_leak_slope_pct_per_hour": 0.0,
        "is_idle": False,
        "idle_recommendation": None,
    }
    await storage.save_recommendation_cache("abc123", fake_payload, datetime.utcnow())

    aggregator = MetricsAggregator(storage)
    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    # Track calls to compute_recommendation
    call_count = 0
    original = server.recommender.compute_recommendation

    async def counting_compute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original(*args, **kwargs)

    server.recommender.compute_recommendation = counting_compute
    route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        resp = await client.get("/api/v1/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) == 1
        rec = data["recommendations"][0]
        assert rec["container_id"] == "abc123"
        assert "computed_at" in rec

    assert call_count == 0, (
        f"compute_recommendation should not be called on a cache hit, "
        f"but was called {call_count} time(s)"
    )

    await storage.close()


@pytest.mark.asyncio
async def test_forecast_cache_stored_and_served():
    """Forecast route serves cached result without calling forecaster."""
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    import dri.api.routes as route_module
    from httpx import AsyncClient, ASGITransport

    storage = MetricsStorage(":memory:")
    await storage.init()

    fake_forecast = {
        "container_id": "abc123",
        "metric": "memory_percent",
        "horizon_hours": 24,
        "current_value": 42.0,
        "predicted_value": 55.0,
        "confidence_low": 48.0,
        "confidence_high": 62.0,
        "predicted_at": (datetime.utcnow() + timedelta(hours=24)).isoformat(),
        "method_used": "linear_regression",
        "sample_count": 100,
    }
    await storage.save_forecast_cache("abc123", "memory_percent", 24, fake_forecast, datetime.utcnow())

    aggregator = MetricsAggregator(storage)
    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    call_count = 0
    original_forecast = server.forecaster.forecast

    async def counting_forecast(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original_forecast(*args, **kwargs)

    server.forecaster.forecast = counting_forecast
    route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        resp = await client.get("/api/v1/forecast/abc123?horizon_hours=24&metric=memory_percent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["container_id"] == "abc123"
        assert data["predicted_value"] == pytest.approx(55.0)
        assert "computed_at" in data

    assert call_count == 0, (
        f"forecast() should not be called on a cache hit, but was {call_count} time(s)"
    )

    await storage.close()


# ---------------------------------------------------------------------------
# Item 6: Global exception handler
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_exception_handler_returns_error_response():
    """
    An unhandled exception in a route returns JSON with status_code=500,
    not a bare HTML traceback.
    """
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    import dri.api.routes as route_module
    from httpx import AsyncClient, ASGITransport
    from fastapi import APIRouter

    storage = MetricsStorage(":memory:")
    await storage.init()

    aggregator = MetricsAggregator(storage)
    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    # Add a test route that always raises
    @server.app.get("/test/boom")
    async def _boom():
        raise RuntimeError("Intentional test explosion")

    route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

    async with AsyncClient(transport=ASGITransport(app=server.app, raise_app_exceptions=False), base_url="http://test") as client:
        resp = await client.get("/test/boom")

    assert resp.status_code == 500
    body = resp.json()
    assert body["status_code"] == 500
    assert "error" in body
    assert "message" in body
    assert "Intentional test explosion" in body["message"]

    await storage.close()


# ---------------------------------------------------------------------------
# Item 6: Collector parallelism
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_collector_parallelises_stats_with_gather():
    """
    stream_metrics must use asyncio.gather to collect per-container stats
    in parallel, not a sequential for-loop.
    """
    from dri.core.collector import DockerStatsCollector
    from dri.utils.metrics import ContainerMetrics

    collector = DockerStatsCollector()
    collector._running = False  # prevent infinite loop

    # Track gather calls
    gather_calls = []
    original_gather = asyncio.gather

    async def tracking_gather(*coros, **kwargs):
        gather_calls.append(len(coros))
        return await original_gather(*coros, **kwargs)

    # Build two fake containers
    fake_metric = _make_sample()

    async def fake_collect_stats(container):
        return fake_metric

    collector.collect_stats = fake_collect_stats
    collector.client = MagicMock()  # mark as connected

    fake_containers = [MagicMock(), MagicMock()]

    async def fake_get_containers():
        # Stop after one iteration
        collector._running = False
        return fake_containers

    collector.get_containers = fake_get_containers

    with patch("dri.core.collector.asyncio.gather", side_effect=tracking_gather):
        metrics_collected = []
        async for m in collector.stream_metrics(interval=0):
            metrics_collected.append(m)

    # gather should have been called once with 2 coroutines (one per container)
    assert len(gather_calls) >= 1, "asyncio.gather was never called"
    assert gather_calls[0] == 2, (
        f"Expected gather called with 2 coroutines (one per container), "
        f"got {gather_calls[0]}"
    )


# ---------------------------------------------------------------------------
# Item 3: force=true bypasses cache and recomputes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendations_force_true_recomputes():
    """?force=true should call compute_recommendation even when cache exists."""
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    import dri.api.routes as route_module
    from httpx import AsyncClient, ASGITransport

    storage = MetricsStorage(":memory:")
    await storage.init()

    # Cache an outdated recommendation
    await storage.save_recommendation_cache("abc123", {
        "container_id": "abc123",
        "container_name": "test-container",
        "recommended_cpu_pct": 10.0,
        "recommended_memory_bytes": 1,
        "p95_cpu": 8.0,
        "p95_memory_bytes": 1,
        "p95_memory_pct": 1.0,
        "sample_count": 5,
        "lookback_days": 7,
        "lookback_actual_days": 0.1,
        "safety_margin": 0.20,
        "data_completeness": "cached",
        "confidence_tier": "low",
        "is_memory_leak": False,
        "memory_leak_slope_pct_per_hour": 0.0,
        "is_idle": False,
        "idle_recommendation": None,
    }, datetime.utcnow())

    # Insert enough samples for a real recommendation
    now = datetime.utcnow()
    for i in range(20):
        ts = now - timedelta(minutes=20 - i)
        await storage.save_metrics(_make_sample(ts=ts))

    aggregator = MetricsAggregator(storage)
    # Add to in-memory window so container appears
    for i in range(5):
        aggregator.add_metrics(_make_sample(ts=now - timedelta(minutes=4 - i)))

    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    call_count = 0
    original = server.recommender.compute_recommendation

    async def counting_compute(*args, **kwargs):
        nonlocal call_count
        call_count += 1
        return await original(*args, **kwargs)

    server.recommender.compute_recommendation = counting_compute
    route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        resp = await client.get("/api/v1/recommendations?force=true")
        assert resp.status_code == 200

    assert call_count >= 1, (
        f"Expected compute_recommendation called at least once with force=true, got {call_count}"
    )

    await storage.close()
