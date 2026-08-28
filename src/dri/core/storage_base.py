"""Abstract base class defining the DRI storage backend contract.

All storage backends (SQLite, TimescaleDB, …) must implement every method
defined here.  Callers (aggregator, recommender, forecaster, API routes)
depend only on this interface — never on a concrete implementation.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional


class StorageBackend(ABC):
    """Abstract storage interface for DRI metrics, alerts, actions, and caches."""

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    @abstractmethod
    async def init(self) -> None:
        """Create tables / schema if they don't exist.  Must be idempotent."""

    @abstractmethod
    async def close(self) -> None:
        """Release all resources (connections, pools, file handles)."""

    # ------------------------------------------------------------------
    # Metrics
    # ------------------------------------------------------------------

    @abstractmethod
    async def save_metrics(self, metrics: Any) -> None:
        """Persist a single ContainerMetrics sample.

        Args:
            metrics: dri.utils.metrics.ContainerMetrics instance.
        """

    @abstractmethod
    async def get_recent_metrics(
        self,
        container_id: str,
        minutes: int = 60,
    ) -> List[Any]:
        """Return raw metric rows for *container_id* covering the last *minutes*.

        Returns:
            List of objects exposing at minimum:
                .timestamp, .cpu_percent, .memory_percent,
                .memory_usage, .memory_limit
            Empty list when no data exists; raises on genuine I/O errors.
        """

    @abstractmethod
    async def cleanup_old_data(self, retention_hours: int = 168) -> None:
        """Delete metrics older than *retention_hours*.

        Implementations backed by database-native retention policies
        (e.g. TimescaleDB ``add_retention_policy``) may implement this
        as a no-op.
        """

    # ------------------------------------------------------------------
    # Alerts
    # ------------------------------------------------------------------

    @abstractmethod
    async def save_alert(self, alert: Any) -> None:
        """Persist a dri.utils.metrics.Alert."""

    @abstractmethod
    async def get_recent_alerts(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Any]:
        """Return alerts ordered newest-first with pagination."""

    @abstractmethod
    async def count_alerts(self) -> int:
        """Return total number of stored alerts."""

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    @abstractmethod
    async def save_action(self, action: Any) -> None:
        """Persist a dri.utils.metrics.Action."""

    @abstractmethod
    async def get_recent_actions(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Any]:
        """Return actions ordered newest-first with pagination."""

    @abstractmethod
    async def count_actions(self) -> int:
        """Return total number of stored actions."""

    # ------------------------------------------------------------------
    # Events
    # ------------------------------------------------------------------

    @abstractmethod
    async def save_event(self, event: Any) -> None:
        """Persist a Docker event (dri.events.listener.ContainerEvent or equivalent)."""

    @abstractmethod
    async def get_recent_events(
        self,
        container_id: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Any]:
        """Return events ordered newest-first with pagination and optional container_id filter."""

    @abstractmethod
    async def count_events(self, container_id: Optional[str] = None) -> int:
        """Return total number of stored events, optionally filtered by container_id."""

    # ------------------------------------------------------------------
    # Recommendation cache
    # ------------------------------------------------------------------

    @abstractmethod
    async def save_recommendation_cache(
        self,
        container_id: str,
        payload: dict,
        computed_at: datetime,
    ) -> None:
        """Upsert a serialised recommendation for *container_id*."""

    @abstractmethod
    async def get_recommendation_cache(
        self,
        container_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Return the cached recommendation dict (with ``computed_at`` injected)
        or ``None`` if absent."""

    @abstractmethod
    async def get_all_recommendation_caches(self) -> List[Dict[str, Any]]:
        """Return every cached recommendation (used by the list endpoint)."""

    # ------------------------------------------------------------------
    # Forecast cache
    # ------------------------------------------------------------------

    @abstractmethod
    async def save_forecast_cache(
        self,
        container_id: str,
        metric: str,
        horizon_hours: int,
        payload: dict,
        computed_at: datetime,
    ) -> None:
        """Upsert a serialised forecast for ``(container_id, metric, horizon)``."""

    @abstractmethod
    async def get_forecast_cache(
        self,
        container_id: str,
        metric: str,
        horizon_hours: int,
    ) -> Optional[Dict[str, Any]]:
        """Return cached forecast dict (with ``computed_at`` injected) or ``None``."""
