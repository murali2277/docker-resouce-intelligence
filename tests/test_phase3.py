"""Phase 3 tests — recommendations, z-score anomaly detection, memory leak detection."""

import asyncio
import pytest
from datetime import datetime, timedelta


def _make_sample(
    container_id: str = "abc123",
    cpu: float = 30.0,
    memory: float = 40.0,
    memory_usage: int = 400 * 1024 * 1024,
    memory_limit: int = 1024 * 1024 * 1024,
    ts: datetime = None,
):
    """Helper that stores a MetricsSample directly in the DB."""
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
# ResourceRecommender — p95 correctness
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommender_p95_correctness():
    """p95 CPU recommendation should be higher than the median sample."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    # 90 samples: 80 at cpu=10%, 10 at cpu=90%  → p95 ≈ 90%
    for i in range(80):
        await storage.save_metrics(_make_sample(cpu=10.0, ts=now - timedelta(minutes=80 - i)))
    for i in range(10):
        await storage.save_metrics(_make_sample(cpu=90.0, ts=now - timedelta(minutes=10 - i, seconds=30)))

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", "test-container", lookback_days=1, safety_margin=0.20)

    assert result is not None
    assert result.p95_cpu >= 80.0, f"Expected p95_cpu ≥ 80, got {result.p95_cpu}"
    assert result.recommended_cpu_pct > result.p95_cpu, "Recommended limit should exceed p95"
    # Safety margin test: recommended ≈ p95 * 1.20
    expected_min = result.p95_cpu * 1.15
    assert result.recommended_cpu_pct >= expected_min

    await storage.close()


@pytest.mark.asyncio
async def test_recommender_returns_none_on_insufficient_data():
    """Recommender should return None when fewer than MIN_SAMPLES exist."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, InsufficientDataResult

    storage = MetricsStorage(":memory:")
    await storage.init()

    # Only 5 samples — below the MIN_SAMPLES=10 threshold
    for i in range(5):
        await storage.save_metrics(_make_sample())

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", lookback_days=1)

    assert isinstance(result, InsufficientDataResult)

    await storage.close()


# ---------------------------------------------------------------------------
# ResourceRecommender — memory leak detection
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_leak_detected_on_sustained_growth():
    """Memory leak should be detected when memory grows steadily over 6 hours."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    # Sustained growth: 20% → 80% over 6 hours (60 samples, 1 per 6 minutes)
    for i in range(60):
        memory = 20.0 + (60.0 * i / 60)
        ts = now - timedelta(hours=6) + timedelta(minutes=i * 6)
        await storage.save_metrics(_make_sample(memory=memory, ts=ts))

    rec = ResourceRecommender(storage)
    is_leak, slope = await rec.detect_memory_leak("abc123", window_hours=6.0)

    assert is_leak, f"Expected memory leak to be detected, slope={slope}"
    assert slope > 0.5, f"Expected slope > 0.5 %/hr, got {slope}"

    await storage.close()


@pytest.mark.asyncio
async def test_memory_leak_not_detected_on_flat_usage():
    """No memory leak when usage is flat."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(60):
        ts = now - timedelta(hours=6) + timedelta(minutes=i * 6)
        await storage.save_metrics(_make_sample(memory=45.0 + (i % 3) * 0.5, ts=ts))  # small noise

    rec = ResourceRecommender(storage)
    is_leak, slope = await rec.detect_memory_leak("abc123", window_hours=6.0)

    assert not is_leak, f"Expected no memory leak, slope={slope}"

    await storage.close()


# ---------------------------------------------------------------------------
# z_score_anomaly helper
# ---------------------------------------------------------------------------


def test_z_score_anomaly_detects_spike():
    """z-score above threshold should flag an anomaly."""
    from dri.core.recommender import z_score_anomaly

    baseline = [20.0] * 50  # mean=20, std≈0 → any deviation is huge
    baseline = list(range(10, 60))  # uniform 10..59, mean=34.5, std≈14.4

    is_anomaly, z = z_score_anomaly(baseline, current=100.0, threshold=3.0)
    assert is_anomaly, f"Expected anomaly, z={z}"
    assert z > 3.0


