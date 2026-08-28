"""Phase 2 tests — historical aggregation via deque + SQLite hybrid."""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from typing import Optional, TYPE_CHECKING
from unittest.mock import MagicMock, AsyncMock

if TYPE_CHECKING:
    from dri.utils.metrics import ContainerMetrics


def _make_metrics(
    container_id: str = "abc123",
    cpu: float = 10.0,
    memory: float = 30.0,
    ts: Optional[datetime] = None,
) -> "ContainerMetrics":
    from dri.utils.metrics import ContainerMetrics

    return ContainerMetrics(
        container_id=container_id,
        container_name="test-container",
        timestamp=ts or datetime.now(timezone.utc),
        cpu_percent=cpu,
        cpu_count=2,
        memory_usage=300 * 1024 * 1024,
        memory_limit=1024 * 1024 * 1024,
        memory_percent=memory,
        net_io_in=0,
        net_io_out=0,
        block_io_read=0,
        block_io_write=0,
        pids=5,
    )


# ---------------------------------------------------------------------------
# Fast path: deque covers the window
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_fast_path_uses_deque():
    """When deque covers the full window, no DB call is made."""
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()
    agg = MetricsAggregator(storage)

    now = datetime.now(timezone.utc)
    # Add samples spanning 10 minutes — more than enough for a 5m window
    for i in range(10):
        m = _make_metrics(cpu=float(20 + i), ts=now - timedelta(minutes=9 - i))
        agg.add_metrics(m)

    # Patch get_recent_metrics to assert it's NOT called
    called = []
    original = storage.get_recent_metrics

    async def spy(*args, **kwargs):
        called.append(args)
        return await original(*args, **kwargs)

    storage.get_recent_metrics = spy

    samples = await agg._get_samples_for_window("abc123", minutes=5)
    assert len(samples) >= 5
    assert len(called) == 0, "DB should not be queried when deque is sufficient"

    await storage.close()


# ---------------------------------------------------------------------------
# Slow path: deque too small, DB supplements
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_fallback_uses_db():
    """When deque is empty, get_recent_metrics is called."""
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()

    # Pre-populate DB with 70 minutes of data
    now = datetime.now(timezone.utc)
    for i in range(70):
        m = _make_metrics(
            cpu=float(10 + i % 10),
            memory=float(30 + i % 20),
            ts=now - timedelta(minutes=70 - i),
        )
        await storage.save_metrics(m)

    agg = MetricsAggregator(storage)
    # Deque is empty — should fall back to DB
    samples = await agg._get_samples_for_window("abc123", minutes=60)

    # Should have retrieved historical DB data
    assert len(samples) > 0, "DB fallback should return historical samples"

    await storage.close()


# ---------------------------------------------------------------------------
# Hybrid merge deduplication
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_hybrid_merge_deduplicates_by_timestamp():
    """Samples present in both deque and DB are not duplicated."""
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.now(timezone.utc)
    shared_ts = now - timedelta(minutes=5)

    # Save to DB
    m_db = _make_metrics(cpu=50.0, ts=shared_ts)
    await storage.save_metrics(m_db)

    agg = MetricsAggregator(storage)

    # Also add the same timestamp to deque
    m_mem = _make_metrics(cpu=50.0, ts=shared_ts)
    agg.add_metrics(m_mem)

    samples = await agg._get_samples_for_window("abc123", minutes=10)
    timestamps = [s.timestamp for s in samples]
    # No duplicate timestamps
    assert len(timestamps) == len(set(timestamps)), "Deduplication failed"

    await storage.close()


# ---------------------------------------------------------------------------
# 60-minute average uses DB when deque only covers 5 minutes
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_60m_average_falls_back_to_db():
    """60-minute CPU average is computed from DB history when deque is short."""
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()

    now = datetime.now(timezone.utc)

    # Insert 60 minutes of DB data — CPU = 80%
    for i in range(60):
        m = _make_metrics(cpu=80.0, ts=now - timedelta(minutes=60 - i))
        await storage.save_metrics(m)

    agg = MetricsAggregator(storage)

    # Add only 2 minutes of in-memory data — CPU = 20% (very recent, after DB data)
    for i in range(2):
        m = _make_metrics(cpu=20.0, ts=now - timedelta(minutes=1 - i, seconds=30))
        agg.add_metrics(m)

    avg_60m = await agg._calculate_moving_average_hybrid("abc123", 60, "cpu_percent")

    # If the 60-minute average were computed only from the 2 in-memory samples
    # it would be 20.0. With DB fallback it should be much higher.
    assert avg_60m > 40.0, (
        f"Expected avg_60m > 40 (DB-backed), got {avg_60m}. "
        "DB fallback may not be working."
    )

    await storage.close()


