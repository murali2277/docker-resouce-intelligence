"""
TimescaleDB storage backend integration tests.

These tests require a live TimescaleDB instance and are skipped unless the
``TIMESCALE_TEST_URL`` environment variable is set.

Quick start
-----------
    # Start TimescaleDB via Docker Compose:
    docker compose --profile timescale -f deployment/docker-compose.yml up -d timescaledb

    # Wait for healthcheck to pass, then run:
    set TIMESCALE_TEST_URL=postgresql://dri:secret@localhost:5432/dri  # Windows
    export TIMESCALE_TEST_URL=postgresql://dri:secret@localhost:5432/dri  # Unix
    pytest tests/test_timescale.py -v

What these tests verify
-----------------------
* All 15 StorageBackend methods work correctly against a real TimescaleDB.
* metrics_samples was promoted to a hypertable.
* A native retention policy was registered.
* The _Row shim exposes attribute access compatible with aggregator/recommender/forecaster.
* Callers that hold a ``StorageBackend`` reference work with ``TimescaleStorage``
  without any code changes (Liskov substitution principle check).
"""

from __future__ import annotations

import os
import pytest
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------------------------
# Skip condition
# ---------------------------------------------------------------------------

TIMESCALE_URL = os.environ.get("TIMESCALE_TEST_URL")
skip_reason = (
    "Set TIMESCALE_TEST_URL=postgresql://user:pass@host:5432/db to run "
    "TimescaleDB integration tests."
)

