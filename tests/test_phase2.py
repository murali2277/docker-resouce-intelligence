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
    net_in: int = 0,
    net_out: int = 0,
    block_read: int = 0,
    block_write: int = 0,
    pids: int = 5,
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
        net_io_in=net_in,
        net_io_out=net_out,
        block_io_read=block_read,
        block_io_write=block_write,
        pids=pids,
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
    """Test that a policy using 'memory_growth_rate_5m' correctly maps and triggers.

    After P0-4 fix: duration_seconds=0 fires on the FIRST breaching call.
    """
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

    # P0-4: duration_seconds=0 -> alert fires on the FIRST call
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


# ---------------------------------------------------------------------------
# Stopped-container status tracking and cleanup
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_stopped_container_status_and_cleanup():
    """Full lifecycle: running → stopped → evicted.

    1. Add metrics for 'abc123' — aggregate() should report container_status=='running'.
    2. mark_container_stopped() — aggregate() should report container_status=='stopped'.
    3. cleanup_stopped_containers(max_stopped_minutes=0) should evict the window.
    """
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()
    agg = MetricsAggregator(storage)

    # -- Phase 1: container is running ---------------------------------------
    now = datetime.now(timezone.utc)
    for i in range(5):
        m = _make_metrics(
            container_id="abc123",
            cpu=float(10 + i),
            memory=float(30 + i),
            ts=now - timedelta(minutes=4 - i),
        )
        agg.add_metrics(m)

    result_running = await agg.aggregate("abc123")
    assert result_running is not None, "aggregate() must return data while running"
    assert result_running.container_status == "running", (
        f"Expected 'running', got {result_running.container_status!r}"
    )

    # -- Phase 2: container stops -------------------------------------------
    agg.mark_container_stopped("abc123")

    result_stopped = await agg.aggregate("abc123")
    assert result_stopped is not None, "aggregate() must still return data right after stop"
    assert result_stopped.container_status == "stopped", (
        f"Expected 'stopped', got {result_stopped.container_status!r}"
    )

    # Marking again is a no-op (idempotent).
    agg.mark_container_stopped("abc123")
    assert list(agg._stopped_at.keys()).count("abc123") == 1

    # -- Phase 3: cleanup evicts the window ---------------------------------
    # max_stopped_minutes=0 means anything stopped up to "now" is eligible,
    # which covers our entry whose stopped_at <= datetime.utcnow().
    # Use a tiny negative offset to ensure the cutoff is strictly in the past.
    import time as _time
    _time.sleep(0.01)  # guarantee stopped_at is strictly before utcnow()
    agg.cleanup_stopped_containers(max_stopped_minutes=0)

    assert "abc123" not in agg._windows, (
        "Window should be evicted after cleanup_stopped_containers"
    )
    assert "abc123" not in agg._stopped_at, (
        "_stopped_at entry should be cleared on eviction"
    )

    # -- Phase 4: aggregate() returns None for evicted container -------------
    result_evicted = await agg.aggregate("abc123")
    assert result_evicted is None, (
        "aggregate() must return None for a container with no window"
    )

    await storage.close()


@pytest.mark.asyncio
async def test_unmark_container_stopped_clears_status():
    """unmark_container_stopped() removes the stopped flag (simulates restart)."""
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()
    agg = MetricsAggregator(storage)

    now = datetime.now(timezone.utc)
    for i in range(3):
        m = _make_metrics(container_id="xyz789", ts=now - timedelta(minutes=2 - i))
        agg.add_metrics(m)

    agg.mark_container_stopped("xyz789")
    assert (await agg.aggregate("xyz789")).container_status == "stopped"

    agg.unmark_container_stopped("xyz789")
    result = await agg.aggregate("xyz789")
    assert result is not None
    assert result.container_status == "running", (
        f"Expected 'running' after unmark, got {result.container_status!r}"
    )

    await storage.close()


@pytest.mark.asyncio
async def test_aggregate_surfaces_io_and_pids():
    """aggregate() returns network, block I/O, and PID stats matching the latest sample."""
    from dri.core.aggregator import MetricsAggregator
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()
    agg = MetricsAggregator(storage)

    now = datetime.now(timezone.utc)
    # Add historical samples
    for i in range(4):
        m = _make_metrics(
            ts=now - timedelta(minutes=5 - i),
            net_in=100 * i,
            net_out=50 * i,
            block_read=200 * i,
            block_write=150 * i,
            pids=10 + i,
        )
        agg.add_metrics(m)

    # Add the latest sample with distinct values
    latest = _make_metrics(
        ts=now,
        net_in=9999,
        net_out=8888,
        block_read=7777,
        block_write=6666,
        pids=99,
    )
    agg.add_metrics(latest)

    result = await agg.aggregate("abc123")
    assert result is not None
    assert result.net_io_in == 9999
    assert result.net_io_out == 8888
    assert result.block_io_read == 7777
    assert result.block_io_write == 6666
    assert result.pids == 99

    await storage.close()


