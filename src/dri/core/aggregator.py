"""Metrics aggregator for moving averages and anomaly detection."""

import asyncio
from collections import deque
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import statistics

from ..utils.logger import get_logger
from ..utils.metrics import ContainerMetrics, AggregatedMetrics
from .storage import MetricsStorage, MetricsSample

logger = get_logger("aggregator")


class MetricsAggregator:
    """Calculate moving averages and detect anomalies."""

    def __init__(self, storage: MetricsStorage):
        """
        Initialize aggregator.

        Args:
            storage: MetricsStorage instance for data persistence
        """
        self.storage = storage
        self._windows: Dict[str, deque] = {}  # Container ID -> metrics deque
        self._max_samples = 1000  # Max samples to keep in memory
        self.metrics_processed: int = 0  # Total samples added across all containers

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
        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
        window = self._get_window(container_id)

        # Fast path: deque covers the whole window
        if window and window[0].timestamp <= cutoff:
            return [m for m in window if m.timestamp >= cutoff]

        # Slow path: supplement with DB rows
        db_samples: List[MetricsSample] = []
        try:
            db_samples = await self.storage.get_recent_metrics(container_id, minutes=minutes)
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

        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
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

        cutoff = datetime.utcnow() - timedelta(minutes=minutes)
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

    def _detect_anomaly(self, metrics: AggregatedMetrics) -> Tuple[bool, Optional[str]]:
        """
        Detect memory anomalies (sudden spikes).

        Args:
            metrics: Aggregated metrics

        Returns:
            Tuple of (is_anomaly, anomaly_type)
        """
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

            agg_metrics = AggregatedMetrics(
                container_id=latest.container_id,
                container_name=latest.container_name,
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
            )

            # Detect anomalies
            is_anomaly, anomaly_type = self._detect_anomaly(agg_metrics)
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
        cutoff = datetime.utcnow() - timedelta(minutes=max_age_minutes)
        to_remove = []

        for container_id, window in self._windows.items():
            if window and window[-1].timestamp < cutoff:
                to_remove.append(container_id)

        for container_id in to_remove:
            del self._windows[container_id]
            logger.debug(f"Removed old container window: {container_id}")