# ---------------------------------------------------------------------------
# aggregate() correctness with hybrid data
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_aggregate_returns_aggregated_metrics():
    """aggregate() returns a valid AggregatedMetrics object."""
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage
    from dri.utils.metrics import AggregatedMetrics

    storage = MetricsStorage(":memory:")
    await storage.init()

    agg = MetricsAggregator(storage)
    now = datetime.now(timezone.utc)

    for i in range(10):
        m = _make_metrics(cpu=float(25 + i), memory=float(40 + i), ts=now - timedelta(minutes=9 - i))
        agg.add_metrics(m)

    result = await agg.aggregate("abc123")

    assert result is not None
    assert isinstance(result, AggregatedMetrics)
    assert result.container_id == "abc123"
    assert 0.0 <= result.cpu_percent_5m <= 100.0
    assert 0.0 <= result.memory_percent_5m <= 100.0

    await storage.close()


# ---------------------------------------------------------------------------
# Policy Engine evaluate with missing / aliased metrics
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_policy_engine_memory_growth_rate_5m_triggers_alert():
    """Test that a policy using 'memory_growth_rate_5m' correctly maps and triggers."""
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig, ContainerPolicy, ThresholdRule
    from dri.utils.metrics import AggregatedMetrics
    from datetime import datetime, timezone

    rule = ThresholdRule(metric="memory_growth_rate_5m", operator=">", value=20.0, duration_seconds=0, action="warning")
    policy = ContainerPolicy(name="test", enabled=True, selector={"image": "*"}, rules=[rule])
    config = DRIConfig(global_policy=policy)
    engine = PolicyEngine(config)

    metrics = AggregatedMetrics(
        container_id="test1",
        container_name="test_container",
        timestamp=datetime.now(timezone.utc),
        cpu_percent=0.0,
        cpu_percent_5m=0.0,
        cpu_percent_15m=0.0,
        cpu_percent_60m=0.0,
        memory_percent=0.0,
        memory_percent_5m=0.0,
        memory_percent_15m=0.0,
        memory_percent_60m=0.0,
        memory_growth_rate_1m=0.0,
        memory_growth_rate_5m=25.0
    )

    # Evaluate twice to allow violation tracker to register and then trigger
    await engine.evaluate(metrics)
    alerts = await engine.evaluate(metrics)
    
    assert alerts is not None, "Alerts should be generated"
    assert len(alerts) == 1
    assert alerts[0].metric == "memory_growth_rate_5m"
    assert alerts[0].current_value == 25.0


@pytest.mark.asyncio
async def test_policy_engine_typo_metric_logs_warning(caplog):
    """Test that a typo in metric name produces a logged warning once."""
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig, ContainerPolicy, ThresholdRule
    from dri.utils.metrics import AggregatedMetrics
    from datetime import datetime, timezone

    rule = ThresholdRule(metric="typo_metric", operator=">", value=20.0, duration_seconds=0, action="warning")
    policy = ContainerPolicy(name="test", enabled=True, selector={"image": "*"}, rules=[rule])
    config = DRIConfig(global_policy=policy)
    engine = PolicyEngine(config)

    metrics = AggregatedMetrics(
        container_id="test1",
        container_name="test_container",
        timestamp=datetime.now(timezone.utc),
        cpu_percent=0.0,
        cpu_percent_5m=0.0,
        cpu_percent_15m=0.0,
        cpu_percent_60m=0.0,
        memory_percent=0.0,
        memory_percent_5m=0.0,
        memory_percent_15m=0.0,
        memory_percent_60m=0.0,
        memory_growth_rate_1m=0.0,
        memory_growth_rate_5m=0.0
    )

    # Evaluate multiple times
    await engine.evaluate(metrics)
    await engine.evaluate(metrics)

    warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
    assert len(warnings) == 1
    assert "Unknown metric 'typo_metric'" in warnings[0]

