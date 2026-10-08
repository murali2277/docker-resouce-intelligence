"""Metrics aggregator for moving averages and anomaly detection."""

import asyncio
from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple
import statistics

from ..utils.logger import get_logger
from ..utils.metrics import ContainerMetrics, AggregatedMetrics
from .storage import MetricsSample
from .storage_base import StorageBackend
from .recommender import z_score_anomaly

logger = get_logger("aggregator")


class MetricsAggregator:
    """Calculate moving averages and detect anomalies."""

    def __init__(self, storage: StorageBackend):
        """
        Initialize aggregator.

        Args:
            storage: StorageBackend instance for data persistence
        """
        self.storage = storage
        self._windows: Dict[str, deque] = {}  # Container ID -> metrics deque
        self._max_samples = 1000  # Max samples to keep in memory
        self.metrics_processed: int = 0  # Total samples added across all containers

        # Tracks containers that have stopped.  Keyed by 12-char container ID;
        # value is the datetime (UTC) when the stop was first detected.
        # Populated by mark_container_stopped(); cleared by either
        # unmark_container_stopped() (container restarted) or
        # cleanup_stopped_containers() (window eviction after grace period).
        self._stopped_at: Dict[str, datetime] = {}

        # In-memory restart counters per container ID (populated by DRIAgent / _on_docker_event).
        self.restart_counts: Dict[str, int] = {}

    def _get_window(self, container_id: str) -> deque:
        """Get or create metric window for container."""
        if container_id not in self._windows:
            self._windows[container_id] = deque(maxlen=self._max_samples)
        return self._windows[container_id]

    def add_metrics(self, metrics: ContainerMetrics) -> None:
        """Add metrics sample to window."""
        window = self._get_window(metrics.container_id)
        window.append(metrics)
        self.metrics_processed += 1

    # ------------------------------------------------------------------
    # Hybrid sample retrieval: deque (fast path) + SQLite (fallback)
    # ------------------------------------------------------------------

    async def _get_samples_for_window(
        self,
        container_id: str,
        minutes: int,
    ) -> List:
        """
        Return metric samples covering the requested time window.

        Strategy:
          1. Check if the in-memory deque already covers the full window.
          2. If the oldest deque sample is younger than the cutoff, fall back
             to SQLite for the remaining history and merge the two sets,
             deduplicating by timestamp.

        Args:
            container_id: Container to query
            minutes: How many minutes back to cover

        Returns:
            List of metric objects (ContainerMetrics or MetricsSample),
            sorted oldest-first.  Both have ``timestamp`` and
            ``cpu_percent`` / ``memory_percent`` attributes.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        window = self._get_window(container_id)

        # Fast path: deque covers the whole window
        if window and window[0].timestamp <= cutoff:
            return [m for m in window if m.timestamp >= cutoff]

        # Slow path: supplement with DB rows
        db_samples: List[MetricsSample] = []
        try:
            db_samples = await self.storage.get_recent_metrics(container_id, minutes=minutes)
            # Normalize naive datetimes from SQLite to UTC aware
            for sample in db_samples:
                if sample.timestamp and sample.timestamp.tzinfo is None:
                    sample.timestamp = sample.timestamp.replace(tzinfo=timezone.utc)
        except Exception as e:
            logger.warning(f"DB fallback failed for {container_id}: {e}")

        # Merge: db_samples (older, ordered asc) + deque items (newer)
        mem_samples = list(window)
        db_timestamps = {s.timestamp for s in db_samples}

        # Only keep mem samples not already in the DB result set
        extra_mem = [m for m in mem_samples if m.timestamp not in db_timestamps]

        all_samples = db_samples + extra_mem
        all_samples.sort(key=lambda m: m.timestamp)
        return [m for m in all_samples if m.timestamp >= cutoff]

    # ------------------------------------------------------------------
    # Aggregation helpers (now hybrid-aware)
    # ------------------------------------------------------------------

    async def _calculate_moving_average_hybrid(
        self,
        container_id: str,
        minutes: int,
        field: str,
    ) -> float:
        """Calculate moving average using hybrid deque+DB samples."""
        samples = await self._get_samples_for_window(container_id, minutes)
        values = [getattr(m, field) for m in samples if getattr(m, field, None) is not None]
        if not values:
            return 0.0
        return round(statistics.mean(values), 2)

    async def _calculate_growth_rate_hybrid(
        self,
        container_id: str,
        minutes: int,
    ) -> float:
        """Calculate memory growth rate using hybrid deque+DB samples."""
        samples = await self._get_samples_for_window(container_id, minutes)
        pairs = [(m.timestamp, m.memory_percent) for m in samples if m.memory_percent is not None]

        if len(pairs) < 2:
            return 0.0

        first = pairs[0]
        last = pairs[-1]
        time_delta_minutes = (last[0] - first[0]).total_seconds() / 60
        if time_delta_minutes == 0:
            return 0.0

        memory_delta = last[1] - first[1]
        return round(memory_delta / time_delta_minutes, 2)

    # ------------------------------------------------------------------
    # Legacy sync helpers (kept for backward compatibility / sync callers)
    # ------------------------------------------------------------------

    def _calculate_moving_average(
        self,
        window: deque,
        minutes: int,
        field: str,
    ) -> float:
        """Calculate moving average for a metric (in-memory only)."""
        if not window:
            return 0.0

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        samples = [
            getattr(m, field)
            for m in window
            if m.timestamp >= cutoff
        ]

        if not samples:
            return 0.0

        return round(statistics.mean(samples), 2)

    def _calculate_growth_rate(
        self,
        window: deque,
        minutes: int,
    ) -> float:
        """
        Calculate memory growth rate (percent per minute).

        Args:
            window: Metric samples window
            minutes: Time window in minutes

        Returns:
            Growth rate as percent per minute
        """
        if len(window) < 2:
            return 0.0

        cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
        samples = [
            (m.timestamp, m.memory_percent)
            for m in window
            if m.timestamp >= cutoff
        ]

        if len(samples) < 2:
            return 0.0

        first = samples[0]
        last = samples[-1]
        time_delta_minutes = (last[0] - first[0]).total_seconds() / 60
        if time_delta_minutes == 0:
            return 0.0

        memory_delta = last[1] - first[1]
        return round(memory_delta / time_delta_minutes, 2)

    def _detect_anomaly(
        self,
        metrics: AggregatedMetrics,
        window: "deque | None" = None,
    ) -> Tuple[bool, Optional[str]]:
        """
        Detect CPU and memory anomalies.

        Uses per-container z-score when sufficient history is available in the
        deque; falls back to fixed thresholds for small windows.

        Args:
            metrics: Aggregated metrics
            window: Optional in-memory deque for baseline computation

        Returns:
            Tuple of (is_anomaly, anomaly_type)
        """
        # --- Statistical z-score path (when enough history exists) ---
        if window and len(window) >= 20:
            cpu_history = [m.cpu_percent for m in window]
            mem_history = [m.memory_percent for m in window]

            cpu_anomaly, cpu_z = z_score_anomaly(cpu_history, metrics.cpu_percent, threshold=3.0)
            if cpu_anomaly:
                return True, "cpu_spike"

            mem_anomaly, mem_z = z_score_anomaly(mem_history, metrics.memory_percent, threshold=3.0)
            if mem_anomaly:
                return True, "memory_spike"

        # --- Legacy threshold path ---
        # Spike detection: sudden memory increase > 20% in 5 minutes
        if metrics.memory_growth_rate_5m > 20.0:
            return True, "memory_spike"

        # High memory with rapid growth rate
        if metrics.memory_percent > 80.0 and metrics.memory_growth_rate_1m > 10.0:
            return True, "high_memory_rapid_growth"

        # Sustained high memory
        if (
            metrics.memory_percent > 95.0 and
            metrics.memory_percent_5m > 90.0 and
            metrics.memory_percent_15m > 85.0
        ):
            return True, "sustained_high_memory"

        return False, None

    async def aggregate(self, container_id: str) -> Optional[AggregatedMetrics]:
        """
        Calculate aggregated metrics for a container.

        Uses the hybrid (deque + SQLite) approach for all time windows,
        so 60-minute averages are accurate even when the deque doesn't
        cover the full window.

        Args:
            container_id: Container ID

        Returns:
            AggregatedMetrics or None if insufficient data
        """
        window = self._get_window(container_id)
        if not window:
            return None

        # Get latest metrics to extract container info
        latest = window[-1]

        try:
            # Calculate moving averages using hybrid approach
            cpu_5m = await self._calculate_moving_average_hybrid(container_id, 5, "cpu_percent")
            cpu_15m = await self._calculate_moving_average_hybrid(container_id, 15, "cpu_percent")
            cpu_60m = await self._calculate_moving_average_hybrid(container_id, 60, "cpu_percent")

            mem_5m = await self._calculate_moving_average_hybrid(container_id, 5, "memory_percent")
            mem_15m = await self._calculate_moving_average_hybrid(container_id, 15, "memory_percent")
            mem_60m = await self._calculate_moving_average_hybrid(container_id, 60, "memory_percent")

            # Calculate growth rates using hybrid approach
            growth_1m = await self._calculate_growth_rate_hybrid(container_id, 1)
            growth_5m = await self._calculate_growth_rate_hybrid(container_id, 5)

            # Determine container status from the stopped-at registry.
            status = "stopped" if container_id in self._stopped_at else "running"
            restart_count = self.restart_counts.get(latest.container_id, 0)

            agg_metrics = AggregatedMetrics(
                container_id=latest.container_id,
                container_name=latest.container_name,
                image=latest.image,
                timestamp=latest.timestamp,
                cpu_percent=latest.cpu_percent,
                memory_percent=latest.memory_percent,
                cpu_percent_5m=cpu_5m,
                cpu_percent_15m=cpu_15m,
                cpu_percent_60m=cpu_60m,
                memory_percent_5m=mem_5m,
                memory_percent_15m=mem_15m,
                memory_percent_60m=mem_60m,
                memory_growth_rate_1m=growth_1m,
                memory_growth_rate_5m=growth_5m,
                container_status=status,
                net_io_in=latest.net_io_in,
                net_io_out=latest.net_io_out,
                block_io_read=latest.block_io_read,
                block_io_write=latest.block_io_write,
                pids=latest.pids,
                restart_count=restart_count,
            )

            # Detect anomalies (pass the window for z-score baseline)
            is_anomaly, anomaly_type = self._detect_anomaly(agg_metrics, window=window)
            agg_metrics.is_anomaly = is_anomaly
            agg_metrics.anomaly_type = anomaly_type

            return agg_metrics

        except Exception as e:
            logger.error(f"Aggregation failed for {container_id}: {e}")
            return None

    async def aggregate_all(self) -> Dict[str, AggregatedMetrics]:
        """
        Aggregate metrics for all containers.

        Returns:
            Dict mapping container ID to AggregatedMetrics
        """
        results = {}
        tasks = [
            self.aggregate(container_id)
            for container_id in self._windows.keys()
        ]

        if not tasks:
            return results

        try:
            agg_list = await asyncio.gather(*tasks)
            for agg in agg_list:
                if agg:
                    results[agg.container_id] = agg
        except Exception as e:
            logger.error(f"Batch aggregation failed: {e}")

        return results

    def cleanup_old_containers(self, max_age_minutes: int = 1440) -> None:
        """Remove old container windows from memory."""
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_age_minutes)
        to_remove = []

        for container_id, window in self._windows.items():
            if window and window[-1].timestamp < cutoff:
                to_remove.append(container_id)

        for container_id in to_remove:
            del self._windows[container_id]
            self._stopped_at.pop(container_id, None)
            self.restart_counts.pop(container_id, None)
            logger.debug(f"Removed old container window: {container_id}")

    def update_restart_count(self, container_id: str, count: int) -> None:
        """Update the stored restart count for a container."""
        self.restart_counts[container_id] = count

    # ------------------------------------------------------------------
    # Stopped-container lifecycle tracking
    # ------------------------------------------------------------------

    def mark_container_stopped(self, container_id: str) -> None:
        """Record that a container has stopped.

        Called by the status-poll loop in DRIAgent when a container that was
        previously in the running set is no longer returned by
        ``get_containers()`` but its window still exists in ``_windows``.

        Args:
            container_id: 12-character container ID.
        """
        if container_id not in self._stopped_at:
            self._stopped_at[container_id] = datetime.now(timezone.utc)
            logger.info(f"Container marked stopped: {container_id}")

    def unmark_container_stopped(self, container_id: str) -> None:
        """Remove a container from the stopped set (e.g. it restarted).

        Args:
            container_id: 12-character container ID.
        """
        if container_id in self._stopped_at:
            del self._stopped_at[container_id]
            logger.info(f"Container unmarked stopped (restarted?): {container_id}")

    def cleanup_stopped_containers(self, max_stopped_minutes: int = 5) -> None:
        """Evict stopped containers whose grace period has elapsed.

        Containers that have been stopped for longer than *max_stopped_minutes*
        are removed from both ``_windows`` and ``_stopped_at`` so they no
        longer appear in API responses.

        Args:
            max_stopped_minutes: Minutes after ``stopped_at`` before eviction.
                Defaults to 5 to prevent stale data lingering for 24 h.
        """
        cutoff = datetime.now(timezone.utc) - timedelta(minutes=max_stopped_minutes)
        to_evict = [
            cid
            for cid, ts in self._stopped_at.items()
            if ts <= cutoff
        ]
        for cid in to_evict:
            self._windows.pop(cid, None)
            del self._stopped_at[cid]
            logger.info(f"Evicted stopped container window: {cid}")
