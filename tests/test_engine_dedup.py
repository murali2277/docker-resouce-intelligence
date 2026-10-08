"""
Tests for P0-4: alert de-duplication, re-notify window, and duration_seconds=0 fix.

Covers:
  - duration_seconds==0 must fire alert on the FIRST breach call
  - 10 consecutive breaching evaluations produce exactly 1 alert (per episode)
  - A second alert only fires after alert_renotify_seconds elapses
  - Clearing the breach resets the episode so a new breach fires again
  - violation_key is simplified (no container_id duplication)
"""

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch


def _make_agg_metrics(
    container_id: str = "abc123",
    container_name: str = "test-container",
    memory_percent: float = 90.0,
    growth_rate_5m: float = 0.0,
):
    from dri.utils.metrics import AggregatedMetrics
    return AggregatedMetrics(
        container_id=container_id,
        container_name=container_name,
        timestamp=datetime.now(timezone.utc),
        cpu_percent=0.0,
        cpu_percent_5m=0.0,
        cpu_percent_15m=0.0,
        cpu_percent_60m=0.0,
        memory_percent=memory_percent,
        memory_percent_5m=memory_percent,
        memory_percent_15m=memory_percent,
        memory_percent_60m=memory_percent,
        memory_growth_rate_1m=growth_rate_5m,
        memory_growth_rate_5m=growth_rate_5m,
    )


def _make_engine(duration_seconds: int = 60, renotify_seconds: int = 300):
    """Build a PolicyEngine with a single memory>80% rule."""
    from dri.core.engine import PolicyEngine
    from dri.config import DRIConfig, ContainerPolicy, ThresholdRule
    rule = ThresholdRule(
        metric="memory",
        operator=">",
        value=80.0,
        duration_seconds=duration_seconds,
        action="warning",
    )
    policy = ContainerPolicy(name="global", enabled=True, selector={}, rules=[rule])
    config = DRIConfig(global_policy=policy)
    config.alert_renotify_seconds = renotify_seconds
    engine = PolicyEngine(config)
    return engine


@pytest.mark.asyncio
async def test_zero_duration_fires_on_first_call():
    """P0-4: duration_seconds=0 must trigger an alert on the FIRST breaching call."""
    engine = _make_engine(duration_seconds=0)
    metrics = _make_agg_metrics(memory_percent=90.0)
    alerts = await engine.evaluate(metrics)
    assert alerts is not None, "Expected alert on first call with duration_seconds=0"
    assert len(alerts) == 1


@pytest.mark.asyncio
async def test_ten_consecutive_breaches_produce_one_alert():
    """P0-4: once an episode fires, repeated evaluations must NOT re-fire
    until alert_renotify_seconds has elapsed.
    """
    engine = _make_engine(duration_seconds=0, renotify_seconds=9999)
    metrics = _make_agg_metrics(memory_percent=90.0)
    all_alerts = []
    for _ in range(10):
        result = await engine.evaluate(metrics)
        if result:
            all_alerts.extend(result)
    assert len(all_alerts) == 1, (
        f"Expected exactly 1 alert across 10 ticks, got {len(all_alerts)}"
    )


@pytest.mark.asyncio
async def test_renotify_after_window_elapses():
    """P0-4: A second alert is allowed after alert_renotify_seconds passes."""
    engine = _make_engine(duration_seconds=0, renotify_seconds=300)
    metrics = _make_agg_metrics(memory_percent=90.0)
    first = await engine.evaluate(metrics)
    assert first is not None and len(first) == 1
    second = await engine.evaluate(metrics)
    assert not second
    rule_key = "memory"
    cid = "abc123"
    engine._last_alerted[cid][rule_key] = (
        datetime.now(timezone.utc) - timedelta(seconds=301)
    )
    third = await engine.evaluate(metrics)
    assert third is not None and len(third) == 1, (
        "Expected alert after re-notify window elapsed"
    )


@pytest.mark.asyncio
async def test_cleared_breach_resets_episode():
    """P0-4: When a violation clears, a new episode must fire an alert on first re-breach."""
    engine = _make_engine(duration_seconds=0, renotify_seconds=9999)
    breach_metrics = _make_agg_metrics(memory_percent=90.0)
    clear_metrics = _make_agg_metrics(memory_percent=50.0)
    a1 = await engine.evaluate(breach_metrics)
    assert a1 is not None and len(a1) == 1
    a2 = await engine.evaluate(clear_metrics)
    assert not a2
    a3 = await engine.evaluate(breach_metrics)
    assert a3 is not None and len(a3) == 1, (
        "Expected alert on re-breach after episode cleared"
    )