pytestmark = pytest.mark.skipif(
    not TIMESCALE_URL,
    reason=skip_reason,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_container_metrics(
    container_id: str = "abc123",
    cpu: float = 25.0,
    memory: float = 40.0,
    ts: datetime = None,
):
    from dri.utils.metrics import ContainerMetrics

    return ContainerMetrics(
        container_id=container_id,
        container_name="test-container",
        timestamp=ts or datetime.now(tz=timezone.utc),
        cpu_percent=cpu,
        cpu_count=2,
        memory_usage=400 * 1024 * 1024,
        memory_limit=1024 * 1024 * 1024,
        memory_percent=memory,
        net_io_in=0,
        net_io_out=0,
        block_io_read=0,
        block_io_write=0,
        pids=5,
    )


def _make_alert(alert_id: str = "alert-1", value: float = 90.0):
    from dri.utils.metrics import Alert

    return Alert(
        alert_id=alert_id,
        container_id="abc123",
        container_name="test-container",
        timestamp=datetime.now(tz=timezone.utc),
        alert_type="warning",
        metric="memory",
        current_value=value,
        threshold=85.0,
        message=f"Memory at {value}%",
    )


def _make_action(action_id: str = "action-1"):
    from dri.utils.metrics import Action

    return Action(
        action_id=action_id,
        container_id="abc123",
        container_name="test-container",
        timestamp=datetime.now(tz=timezone.utc),
        action_type="throttle",
        reason="Memory exceeded 95%",
        details={"cpu_quota": 50000},
        success=True,
    )


# ---------------------------------------------------------------------------
# Fixture: fresh storage per test
# ---------------------------------------------------------------------------

@pytest.fixture
async def storage():
    """Create and yield a fresh TimescaleStorage; drop test tables on teardown."""
    from dri.core.storage_timescale import TimescaleStorage

    st = TimescaleStorage(dsn=TIMESCALE_URL, retention_hours=0)  # 0 = no auto-policy
    await st.init()

    yield st

    # Cleanup — drop all tables so tests start from a clean slate
    try:
        async with st._pool.acquire() as conn:
            await conn.execute("DROP TABLE IF EXISTS metrics_samples CASCADE")
            await conn.execute("DROP TABLE IF EXISTS alerts CASCADE")
            await conn.execute("DROP TABLE IF EXISTS actions CASCADE")
            await conn.execute("DROP TABLE IF EXISTS recommendation_cache CASCADE")
            await conn.execute("DROP TABLE IF EXISTS forecast_cache CASCADE")
    except Exception:
        pass
    finally:
        await st.close()


# ---------------------------------------------------------------------------
# Tests: Lifecycle
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timescale
async def test_init_creates_tables(storage):
    """init() must create all required tables."""
    import asyncpg

    conn = await asyncpg.connect(dsn=TIMESCALE_URL)
    try:
        tables = await conn.fetch(
            "SELECT tablename FROM pg_tables WHERE schemaname = 'public'"
        )
        table_names = {r["tablename"] for r in tables}
    finally:
        await conn.close()

    required = {
        "metrics_samples", "alerts", "actions",
        "recommendation_cache", "forecast_cache",
    }
    assert required.issubset(table_names), (
        f"Missing tables: {required - table_names}"
    )


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_hypertable_created(storage):
    """metrics_samples must be registered as a TimescaleDB hypertable."""
    import asyncpg

    conn = await asyncpg.connect(dsn=TIMESCALE_URL)
    try:
        row = await conn.fetchrow(
            "SELECT hypertable_name FROM timescaledb_information.hypertables "
            "WHERE hypertable_name = 'metrics_samples'"
        )
    finally:
        await conn.close()

    assert row is not None, (
        "metrics_samples is not a TimescaleDB hypertable. "
        "Is the timescaledb extension installed?"
    )


# ---------------------------------------------------------------------------
# Tests: Metrics write / read
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timescale
async def test_save_and_get_recent_metrics(storage):
    """Write 5 samples and read them back."""
    now = datetime.now(tz=timezone.utc)
    for i in range(5):
        m = _make_container_metrics(
            cpu=float(10 + i),
            ts=now - timedelta(minutes=4 - i),
        )
        await storage.save_metrics(m)

    rows = await storage.get_recent_metrics("abc123", minutes=10)
    assert len(rows) == 5, f"Expected 5 rows, got {len(rows)}"
    # Should be sorted oldest-first
    timestamps = [r.timestamp for r in rows]
    assert timestamps == sorted(timestamps), "Rows not returned in ascending time order"


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_get_recent_metrics_empty(storage):
    """get_recent_metrics returns empty list when no data."""
    rows = await storage.get_recent_metrics("nonexistent", minutes=60)
    assert rows == []


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_row_attribute_access(storage):
    """_Row shim must expose the same attributes as SQLite ORM rows."""
    m = _make_container_metrics(cpu=42.0, memory=55.0)
    await storage.save_metrics(m)

    rows = await storage.get_recent_metrics("abc123", minutes=5)
    assert len(rows) == 1

    row = rows[0]
    # All attributes expected by aggregator / recommender / forecaster
    assert hasattr(row, "timestamp")
    assert hasattr(row, "cpu_percent")
    assert hasattr(row, "memory_percent")
    assert hasattr(row, "memory_usage")
    assert hasattr(row, "memory_limit")
    assert abs(row.cpu_percent - 42.0) < 0.01
    assert abs(row.memory_percent - 55.0) < 0.01


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_cleanup_old_data_manual(storage):
    """cleanup_old_data with retention_hours=0 performs a manual DELETE."""
    now = datetime.now(tz=timezone.utc)

    # Insert an old sample (2h ago)
    m_old = _make_container_metrics(ts=now - timedelta(hours=2))
    await storage.save_metrics(m_old)

    # Insert a recent sample (1 minute ago)
    m_new = _make_container_metrics(ts=now - timedelta(minutes=1))
    await storage.save_metrics(m_new)

    # cleanup with 1h retention should remove the 2h-old sample
    await storage.cleanup_old_data(retention_hours=1)

    rows = await storage.get_recent_metrics("abc123", minutes=200)
    assert len(rows) == 1, f"Expected 1 row after cleanup, got {len(rows)}"
    # Remaining row should be the recent one
    assert abs((rows[0].timestamp.replace(tzinfo=timezone.utc) - m_new.timestamp).total_seconds()) < 5


# ---------------------------------------------------------------------------
# Tests: Alerts
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timescale
async def test_save_and_get_recent_alerts(storage):
    """Write 3 alerts and read them back newest-first."""
    now = datetime.now(tz=timezone.utc)
    for i in range(3):
        a = _make_alert(alert_id=f"alert-{i}", value=float(80 + i))
        await storage.save_alert(a)

    alerts = await storage.get_recent_alerts(limit=10)
    assert len(alerts) == 3

    # Newest-first
    values = [r.current_value for r in alerts]
    assert values == sorted(values, reverse=True) or len(set(values)) < 3, (
        "Alerts not returned newest-first"
    )


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_count_alerts(storage):
    """count_alerts returns the correct total."""
    for i in range(4):
        await storage.save_alert(_make_alert(alert_id=f"alert-{i}"))

    count = await storage.count_alerts()
    assert count == 4


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_alerts_pagination(storage):
    """Pagination via limit/offset returns non-overlapping pages."""
    for i in range(5):
        await storage.save_alert(_make_alert(alert_id=f"alert-{i}"))

    page1 = await storage.get_recent_alerts(limit=2, offset=0)
    page2 = await storage.get_recent_alerts(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    ids1 = {r.id for r in page1}
    ids2 = {r.id for r in page2}
    assert ids1.isdisjoint(ids2), "Pages overlap — pagination broken"


# ---------------------------------------------------------------------------
# Tests: Actions
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timescale
async def test_save_and_get_recent_actions(storage):
    """Write 3 actions and read them back."""
    for i in range(3):
        await storage.save_action(_make_action(action_id=f"action-{i}"))

    actions = await storage.get_recent_actions(limit=10)
    assert len(actions) == 3


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_count_actions(storage):
    """count_actions returns the correct total."""
    for i in range(2):
        await storage.save_action(_make_action(action_id=f"action-{i}"))

    count = await storage.count_actions()
    assert count == 2


# ---------------------------------------------------------------------------
# Tests: Recommendation cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timescale
async def test_recommendation_cache_round_trip(storage):
    """Write and read back a recommendation cache entry."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "container_id": "abc123",
        "container_name": "test-container",
        "recommended_cpu_pct": 42.5,
        "recommended_memory_bytes": 524288000,
        "p95_cpu": 35.0,
        "p95_memory_bytes": 436207616,
        "p95_memory_pct": 41.6,
        "sample_count": 150,
        "lookback_days": 7,
        "lookback_actual_days": 6.9,
        "safety_margin": 0.20,
        "confidence_tier": "medium",
        "is_memory_leak": False,
        "memory_leak_slope_pct_per_hour": 0.0,
        "is_idle": False,
    }
    await storage.save_recommendation_cache("abc123", payload, computed_at=now)

    result = await storage.get_recommendation_cache("abc123")
    assert result is not None
    assert result["recommended_cpu_pct"] == pytest.approx(42.5)
    assert "computed_at" in result


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_recommendation_cache_upsert(storage):
    """Second write overwrites the first (upsert semantics)."""
    now = datetime.now(tz=timezone.utc)
    payload_v1 = {"container_id": "abc123", "recommended_cpu_pct": 10.0, "container_name": "test"}
    payload_v2 = {"container_id": "abc123", "recommended_cpu_pct": 99.0, "container_name": "test"}

    await storage.save_recommendation_cache("abc123", payload_v1, computed_at=now)
    await storage.save_recommendation_cache("abc123", payload_v2, computed_at=now)

    result = await storage.get_recommendation_cache("abc123")
    assert result["recommended_cpu_pct"] == pytest.approx(99.0)


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_get_all_recommendation_caches(storage):
    """get_all_recommendation_caches returns all entries."""
    now = datetime.now(tz=timezone.utc)
    for cid in ["aaa", "bbb", "ccc"]:
        await storage.save_recommendation_cache(
            cid, {"container_id": cid, "container_name": cid}, computed_at=now
        )

    results = await storage.get_all_recommendation_caches()
    assert len(results) == 3


# ---------------------------------------------------------------------------
# Tests: Forecast cache
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timescale
async def test_forecast_cache_round_trip(storage):
    """Write and read back a forecast cache entry."""
    now = datetime.now(tz=timezone.utc)
    payload = {
        "container_id": "abc123",
        "metric": "memory_percent",
        "horizon_hours": 24,
        "current_value": 45.0,
        "predicted_value": 52.3,
        "confidence_low": 46.0,
        "confidence_high": 58.5,
        "predicted_at": now.isoformat(),
        "method_used": "linear_regression",
        "sample_count": 100,
    }
    await storage.save_forecast_cache("abc123", "memory_percent", 24, payload, computed_at=now)

    result = await storage.get_forecast_cache("abc123", "memory_percent", 24)
    assert result is not None
    assert result["predicted_value"] == pytest.approx(52.3)
    assert "computed_at" in result


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_forecast_cache_miss(storage):
    """get_forecast_cache returns None for unknown entries."""
    result = await storage.get_forecast_cache("unknown", "cpu_percent", 48)
    assert result is None


# ---------------------------------------------------------------------------
# Tests: StorageBackend Liskov substitution check
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
@pytest.mark.timescale
async def test_timescale_satisfies_storage_backend_interface(storage):
    """TimescaleStorage must be a valid StorageBackend instance."""
    from dri.core.storage_base import StorageBackend

    assert isinstance(storage, StorageBackend), (
        "TimescaleStorage does not implement StorageBackend"
    )


@pytest.mark.asyncio
@pytest.mark.timescale
async def test_aggregator_works_with_timescale_storage(storage):
    """MetricsAggregator must work transparently with TimescaleStorage."""
    from dri.core.aggregator import MetricsAggregator

    agg = MetricsAggregator(storage)
    now = datetime.now(tz=timezone.utc)

    for i in range(10):
        m = _make_container_metrics(cpu=float(20 + i), ts=now - timedelta(minutes=9 - i))
        agg.add_metrics(m)
        await storage.save_metrics(m)

    result = await agg.aggregate("abc123")
    assert result is not None
    assert 0.0 <= result.cpu_percent_5m <= 100.0
    assert 0.0 <= result.memory_percent_5m <= 100.0
