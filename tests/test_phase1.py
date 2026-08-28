"""Phase 1 tests — bug fixes only, no Docker daemon required."""

import asyncio
import pytest
import time
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from dri.utils.metrics import ContainerMetrics

# ---------------------------------------------------------------------------
# Config validators
# ---------------------------------------------------------------------------


def test_threshold_rule_valid_operator():
    from dri.config import ThresholdRule

    rule = ThresholdRule(metric="cpu", operator=">", value=80.0, action="warning")
    assert rule.operator == ">"


def test_threshold_rule_invalid_operator():
    from dri.config import ThresholdRule
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ThresholdRule(metric="cpu", operator="!=", value=80.0, action="warning")


def test_threshold_rule_invalid_action():
    from dri.config import ThresholdRule
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        ThresholdRule(metric="cpu", operator=">", value=80.0, action="explode")


def test_dri_config_valid_log_level():
    from dri.config import DRIConfig

    config = DRIConfig(log_level="DEBUG")
    assert config.log_level == "DEBUG"


def test_dri_config_invalid_log_level():
    from dri.config import DRIConfig
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        DRIConfig(log_level="VERBOSE")


# ---------------------------------------------------------------------------
# MetricsAggregator.metrics_processed counter
# ---------------------------------------------------------------------------


def _make_metrics(container_id: str = "abc123", cpu: float = 10.0) -> "ContainerMetrics":
    from dri.utils.metrics import ContainerMetrics

    return ContainerMetrics(
        container_id=container_id,
        container_name="test-container",
        timestamp=datetime.now(timezone.utc),
        cpu_percent=cpu,
        cpu_count=2,
        memory_usage=100 * 1024 * 1024,
        memory_limit=1024 * 1024 * 1024,
        memory_percent=10.0,
        net_io_in=0,
        net_io_out=0,
        block_io_read=0,
        block_io_write=0,
        pids=5,
    )


@pytest.mark.asyncio
async def test_aggregator_metrics_processed_counter():
    """metrics_processed increments on every add_metrics call."""
    from dri.core.aggregator import MetricsAggregator

    storage_mock = MagicMock()
    agg = MetricsAggregator(storage_mock)

    assert agg.metrics_processed == 0

    for i in range(5):
        agg.add_metrics(_make_metrics())

    assert agg.metrics_processed == 5


# ---------------------------------------------------------------------------
# Storage: get_recent_alerts / get_recent_actions
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_storage_get_recent_alerts_empty():
    """get_recent_alerts returns empty list when nothing stored."""
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()
    alerts = await storage.get_recent_alerts(limit=10)
    assert alerts == []
    await storage.close()


@pytest.mark.asyncio
async def test_storage_get_recent_alerts_returns_data():
    """get_recent_alerts returns stored alerts newest-first."""
    from dri.core.storage import MetricsStorage
    from dri.utils.metrics import Alert

    storage = MetricsStorage(":memory:")
    await storage.init()

    for i in range(3):
        alert = Alert(
            alert_id=f"alert-{i}",
            container_id="abc123",
            container_name="test",
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=i),
            alert_type="warning",
            metric="cpu",
            current_value=float(80 + i),
            threshold=80.0,
            message=f"Alert {i}",
        )
        await storage.save_alert(alert)

    alerts = await storage.get_recent_alerts(limit=10)
    assert len(alerts) == 3
    # Newest-first ordering
    assert alerts[0].current_value >= alerts[1].current_value >= alerts[2].current_value

    count = await storage.count_alerts()
    assert count == 3

    await storage.close()


@pytest.mark.asyncio
async def test_storage_get_recent_actions_empty():
    """get_recent_actions returns empty list when nothing stored."""
    from dri.core.storage import MetricsStorage

    storage = MetricsStorage(":memory:")
    await storage.init()
    actions = await storage.get_recent_actions(limit=10)
    assert actions == []
    await storage.close()


@pytest.mark.asyncio
async def test_storage_get_recent_actions_returns_data():
    """get_recent_actions returns stored actions newest-first."""
    from dri.core.storage import MetricsStorage
    from dri.utils.metrics import Action

    storage = MetricsStorage(":memory:")
    await storage.init()

    for i in range(3):
        action = Action(
            action_id=f"action-{i}",
            container_id="abc123",
            container_name="test",
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=i),
            action_type="throttle",
            reason=f"Reason {i}",
            details={"cpu_quota": 50000},
            success=True,
        )
        await storage.save_action(action)

    actions = await storage.get_recent_actions(limit=10)
    assert len(actions) == 3
    count = await storage.count_actions()
    assert count == 3

    await storage.close()