def test_z_score_anomaly_no_flag_for_normal():
    """Normal value close to mean should not be flagged."""
    from dri.core.recommender import z_score_anomaly

    baseline = list(range(10, 60))  # mean≈34.5
    is_anomaly, z = z_score_anomaly(baseline, current=35.0, threshold=3.0)
    assert not is_anomaly


def test_z_score_anomaly_insufficient_data():
    """Too few baseline values → never anomaly."""
    from dri.core.recommender import z_score_anomaly

    is_anomaly, z = z_score_anomaly([50.0, 51.0, 49.0], current=200.0, threshold=3.0)
    assert not is_anomaly  # only 3 samples — below minimum


# ---------------------------------------------------------------------------
# /api/v1/recommendations endpoint
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendations_endpoint_returns_data():
    """GET /api/v1/recommendations returns recommendations for known containers."""
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.recommender import ResourceRecommender
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    from httpx import AsyncClient, ASGITransport

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    # Insert 15 samples for container "abc123"
    for i in range(15):
        m = _make_sample(cpu=float(20 + i), memory=float(30 + i), ts=now - timedelta(minutes=15 - i))
        await storage.save_metrics(m)

    aggregator = MetricsAggregator(storage)
    # Add to in-memory window so container appears in aggregate_all()
    for i in range(5):
        m = _make_sample(cpu=float(30 + i), memory=float(45 + i), ts=now - timedelta(minutes=4 - i))
        aggregator.add_metrics(m)

    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        # Manually trigger lifespan (set_dependencies)
        import dri.api.routes as route_module
        route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

        resp = await client.get("/api/v1/recommendations")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data
        assert data["total_count"] >= 0  # may be 0 if samples insufficient

    await storage.close()


@pytest.mark.asyncio
async def test_recommendations_endpoint_with_sufficient_data():
    """Recommendations endpoint returns ≥1 result when 15+ samples exist."""
    from dri.core.storage import MetricsStorage
    from dri.core.aggregator import MetricsAggregator
    from dri.core.recommender import ResourceRecommender
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig
    from dri.api.server import DRIAPIServer
    from httpx import AsyncClient, ASGITransport

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    # 20 samples — enough for recommender
    for i in range(20):
        m = _make_sample(cpu=float(20 + i % 10), memory=float(30 + i % 15), ts=now - timedelta(minutes=20 - i))
        await storage.save_metrics(m)

    aggregator = MetricsAggregator(storage)
    for i in range(3):
        m = _make_sample(cpu=25.0, memory=40.0, ts=now - timedelta(minutes=2 - i))
        aggregator.add_metrics(m)

    config = DRIConfig()
    pe = PolicyEngine(config)
    server = DRIAPIServer(config, storage, aggregator, pe)

    async with AsyncClient(transport=ASGITransport(app=server.app), base_url="http://test") as client:
        # Manually trigger set_dependencies
        import dri.api.routes as route_module
        route_module.set_dependencies(storage, aggregator, pe, None, server.recommender, server.forecaster)

        resp = await client.get("/api/v1/recommendations?lookback_days=1&safety_margin=0.25")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) >= 1
        rec = data["recommendations"][0]
        assert rec["recommended_cpu_pct"] >= rec["p95_cpu"]
        assert rec["recommended_memory_bytes"] >= rec["p95_memory_bytes"]

    await storage.close()


