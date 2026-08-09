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
    from dri.core.recommender import ResourceRecommender

    storage = MetricsStorage(":memory:")
    await storage.init()

    # Only 5 samples — below the MIN_SAMPLES=10 threshold
    for i in range(5):
        await storage.save_metrics(_make_sample())

    rec = ResourceRecommender(storage)
    result = await rec.compute_recommendation("abc123", lookback_days=1)

    assert result is None

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
        resp = await client.get("/api/v1/recommendations?lookback_days=1&safety_margin=0.25")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["recommendations"]) >= 1
        rec = data["recommendations"][0]
        assert rec["recommended_cpu_pct"] >= rec["p95_cpu"]
        assert rec["recommended_memory_bytes"] >= rec["p95_memory_bytes"]

    await storage.close()
