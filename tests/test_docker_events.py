"""Tests for Docker Event Tracking (Storage, API routes, and Restart counting)."""

import asyncio
import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from dri.core.storage import MetricsStorage
from dri.events.listener import ContainerEvent
from dri.api.routes import router, set_dependencies
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.mark.asyncio
async def test_storage_save_and_get_events():
    """Verify Docker events round-trip through save_event / get_recent_events / count_events."""
    storage = MetricsStorage(":memory:")
    await storage.init()

    # Verify empty state
    events = await storage.get_recent_events()
    assert events == []
    assert await storage.count_events() == 0

    now = datetime.now(timezone.utc)
    ev1 = {
        "container_id": "c11111111111",
        "container_name": "app-web",
        "event_type": "container",
        "action": "die",
        "timestamp": now - timedelta(seconds=10),
        "attributes": {"exitCode": "137"},
    }
    ev2 = {
        "container_id": "c11111111111",
        "container_name": "app-web",
        "event_type": "container",
        "action": "start",
        "timestamp": now - timedelta(seconds=5),
        "attributes": {"image": "web:v1"},
    }
    ev3 = {
        "container_id": "c22222222222",
        "container_name": "app-db",
        "event_type": "container",
        "action": "oom",
        "timestamp": now,
        "attributes": {},
    }

    await storage.save_event(ev1)
    await storage.save_event(ev2)
    await storage.save_event(ev3)

    assert await storage.count_events() == 3
    assert await storage.count_events("c11111111111") == 2
    assert await storage.count_events("c22222222222") == 1

    # Order newest-first
    recent = await storage.get_recent_events()
    assert len(recent) == 3
    assert recent[0].action == "oom"
    assert recent[1].action == "start"
    assert recent[2].action == "die"

    # Container ID filter
    filtered = await storage.get_recent_events(container_id="c11111111111")
    assert len(filtered) == 2
    assert all(r.container_id == "c11111111111" for r in filtered)

    await storage.close()


@pytest.mark.asyncio
async def test_events_api_endpoint():
    """Verify /api/v1/events endpoint pagination & serialization."""
    storage = MetricsStorage(":memory:")
    await storage.init()

    mock_agg = MagicMock()
    mock_pe = MagicMock()

    set_dependencies(s=storage, a=mock_agg, pe=mock_pe)

    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    # Save event
    event_data = {
        "container_id": "abc123def456",
        "container_name": "test-app",
        "event_type": "container",
        "action": "oom",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "attributes": {"memory_limit": "512MB"},
    }
    await storage.save_event(event_data)

    res = client.get("/api/v1/events")
    assert res.status_code == 200
    body = res.json()
    assert body["total_count"] == 1
    assert len(body["events"]) == 1
    ev = body["events"][0]
    assert ev["container_id"] == "abc123def456"
    assert ev["action"] == "oom"
    assert ev["attributes"] == {"memory_limit": "512MB"}

    # Test filtering by container_id
    res_filtered = client.get("/api/v1/events?container_id=nonexistent")
    assert res_filtered.status_code == 200
    assert res_filtered.json()["total_count"] == 0

    await storage.close()


@pytest.mark.asyncio
async def test_restart_count_tracking():
    """Verify restart_count increments across die -> start sequence for a container."""
    from dri.main import DRIAgent
    from dri.config import DRIConfig

    config = DRIConfig()
    agent = DRIAgent(config)

    storage = MetricsStorage(":memory:")
    await storage.init()
    agent.storage = storage

    aggregator = MagicMock()
    agent.aggregator = aggregator

    cid = "testcontain1"

    # Simulate ContainerEvent for die
    die_data = {
        "Type": "container",
        "Action": "die",
        "Actor": {"ID": cid, "Attributes": {"name": "my-service"}},
    }
    event_die = ContainerEvent(die_data)

    await agent._on_docker_event(event_die)
    assert agent.restart_counts.get(cid, 0) == 0
    assert cid in agent._container_died

    # Simulate ContainerEvent for start (sequence die -> start)
    start_data = {
        "Type": "container",
        "Action": "start",
        "Actor": {"ID": cid, "Attributes": {"name": "my-service"}},
    }
    event_start = ContainerEvent(start_data)

    await agent._on_docker_event(event_start)
    assert agent.restart_counts.get(cid) == 1
    assert cid not in agent._container_died
    aggregator.update_restart_count.assert_called_with(cid, 1)

    # Second restart sequence (die -> start)
    await agent._on_docker_event(event_die)
    await agent._on_docker_event(event_start)
    assert agent.restart_counts.get(cid) == 2
    aggregator.update_restart_count.assert_called_with(cid, 2)

    # Isolated start (without preceding die) should NOT increment restart_count
    await agent._on_docker_event(event_start)
    assert agent.restart_counts.get(cid) == 2

    # Verify event was saved to storage
    events_in_db = await storage.get_recent_events(container_id=cid[:12])
    assert len(events_in_db) == 5

    await storage.close()