# ---------------------------------------------------------------------------
# Restart-boundary memory leak detection (Item 4)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_leak_restart_boundary():
    """
    Memory ramps up, drops sharply (simulated restart), ramps again.
    Assert the leak slope is computed only from the post-restart segment.
    """
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()

    # Phase 1: ramp up 20% -> 60% over first 3 hours (36 samples, 5 min each)
    for i in range(36):
        memory = 20.0 + (40.0 * i / 36)
        ts = now - timedelta(hours=6) + timedelta(minutes=i * 5)
        await storage.save_metrics(_make_sample(memory=memory, ts=ts))

    # Simulated restart: sharp drop to 15%
    restart_ts = now - timedelta(hours=3, minutes=1)
    await storage.save_metrics(_make_sample(memory=15.0, ts=restart_ts))

    # Phase 2: ramp up 15% -> 55% over next 3 hours (36 samples)
    for i in range(36):
        memory = 15.0 + (40.0 * i / 36)
        ts = now - timedelta(hours=3) + timedelta(minutes=i * 5)
        await storage.save_metrics(_make_sample(memory=memory, ts=ts))

    rec = ResourceRecommender(storage)
    is_leak, slope = await rec.detect_memory_leak("abc123", window_hours=6.0)

    assert is_leak, f"Expected leak detected from post-restart segment, slope={slope}"
    assert slope > 0.5, f"Expected slope > 0.5 %/hr, got {slope}"

    await storage.close()


@pytest.mark.asyncio
async def test_memory_leak_no_false_positive_after_restart_flat_tail():
    """Ramp, restart, flat tail — should NOT flag a leak."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(36):
        memory = 20.0 + (40.0 * i / 36)
        ts = now - timedelta(hours=6) + timedelta(minutes=i * 5)
        await storage.save_metrics(_make_sample(memory=memory, ts=ts))

    await storage.save_metrics(_make_sample(memory=10.0, ts=now - timedelta(hours=3, minutes=1)))

    for i in range(36):
        memory = 12.0 + (i % 3) * 0.3
        ts = now - timedelta(hours=3) + timedelta(minutes=i * 5)
        await storage.save_metrics(_make_sample(memory=memory, ts=ts))

    rec = ResourceRecommender(storage)
    is_leak, slope = await rec.detect_memory_leak("abc123", window_hours=6.0)

    assert not is_leak, f"Flat post-restart should not flag a leak, slope={slope}"

    await storage.close()


# ---------------------------------------------------------------------------
# data_completeness field (Item 1)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_data_completeness_field():
    """Recommendation must include a non-empty data_completeness string."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, Recommendation

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(15):
        ts = now - timedelta(hours=3) + timedelta(minutes=i * 12)
        await storage.save_metrics(_make_sample(ts=ts))

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", lookback_days=7)

    assert isinstance(result, Recommendation), f"Expected Recommendation, got {type(result)}"
    assert result.data_completeness, "data_completeness must not be empty"
    assert "days available" in result.data_completeness
    assert result.lookback_actual_days < 1.0

    await storage.close()


# ---------------------------------------------------------------------------
# Confidence tiers (Item 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_confidence_tier_low():
    """sample_count < 50 -> confidence_tier == 'low'."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, Recommendation

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(20):
        await storage.save_metrics(_make_sample(ts=now - timedelta(minutes=20 - i)))

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", lookback_days=1)

    assert isinstance(result, Recommendation)
    assert result.confidence_tier == "low", f"Got '{result.confidence_tier}'"

    await storage.close()


@pytest.mark.asyncio
async def test_recommendation_confidence_tier_medium():
    """50 <= sample_count < 300 -> confidence_tier == 'medium'."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, Recommendation

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(100):
        await storage.save_metrics(_make_sample(cpu=float(20 + i % 30), ts=now - timedelta(minutes=200 - i * 2)))

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", lookback_days=1)

    assert isinstance(result, Recommendation)
    assert result.confidence_tier == "medium", f"Got '{result.confidence_tier}'"

    await storage.close()


