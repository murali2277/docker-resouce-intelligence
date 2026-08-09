"""Phase 1 tests — bug fixes only, no Docker daemon required."""

import asyncio
import pytest
import time
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch

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
        timestamp=datetime.utcnow(),
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
            timestamp=datetime.utcnow() + timedelta(seconds=i),
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
            timestamp=datetime.utcnow() + timedelta(seconds=i),
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
            timestamp=datetime.utcnow() + timedelta(seconds=i),
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
