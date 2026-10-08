"""
Tests for action handlers: throttle, isolate, heal (graceful_restart).

All Docker interactions are mocked — no running Docker daemon required.
Covers:
  - Successful action -> success=True
  - Logger kwargs TypeError regression (P0-1)
  - graceful_restart: stop() called before start() (P0-1)
  - _handle_alert_action dispatches restart alerts (P0-2)
  - Failed actions are recorded in storage (P0-2)
  - Per-container/rule cooldown prevents repeat firing (P0-2)
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch, call


def _make_docker_client(container):
    client = MagicMock()
    client.containers.get = MagicMock(return_value=container)
    return client


def _make_container(name="test-container"):
    c = MagicMock()
    c.name = name
    c.id = "abc123def456"
    c.update = MagicMock(return_value=None)
    c.stop = MagicMock(return_value=None)
    c.start = MagicMock(return_value=None)
    return c


def _make_alert(container_id="abc123", container_name="test-container",
                alert_type="throttle", metric="memory"):
    a = MagicMock()
    a.alert_id = "alert-001"
    a.container_id = container_id
    a.container_name = container_name
    a.alert_type = alert_type
    a.metric = metric
    a.message = f"{metric} threshold breached"
    a.to_dict = MagicMock(return_value={"container_id": container_id})
    return a


def _make_agent():
    from dri.main import DRIAgent
    from dri.config import DRIConfig
    config = DRIConfig()
    agent = DRIAgent(config)
    agent.storage = AsyncMock()
    agent.storage.save_action = AsyncMock()
    agent.throttle_action = AsyncMock()
    agent.throttle_action.throttle = AsyncMock(return_value={"success": True, "parameters": {}})
    agent.isolate_action = AsyncMock()
    agent.isolate_action.isolate = AsyncMock(return_value={"success": True, "cpuset": "0-1"})
    agent.heal_action = AsyncMock()
    agent.heal_action.graceful_restart = AsyncMock(
        return_value={"success": True, "action": "graceful_restart", "reason": "policy"}
    )
    agent.heal_action.trigger_webhook = AsyncMock(return_value=True)
    return agent


# --- ThrottleAction ---

@pytest.mark.asyncio
async def test_throttle_success():
    from dri.actions.throttle import ThrottleAction
    from dri.config import ThrottleConfig
    container = _make_container()
    action = ThrottleAction(_make_docker_client(container))
    result = await action.throttle("abc", ThrottleConfig(cpu_shares=512, memory_limit="512m"))
    assert result["success"] is True
    container.update.assert_called_once_with(
        cpu_shares=512, mem_limit=536870912, memswap_limit=536870912
    )


@pytest.mark.asyncio
async def test_throttle_not_found():
    import docker
    from dri.actions.throttle import ThrottleAction
    from dri.config import ThrottleConfig
    client = MagicMock()
    client.containers.get = MagicMock(side_effect=docker.errors.NotFound("x"))
    result = await ThrottleAction(client).throttle("abc", ThrottleConfig(cpu_shares=512, memory_limit="512m"))
    assert result["success"] is False
    assert "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_throttle_empty_config():
    from dri.actions.throttle import ThrottleAction
    from dri.config import ThrottleConfig
    container = _make_container()
    result = await ThrottleAction(_make_docker_client(container)).throttle("abc123", ThrottleConfig())
    assert result["success"] is False
    container.update.assert_not_called()


@pytest.mark.asyncio
async def test_throttle_memory_reservation_uses_correct_docker_key():
    """P0-2: memory_reservation must be passed as mem_reservation to container.update(),
    not as 'memory_reservation' (which docker-py ignores / rejects).
    Also asserts mem_limit and memswap_limit are set correctly for '512m'.
    """
    from dri.actions.throttle import ThrottleAction
    from dri.config import ThrottleConfig
    container = _make_container()
    result = await ThrottleAction(_make_docker_client(container)).throttle(
        "abc123", ThrottleConfig(memory_limit="512m", memory_reservation="256m")
    )
    assert result["success"] is True
    call_kwargs = container.update.call_args[1]
    # docker-py keys
    assert "mem_limit" in call_kwargs, "mem_limit not passed to container.update()"
    assert "memswap_limit" in call_kwargs, "memswap_limit not passed to container.update()"
    assert "mem_reservation" in call_kwargs, "mem_reservation not passed (got memory_reservation?)"
    assert "memory_reservation" not in call_kwargs, "wrong key 'memory_reservation' passed to container.update()"
    assert call_kwargs["mem_limit"] == 512 * 1024 * 1024
    assert call_kwargs["mem_reservation"] == 256 * 1024 * 1024


@pytest.mark.asyncio
async def test_throttle_no_typeerror_from_logger():
    """P0-1: logger kwargs must not raise TypeError."""
    from dri.actions.throttle import ThrottleAction
    from dri.config import ThrottleConfig
    container = _make_container()
    result = await ThrottleAction(_make_docker_client(container)).throttle(
        "abc123", ThrottleConfig(cpu_shares=256)
    )
    assert result["success"] is True


# --- IsolateAction ---

@pytest.mark.asyncio
async def test_isolate_success():
    from dri.actions.isolate import IsolateAction
    container = _make_container()
    result = await IsolateAction(_make_docker_client(container)).isolate("abc", "0-1")
    assert result["success"] is True
    container.update.assert_called_once_with(cpuset_cpus="0-1")


@pytest.mark.asyncio
async def test_isolate_not_found():
    import docker
    from dri.actions.isolate import IsolateAction
    client = MagicMock()
    client.containers.get = MagicMock(side_effect=docker.errors.NotFound("x"))
    result = await IsolateAction(client).isolate("missing", "0")
    assert result["success"] is False


@pytest.mark.asyncio
async def test_isolate_no_typeerror_from_logger():
    """P0-1: logger kwargs must not raise TypeError."""
    from dri.actions.isolate import IsolateAction
    container = _make_container()
    result = await IsolateAction(_make_docker_client(container)).isolate("abc123", "0")
    assert result["success"] is True


# --- HealAction.graceful_restart ---

@pytest.mark.asyncio
async def test_graceful_restart_success_stop_before_start():
    """P0-1: stop() must be called BEFORE start(), and result must be success=True."""
    from dri.actions.heal import HealAction
    container = _make_container()
    with patch("dri.actions.heal.time.sleep"):
        result = await HealAction(_make_docker_client(container)).graceful_restart("abc")
    assert result["success"] is True
    container.stop.assert_called_with(timeout=30)
    container.start.assert_called_once()


@pytest.mark.asyncio
async def test_graceful_restart_no_typeerror_from_logger():
    """P0-1 regression: logger inside _restart() must not abort the restart."""
    from dri.actions.heal import HealAction
    container = _make_container()
    with patch("dri.actions.heal.time.sleep"):
        result = await HealAction(_make_docker_client(container)).graceful_restart("abc123")
    assert result["success"] is True
    container.stop.assert_called_once()
    container.start.assert_called_once()


@pytest.mark.asyncio
async def test_graceful_restart_not_found():
    import docker
    from dri.actions.heal import HealAction
    client = MagicMock()
    client.containers.get = MagicMock(side_effect=docker.errors.NotFound("gone"))
    with patch("dri.actions.heal.time.sleep"):
        result = await HealAction(client).graceful_restart("gone")
    assert result["success"] is False


# --- DRIAgent._handle_alert_action ---

@pytest.mark.asyncio
async def test_alert_throttle_saved_to_storage():
    agent = _make_agent()
    await agent._handle_alert_action(_make_alert(alert_type="throttle"))
    agent.throttle_action.throttle.assert_called_once()
    agent.storage.save_action.assert_called_once()
    assert agent.storage.save_action.call_args[0][0].action_type == "throttle"
    assert agent.actions_executed == 1


@pytest.mark.asyncio
async def test_alert_isolate_saved_to_storage():
    agent = _make_agent()
    # isolate_cpuset must be configured or the branch guard skips the action
    agent.config.actions.isolate_cpuset = "0-1"
    await agent._handle_alert_action(_make_alert(alert_type="isolate", metric="cpu"))
    agent.isolate_action.isolate.assert_called_once()
    saved = agent.storage.save_action.call_args[0][0]
    assert saved.action_type == "isolate"


@pytest.mark.asyncio
async def test_alert_restart_dispatched():
    """P0-2: restart alert_type must call graceful_restart (was a no-op before)."""
    agent = _make_agent()
    alert = _make_alert(alert_type="restart")
    await agent._handle_alert_action(alert)
    agent.heal_action.graceful_restart.assert_called_once_with(
        alert.container_id,
        stop_timeout=agent.config.actions.restart_grace_period,
        reason=alert.message,
    )
    saved = agent.storage.save_action.call_args[0][0]
    assert saved.action_type == "restart"
    assert saved.success is True


@pytest.mark.asyncio
async def test_failed_action_still_recorded():
    """P0-2: failed actions must be recorded, not silently dropped."""
    agent = _make_agent()
    agent.throttle_action.throttle = AsyncMock(
        return_value={"success": False, "error": "Container not found"}
    )
    await agent._handle_alert_action(_make_alert(alert_type="throttle"))
    agent.storage.save_action.assert_called_once()
    saved = agent.storage.save_action.call_args[0][0]
    assert saved.success is False
    assert saved.error_message is not None
    assert agent.actions_executed == 0


@pytest.mark.asyncio
async def test_cooldown_prevents_repeat():
    """P0-2: same (container, type, metric) within cooldown must be suppressed."""
    agent = _make_agent()
    alert = _make_alert(alert_type="throttle")
    await agent._handle_alert_action(alert)
    await agent._handle_alert_action(alert)
    assert agent.throttle_action.throttle.call_count == 1
    assert agent.storage.save_action.call_count == 1


@pytest.mark.asyncio
async def test_cooldown_expired_allows_repeat():
    """Expired cooldown allows the action to fire again."""
    agent = _make_agent()
    alert = _make_alert(alert_type="throttle")
    await agent._handle_alert_action(alert)
    key = (alert.container_id, alert.alert_type, alert.metric)
    agent._action_cooldowns[key] = datetime.now(timezone.utc) - timedelta(
        seconds=agent._ACTION_COOLDOWN_SECONDS + 1
    )
    await agent._handle_alert_action(alert)
    assert agent.throttle_action.throttle.call_count == 2


@pytest.mark.asyncio
async def test_warning_alert_does_nothing():
    """warning alerts must not trigger any Docker action."""
    agent = _make_agent()
    await agent._handle_alert_action(_make_alert(alert_type="warning"))
    agent.throttle_action.throttle.assert_not_called()
    agent.isolate_action.isolate.assert_not_called()
    agent.heal_action.graceful_restart.assert_not_called()
    agent.storage.save_action.assert_not_called()


# --- P0-3: predict_oom wired into _policy_check_loop ---

@pytest.mark.asyncio
async def test_policy_check_loop_calls_predict_oom_and_emits_warning_alert():
    """P0-3: _policy_check_loop must call heal_action.predict_oom for each container
    and emit a 'warning' alert (via _on_alert) when risk_level is 'critical'.
    The test calls _policy_check_loop directly with running=False so only one
    iteration executes (the first asyncio.sleep is patched to return immediately
    and then running is set False to exit the while-loop).
    """
    import asyncio
    from dri.main import DRIAgent
    from dri.config import DRIConfig
    from dri.utils.metrics import AggregatedMetrics
    from datetime import datetime, timezone

    config = DRIConfig()
    agent = DRIAgent(config)
    agent.storage = AsyncMock()
    agent.storage.save_alert = AsyncMock()

    critical_metrics = AggregatedMetrics(
        container_id="crit001",
        container_name="crit-container",
        timestamp=datetime.now(timezone.utc),
        cpu_percent=10.0, cpu_percent_5m=10.0, cpu_percent_15m=10.0,
        cpu_percent_60m=10.0,
        memory_percent=97.0,  # > 95 -> critical
        memory_percent_5m=96.0, memory_percent_15m=95.0, memory_percent_60m=80.0,
        memory_growth_rate_1m=0.0, memory_growth_rate_5m=0.0,
    )

    mock_aggregator = AsyncMock()
    mock_aggregator.aggregate_all = AsyncMock(return_value={"crit001": critical_metrics})
    agent.aggregator = mock_aggregator

    mock_engine = AsyncMock()
    mock_engine.evaluate = AsyncMock(return_value=None)
    agent.policy_engine = mock_engine

    agent.heal_action = AsyncMock()
    agent.heal_action.predict_oom = AsyncMock(
        return_value={
            "container_id": "crit001",
            "container_name": "crit-container",
            "risk_level": "critical",
            "reason": "Memory at 97.0% of limit",
            "memory_percent": 97.0,
            "growth_rate_5m": 0.0,
        }
    )

    alerts_received = []

    async def fake_on_alert(alert):
        alerts_received.append(alert)
        if agent.storage:
            await agent.storage.save_alert(alert)

    agent._on_alert = fake_on_alert

    # Patch asyncio.sleep so the loop body executes once then stops
    async def sleep_then_stop(_):
        agent.running = False

    agent.running = True
    with patch("asyncio.sleep", side_effect=sleep_then_stop):
        await agent._policy_check_loop()

    # predict_oom MUST have been called by _policy_check_loop
    agent.heal_action.predict_oom.assert_called_once_with(critical_metrics)
    # And a warning alert MUST have been emitted
    assert len(alerts_received) >= 1, "_on_alert was never called with a warning"
    assert any(a.alert_type == "warning" for a in alerts_received)
    assert any(a.container_id == "crit001" for a in alerts_received)