# ---------------------------------------------------------------------------
# Structured InsufficientDataResult (Item 6)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_insufficient_data_structured():
    """compute_recommendation returns InsufficientDataResult with structured fields."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, InsufficientDataResult

    storage = MetricsStorage(":memory:")
    await storage.init()

    for _ in range(3):
        await storage.save_metrics(_make_sample())

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", "test-container")

    assert isinstance(result, InsufficientDataResult), f"Got {type(result)}"
    assert result.status == "insufficient_data"
    assert result.min_samples_required == ResourceRecommender.MIN_SAMPLES
    assert result.samples_available == 3

    await storage.close()


# ---------------------------------------------------------------------------
# Idle detection / scale-to-zero (Item 5)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_idle_detection():
    """Near-zero CPU and memory -> is_idle=True, idle_recommendation='scale_to_zero'."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, Recommendation

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(30):
        ts = now - timedelta(minutes=60 - i * 2)
        await storage.save_metrics(
            _make_sample(cpu=0.1, memory=0.3, memory_usage=3 * 1024 * 1024, ts=ts)
        )

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", "test-container", lookback_days=1)

    assert isinstance(result, Recommendation), f"Got {type(result)}"
    assert result.is_idle, "Expected is_idle=True for near-zero usage"
    assert result.idle_recommendation == "scale_to_zero"

    await storage.close()


@pytest.mark.asyncio
async def test_recommendation_not_idle_under_load():
    """Container with real load must not be flagged idle."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, Recommendation

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    for i in range(20):
        await storage.save_metrics(_make_sample(cpu=30.0, memory=50.0, ts=now - timedelta(minutes=40 - i * 2)))

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", "test-container", lookback_days=1)

    assert isinstance(result, Recommendation)
    assert not result.is_idle
    assert result.idle_recommendation is None

    await storage.close()


# ---------------------------------------------------------------------------
# Edge cases (Item 7 — extend test_phase3.py)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommender_empty_storage():
    """Empty DB (zero samples) must return InsufficientDataResult, not crash."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, InsufficientDataResult

    storage = MetricsStorage(":memory:")
    await storage.init()

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", "test-container", lookback_days=7)

    assert isinstance(result, InsufficientDataResult), (
        f"Expected InsufficientDataResult for empty DB, got {type(result)}"
    )
    assert result.samples_available == 0
    assert result.min_samples_required == ResourceRecommender.MIN_SAMPLES

    await storage.close()


@pytest.mark.asyncio
async def test_recommender_single_sample():
    """Exactly one sample must return InsufficientDataResult, not crash."""
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, InsufficientDataResult

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    await storage.save_metrics(_make_sample(cpu=50.0, memory=60.0, ts=now - timedelta(minutes=1)))

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", "test-container", lookback_days=7)

    assert isinstance(result, InsufficientDataResult), (
        f"Expected InsufficientDataResult for 1-sample container, got {type(result)}"
    )
    assert result.samples_available == 1

    await storage.close()


@pytest.mark.asyncio
async def test_recommender_all_zero_metrics():
    """
    All-zero CPU and memory (e.g. a paused container) must produce a valid
    Recommendation with p95_cpu==0 and recommended_cpu_pct==0, not crash or
    return InsufficientDataResult.
    """
    from dri.core.storage import MetricsStorage
    from dri.core.recommender import ResourceRecommender, Recommendation

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.utcnow()
    # MIN_SAMPLES (10) + a few extra, all at zero usage
    for i in range(15):
        await storage.save_metrics(
            _make_sample(
                cpu=0.0,
                memory=0.0,
                memory_usage=0,
                ts=now - timedelta(minutes=15 - i),
            )
        )

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", "test-container", lookback_days=1)

    assert isinstance(result, Recommendation), (
        f"Expected Recommendation for all-zero metrics, got {type(result)}"
    )
    assert result.p95_cpu == 0.0, f"p95_cpu should be 0, got {result.p95_cpu}"
    assert result.recommended_cpu_pct == 0.0
    assert result.is_idle, "All-zero usage should be flagged idle"
    assert result.idle_recommendation == "scale_to_zero"

    await storage.close()