@pytest.mark.asyncio
async def test_storage_get_recent_alerts_pagination():
    """get_recent_alerts respects limit and offset."""
    from dri.core.storage import MetricsStorage
    from dri.utils.metrics import Alert

    storage = MetricsStorage(":memory:")
    await storage.init()

    for i in range(5):
        alert = Alert(
            alert_id=f"alert-{i}",
            container_id="abc123",
            container_name="test",
            timestamp=datetime.now(timezone.utc) + timedelta(seconds=i),
            alert_type="warning",
            metric="cpu",
            current_value=float(80 + i),
            threshold=80.0,
            message=f"Alert {i}",
        )
        await storage.save_alert(alert)

    page1 = await storage.get_recent_alerts(limit=2, offset=0)
    page2 = await storage.get_recent_alerts(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    # Pages should not overlap
    ids1 = {r.id for r in page1}
    ids2 = {r.id for r in page2}
    assert ids1.isdisjoint(ids2)

    await storage.close()


# ---------------------------------------------------------------------------
# heal.py: time.sleep instead of asyncio.run
# ---------------------------------------------------------------------------


def test_heal_uses_time_sleep_not_asyncio_run():
    """_restart() must use time.sleep — not asyncio.run(asyncio.sleep(...))."""
    import inspect
    import dri.actions.heal as heal_module

    source = inspect.getsource(heal_module)
    assert "time.sleep(2)" in source, "time.sleep(2) must be present in heal.py"
    assert "asyncio.run(asyncio.sleep" not in source, (
        "asyncio.run(asyncio.sleep(...)) must not be in heal.py"
    )


# ---------------------------------------------------------------------------
# declarative_base import migration
# ---------------------------------------------------------------------------


def test_storage_uses_orm_declarative_base():
    """storage.py must import declarative_base from sqlalchemy.orm, not ext.declarative."""
    import inspect
    import dri.core.storage as storage_module

    source = inspect.getsource(storage_module)
    assert "sqlalchemy.ext.declarative" not in source, (
        "declarative_base must not be imported from sqlalchemy.ext.declarative"
    )
    assert "sqlalchemy.orm" in source and "declarative_base" in source


# ---------------------------------------------------------------------------
# Collector _parse_stats CPU calculation
# ---------------------------------------------------------------------------


def test_collector_parse_stats_cpu_calculation():
    """_parse_stats calculates CPU percent using deltas correctly."""
    from dri.core.collector import DockerStatsCollector
    from unittest.mock import MagicMock

    collector = DockerStatsCollector()
    container_mock = MagicMock()
    container_mock.id = "abc123def456"
    container_mock.name = "test_container"

    # Test normal calculation
    stats_data = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1500},
            "system_cpu_usage": 3000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 1000},
            "system_cpu_usage": 2000,
        },
        "memory_stats": {"usage": 1024, "limit": 2048},
        "networks": {},
        "blkio_stats": {},
        "pids_stats": {"current": 5},
    }
    metrics = collector._parse_stats(container_mock, stats_data)
    # delta_cpu = 500, delta_system = 1000, cpus = 2
    # cpu_percent = (500 / 1000) * 2 * 100 = 100.0
    assert metrics is not None
    assert metrics.cpu_percent == 100.0
    assert metrics.cpu_count == 2

    # Test first sample (precpu_stats is empty/zeroed)
    stats_data_first = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1500},
            "system_cpu_usage": 3000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 0},
            "system_cpu_usage": 0,
        },
        "memory_stats": {"usage": 1024, "limit": 2048},
    }
    metrics_first = collector._parse_stats(container_mock, stats_data_first)
    assert metrics_first is not None
    assert metrics_first.cpu_percent == 0.0

    # Test missing precpu_stats
    stats_data_missing = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1500},
            "system_cpu_usage": 3000,
            "online_cpus": 2,
        },
        "memory_stats": {"usage": 1024, "limit": 2048},
    }
    metrics_missing = collector._parse_stats(container_mock, stats_data_missing)
    assert metrics_missing is not None
    assert metrics_missing.cpu_percent == 0.0

    # Test negative delta (e.g. daemon restart)
    stats_data_negative = {
        "cpu_stats": {
            "cpu_usage": {"total_usage": 1500},
            "system_cpu_usage": 3000,
            "online_cpus": 2,
        },
        "precpu_stats": {
            "cpu_usage": {"total_usage": 2000},
            "system_cpu_usage": 4000,
        },
        "memory_stats": {"usage": 1024, "limit": 2048},
    }
    metrics_negative = collector._parse_stats(container_mock, stats_data_negative)
    assert metrics_negative is not None
    assert metrics_negative.cpu_percent == 0.0


def test_collector_parse_stats_memory_cgroup_v1_v2_and_unlimited():
    """_parse_stats correctly subtracts cache/inactive_file and guards against huge memory_limit."""
    from dri.core.collector import DockerStatsCollector
    from unittest.mock import MagicMock

    collector = DockerStatsCollector()
    container_mock = MagicMock()
    container_mock.id = "abc123def456"
    container_mock.name = "test_container"

    # 1. cgroup v1 style: cache key in memory_stats.stats
    stats_v1 = {
        "memory_stats": {
            "usage": 2048,
            "limit": 4096,
            "stats": {"cache": 512, "inactive_file": 256},
        }
    }
    metrics_v1 = collector._parse_stats(container_mock, stats_v1)
    assert metrics_v1 is not None
    # raw_usage (2048) - cache (512) = 1536
    assert metrics_v1.memory_usage == 1536
    assert metrics_v1.memory_percent == 37.5

    # 2. cgroup v2 style: only inactive_file key in memory_stats.stats
    stats_v2 = {
        "memory_stats": {
            "usage": 2048,
            "limit": 4096,
            "stats": {"inactive_file": 512},
        }
    }
    metrics_v2 = collector._parse_stats(container_mock, stats_v2)
    assert metrics_v2 is not None
    # raw_usage (2048) - inactive_file (512) = 1536
    assert metrics_v2.memory_usage == 1536
    assert metrics_v2.memory_percent == 37.5

    # 3. Unlimited/huge memory limit (e.g. 9223372036854771712)
    stats_unlimited = {
        "memory_stats": {
            "usage": 1024 * 1024 * 100,  # 100 MB
            "limit": 9223372036854771712,  # Huge cgroup limit
            "stats": {"cache": 1024 * 1024 * 10},  # 10 MB cache
        }
    }
    metrics_unlimited = collector._parse_stats(container_mock, stats_unlimited)
    assert metrics_unlimited is not None
    assert metrics_unlimited.memory_usage == 1024 * 1024 * 90
    assert metrics_unlimited.memory_percent == 0.0

